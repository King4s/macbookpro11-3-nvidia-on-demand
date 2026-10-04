# MacBookPro11,3: Nvidia GT 750M Nouveau on-demand runtime PM

A model-specific reference experiment for an **Intel-rendered internal desktop**, with the **Nvidia GeForce GT 750M (GK107)** available for explicitly offloaded applications and returning to **D3hot** when idle.

**Experimental, not a general laptop fix or an automatic installer.** The reference boot helper performs privileged GPU module loading, physical display mux selection, and potentially i915 unbind/rebind. Incorrect use can leave the display unavailable or prevent the display manager from starting. Read the code, [build/preflight guide](docs/build-and-install.md), and [recovery procedure](docs/recovery.md) before installing anything. Have backups, a known-working kernel, rescue media, and independently tested SSH access.

## Tested scope

| Component | Reference environment |
| --- | --- |
| Machine | Apple MacBookPro11,3 |
| Discrete GPU | Nvidia GT 750M / GK107, PCI `0000:01:00.0`, `10de:0fe9` |
| HDMI audio | Nvidia function at `0000:01:00.1` |
| Integrated GPU | Intel Iris Pro P5200, PCI `0000:00:02.0` |
| Kernel | Ubuntu `7.0.0-34-generic` |
| Ubuntu kernel source | `linux-hwe-7.0`, `7.0.0-34.34~24.04.1` |
| Mesa / TLP | `25.2.8` / `1.6.1` |
| Display setup | Xorg / LightDM; internal panel on Intel |

Prior machine testing observed Nvidia application rendering, repeated wake/idle cycles, idle **D3hot**, and a successful cold boot. See [tested results and limitations](docs/tested-results.md). These are observations on one reference machine, not a promise of portability or long-term stability. The TLP override passed an AC policy reapply and three rendering cycles; its next-cold-boot persistence has **not** been tested.

D3hot is the accepted outcome here. This project does **not** claim D3cold, gmux rail-off, measured watt savings, a battery-life improvement, or a universal PCI resume fix. The two upstream patches fix scheduler exposure and Nouveau ABI16 teardown, not PCI power management in general.

## How the reference sequence works

1. Before the display manager starts, release Plymouth with bounded quit/wait commands and check for DRM clients.
2. When the Intel panel is not already available, load the patched Nouveau with `modeset=1 runpm=0`.
3. Request physical Intel mux selection with `MIGD`. A vgaswitcheroo `+` marker alone is **not** proof of physical routing.
4. Reprobe i915 only after another no-client check and verify Intel ownership of the connected internal panel.
5. Cleanly unload/reload the patched Nouveau with `modeset=1 runpm=1`.
6. Set both Nvidia GPU and HDMI audio runtime power controls to `auto`; keep Xorg on Intel.

A ready setup avoids reprobe. Failures gate the display manager through a systemd **Requires** dependency; bounded recovery aims to restore the Intel panel, not the original GPU state. An absent bundle for a new kernel skips Nvidia activation and removes only the helper's own marked Xorg configuration; it does not install a stock fallback or undo the module policy.

## What is included

- `reference/`: exact reviewed copies of the tested Python helpers, systemd unit, modprobe policy, scoped TLP override, and explicit unit-test modules.
- `patches/`: two unmodified upstream patch messages, preserving authors, sign-offs, and links.
- `docs/`: tested observations, manual build/install steps, recovery, and publication review.
- `LICENSES/`, `LICENSE`, `NOTICE`: component-specific licensing and upstream attribution.

No kernel source tree, compiled modules, live manifest, hardware-running diagnostic scripts, logs, images, or machine identifiers are included. There is no root installer, remote download-and-execute command, or automatic enable action.

## Safe local regression tests

From the repository root, use Python 3 and run the named module:

```sh
cd reference
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_boot -v
```

The 48 boot regression tests mock hardware mutation boundaries and use temporary fixture files. Some deliberately rejected operations print errors; a passing run ends in `OK`. Do **not** substitute broad discovery in a directory containing unrelated live diagnostic scripts.

`test_safety` contains two optional source-level assertions, not hardware tests. It requires a locally prepared, patched kernel tree at `reference/source/linux` (ignored and not distributed):

```sh
cd reference
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_safety -v
```

The publication preparation ran all 48 boot tests successfully and both source assertions successfully against the existing patched source tree. It did not repeat hardware experiments or install this package.

## Upstream work and licensing

The fixes are by **Philipp Stanner**, suggested by and signed off by **Danilo Krummrich**:

- [`2f5f05633e2229c8ec379e1d65151165c905671e`](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=2f5f05633e2229c8ec379e1d65151165c905671e): make `drm_sched_entity_kill()` public.
- [`cac96c8d93faa073456fbb3a504b2a3d15d51841`](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=cac96c8d93faa073456fbb3a504b2a3d15d51841): avoid the double `drm_sched_entity_fini()` call in Nouveau ABI16 teardown.

Related community research: [joaodriessen's MacBookPro11,3 hybrid GPU results](https://github.com/joaodriessen/macbookpro11-3-cachyos/blob/main/docs/hybrid-gpu-results.md). Credit is not a claim of endorsement, identical configuration, or independent verification of these results.

Project-owned helpers, tests, configuration and documentation are MIT-licensed. Linux kernel patch material is distributed under GPL-2.0-only with upstream notices retained; affected upstream files also carry permissive notices. **The root MIT license does not relicense kernel material.** See [NOTICE](NOTICE) and [component licensing](LICENSES/README.md).

## Reporting results safely

State the model, PCI IDs, kernel/source version, Mesa/TLP versions, and whether the internal panel remains on Intel. Distinguish runtime status from actual PCI power state. Describe failures and recovery without uploading raw journals or manifests. Remove hostnames, network addresses, serials, boot identifiers, filesystem UUIDs and personal paths before posting. Do not claim success for suspend/resume or heavy load without testing it.
