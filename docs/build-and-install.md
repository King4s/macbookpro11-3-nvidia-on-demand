# Manual build and installation reference

**Do not paste this page as one script.** Each section is a separate review gate. Root commands below describe a deliberate installation on an eligible machine; they are not part of the offline tests. No installer is provided. The repository contains reference copies, not a universal laptop service.

Read [recovery](recovery.md) first. Back up affected configuration and keep a working kernel, rescue media and tested SSH recovery. Module loading, gmux selection and i915 reprobe can blank the panel. Stop if the machine, kernel, symbol versions or module ownership differ from the reference. Do not unload graphics modules from an active desktop.

## 1. Read-only model and PCI preflight

Inspect these locally; do not upload raw hardware inventories:

```sh
cat /sys/class/dmi/id/product_name
uname -r
lspci -nn -s 00:02.0
lspci -nn -s 01:00.0
lspci -nn -s 01:00.1
cat /sys/bus/pci/devices/0000:01:00.0/vendor
cat /sys/bus/pci/devices/0000:01:00.0/device
readlink /sys/bus/pci/devices/0000:00:02.0/driver
```

**Required manual guard:** product name must be `MacBookPro11,3`; GPU vendor/device must be `0x10de` / `0x0fe9` at `0000:01:00.0`; its Nvidia HDMI audio sibling must exist at `0000:01:00.1`; Intel Iris Pro P5200 must exist at `0000:00:02.0` and use i915. The reference kernel is exactly `7.0.0-34-generic`. Confirm the internal panel topology and the Xorg/LightDM setup. This page is not validated for any other kernel or hardware layout.

**The helper does not enforce DMI/vendor/device identity.** Its PCI paths are hard-coded. Its `--check-only` mode is a read-only plan/manifest check, not a replacement for this model guard or a complete security/ABI preflight. It reads live DRM/module state and may refuse while a desktop is active; that refusal is expected.

Check for other GPU policies, proprietary drivers, existing Xorg overrides, Secure Boot restrictions, and earlier initramfs driver loading. Do not overwrite someone else's files. Decide on a trusted module signing procedure if signature enforcement applies; this experiment is not verified under enforced Secure Boot. Do not disable security protections merely to make this reference run.

## 2. Obtain exact Ubuntu source and headers

Use an unprivileged local checkout/work directory. Install matching headers and reviewed build tools through your distribution package manager as a separate administration step. The reference used `x86_64-linux-gnu-gcc-13`, GNU make, binutils, and the configured Ubuntu headers/build tree at `/lib/modules/7.0.0-34-generic/build`. A `modules_prepare` run on arbitrary upstream source does not replace Ubuntu's matching configuration and symbol-version data.

Prefer APT source retrieval using authenticated Ubuntu source repository metadata and the pinned package version:

```sh
mkdir -p source
cd source
apt-get source linux-hwe-7.0=7.0.0-34.34~24.04.1
```

This requires appropriate `deb-src` entries and availability of the pinned source version. Inspect the extracted tree, then arrange that exact source tree at `source/linux` beneath the repository root. Do not select a nearby version silently. Return to the repository root before the following sections.

The reference source descriptor names these files:

- `linux-hwe-7.0_7.0.0-34.34~24.04.1.dsc`
- `linux-hwe-7.0_7.0.0.orig.tar.gz`
- `linux-hwe-7.0_7.0.0-34.34~24.04.1.diff.gz`

A mirror used in the original experiment was [mirror.group.one's linux-hwe-7.0 pool](https://mirror.group.one/ubuntu/pool/main/l/linux-hwe-7.0/). If using a mirror instead of APT, independently authenticate the descriptor against trusted Ubuntu keys/metadata, verify the descriptor's checksums, and use `dpkg-source -x` so the Ubuntu delta is included. Do not trust a downloaded descriptor merely because its hashes match its neighboring downloads. The original descriptor declares these SHA-256 values:

| File | SHA-256 |
| --- | --- |
| Original tarball | `c6343795c8c7e4feff55f5b309365c8e0eaf49cd6abcb412e32315313f149536` |
| Ubuntu diff | `81b9d83f6863ea9d41bde191923134fe6bf4261bfcf94a376b85c094fafd6c32` |

These are provenance aids, not substitutes for source authentication. Kernel source, archives and build products remain local and ignored.

## 3. Review and apply the two upstream patches

From the repository root, inspect the entire patch messages and target source before applying:

```sh
patch --dry-run -d source/linux -p1 < patches/nouveau-scheduler-export.patch
patch -d source/linux -p1 < patches/nouveau-scheduler-export.patch
patch --dry-run -d source/linux -p1 < patches/nouveau-teardown-fix.patch
patch -d source/linux -p1 < patches/nouveau-teardown-fix.patch
```

Stop on failed/reversed/already-applied hunks, offsets or unexpected changes. Investigate rather than forcing them. The first patch exports and declares `drm_sched_entity_kill`; the second calls it in `nouveau_abi16_chan_fini` instead of directly finalizing the scheduler entity twice. They are teardown fixes, not a general runtime-resume solution. Do not apply them again to kernels that already contain them.

## 4. Build against the exact installed kernel

From the repository root:

```sh
KERNEL=7.0.0-34-generic
SRC="$PWD/source/linux"
SCHED="$SRC/drivers/gpu/drm/scheduler"
NOUVEAU="$SRC/drivers/gpu/drm/nouveau"
KFLAGS="-include $SRC/include/drm/gpu_scheduler.h -I$SRC/include/trace"
make -C "/lib/modules/$KERNEL/build" M="$SCHED"     CC=x86_64-linux-gnu-gcc-13 KCFLAGS="$KFLAGS" modules
make -C "/lib/modules/$KERNEL/build" M="$NOUVEAU"     CC=x86_64-linux-gnu-gcc-13 KCFLAGS="$KFLAGS"     KBUILD_EXTRA_SYMBOLS="$SCHED/Module.symvers" modules
```

The source path must not contain whitespace for these reference include flags. The forced include uses the patched scheduler API while building against the installed Ubuntu build tree. The scheduler's `Module.symvers` supplies the newly exported symbol to Nouveau's modpost stage. A missing-symbol/CRC/type mismatch is a stop condition, not a warning to suppress.

Before any insertion, inspect both modules:

```sh
modinfo "$SCHED/gpu-sched.ko"
modinfo "$NOUVEAU/nouveau.ko"
modprobe --dump-modversions "$SCHED/gpu-sched.ko"
modprobe --dump-modversions "$NOUVEAU/nouveau.ko"
```

Manually compare every existing imported symbol's version CRC against the exact installed build tree's `Module.symvers`. For Nouveau's new `drm_sched_entity_kill` import use the newly built scheduler's `Module.symvers`. Verify all imported symbols have providers, matching vermagic, reviewed dependencies, compiler/configuration compatibility and any required signatures. Review the full `modprobe --show-depends` closure for prerequisite modules: it must not autoload either stock GPU module or execute opaque install hooks. The helper performs this last closure guard too; hashes alone do not prove ABI compatibility.

The original experiment checked these conditions and loaded-note identity. This package does not rebuild or reverify your kernel ABI automatically. New kernel versions need a new build and review, not renamed old modules.

## 5. Prepare a local bundle and manifest (offline)

Do not copy a live machine manifest from elsewhere. Create a fresh local bundle from your reviewed build; the module files are deliberately not shipped:

```sh
mkdir -p bundle
cp "$SCHED/gpu-sched.ko" "$NOUVEAU/nouveau.ko" bundle/
```

Complete any transformative processing (such as stripping) **before** final signing. If signing is required, sign the final bundle modules **before** final hashing; do not modify them afterward. From the repository root, extract the complete GNU build-ID **note section** without rewriting the input modules and inspect its hex encoding:

```sh
objcopy --dump-section .note.gnu.build-id=bundle/gpu_sched.note bundle/gpu-sched.ko /dev/null
objcopy --dump-section .note.gnu.build-id=bundle/nouveau.note bundle/nouveau.ko /dev/null
sha256sum bundle/gpu-sched.ko bundle/nouveau.ko
xxd -p -c 0 bundle/gpu_sched.note
xxd -p -c 0 bundle/nouveau.note
```

The explicit `/dev/null` output is required: omitting the output file makes `objcopy` rewrite the input in place and can strip an appended module signature. Check each command succeeds and independently confirm the input hashes are unchanged across extraction. Verify any required signatures on the final files using your trusted signing procedure; note extraction alone is not signature verification.

Create `bundle/manifest.json` manually in an editor with this schema, substituting every placeholder using the preceding output:

```json
{
  "kernel": "7.0.0-34-generic",
  "modules": {
    "gpu-sched.ko": "REPLACE_WITH_SHA256_OF_FINAL_MODULE",
    "nouveau.ko": "REPLACE_WITH_SHA256_OF_FINAL_MODULE"
  },
  "build_ids": {
    "gpu_sched": "REPLACE_WITH_HEX_OF_COMPLETE_GPU_SCHED_NOTE_SECTION",
    "nouveau": "REPLACE_WITH_HEX_OF_COMPLETE_NOUVEAU_NOTE_SECTION"
  }
}
```

`build_ids` here means **all note bytes**, including ELF note headers/padding, not just the shorter `readelf -n` Build ID digest. The module filenames use `gpu-sched`; the loaded sysfs module key uses `gpu_sched`. If either note is absent, stop. Verify JSON and independently recheck the final module hashes against the manifest and any required signatures before installation. Any subsequent module change requires final signing, hashing and manifest verification again. No new manifest utility is included; manual preparation avoids introducing untested privileged tooling.

## 6. Run offline regression and source checks

Run the boot tests as described in the README. For source assertions, arrange the local patched tree at `reference/source/linux`, or use a local symlink to your prepared `source/linux`. Do not publish that tree or symlink. From `reference/`, run the named `test_safety` module. The two checks are additional source gates, not a full kernel test suite.

An optional read-only plan check from the repository root is:

```sh
python3 reference/gpu_boot.py --check-only     --module-dir "$PWD/bundle" --kernel 7.0.0-34-generic
```

Do not run the helper without `--check-only` as a test. This check inspects live state and can fail on DRM access or active-client guards. It skips installation ownership checks, does not verify hardware identity, and does not validate every build-ID field before all later paths. Review the manifest yourself. Success is not permission to mutate a running desktop.

## 7. Deliberate manual installation, only after all review gates

Record backups and the prior absence/presence of every affected file. Check for existing unrelated owners before copying anything. The local bundle, helpers, unit and **all lexical ancestor directories** must be root-owned, not group/world-writable, and not symlinks. The service must be installed at `/etc/systemd/system/gpu-on-demand.service`, not only in a vendor unit directory. The service supplies a root-only runtime directory.

The following are individual manual operations for an administrator, not an installer. From the reviewed repository root:

```sh
sudo install -d -o root -g root -m 0755 /usr/local/libexec
sudo install -d -o root -g root -m 0755 /usr/local/lib/gpu-on-demand/7.0.0-34-generic
sudo install -d -o root -g root -m 0755 /etc/X11/xorg.conf.d
sudo install -o root -g root -m 0644 reference/gpu_boot.py /usr/local/libexec/gpu_boot.py
sudo install -o root -g root -m 0644 reference/gpu_on_demand_disable.py /usr/local/libexec/gpu_on_demand_disable.py
sudo install -o root -g root -m 0644 reference/gpu-on-demand.service /etc/systemd/system/gpu-on-demand.service
sudo install -o root -g root -m 0644 bundle/gpu-sched.ko bundle/nouveau.ko bundle/manifest.json /usr/local/lib/gpu-on-demand/7.0.0-34-generic/
```

Do not start the service in the current graphics session. The unit invokes the boot helper with Python isolated mode. The disable helper imports its adjacent helper normally; invoke only the installed root-owned copies from a trusted administrative working directory with a clean environment, never from an untrusted checkout.

Inspect and back up `/etc/modprobe.d/gpu-on-demand.conf`. If absent or deliberately replaced after review, install the policy:

```sh
sudo install -o root -g root -m 0644 reference/gpu-on-demand-modprobe.conf /etc/modprobe.d/gpu-on-demand.conf
```

It blocks stock Nouveau autoload and ordinary stock `gpu_sched` loading. This is not scoped by PCI identity and can affect other consumers of the shared scheduler. Stop if any other GPU depends on it. It does not unload already loaded modules. The reference does not replace distribution modules in `/lib/modules` or change EFI/GRUB.

Inspect TLP configuration precedence and all existing `RUNTIME_PM_ENABLE` lists before optionally installing the Nvidia-only override at `/etc/tlp.d/99-nvidia-on-demand.conf`. Preserve any earlier lists deliberately; the supplied assignment replaces the list and must not silently discard another device's required policy. Its AC reapply was tested, but persistence through the next cold boot remains unverified.

```sh
sudo install -o root -g root -m 0644 reference/99-nvidia-on-demand.conf /etc/tlp.d/99-nvidia-on-demand.conf
```

If the stock driver can be loaded from the initramfs, refresh the intended kernel's initramfs after reviewing/backing up the policy, and inspect its contents/policy before boot. This distribution-specific step is commonly `sudo update-initramfs -u -k 7.0.0-34-generic`; keep an independent recovery path. An early stock load causes the helper to refuse replacement. Do not remove distribution drivers as a shortcut.

Review the unit, then explicitly enable it **without `--now`**:

```sh
sudo systemctl daemon-reload
sudo systemctl enable gpu-on-demand.service
readlink /etc/systemd/system/display-manager.service.requires/gpu-on-demand.service
readlink /etc/systemd/system/graphical.target.wants/gpu-on-demand.service
systemctl cat gpu-on-demand.service
systemctl show display-manager.service -p Requires -p After
```

Verify both enable links and the effective display-manager dependency/order. A WantedBy-only link is insufficient: setup or recovery failure must block the display manager. Review any local overrides. Only then choose a controlled reboot into the exact reviewed kernel with SSH/rescue access available.

## 8. Verify outcomes locally

After the controlled boot, verify unit success and the connected eDP panel's device ancestry points to Intel `0000:00:02.0`. Confirm `nouveau` has `modeset=1`, `runpm=1`, and both loaded note sections match the manifest:

```sh
systemctl status gpu-on-demand.service --no-pager
cat /sys/module/nouveau/parameters/modeset
cat /sys/module/nouveau/parameters/runpm
xxd -p -c 0 /sys/module/gpu_sched/notes/.note.gnu.build-id
xxd -p -c 0 /sys/module/nouveau/notes/.note.gnu.build-id
cat /sys/bus/pci/devices/0000:01:00.0/power/control
cat /sys/bus/pci/devices/0000:01:00.1/power/control
cat /sys/bus/pci/devices/0000:01:00.0/power/runtime_status
cat /sys/bus/pci/devices/0000:01:00.0/power_state
```

The target is Nvidia runtime suspension and reported D3hot after application exit, while the Intel desktop remains usable. Runtime `suspended` by itself is not proof of D3cold or rail-off. DRM card numbers can change; map render nodes through their PCI ancestry instead of assuming `card1` or `renderD129`.

Run a deliberately selected application with `DRI_PRIME=1` only after verifying that selection maps to Nvidia on this machine. Confirm actual rendering and visible operation, then close it and recheck idle state. If TLP is installed, deliberately reapply the applicable AC/battery policy and repeat the checks. Do not infer heavy-load or suspend/resume stability from short context cycles. Keep local logs private; publish only sanitized observations.

## Kernel updates

There is no DKMS or automatic rebuild. For a new kernel, an absent bundle causes activation to skip before GPU hardware mutation, removing only the helper-marked Xorg file. The module blacklist/install policy remains in place. That is **not** a stock Nvidia fallback, and offload may be unavailable. To restore normal policy use the reviewed disable/recovery procedure, or build/review a fresh exact-kernel bundle before a controlled reboot. A present but corrupt/untrusted bundle is an error and fails closed rather than being treated as a benign skip.
