<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Merge of origin/debian/bookworm (T008–T017)

Source `origin/debian/bookworm` @ `3108b4f` (0.1.0rc6-6) into `de934d3`. Merge commit **`1c12959`**.

## Conflict list (T008)

`git diff --name-only --diff-filter=U` after `git merge --no-ff --no-commit`:

```
CLAUDE.md
debian/changelog
debian/control
pyproject.toml
src/cuemsengine/ControllerEngine.py
src/cuemsengine/__init__.py
tests/test_controller_commands.py
tests/test_nodelist_modify.py
```

**Difference from spec M4 (7 files): `CLAUDE.md` is extra.** Cause: M4 was measured on `e994a5e`; this
branch has since gained the `<!-- SPECKIT START -->` block at the end of `CLAUDE.md`, which collides with
the gotcha bullets bookworm appended there (rc6-3..rc6-5). It is not caused by the rc6-6 delta: that
delta's `CLAUDE.md` line (the A/V loop guarantee) auto-merged. Resolved by taking bookworm's bullets
(including its `enabled=`-aware canvas line) and keeping the SPECKIT block untouched. The other seven
are M4's list.

## Resolutions (FR-004)

| File | Hunks | Resolution |
|---|---|---|
| `ControllerEngine.py` | 2 | hunk 1 theirs (`script_finished` branch gone, `stop_project` kept); hunk 2 theirs' `{what} stalled` text with ours' `_sorted_ids(pending)` (module-level helper) |
| `tests/test_controller_commands.py` | 2 | theirs (`_loaded_script()`, `project_unix_name`, `set_status("load", …)`) |
| `tests/test_nodelist_modify.py` | 1 | ours (typed `adopted_network_map(...)`) |
| `pyproject.toml` | 2 | ours, plus the X-1 comment above the `cuemsutils` constraint |
| `src/cuemsengine/__init__.py` | 1 | ours (`0.1.1`) plus theirs' Ion Reguera contributor line |
| `debian/control` | 2 | ours for versioned `Depends`; theirs for the SPDX header, `Conflicts: cuems-audioplayer, cuems-dmxplayer` and the renamed mock binaries. `grep -nE "0\.1\.0rc17|>= 1\.0\.0\)|0\.1\.0rc2\)" debian/control` is empty |
| `debian/changelog` | 1 | ours' `0.1.1-1` on top; bookworm's `0.1.0rc6-6 … rc3-1` verbatim; ours' `rc2-3`; the shared `rc2-2 … rc1-1`. `dpkg-parsechangelog -S Version` → `0.1.1-1` |
| `CLAUDE.md` | 1 | see above |

**UUID_A (T010).** Bookworm's literal `aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee` is not a uuid4 (version
nibble `c`). It is replaced by 008's `aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee`; `uuid.UUID(UUID_A).version == 4`.

## Arm B (T017)

`suite-arm-B.txt`: **10 failed, 1395 passed, 1 xfailed** (pass 1); 32 passed (pass 2). `arm-B-failures.txt`
holds the 10 ids. `comm -13 arm-A-failures.txt arm-B-failures.txt` (arm A had no failures) is the same 10,
which are exactly `expected-reds.md`: A-1 ×1, A-2 ×5, A-3 ×2, A-4 ×1, A-6 ×1. **No new finding**: the
rc6-6 delta (the unload fix, `tests/test_node_unload_project.py`) merged green.
