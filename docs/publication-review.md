# Publication review

## Allowlisted contents

This package intentionally contains only English documentation, licensing,
two unmodified upstream patches and these reviewed reference files:

- `gpu_boot.py`
- `gpu_on_demand_disable.py`
- `test_boot.py`
- `test_safety.py`
- `gpu-on-demand.service`
- `gpu-on-demand-modprobe.conf`
- `99-nvidia-on-demand.conf`

The reference files are copies, not newly adapted hardware code. Six remain
byte-for-byte copies; only the disable helper's introductory docstring was
clarified for `python3 -Es` and possible service recovery-hook side effects.
The tests and policy files were reviewed before copying. No new production
utility was introduced; no TDD exception was needed for new utility code.

## Excluded material

Do not publish kernel sources, build artifacts, compiled modules, local
manifests, raw hardware inventories, diagnostics that run hardware at import,
logs, screenshots, networking information, machine serials, boot identifiers,
filesystem identifiers, or personal directory paths. Keep local evidence local.
The `.gitignore` is defense in depth, not a data-loss-prevention guarantee;
review every file before adding it, including any future workflow metadata.

## Verification completed during packaging

- 48 boot regression tests passed using temporary fixtures and mocked hardware
  mutation boundaries.
- Two source safety checks passed against an existing patched source tree,
  outside the publication payload. That tree is not shipped.
- All seven reference file copies initially matched their reviewed originals
  byte-for-byte; the disable helper subsequently received only the docstring
  clarification noted above. Both patch copies and the GPL text matched their
  reviewed originals byte-for-byte.
- Text scan for personal directory paths, network address literals and excluded
  system topics completed; local Markdown links checked for target existence.
- No activation helper was run against hardware, no service/configuration was
  installed, and no remote publish, Git commit or authentication occurred.

These checks do not establish that a first-time installation from this package
works on another machine. The manual guide describes the prior build approach;
source download, rebuild, privileged installation and a fresh hardware boot
were not repeated during publication preparation.

No GitHub Actions workflow is included in this first package. The named offline
unit-test command can be added to CI later without running hardware diagnostics.
Before remote publication, review the staged file list and diff explicitly.
