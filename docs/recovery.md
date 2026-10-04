# Recovery and deliberate removal

Prepare recovery **before** enabling the reference unit. Keep a working kernel, rescue media, configuration backups, and tested SSH access independent of the graphical login. No procedure here guarantees recovery from every firmware/kernel failure.

The unit intentionally blocks the display manager when setup or bounded recovery fails. Do not defeat that dependency by starting graphics while the physical panel state is unknown. Do not unload Nouveau, unbind i915, or write gmux controls from a live graphical session.

## Interrupted activation with a trusted installed helper

From a trusted root administrative console/SSH session, inspect the service and its journal locally, plus `/run/gpu-on-demand/phase`. Do not upload the raw journal. The checkpoint records transition intent and is not proof that the write completed.

If activation is still running, let its bounded deadline/stop-post path finish or deliberately stop the unit. Stop-post may perform a bounded Intel rebind when an interrupted `intel_rebind` phase requires it. Recovery does not replace loaded modules or restore the original discrete-GPU state.

After the activation process has stopped, and after inspecting the installed root-owned helper and unit:

```sh
sudo python3 -I /usr/local/libexec/gpu_boot.py --recover
```

Recovery acquires the nonblocking activation lock, checks recognized checkpoints, and waits a bounded time for the Intel panel. It may rebind Intel once; it never repeats an unbind. If successful it clears the checkpoint and removes its own generated Xorg override. If recovery cannot prove panel availability, it returns failure and retains the checkpoint. Do not delete a checkpoint merely to bypass that guard, and do not retry unknown hardware writes blindly. Use rescue boot instead when state remains ambiguous.

With no checkpoint, `--recover` is not a general display repair tool. It does not undo the module blacklist, TLP policy, or service enable links.

## Normal deliberate disable

Only after recovery is complete and no unfinished checkpoint remains, invoke the installed disable helper from a trusted administrative working directory and a clean environment:

```sh
sudo python3 -Es /usr/local/libexec/gpu_on_demand_disable.py
```

It checks exact ownership markers and trusted paths for **both** the generated Xorg override and module policy before disabling/stopping the service. It rechecks after stopping and removes only its own marked files. It retains the helper, unit and per-kernel bundles for deliberate reinstallation. It refuses unknown/symlink/untrusted configuration rather than removing it.

The disable helper itself does not unload live GPU modules. However, its service stop can invoke the unit's recovery hook; unresolved recovery must be addressed first. Its adjacent-module import is why the command uses `-Es` (ignore Python environment overrides and user site packages) but not `-I` (which would hide the sibling helper). Use the root-owned installed copy, not an arbitrary script in a writable checkout.

**The disable helper does not remove the TLP override.** Inspect `/etc/tlp.d/99-nvidia-on-demand.conf`, compare it with your backed-up prior contents, and restore the previous file or remove only the exact file you installed if it was previously absent. Preserve unrelated configuration. Reapply policy only when appropriate for the current safe hardware state.

If the modprobe policy was embedded in the initramfs, regenerate the affected kernel's initramfs after restoring/removing that policy, using the distribution's supported tooling. Restoring the policy on the root filesystem alone may not restore early-boot driver behavior.

Verify locally:

```sh
systemctl is-enabled gpu-on-demand.service
systemctl show display-manager.service -p Requires
```

Check that the GPU service enable links no longer exist. Inspect the affected files and ensure that the previous policy is restored. Reboot deliberately to return to the distribution's normal module policy; do not attempt to transform a running graphics session by unloading drivers.

## Rescue boot when the helper cannot recover

Use a text/rescue target or rescue media, not a graphical login that depends on the failed GPU service. In a bootloader's one-time command-line edit, selecting `systemd.unit=multi-user.target` can avoid the graphical target; this is a recovery choice, not a persistent bootloader change made by this project. Availability of the panel/console still depends on the machine's actual hardware state. Use independent SSH or rescue media if necessary.

If using rescue media, identify and mount the installed root filesystem privately. Do not publish its identifiers. Work against that mounted installation, not the rescue system's own `/etc`.

1. Preserve local error evidence and backups; inspect the unit and checkpoint.
2. Disable the installed unit's enable links using the appropriate installed-system/offline systemd workflow. Review both `graphical.target.wants` and `display-manager.service.requires`; do not remove unrelated links.
3. Restore the backed-up Xorg, modprobe and TLP configuration. If a file was originally absent, remove only the exact helper-owned file after inspection.
4. Regenerate the intended installed kernel's initramfs if the module policy was embedded there, using the distribution's supported rescue/chroot procedure.
5. Reboot into a known-working kernel and verify normal display behavior before attempting another experiment.

Do not copy the old modules into a new kernel directory, spoof the manifest kernel, discard checkpoints blindly, or force `insmod` past version/signature errors. A failed safety gate is a reason to investigate, not an invitation to bypass it.

## Files affected by a deliberate installation

- `/usr/local/libexec/gpu_boot.py`
- `/usr/local/libexec/gpu_on_demand_disable.py`
- `/usr/local/lib/gpu-on-demand/<exact-kernel>/` (two modules and local manifest)
- `/etc/systemd/system/gpu-on-demand.service` and its enable links
- `/etc/modprobe.d/gpu-on-demand.conf`
- `/etc/X11/xorg.conf.d/91-gpu-on-demand.conf` (generated only by successful activation)
- `/etc/tlp.d/99-nvidia-on-demand.conf` (optional manual policy)
- `/run/gpu-on-demand/` (runtime lock/checkpoint)
- The affected initramfs, only if you deliberately regenerated it

No distribution driver replacement, EFI mutation or persistent GRUB edit is part of the reference. Removing policy files does not undo a previous physical mux transition immediately; use the controlled recovery/reboot path.
