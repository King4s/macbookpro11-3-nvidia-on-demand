import importlib
import json
import hashlib
from pathlib import Path
import tempfile
import unittest

class BootSafety(unittest.TestCase):
    def test_rejects_kernel_mismatch_before_loading(self):
        module = importlib.import_module('gpu_boot')
        self.assertTrue(hasattr(module, 'validate_manifest'), 'kernel compatibility guard is missing')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'manifest.json').write_text(json.dumps({'kernel':'7.0.0-34-generic','modules':{}}))
            with self.assertRaisesRegex(ValueError, 'kernel'):
                module.validate_manifest(root,'different-kernel')

    def test_rejects_changed_module_bytes(self):
        module=importlib.import_module('gpu_boot')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            good=hashlib.sha256(b'original').hexdigest()
            for name in ['gpu-sched.ko','nouveau.ko']:
                (root/name).write_bytes(b'changed')
            (root/'manifest.json').write_text(json.dumps({'kernel':'same','modules':{'gpu-sched.ko':good,'nouveau.ko':good}}))
            with self.assertRaisesRegex(ValueError,'checksum'):
                module.validate_manifest(root,'same')

    def test_ready_session_requires_no_disruptive_work(self):
        module=importlib.import_module('gpu_boot')
        self.assertTrue(hasattr(module,'activation_plan'), 'idempotent activation planner is missing')
        self.assertEqual(module.activation_plan(True,True,True), ['configure_idle'])

    def test_refuses_disruptive_setup_with_live_clients(self):
        module=importlib.import_module('gpu_boot')
        with self.assertRaisesRegex(ValueError,'clients'):
            module.activation_plan(False,False,True)

    def test_cold_boot_initializes_display_before_runtime_sleep(self):
        module=importlib.import_module('gpu_boot')
        self.assertEqual(module.activation_plan(False,False,False),
                         ['load_safe','mux_intel','reprobe_intel','reload_runtime','configure_idle'])

    def test_existing_intel_panel_is_not_reprobed(self):
        module=importlib.import_module('gpu_boot')
        self.assertEqual(module.activation_plan(False,True,False),
                         ['load_runtime','configure_idle'])

    def test_panel_check_uses_intel_pci_ownership(self):
        module=importlib.import_module('gpu_boot')
        self.assertTrue(hasattr(module,'intel_panel_ready'),'panel ownership detector missing')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            panel=root/'card9-eDP-2'; panel.mkdir()
            (panel/'status').write_text('connected')
            target=root/'devices/0000:00:02.0/drm/card9'; target.mkdir(parents=True)
            (panel/'device').symlink_to(target)
            self.assertTrue(module.intel_panel_ready(root))
            (panel/'device').unlink()
            other=root/'devices/0000:01:00.0/drm/card9'; other.mkdir(parents=True)
            (panel/'device').symlink_to(other)
            self.assertFalse(module.intel_panel_ready(root))

    def test_command_failures_abort_activation(self):
        module=importlib.import_module('gpu_boot')
        self.assertTrue(hasattr(module,'command'),'checked command runner missing')
        with self.assertRaises(RuntimeError):
            module.command(['/usr/bin/false'])

    def test_cli_rejects_wrong_kernel(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'manifest.json').write_text(json.dumps({'kernel':'good','modules':{}}))
            result=subprocess.run(['python3','gpu_boot.py','--check-only','--module-dir',str(root),'--kernel','bad'],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0,'CLI must fail before any hardware operation')
            self.assertIn('kernel',result.stderr)

class OwnedFileRegression(unittest.TestCase):
    def test_owned_file_checks_exact_marker_and_rejects_nonowned_or_symlink(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        import gpu_boot
        self.assertTrue(hasattr(gpu_boot, 'owned_file'), 'bounded ownership guard missing')
        marker='# Managed by gpu-on-demand; remove when disabling its service.\n'
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); path=root/'override.conf'
            original=Path.lstat
            def root_owned(p):
                st=original(p)
                return SimpleNamespace(st_uid=0, st_mode=st.st_mode & ~0o022)
            with patch.object(Path,'lstat',root_owned):
                self.assertFalse(gpu_boot.owned_file(path,marker))
                path.write_text(marker+'Section "Device"\n')
                self.assertTrue(gpu_boot.owned_file(path,marker))
                path.write_text('# unrelated config\n'+marker)
                with self.assertRaisesRegex(RuntimeError,'owned'):
                    gpu_boot.owned_file(path,marker)
                path.unlink(); path.symlink_to(root/'absent')
                with self.assertRaisesRegex(PermissionError,'symlink'):
                    gpu_boot.owned_file(path,marker)

class DisableRegression(unittest.TestCase):
    def test_disable_refuses_nonowned_files_before_any_service_change(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        import gpu_on_demand_disable as disable
        for case in ['xorg','policy','symlink','checkpoint','command-failure']:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as d:
                root=Path(d); xorg=root/'xorg.conf'; policy=root/'modprobe.conf'; state=root/'phase'
                xorg.write_text(disable.XORG_MARKER+'Xorg\n')
                policy.write_text(disable.POLICY_MARKER+'blacklist nouveau\n')
                if case=='xorg': xorg.write_text('unowned Xorg\n')
                if case=='policy': policy.write_text('unowned policy\n')
                if case=='symlink':
                    policy.unlink(); policy.symlink_to(root/'missing')
                if case=='checkpoint': state.write_text('intel_rebind')
                original=Path.lstat
                def root_owned(p):
                    st=original(p)
                    return SimpleNamespace(st_uid=0, st_mode=st.st_mode & ~0o022)
                with patch.object(Path,'lstat',root_owned), patch.object(disable,'XORG',xorg), patch.object(disable,'POLICY',policy), patch.object(disable,'STATE',state), patch('os.geteuid',return_value=0), patch.object(disable,'command',side_effect=RuntimeError('disable failed') if case=='command-failure' else None) as command:
                    self.assertEqual(disable.main(),1)
                if case=='command-failure': command.assert_called_once()
                else: command.assert_not_called()
                self.assertTrue(xorg.exists())
                self.assertTrue(policy.exists() or policy.is_symlink())

    def test_disable_removes_only_owned_configs_after_service_disable(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        self.assertTrue(Path('gpu_on_demand_disable.py').is_file(), 'disable source missing')
        import gpu_on_demand_disable as disable
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); xorg=root/'xorg.conf'; policy=root/'modprobe.conf'
            xorg.write_text('# Managed by gpu-on-demand; remove when disabling its service.\nXorg data\n')
            policy.write_text('# Managed Nvidia on-demand modules: load reviewed per-kernel copies explicitly.\nblacklist nouveau\n')
            unrelated=root/'distro.conf'; unrelated.write_text('distro policy')
            original=Path.lstat
            def root_owned(p):
                st=original(p)
                return SimpleNamespace(st_uid=0, st_mode=st.st_mode & ~0o022)
            def run(args):
                self.assertTrue(xorg.exists()); self.assertTrue(policy.exists())
                self.assertEqual(args,['/usr/bin/systemctl','disable','--now','gpu-on-demand.service'])
                return ''
            with patch.object(Path,'lstat',root_owned), patch.object(disable,'XORG',xorg), patch.object(disable,'POLICY',policy), patch.object(disable,'STATE',root/'phase'), patch('os.geteuid',return_value=0), patch.object(disable,'command',side_effect=run) as command:
                self.assertEqual(disable.main(),0)
            command.assert_called_once()
            self.assertFalse(xorg.exists()); self.assertFalse(policy.exists())
            self.assertEqual(unrelated.read_text(),'distro policy')

class TrustRegression(unittest.TestCase):
    def test_trust_rejected_before_manifest_read(self):
        from unittest.mock import patch
        import gpu_boot
        with patch.object(gpu_boot, 'validate_installation', create=True, side_effect=PermissionError('untrusted')), patch.object(Path, 'read_text') as read:
            with self.assertRaisesRegex(PermissionError, 'untrusted'):
                gpu_boot.validate_manifest(Path('/unsafe/kernel'), 'kernel', trusted=True)
            read.assert_not_called()

    def test_trust_covers_helper_unit_modules_and_manifest(self):
        from unittest.mock import patch
        import gpu_boot
        with patch.object(gpu_boot,'validate_installation') as trust, patch.object(Path,'read_text',return_value='{"kernel":"other"}'):
            with self.assertRaisesRegex(ValueError,'kernel'):
                gpu_boot.validate_manifest(Path('/usr/local/lib/gpu-on-demand/kernel'),'kernel',trusted=True)
        paths=trust.call_args.args[0]
        self.assertEqual(paths,[Path('/usr/local/lib/gpu-on-demand/kernel')/name for name in ['manifest.json','gpu-sched.ko','nouveau.ko']]
                         +[Path('/usr/local/libexec/gpu_boot.py'),Path('/etc/systemd/system/gpu-on-demand.service')])

    def test_symlink_in_ancestor_is_rejected(self):
        import gpu_boot
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'real').mkdir(); (root/'alias').symlink_to(root/'real')
            from unittest.mock import patch
            from types import SimpleNamespace
            original = Path.lstat
            def root_owned(path):
                st = original(path)
                return SimpleNamespace(st_uid=0, st_mode=st.st_mode & ~0o022)
            with patch.object(Path, 'lstat', root_owned), self.assertRaisesRegex(PermissionError, 'symlink'):
                gpu_boot.validate_installation([root/'alias'/'manifest.json'])

    def test_writable_ancestor_is_rejected(self):
        import gpu_boot
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); root.chmod(0o777); (root/'manifest.json').write_text('{}')
            from unittest.mock import patch
            from types import SimpleNamespace
            original = Path.lstat
            def root_owned(path):
                st = original(path)
                mode = st.st_mode if path == root else st.st_mode & ~0o022
                return SimpleNamespace(st_uid=0, st_mode=mode)
            with patch.object(Path, 'lstat', root_owned), self.assertRaisesRegex(PermissionError, 'writable.*' + str(root)):
                gpu_boot.validate_installation([root/'manifest.json'])

class DependencyRegression(unittest.TestCase):
    def test_scheduler_prerequisites_precede_patched_insertion(self):
        from unittest.mock import patch
        import gpu_boot
        calls=[]
        def run(args):
            calls.append(args)
            if 'modinfo' in args[0]:
                return 'drm\n' if args[-1].endswith('gpu-sched.ko') else 'gpu_sched,drm,nouveau\n'
            return ''
        with patch.object(gpu_boot, 'command', side_effect=run):
            gpu_boot.load_patched(Path('/modules'), '0')
        self.assertEqual(calls, [
            ['/usr/sbin/modinfo','-F','depends','/modules/gpu-sched.ko'],
            ['/usr/sbin/modprobe','--show-depends','--all','drm'],
            ['/usr/sbin/modprobe','--all','drm'],
            ['/usr/sbin/insmod','/modules/gpu-sched.ko'],
            ['/usr/sbin/modinfo','-F','depends','/modules/nouveau.ko'],
            ['/usr/sbin/modprobe','--show-depends','--all','drm'],
            ['/usr/sbin/modprobe','--all','drm'],
            ['/usr/sbin/insmod','/modules/nouveau.ko','modeset=1','runpm=0']])

    def test_empty_dependencies_never_invokes_operandless_modprobe(self):
        from unittest.mock import patch
        import gpu_boot
        calls=[]
        def run(args):
            calls.append(args)
            return '\n' if args[0].endswith('modinfo') else ''
        with patch.object(gpu_boot,'command',side_effect=run):
            gpu_boot.load_patched(Path('/modules'),'1')
        self.assertFalse(any(c[0].endswith('modprobe') for c in calls))
        self.assertEqual(sum(c[0].endswith('insmod') for c in calls),2)

    def test_transitive_stock_scheduler_is_rejected_before_modprobe(self):
        from unittest.mock import patch
        import gpu_boot
        calls=[]
        def run(args):
            calls.append(args)
            if args[0].endswith('modinfo'): return 'drm_helper\n'
            if '--show-depends' in args: return 'insmod /lib/modules/kernel/gpu-sched.ko\n'
            return ''
        with patch.object(gpu_boot,'command',side_effect=run), self.assertRaisesRegex(RuntimeError,'stock GPU'):
            gpu_boot.load_patched(Path('/modules'),'1')
        self.assertFalse(any((c[0].endswith('modprobe') and '--show-depends' not in c) or c[0].endswith('insmod') for c in calls))

    def test_dependency_failure_never_inserts_scheduler(self):
        from unittest.mock import patch
        import gpu_boot
        calls=[]
        def run(args):
            calls.append(args)
            if args[0].endswith('modinfo'): return 'drm\n'
            raise RuntimeError('dependency failed')
        with patch.object(gpu_boot,'command',side_effect=run), self.assertRaisesRegex(RuntimeError,'dependency failed'):
            gpu_boot.load_patched(Path('/modules'),'1')
        self.assertFalse(any(c[0].endswith('insmod') for c in calls))

class ClientRegression(unittest.TestCase):
    def test_scanner_fails_closed_on_errors_and_empty_nodes(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        import gpu_boot
        for code, out, err in [(2,'',''), (1,'','permission denied'), (0,'',''), (1,'123','')]:
            with self.subTest(code=code,out=out,err=err), patch('subprocess.run', return_value=SimpleNamespace(returncode=code,stdout=out,stderr=err)):
                with self.assertRaisesRegex(RuntimeError, 'client scan'):
                    gpu_boot.graphics_clients(['/dev/dri/card0'])
        with patch('subprocess.run') as run:
            with self.assertRaisesRegex(RuntimeError, 'no DRM'):
                gpu_boot.graphics_clients([])
            run.assert_not_called()

    def test_only_documented_empty_result_allows_disruption(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        import gpu_boot
        with patch('subprocess.run', return_value=SimpleNamespace(returncode=1,stdout='',stderr='')) as run:
            self.assertFalse(gpu_boot.graphics_clients(['/dev/dri/card0']))
            self.assertEqual(run.call_args.kwargs['timeout'], 10)
        with patch('subprocess.run', return_value=SimpleNamespace(returncode=0,stdout='123',stderr='/dev/dri/card0:')):
            self.assertTrue(gpu_boot.graphics_clients(['/dev/dri/card0']))

    def test_ready_nvidia_nonready_intel_is_rejected(self):
        import gpu_boot
        for clients in [False, True]:
            with self.assertRaisesRegex(ValueError, 'Intel'):
                gpu_boot.activation_plan(True,False,clients)

class RecoveryRegression(unittest.TestCase):
    def backend(self):
        from unittest.mock import Mock
        backend=Mock()
        backend.clients.return_value=False
        backend.panel.return_value=True
        backend.exists.return_value=False
        backend.read.return_value=''
        return backend

    def test_partial_intel_bind_failure_attempts_bounded_rebind(self):
        import gpu_boot
        b=self.backend(); b.write.side_effect=[None, OSError('bind failed'), None]
        with self.assertRaisesRegex(OSError, 'bind failed'):
            gpu_boot.execute_plan(['reprobe_intel'], Path('/modules'), {}, b)
        self.assertEqual(b.write.call_args_list[-1].args,
                         ('/sys/bus/pci/drivers/i915/bind', '0000:00:02.0'))
        self.assertEqual(b.write.call_count, 3)
        b.checkpoint.assert_called_once_with('intel_rebind')
        b.clear_checkpoint.assert_called_once()

    def test_failed_unbind_with_intel_still_bound_is_not_rebound(self):
        import gpu_boot
        b=self.backend(); b.write.side_effect=OSError('unbind failed'); b.exists.return_value=True
        with self.assertRaisesRegex(OSError,'unbind failed'):
            gpu_boot.execute_plan(['reprobe_intel'],Path('/modules'),{},b)
        self.assertEqual(b.write.call_count,1)
        b.clear_checkpoint.assert_called_once()

    def test_clients_appearing_after_mux_prevent_intel_unbind(self):
        import gpu_boot
        b=self.backend(); b.clients.return_value=True
        with self.assertRaisesRegex(RuntimeError,'clients appeared'):
            gpu_boot.execute_plan(['mux_intel','reprobe_intel'],Path('/modules'),{},b)
        b.write.assert_called_once_with('/sys/kernel/debug/vgaswitcheroo/switch','MIGD\n')
        b.clear_checkpoint.assert_called_once()

    def test_recovery_failure_keeps_checkpoint_for_stop_post(self):
        import gpu_boot
        b=self.backend(); b.write.side_effect=OSError('rebind failed')
        with self.assertRaisesRegex(OSError, 'rebind failed'):
            gpu_boot.execute_plan(['reprobe_intel'], Path('/modules'), {}, b)
        self.assertLessEqual(b.write.call_count, 2)
        b.clear_checkpoint.assert_not_called()

    def test_stop_post_recovers_interrupted_unbind_without_module_replacement(self):
        import gpu_boot
        b=self.backend(); b.read.return_value='intel_rebind'
        gpu_boot.recover(b)
        b.write.assert_called_once_with('/sys/bus/pci/drivers/i915/bind', '0000:00:02.0')
        b.command.assert_not_called()
        b.clear_checkpoint.assert_called_once()

    def test_signal_interrupt_recovers_like_command_failure(self):
        import gpu_boot
        b=self.backend(); b.sleep.side_effect=InterruptedError('termination')
        with self.assertRaisesRegex(InterruptedError, 'termination'):
            gpu_boot.execute_plan(['reprobe_intel'], Path('/modules'), {}, b)
        self.assertEqual(b.write.call_count, 2)
        b.clear_checkpoint.assert_called_once()

    def test_unit_requires_success_and_has_stop_post_timeout_recovery(self):
        content=Path('gpu-on-demand.service').read_text()
        self.assertIn('RequiredBy=display-manager.service', content)
        self.assertIn('ExecStopPost=/usr/bin/python3 -I /usr/local/libexec/gpu_boot.py --recover', content)
        self.assertIn('TimeoutStopSec=', content)

class TerminationRegression(unittest.TestCase):
    def test_installed_signal_handler_turns_timeout_and_term_into_recoverable_errors(self):
        import signal
        from unittest.mock import patch
        import gpu_boot
        saved={}
        with patch('signal.signal') as install, patch('signal.alarm') as alarm:
            gpu_boot.arm_deadline(100, saved)
        self.assertEqual(set(saved), {signal.SIGTERM, signal.SIGINT, signal.SIGALRM})
        alarm.assert_called_once_with(100)
        for call in install.call_args_list:
            with self.assertRaises(InterruptedError):
                call.args[1](call.args[0], None)

    def test_recovery_panel_wait_has_finite_deadline(self):
        from unittest.mock import Mock, patch
        import gpu_boot
        b=Mock(); b.panel.return_value=False
        with patch('time.monotonic', side_effect=[0, 6]):
            with self.assertRaisesRegex(RuntimeError, 'bounded recovery'):
                gpu_boot.recover(b, 'mux_intel')
        b.clear_checkpoint.assert_not_called()
        b.write.assert_not_called()

class ExecutableRegression(unittest.TestCase):
    def mocked_main(self, ready=False, panel=False, clients=False, config=False):
        """All hardware/system-write boundaries mocked; exercise real main+executor."""
        from contextlib import ExitStack
        from unittest.mock import Mock, patch, mock_open
        import gpu_boot
        stack=ExitStack(); self.addCleanup(stack.close)
        b=Mock(); b.exists.return_value=False; b.panel.return_value=True; b.clients.return_value=False
        stack.enter_context(patch.object(gpu_boot, 'Backend', return_value=b))
        manifest={'build_ids':{'nouveau':'ab','gpu_sched':'ab'}}
        validate=stack.enter_context(patch.object(gpu_boot,'validate_manifest',return_value=manifest))
        stack.enter_context(patch.object(gpu_boot,'validate_installation'))
        stack.enter_context(patch('os.geteuid',return_value=0))
        stack.enter_context(patch('builtins.open',mock_open()))
        stack.enter_context(patch('fcntl.flock'))
        deadline=stack.enter_context(patch.object(gpu_boot,'arm_deadline'))
        stack.enter_context(patch.object(gpu_boot,'intel_panel_ready',return_value=panel))
        scan=stack.enter_context(patch.object(gpu_boot,'graphics_clients',return_value=clients))
        stack.enter_context(patch.object(Path,'glob',return_value=[Path('/dev/dri/card0')]))
        stack.enter_context(patch.object(Path,'is_dir',return_value=False))
        stack.enter_context(patch.object(Path,'lstat'))
        def exists(path):
            value=str(path)
            if value.startswith('/sys/module/'):
                return ready
            return config and value.endswith('91-gpu-on-demand.conf')
        stack.enter_context(patch.object(Path,'exists',exists))
        stack.enter_context(patch.object(Path,'is_symlink',return_value=False))
        stack.enter_context(patch.object(Path,'read_bytes',return_value=b'\xab'))
        # read_text needs the managed marker only for config-present scenarios.
        stack.enter_context(patch.object(Path,'read_text',lambda p: ('# Managed by gpu-on-demand; remove when disabling its service.\n' if str(p).endswith('.conf') else '1')))
        write=stack.enter_context(patch.object(Path,'write_text'))
        stack.enter_context(patch.object(Path,'chmod'))
        stack.enter_context(patch.object(Path,'replace'))
        unlink=stack.enter_context(patch.object(Path,'unlink'))
        calls=[]
        def command(args):
            calls.append(args)
            return 'drm\n' if args[0].endswith('modinfo') else ''
        stack.enter_context(patch.object(gpu_boot,'command',side_effect=command))
        return b, scan, write, unlink, calls, validate, deadline

    def test_missing_kernel_bundle_skips_before_hardware_and_removes_owned_override(self):
        from unittest.mock import patch, Mock, mock_open
        import gpu_boot
        b,scan,write,unlink,calls,validate,deadline=self.mocked_main(config=True)
        validate.side_effect=FileNotFoundError('missing bundle')
        def lstat(path):
            if str(path).startswith('/usr/local/lib/gpu-on-demand/'):
                raise FileNotFoundError('missing bundle')
            return Mock()
        marker=b'# Managed by gpu-on-demand; remove when disabling its service.\n'
        with patch.object(Path,'lstat',lstat), patch.object(Path,'open',mock_open(read_data=marker)):
            self.assertEqual(gpu_boot.main([]),0)
        validate.assert_not_called(); scan.assert_not_called()
        b.write.assert_not_called(); b.checkpoint.assert_not_called()
        write.assert_not_called(); unlink.assert_called_once()
        deadline.assert_not_called(); self.assertEqual(calls,[])

    def test_missing_bundle_without_override_skips_without_config_or_hardware_writes(self):
        from unittest.mock import patch
        import gpu_boot
        b,scan,write,unlink,calls,validate,deadline=self.mocked_main()
        with patch.object(Path,'lstat',side_effect=FileNotFoundError('absent')), patch.object(Path,'open') as read:
            self.assertEqual(gpu_boot.main([]),0)
        read.assert_not_called(); validate.assert_not_called(); scan.assert_not_called()
        b.write.assert_not_called(); b.checkpoint.assert_not_called()
        write.assert_not_called(); unlink.assert_not_called(); self.assertEqual(calls,[])

    def test_existing_untrusted_bundle_is_error_not_skip(self):
        from unittest.mock import patch
        import gpu_boot
        b,scan,write,unlink,calls,validate,deadline=self.mocked_main(config=True)
        validate.side_effect=PermissionError('untrusted bundle symlink')
        self.assertEqual(gpu_boot.main([]),1)
        validate.assert_called_once(); scan.assert_not_called()
        b.write.assert_not_called(); b.checkpoint.assert_not_called()
        write.assert_not_called(); unlink.assert_not_called()
        validate.reset_mock()
        with patch.object(Path,'lstat',side_effect=PermissionError('bundle inaccessible')):
            self.assertEqual(gpu_boot.main([]),1)
        validate.assert_not_called(); unlink.assert_not_called()

    def test_kernel_skip_fails_closed_for_checkpoint_trust_and_cleanup_errors(self):
        from unittest.mock import patch, Mock, mock_open
        import gpu_boot
        for case in ['checkpoint','untrusted-parent','untrusted-helper','nonowned-config','symlink-config','cleanup-denied','lock-busy']:
            with self.subTest(case=case):
                b,scan,write,unlink,calls,validate,deadline=self.mocked_main(config=True)
                def lstat(path):
                    if str(path).startswith('/usr/local/lib/gpu-on-demand/'):
                        raise FileNotFoundError('missing bundle')
                    return Mock()
                original_exists=Path.exists
                def exists(path):
                    return (case=='checkpoint' and str(path)==gpu_boot.STATE) or original_exists(path)
                def trust(paths, directories=False):
                    if case=='untrusted-parent' and Path('/usr/local/lib/gpu-on-demand') in paths:
                        raise PermissionError('untrusted parent')
                    if case=='untrusted-helper' and Path('/usr/local/libexec/gpu_boot.py') in paths:
                        raise PermissionError('untrusted helper')
                    if case=='symlink-config' and Path('/etc/X11/xorg.conf.d/91-gpu-on-demand.conf') in paths:
                        raise PermissionError('symlink config')
                marker=b'# Managed by gpu-on-demand; remove when disabling its service.\n'
                if case=='nonowned-config': marker=b'# other owner\n'
                if case=='cleanup-denied': unlink.side_effect=PermissionError('cleanup denied')
                with patch.object(Path,'lstat',lstat), patch.object(Path,'exists',exists), patch.object(Path,'open',mock_open(read_data=marker)), patch.object(gpu_boot,'validate_installation',side_effect=trust), patch('fcntl.flock',side_effect=BlockingIOError('busy') if case=='lock-busy' else None):
                    self.assertEqual(gpu_boot.main([]),1)
                validate.assert_not_called(); scan.assert_not_called()
                b.write.assert_not_called(); b.checkpoint.assert_not_called()
                write.assert_not_called(); self.assertEqual(calls,[])
                if case!='cleanup-denied': unlink.assert_not_called()
                self.doCleanups()

    def test_existing_broken_bundle_never_becomes_skip(self):
        import gpu_boot
        b,scan,write,unlink,calls,validate,deadline=self.mocked_main(config=True)
        validate.side_effect=FileNotFoundError('manifest absent in existing bundle')
        self.assertEqual(gpu_boot.main([]),1)
        validate.assert_called_once(); scan.assert_not_called()
        b.write.assert_not_called(); b.checkpoint.assert_not_called()
        write.assert_not_called(); unlink.assert_not_called()

    def test_check_only_missing_manifest_is_error_not_skip(self):
        import gpu_boot
        b,scan,write,unlink,calls,validate,deadline=self.mocked_main()
        validate.side_effect=FileNotFoundError('missing manifest')
        self.assertEqual(gpu_boot.main(['--check-only','--module-dir','/fixture','--kernel','fixture']),1)
        validate.assert_called_once(); scan.assert_not_called()
        b.write.assert_not_called(); b.checkpoint.assert_not_called()
        write.assert_not_called(); unlink.assert_not_called()

    def test_mocked_cold_path_loads_deps_mux_reprobes_reloads_then_configures(self):
        import gpu_boot
        b,scan,write,unlink,calls,validate,deadline=self.mocked_main()
        self.assertEqual(gpu_boot.main([]),0)
        self.assertTrue(validate.call_args.kwargs['trusted'])
        deadline.assert_called_once()
        self.assertEqual(deadline.call_args.args[0],100)
        phases=[c.args[0] for c in b.checkpoint.call_args_list]
        self.assertEqual(phases,['load_safe','mux_intel','intel_rebind','reload_runtime','configure_idle'])
        self.assertEqual([c.args[0] for c in b.write.call_args_list][:3],
                         ['/sys/kernel/debug/vgaswitcheroo/switch','/sys/bus/pci/drivers/i915/unbind','/sys/bus/pci/drivers/i915/bind'])
        self.assertIn('AutoAddGPU',write.call_args.args[0])
        self.assertEqual(calls[0][-1].split('/')[-1],'gpu-sched.ko')
        self.assertEqual(calls[1],['/usr/sbin/modprobe','--show-depends','--all','drm'])
        self.assertEqual(calls[2],['/usr/sbin/modprobe','--all','drm'])
        self.assertEqual(calls[3][0],'/usr/sbin/insmod')
        self.assertEqual(b.command.call_args_list[0].args[0],['/usr/sbin/rmmod','nouveau'])
        unlink.assert_not_called()

    def test_scan_failure_aborts_executable_before_mutation(self):
        import gpu_boot
        b,scan,write,unlink,calls,validate,deadline=self.mocked_main()
        scan.side_effect=RuntimeError('client scan failed')
        self.assertEqual(gpu_boot.main([]),1)
        b.write.assert_not_called(); b.checkpoint.assert_not_called()
        write.assert_not_called(); unlink.assert_not_called()
        self.assertEqual(calls,[])

    def test_ready_nv_nonready_intel_aborts_executable_before_mutation(self):
        import gpu_boot
        b,scan,write,unlink,calls,validate,deadline=self.mocked_main(ready=True)
        self.assertEqual(gpu_boot.main([]),1)
        b.write.assert_not_called(); b.checkpoint.assert_not_called()
        write.assert_not_called(); unlink.assert_not_called()
        self.assertEqual(calls,[])

    def test_termination_during_intel_unbind_recovers_and_removes_only_override(self):
        import gpu_boot
        b,scan,write,unlink,calls,validate,deadline=self.mocked_main(config=True)
        b.sleep.side_effect=[None, InterruptedError('SIGTERM'), None]
        self.assertEqual(gpu_boot.main([]),1)
        self.assertEqual(b.write.call_args_list[-1].args,
                         ('/sys/bus/pci/drivers/i915/bind','0000:00:02.0'))
        unlink.assert_called_once()
        write.assert_not_called()
        b.clear_checkpoint.assert_called_once()

    def test_stop_post_refuses_recovery_when_activation_lock_is_busy(self):
        from unittest.mock import patch
        import gpu_boot
        b,scan,write,unlink,calls,validate,deadline=self.mocked_main()
        b.read.return_value='intel_rebind'
        original_exists=Path.exists
        with patch.object(Path,'exists',lambda p: str(p)==gpu_boot.STATE or original_exists(p)), patch('fcntl.flock',side_effect=BlockingIOError('lock busy')):
            self.assertEqual(gpu_boot.main(['--recover']),1)
        b.write.assert_not_called(); b.clear_checkpoint.assert_not_called()

    def test_stop_post_removes_generated_override_after_interrupted_start(self):
        from unittest.mock import patch
        import gpu_boot
        b,scan,write,unlink,calls,validate,deadline=self.mocked_main(config=True)
        b.read.return_value='intel_rebind'
        original_exists=Path.exists
        def exists(path):
            return str(path)==gpu_boot.STATE or original_exists(path)
        with patch.object(Path,'exists',exists):
            self.assertEqual(gpu_boot.main(['--recover']),0)
        unlink.assert_called_once()
        self.assertEqual(deadline.call_args.args[0],20)
        self.assertEqual(b.write.call_args.args,('/sys/bus/pci/drivers/i915/bind','0000:00:02.0'))
        self.assertEqual(calls,[])

    def test_override_cleanup_error_does_not_escape_or_hide_original_failure(self):
        from unittest.mock import patch
        import io
        import gpu_boot
        b,scan,write,unlink,calls,validate,deadline=self.mocked_main(config=True)
        b.sleep.side_effect=InterruptedError('original timeout')
        unlink.side_effect=PermissionError('cleanup denied')
        stderr=io.StringIO()
        with patch('sys.stderr',stderr):
            self.assertEqual(gpu_boot.main([]),1)
        self.assertIn('original timeout',stderr.getvalue())
        self.assertIn('cleanup denied',stderr.getvalue())

    def test_activation_rejects_fixture_overrides_instead_of_ignoring_them(self):
        import gpu_boot
        b,scan,write,unlink,calls,validate,deadline=self.mocked_main()
        with self.assertRaises(SystemExit) as exited:
            gpu_boot.main(['--module-dir','/fixture'])
        self.assertEqual(exited.exception.code,2)
        validate.assert_not_called()
        b.write.assert_not_called()

    def test_check_only_never_runs_activation_or_writes_fixtures(self):
        import gpu_boot
        b,scan,write,unlink,calls,validate,deadline=self.mocked_main()
        with self.assertRaises(SystemExit) as exited:
            gpu_boot.main(['--check-only','--module-dir','/fixture','--kernel','fixture'])
        self.assertEqual(exited.exception.code,0)
        self.assertFalse(validate.call_args.kwargs['trusted'])
        self.assertEqual(validate.call_args.args,(Path('/fixture'),'fixture'))
        b.write.assert_not_called(); b.checkpoint.assert_not_called()
        deadline.assert_not_called(); write.assert_not_called(); unlink.assert_not_called()
        self.assertEqual(calls,[])

class BootOrdering(unittest.TestCase):
    def test_boot_splash_is_released_before_gpu_client_scan(self):
        unit=(Path(__file__).parent/'gpu-on-demand.service').read_text().splitlines()
        after=' '.join(line.split('=',1)[1] for line in unit if line.startswith('After='))
        self.assertIn('plymouth-start.service',after.split())
        quit_line='ExecStartPre=-/usr/bin/timeout 20s /usr/bin/plymouth quit'
        wait_line='ExecStartPre=-/usr/bin/timeout 20s /usr/bin/plymouth --wait'
        self.assertIn(quit_line,unit)
        self.assertIn(wait_line,unit)
        self.assertLess(unit.index(quit_line),unit.index(wait_line))
        start=next(i for i,line in enumerate(unit) if line.startswith('ExecStart='))
        self.assertLess(unit.index(wait_line),start)
        self.assertNotIn('Wants=plymouth-quit.service',unit)

if __name__=='__main__': unittest.main()
