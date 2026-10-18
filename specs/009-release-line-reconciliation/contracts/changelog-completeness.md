<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Contract C3: changelog completeness (`tests/contract/test_changelog_complete.py`)

**Implements** FR-030…FR-033 and SC-007, as clarified on 2026-10-17 (live refs, loud skip).
**Decisions** in research R2.

## Sources

| Name | Resolved by | Contributes |
|---|---|---|
| `bookworm` | `git rev-parse --verify origin/debian/bookworm` | every header in its `debian/changelog` |
| `rc_1` | `git rev-parse --verify origin/rc_1` | every header in its `debian/changelog` |
| tags | `git tag -l 'v0.1.0*'` (must be non-empty) | every header in each tag's `debian/changelog` (today `v0.1.0rc5-6` adds `rc5-2…rc5-6`) |

**If any source is missing**, the test calls `pytest.skip(f"missing refs: {missing}")`. The skip is
never silent; `gate-summary` lists it.

## Assertions

1. The top entry of the working-tree `debian/changelog` is `0.1.1-1`.
2. **Superset**: `versions(worktree) ⊇ versions(bookworm) ∪ versions(rc_1) ∪ ⋃ versions(tag)`.
   The failure message lists the missing versions.
3. **Byte identity**: for each version first released on a source, the worktree entry equals that
   source's entry byte for byte. This covers `rc3-1…rc6-5` against bookworm and `rc5-2…rc5-6`
   against `v0.1.0rc5-6`. The entry is the text from its header line to the line before the next
   header.
4. **Order**: the entries are in strictly descending dpkg version order, compared with
   `dpkg --compare-versions` if present, otherwise with a `debian_version`-style comparison
   implemented in the test helper. Released history that is *date*-inverted (`rc2-3` below `rc3-1`)
   is allowed.
5. **`CHANGELOG.md`**: every version from assertion 2 appears either in a `<!-- source: … <version>
   … -->` comment or as an inline `(<version>, YYYY-MM-DD)`. The first `## v…` header is `v0.1.1`,
   and the `v0.1.1` section does not contain "not reconciled" (case-insensitive).

## Red-first

On the branch before FR-008 copies the five hotfix entries, assertion 2 fails and lists
`0.1.0rc5-2…rc5-6`. Before FR-032, assertion 5 fails. Both failures are captured as red evidence.
