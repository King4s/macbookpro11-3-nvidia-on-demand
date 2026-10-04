# Tested results and boundaries

## Evidence provenance

This is a deliberately sanitized account of prior tests on a single MacBookPro11,3. Raw journals, screenshots, per-machine manifests, and unrelated system investigations are not published. The results below are recorded observations supplied with the reference experiment; publication preparation only reran offline regression/source tests. Readers cannot independently reconstruct the complete hardware run from this package alone.

## Reference environment

- Apple MacBookPro11,3; Intel Iris Pro P5200 at `0000:00:02.0`.
- Nvidia GeForce GT 750M, GK107 (`10de:0fe9`), at `0000:01:00.0`; HDMI audio at `0000:01:00.1`.
- Ubuntu kernel `7.0.0-34-generic`; source package `linux-hwe-7.0` version `7.0.0-34.34~24.04.1`.
- Mesa `25.2.8`, TLP `1.6.1`, Xorg/LightDM.
- Both upstream fixes included in `patches/` were applied. Existing symbol-version CRC compatibility and all imported symbols were checked during the original build; loaded module note bytes were checked against the built modules.

## Observed outcomes

| Test | Observed outcome | Boundary |
| --- | --- | --- |
| Initial safe load | Patched Nouveau loaded with `modeset=1 runpm=0` | Not a safe hot-session operation |
| Physical routing | `MIGD` selected Intel; vgaswitcheroo software `+` remained unchanged | Do not infer physical routing from `+` |
| Intel reprobe | No-DRM-client guard allowed reprobe; Intel internal panel available | Refused while clients were present |
| Runtime reload | Clean Nouveau unload and load with `runpm=1` | Depends on patched teardown and no live clients |
| Explicit Nvidia application | Visible Android emulator window; SurfaceFlinger reported `NVE7` rendering | Not merely a renderer-string-only probe |
| After application exit | Nvidia returned to idle D3hot | No rail-off or watt measurement |
| Repeated context wake/idle | Repeated cycles passed | Not a stress or endurance test |
| Cold boot before LightDM | Greeter appeared after helper completed | One reference setup, not a benchmark guarantee |
| Scoped TLP policy | AC reapply plus three Nvidia rendering/idle cycles passed | New TLP file has not yet been retested through another cold boot |

One successful cold-boot measurement was **15.661 s** systemd total and **16.529 s** to the greeter. These have different observation endpoints. They are reference observations only; no claim is made that this package improves boot time or reproduces those timings elsewhere.

## Plymouth and TLP findings

Plymouth initially held a DRM client, correctly blocking the client guard. The reference unit orders after `plymouth-start.service` and explicitly runs bounded Plymouth quit then wait before the helper. It deliberately does not request `plymouth-quit.service` through `Wants`, because that arrangement conflicted with LightDM in the tested setup. Failure of either pre-command is tolerated; the helper's client guard remains authoritative.

TLP policy reapplication initially set Nvidia HDMI audio runtime PM to `on`, keeping the GPU awake despite the helper setting both functions to `auto`. The included override is scoped to `01:00.0 01:00.1` and does not change the global runtime-PM profile. **Review existing `RUNTIME_PM_ENABLE` assignments**: this is a replacement assignment, not a list append. Its next-cold-boot persistence remains unverified.

## What is not established

- D3cold, complete rail-off, measured energy savings, or battery-life gains.
- General PCI resume correctness. The patches address scheduler/entity teardown.
- Heavy GPU load, reclocking, suspend/resume, external display/HDMI behavior, audio use, long-term stability, or other MacBook models.
- Compatibility with another kernel, Wayland, another display manager, proprietary Nvidia drivers, Secure Boot module enforcement, or a different initramfs policy.
- That the boot helper is a universal model validator or a fully audited security boundary. Its hard-coded PCI layout requires manual preflight.
- That a missing new-kernel bundle preserves Nvidia offload. It safely skips activation, but the reviewed modprobe policy still applies until deliberately removed.

## Publication-time verification

- `python3 -m unittest test_boot -v`: **48 tests, OK**.
- `test_safety` against the pre-existing patched kernel source: **2 tests, OK**.
- Reference copies and upstream patch copies initially checked byte-for-byte against the reviewed originals. The disable helper subsequently received only an introductory docstring clarification; its executable logic remains unchanged.
- No hardware activation, root installation, Git commit, remote publishing, or authentication performed during packaging.

The source assertions check the public scheduler kill operation and absence of the double entity finalization; they do not prove runtime hardware behavior or general ABI safety. Boot tests primarily prove guard/control-flow behavior through mocked hardware boundaries.
