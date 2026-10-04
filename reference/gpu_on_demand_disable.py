"""Reversible maintenance: disable gpu-on-demand and remove its marked policies.

Install beside gpu_boot.py at /usr/local/libexec/gpu_on_demand_disable.py;
invoke with sudo python3 -Es /usr/local/libexec/gpu_on_demand_disable.py (no SUID).
Retains the unit, helper, module bundles and backups for deliberate reinstallation.
Does not directly unload drivers or change live GPU hardware, distro drivers,
EFI or GRUB. Stopping the service can invoke its recovery hook, which may rebind
GPU hardware if a recovery checkpoint is pending; recover before disabling.
"""
import os
import sys
from pathlib import Path
from gpu_boot import command, owned_file, STATE as BOOT_STATE

XORG = Path('/etc/X11/xorg.conf.d/91-gpu-on-demand.conf')
POLICY = Path('/etc/modprobe.d/gpu-on-demand.conf')
STATE = Path(BOOT_STATE)
XORG_MARKER = '# Managed by gpu-on-demand; remove when disabling its service.\n'
POLICY_MARKER = '# Managed Nvidia on-demand modules: load reviewed per-kernel copies explicitly.\n'


def main():
    try:
        if os.geteuid() != 0:
            raise PermissionError('maintenance requires root')
        # Check BOTH ownership markers before disabling or removing anything.
        files = [(XORG, XORG_MARKER), (POLICY, POLICY_MARKER)]
        for path, marker in files:
            owned_file(path, marker)
        if STATE.exists() or STATE.is_symlink():
            raise RuntimeError('unfinished recovery checkpoint; recover before disabling')
        # systemctl disable removes the unit's RequiredBy dependency links too.
        command(['/usr/bin/systemctl', 'disable', '--now', 'gpu-on-demand.service'])
        if STATE.exists() or STATE.is_symlink():
            raise RuntimeError('recovery checkpoint remains; refusing policy removal')
        # Stop-post may have removed Xorg. Recheck both targets after stopping.
        removable = [path for path, marker in files if owned_file(path, marker)]
        for path in removable:
            path.unlink()
        print('gpu-on-demand disabled; owned policies removed; live drivers unchanged.')
        return 0
    except Exception as exc:
        print('gpu-on-demand: ' + str(exc), file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
