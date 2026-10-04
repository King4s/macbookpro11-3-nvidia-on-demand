"""GPU on-demand boot safety and activation."""
import json
from pathlib import Path


def validate_installation(paths, directories=False):
    """Check lexical ancestors with lstat; never follow installation symlinks."""
    import stat
    for target in paths:
        target = Path(target).absolute()
        for path in [*reversed(target.parents), target]:
            st = path.lstat()
            if stat.S_ISLNK(st.st_mode):
                raise PermissionError('untrusted symlink installation: ' + str(path))
            if st.st_uid != 0 or st.st_mode & 0o022:
                raise PermissionError('untrusted writable installation: ' + str(path))
            if path != target and not stat.S_ISDIR(st.st_mode):
                raise PermissionError('installation ancestor is not a directory: ' + str(path))
            if path == target and not (stat.S_ISDIR(st.st_mode) if directories else stat.S_ISREG(st.st_mode)):
                raise PermissionError('installation target is not a regular file: ' + str(path))


def owned_file(path, marker):
    """Absent is harmless; existing files must be trusted and exactly marked."""
    path = Path(path)
    validate_installation([path.parent], directories=True)
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    validate_installation([path])
    with path.open('rb') as stream:
        if stream.read(len(marker.encode())) != marker.encode():
            raise RuntimeError('refusing removal of nonowned file: ' + str(path))
    return True


def validate_manifest(root, kernel, trusted=False):
    if trusted:
        validate_installation([Path(root)/name for name in ['manifest.json', 'gpu-sched.ko', 'nouveau.ko']]
                              + [Path('/usr/local/libexec/gpu_boot.py'), Path('/etc/systemd/system/gpu-on-demand.service')])
    manifest = json.loads((Path(root) / 'manifest.json').read_text())
    if manifest.get('kernel') != kernel:
        raise ValueError('kernel mismatch: refusing module load')
    import hashlib
    modules = manifest.get('modules', {})
    if set(modules) != {'gpu-sched.ko', 'nouveau.ko'}:
        raise ValueError('invalid module manifest')
    for name, expected in modules.items():
        path = Path(root) / name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('module checksum mismatch: ' + name)
    return manifest


def command(args):
    import subprocess
    result = subprocess.run(args, text=True, capture_output=True, timeout=40)
    if result.returncode:
        raise RuntimeError(str(args) + ': ' + result.stderr)
    return result.stdout


def load_dependencies(path):
    deps = command(['/usr/sbin/modinfo', '-F', 'depends', str(path)]).strip().split(',')
    deps = [d for d in deps if d and d.replace('-', '_') not in {'gpu_sched', 'nouveau'}]
    if deps:
        # Inspect the full dependency closure, not only modinfo's direct edges.
        # Do not let a prerequisite autoload either stock GPU module (or run an
        # opaque install hook); insmod below is the only authorized GPU loader.
        import shlex
        dry_run = command(['/usr/sbin/modprobe', '--show-depends', '--all', *deps])
        for line in dry_run.splitlines():
            fields = shlex.split(line)
            if not fields:
                continue
            if fields[0] == 'insmod' and len(fields) >= 2:
                name = Path(fields[1]).name.split('.ko')[0].replace('-', '_')
                if name in {'gpu_sched', 'nouveau'}:
                    raise RuntimeError('dependency would autoload a stock GPU module: ' + fields[1])
            elif fields[0] != 'builtin':
                raise RuntimeError('opaque dependency command: refusing autoload: ' + line)
        command(['/usr/sbin/modprobe', '--all', *deps])


def load_patched(root, runpm, scheduler_loaded=False):
    if not scheduler_loaded:
        load_dependencies(root/'gpu-sched.ko')
        command(['/usr/sbin/insmod', str(root/'gpu-sched.ko')])
    load_dependencies(root/'nouveau.ko')
    command(['/usr/sbin/insmod', str(root/'nouveau.ko'), 'modeset=1', 'runpm=' + runpm])


def intel_panel_ready(drm_root):
    for panel in Path(drm_root).glob('*-eDP-*'):
        if ((panel / 'status').read_text().strip() == 'connected'
                and '0000:00:02.0' in (panel / 'device').resolve().parts):
            return True
    return False


def graphics_clients(nodes):
    import subprocess
    if not nodes:
        raise RuntimeError('no DRM nodes: client scan cannot authorize activation')
    result = subprocess.run(['/usr/bin/fuser', *nodes], capture_output=True, text=True, timeout=10)
    if result.returncode == 0 and result.stdout.strip():
        return True  # Any positive/ambiguous evidence is treated as busy.
    if result.returncode == 1 and not result.stdout.strip() and not result.stderr.strip():
        return False
    raise RuntimeError('client scan failed: ' + result.stderr)


def activation_plan(ready, intel_ready, clients):
    if ready and not intel_ready:
        raise ValueError('runtime Nvidia ready but Intel panel unavailable; refusing mutation')
    if ready and intel_ready:
        return ['configure_idle']
    if clients:
        raise ValueError('graphics clients active: refusing disruptive setup')
    if intel_ready:
        return ['load_runtime','configure_idle']
    return ['load_safe','mux_intel','reprobe_intel','reload_runtime','configure_idle']


STATE = '/run/gpu-on-demand/phase'
INTEL_DRIVER = '/sys/bus/pci/drivers/i915'
INTEL_PCI = '0000:00:02.0'


class Backend:
    """Small hardware boundary, replaced entirely by mocks in regression tests."""
    command = staticmethod(command)

    def exists(self, path):
        return Path(path).exists()

    def read(self, path):
        return Path(path).read_text().strip()

    def write(self, path, text):
        Path(path).write_text(text)

    def sleep(self, seconds):
        import time
        time.sleep(seconds)

    def panel(self):
        return intel_panel_ready('/sys/class/drm')

    def clients(self):
        nodes = [str(p) for p in Path('/dev/dri').glob('*') if not p.is_dir()]
        return graphics_clients(nodes)

    def checkpoint(self, phase):
        import os
        import tempfile
        directory = Path(STATE).parent
        validate_installation([directory], directories=True)
        with tempfile.NamedTemporaryFile(mode='w', dir=directory, delete=False) as f:
            temporary = Path(f.name)
            try:
                f.write(phase)
                f.flush()
                os.fsync(f.fileno())
                temporary.replace(STATE)
            finally:
                temporary.unlink(missing_ok=True)

    def clear_checkpoint(self):
        Path(STATE).unlink(missing_ok=True)


def recover(backend, phase=None):
    """One Intel rebind at most. Never unbind again or replace live modules.

    This restores display availability, not the original discrete-GPU state.
    Failed recovery keeps the journal and the service failed, gating the DM.
    """
    phase = backend.read(STATE) if phase is None else phase
    if phase not in {'load_safe', 'load_runtime', 'mux_intel', 'intel_rebind', 'reload_runtime', 'configure_idle'}:
        raise RuntimeError('unknown recovery checkpoint; refusing hardware recovery')
    if phase == 'intel_rebind' and not backend.exists(INTEL_DRIVER + '/' + INTEL_PCI):
        backend.write(INTEL_DRIVER + '/bind', INTEL_PCI)
    # A successful bind is not itself proof of an available panel.
    import time
    deadline = time.monotonic() + 5
    while not backend.panel():
        if time.monotonic() >= deadline:
            raise RuntimeError('Intel panel unavailable after bounded recovery; display manager blocked')
        backend.sleep(0.2)
    backend.clear_checkpoint()


def execute_plan(plan, root, manifest, backend):
    phase = None
    try:
        for step in plan:
            print('gpu-on-demand: ' + step, flush=True)
            if step == 'reprobe_intel' and backend.clients():
                raise RuntimeError('graphics clients appeared; refusing Intel reprobe')
            phase = 'intel_rebind' if step == 'reprobe_intel' else step
            backend.checkpoint(phase)  # Write intent BEFORE a potentially interruptible write.
            if step in ['load_safe', 'load_runtime']:
                scheduler_loaded = backend.exists('/sys/module/gpu_sched')
                if scheduler_loaded:
                    note = '/sys/module/gpu_sched/notes/.note.gnu.build-id'
                    if Path(note).read_bytes().hex() != manifest['build_ids']['gpu_sched']:
                        raise RuntimeError('different scheduler already loaded; refusing replacement')
                load_patched(root, '0' if step == 'load_safe' else '1', scheduler_loaded)
            elif step == 'mux_intel':
                backend.write('/sys/kernel/debug/vgaswitcheroo/switch', 'MIGD\n')
                backend.sleep(1)
            elif step == 'reprobe_intel':
                backend.write(INTEL_DRIVER + '/unbind', INTEL_PCI)
                backend.sleep(1)
                backend.write(INTEL_DRIVER + '/bind', INTEL_PCI)
                backend.sleep(2)
                if not backend.panel():
                    raise RuntimeError('Intel panel not detected after mux selection')
            elif step == 'reload_runtime':
                if backend.clients():
                    raise RuntimeError('graphics clients appeared; refusing module reload')
                backend.command(['/usr/sbin/rmmod', 'nouveau'])
                backend.command(['/usr/sbin/insmod', str(root/'nouveau.ko'), 'modeset=1', 'runpm=1'])
            elif step == 'configure_idle':
                for pci in ['0000:01:00.0', '0000:01:00.1']:
                    backend.write('/sys/bus/pci/devices/' + pci + '/power/control', 'auto\n')
    except BaseException:
        if phase is not None:
            try:
                recover(backend, phase)
            except BaseException as exc:
                import sys
                print('gpu-on-demand: recovery failed: ' + str(exc), file=sys.stderr, flush=True)
        raise


def arm_deadline(seconds, saved):
    import signal
    def interrupted(signum, frame):
        raise InterruptedError('activation/recovery interrupted by signal ' + str(signum))
    for signum in [signal.SIGTERM, signal.SIGINT, signal.SIGALRM]:
        saved[signum] = signal.signal(signum, interrupted)
    signal.alarm(seconds)


def main(argv=None):
    import argparse
    import fcntl
    import hashlib
    import os
    import platform
    import subprocess
    import sys
    import time

    parser = argparse.ArgumentParser()
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--module-dir', type=Path)
    parser.add_argument('--kernel')
    parser.add_argument('--recover', action='store_true')
    args = parser.parse_args(argv)
    if (args.module_dir is not None or args.kernel is not None) and not args.check_only:
        parser.error('fixture paths/kernel overrides require --check-only')
    if args.recover and args.check_only:
        parser.error('--recover cannot be combined with --check-only')
    kernel = args.kernel if args.check_only and args.kernel else platform.release()
    root = args.module_dir if args.check_only and args.module_dir else Path('/usr/local/lib/gpu-on-demand') / kernel
    config = Path('/etc/X11/xorg.conf.d/91-gpu-on-demand.conf')
    marker = '# Managed by gpu-on-demand; remove when disabling its service.\n'
    backend = Backend()
    cleanup = False
    saved_signals = {}
    lock = None
    try:
        if args.recover:
            if os.geteuid() != 0:
                raise PermissionError('recovery requires root')
            validate_installation([Path('/usr/local/libexec/gpu_boot.py'), Path('/etc/systemd/system/gpu-on-demand.service')])
            if Path(STATE).exists():
                validate_installation([Path(STATE)])
                lock = open('/run/gpu-on-demand/lock', 'a')
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                arm_deadline(20, saved_signals)
                cleanup = True
                recover(backend)
                if not config.is_symlink() and config.exists() and config.read_text().startswith(marker):
                    config.unlink()
            return 0
        if not args.check_only:
            # Only an absent per-kernel directory is a benign kernel-update skip.
            # lstat distinguishes absence from dangling symlinks and bad paths.
            validate_installation([root.parent], directories=True)
            try:
                root.lstat()
            except FileNotFoundError:
                if os.geteuid() != 0:
                    raise PermissionError('activation requires root')
                validate_installation([Path('/usr/local/libexec/gpu_boot.py'),
                                       Path('/etc/systemd/system/gpu-on-demand.service')])
                validate_installation([Path(STATE).parent, config.parent], directories=True)
                lock = open('/run/gpu-on-demand/lock', 'a')
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if Path(STATE).exists() or Path(STATE).is_symlink():
                    raise RuntimeError('unfinished recovery checkpoint; refusing kernel-bundle skip')
                if owned_file(config, marker):
                    config.unlink()
                print('gpu-on-demand: WARNING: no module bundle for ' + kernel +
                      '; activation skipped; stock driver policy unchanged.', file=sys.stderr, flush=True)
                return 0
        manifest = validate_manifest(root, kernel, trusted=not args.check_only)
        if not args.check_only:
            if os.geteuid() != 0:
                raise PermissionError('activation requires root')
            validate_installation([Path(STATE).parent], directories=True)
            lock = open('/run/gpu-on-demand/lock', 'a')
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            arm_deadline(100, saved_signals)
            if Path(STATE).exists():
                raise RuntimeError('unfinished recovery checkpoint; run --recover before activation')
        panel = intel_panel_ready('/sys/class/drm')
        ready = False
        if Path('/sys/module/nouveau').exists():
            ready = Path('/sys/module/nouveau/parameters/runpm').read_text().strip() == '1'
            for name in ['nouveau', 'gpu_sched']:
                note = Path('/sys/module') / name / 'notes/.note.gnu.build-id'
                ready = ready and note.exists() and note.read_bytes().hex() == manifest['build_ids'].get(name)
            if not ready:
                raise RuntimeError('different or non-runtime GPU module already loaded; refusing replacement')
        nodes = [str(p) for p in Path('/dev/dri').glob('*') if not p.is_dir()]
        clients = graphics_clients(nodes)
        plan = activation_plan(ready, panel, clients)
        print(json.dumps({'kernel': kernel, 'intel_panel': panel, 'modules_ready': ready, 'plan': plan}), flush=True)
        if args.check_only:
            sys.exit(0)
        if config.exists() and not config.read_text().startswith(marker):
            raise RuntimeError('Xorg config path already owned by another configuration')
        cleanup = True
        execute_plan(plan, root, manifest, backend)
        # Ensure Xorg renders on Intel and never holds the discrete KMS card.
        content = marker + '''Section "ServerFlags"
    Option "AutoAddGPU" "false"
EndSection
Section "Device"
    Identifier "IntelOnDemandDesktop"
    Driver "modesetting"
    BusID "PCI:0:2:0"
    Option "PrimaryGPU" "true"
EndSection
Section "Screen"
    Identifier "IntelOnDemandScreen"
    Device "IntelOnDemandDesktop"
EndSection
Section "ServerLayout"
    Identifier "IntelOnDemandLayout"
    Screen "IntelOnDemandScreen"
EndSection
'''
        temporary = config.with_suffix('.tmp')
        temporary.write_text(content)
        temporary.chmod(0o644)
        temporary.replace(config)
        backend.clear_checkpoint()
        print('GPU setup ready; Intel panel preserved, Nvidia runtime PM enabled.', flush=True)
        return 0
    except Exception as exc:
        # Never let override inspection/removal hide the original setup failure.
        # A guard rejection before any transition does not mutate configuration.
        if cleanup and not args.check_only and os.geteuid() == 0:
            try:
                if not config.is_symlink() and config.exists() and config.read_text().startswith(marker):
                    config.unlink()
            except Exception as cleanup_exc:
                print('gpu-on-demand: override cleanup failed: ' + str(cleanup_exc), file=sys.stderr, flush=True)
        print('gpu-on-demand: ' + str(exc), file=sys.stderr, flush=True)
        return 1
    finally:
        if saved_signals:
            import signal
            signal.alarm(0)
            for signum, handler in saved_signals.items():
                signal.signal(signum, handler)
        if lock is not None:
            lock.close()


if __name__ == '__main__':
    raise SystemExit(main())

