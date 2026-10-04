# Component licensing

| Component | Distribution terms / provenance |
| --- | --- |
| Project-owned README, docs, Python helpers/tests, service, policy files and repository metadata | MIT; full text in `../LICENSE` |
| `patches/nouveau-scheduler-export.patch` and `patches/nouveau-teardown-fix.patch` | Upstream Linux kernel patch material, distributed here under GPL-2.0-only; full Linux license text in `GPL-2.0-only.txt` |
| Affected upstream source-file notices | Existing permissive notices are retained in `upstream-permissive-notices.txt`; they are not erased by the patch distribution classification |

The GPL file is copied verbatim from the reference Ubuntu/Linux source tree's `LICENSES/preferred/GPL-2.0`, including its SPDX usage metadata and complete license text. The patch messages remain unmodified with author/date/commit identity, sign-offs and original upstream links.

The affected upstream files (`sched_entity.c`, `gpu_scheduler.h`, and `nouveau_abi16.c`) have permissive copyright/license headers in the reviewed source. Those file-level rights remain in force; referring to this patch package as GPL kernel material does not assert that all Linux files have one license or that the project owns upstream work. Build outputs form part of the Linux module distribution context and are **not** covered by the project-owned MIT grant merely because the repository also contains MIT helpers.

No kernel source tree or module binary is distributed here. Anyone redistributing built kernel modules must review and meet applicable corresponding-source and licensing obligations. Attribution alone is not a substitute for those obligations. This repository is not legal advice.
