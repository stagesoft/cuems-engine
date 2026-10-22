<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# CHANGELOG.md audit against debian/changelog (T052)

Each build of the merged `debian/changelog` and where `CHANGELOG.md` names it (a `<!-- source: … -->` comment or an
inline `(<version>, date)`). Checked by `tests/test_changelog_complete.py::test_changelog_md_names_every_released_build`.

| Build | CHANGELOG.md section | Named by |
|---|---|---|
| `0.1.1-1` | v0.1.1 | this release (top entry) |
| `0.1.0rc6-6` | v0.1.0rc6 | source comment |
| `0.1.0rc6-5` | v0.1.0rc6 | source comment |
| `0.1.0rc6-4` | v0.1.0rc6 | source comment |
| `0.1.0rc6-3` | v0.1.0rc6 | source comment |
| `0.1.0rc6-2` | v0.1.0rc6 | source comment |
| `0.1.0rc6-1` | v0.1.0rc6 | source comment |
| `0.1.0rc5-6` | v0.1.0rc5 | source comment |
| `0.1.0rc5-5` | v0.1.0rc5 | source comment |
| `0.1.0rc5-4` | v0.1.0rc5 | source comment |
| `0.1.0rc5-3` | v0.1.0rc5 | source comment |
| `0.1.0rc5-2` | v0.1.0rc5 | source comment |
| `0.1.0rc5-1` | v0.1.0rc5 | source comment |
| `0.1.0rc4-1` | v0.1.0rc4 | source comment |
| `0.1.0rc3-2` | v0.1.0rc3 | source comment |
| `0.1.0rc3-1` | v0.1.0rc3 | source comment |
| `0.1.0rc2-3` | v0.1.0rc2 | source comment |
| `0.1.0rc2-2` | v0.1.0rc2 | source comment |
| `0.1.0rc2-1` | v0.1.0rc2 | source comment |
| `0.1.0rc1-1` | v0.1.0 | source comment |

Known unverified rows before this task: `0.1.0rc2-3` (the mock rsync shim) and `0.1.0rc1-1`. Both were absent from
`CHANGELOG.md`; now named in the `v0.1.0rc2` section (a source comment and a "Packaging builds" paragraph) and in the
`v0.1.0` section. The Debian entries for `0.1.0rc2-1` and `0.1.0rc2-2` were absent as well and are named in the same
places. `rc3-1` / `rc3-2`, `rc4-1` and `rc5-1` / `rc6-1` already carried source comments.
