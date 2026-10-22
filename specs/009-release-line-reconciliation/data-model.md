<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Data model: Release-line reconciliation before 0.1.1-1

This feature adds no runtime data. Its "entities" are the release-engineering records it creates and
checks, together with the states they pass through. These are what `tasks.md` and the evidence files
track.

## Entities

### Release source

A git ref whose history must end up inside HEAD.

| Field | Values (2026-10-17) |
|---|---|
| `ref` | `origin/debian/bookworm`, `origin/rc_1`, `v0.1.0rc5-6` (`-s ours`, FR-008) |
| `commit` | `b8431a3`, `698e777`, `69e91e4` |
| `behind_count` | `git rev-list --count HEAD..<ref>`. **Rule: 0 at hand-off** (SC-001) |
| `measured_at` | timestamp of the fetch the count was taken on |

### Stray head

A branch head that is on neither line (the WO §4.1 sweep).

| Field | Notes |
|---|---|
| `sha`, `branch`, `author_date` | e.g. `35cbe78` `fix/node-output-maps-ignore-inputs` 2026-10-15 |
| `verdict` | `merge-by-sha` (#22, #23) · `sequenced-after-nodeconf` (#24) · `ancestry-only` (`v0.1.0rc5-6`) · `excluded` (rig build, `gh-pages`, `archive/*`) |
| `reason` | one line, recorded in `evidence/stray-head-sweep.md` |

**Rule**: every head the hand-off sweep finds has exactly one verdict.

### Released build

One `cuems-engine (<version>) <dist>; urgency=…` entry in a shipped `debian/changelog`.

| Field | Notes |
|---|---|
| `version` | Debian version, e.g. `0.1.0rc6-3` |
| `source_ref` | where the authoritative text lives: bookworm, `v0.1.0rc5-6`, or this branch (`rc1-1…rc2-3`) |
| `entry_bytes` | the entry text from its header line up to the next header |
| `changelog_md_anchor` | the `<!-- source: … -->` comment or inline `(version, date)` in `CHANGELOG.md` |

**Validation** (FR-030…FR-033):
- `version` ∈ the merged `debian/changelog`.
- The merged `entry_bytes` equal `source_ref`'s bytes.
- `changelog_md_anchor` exists.
- The order is by dpkg version, and `0.1.1-1` is on top.

### Inventory item

#1–#24 of the spec's inventory.

| Field | Notes |
|---|---|
| `id` | `#1`…`#24` |
| `method` | `M` · `R` · `A` · `D` (combinations allowed, e.g. `M + R`) |
| `seams` | adaptation ids (`A-1`…`A-8`, `R-1`…`R-4`, `X-1`) |
| `proof` | a test node id, or a recorded check (SC-002) |
| `state` | see the state machine below |

**State machine**:

```
pending ──merge/copy──▶ absorbed ──(seams?)──▶ adapted ──proof passes──▶ proven
   │                        └──────(no seams)───────────────────────────▲
   └──(#24 only)──▶ sequenced (lands after the cuems-nodeconf consolidation; FR-016a message written)
```

`proven` for every item except #24 is the hand-off condition. #24 ends as `sequenced`, or as
`proven` if the FR-007 safety net fires.

### Adaptation

A post-merge commit that brings absorbed code under the 008 contract.

| Field | Notes |
|---|---|
| `id` | `A-1`…`A-8`, `R-1`…`R-4` |
| `red_test` | the node id that fails on the merge commit, or is written first and fails |
| `red_evidence` | the failing output, captured before the fix (constitution II, step 2) |
| `commit` | exactly one GPG-signed commit (FR-061) |

**Rule**: `red_evidence` precedes `commit`. An adaptation with no red evidence is a constitution
violation.

### Strict xfail

| Field | Notes |
|---|---|
| `node_id` | the test |
| `obligation` | `FR-022 (cuems-utils 016)` for the lock test, or `X-1` |
| `reason` | **must contain** the upstream-report path |

**Allowed set** (SC-004): `test_lock_is_current.py::test_poetry_lock_is_current` ∪ {X-1 tests}. Nothing else.

### Test module placement

The FR-047 re-layout.

| Field | Notes |
|---|---|
| `old_path` | `tests/test_x.py` |
| `new_dir` | `unit` · `integration` · `contract` · `retired` |
| `signal` | why: real socket / NNG / pyossia / UDP / subprocess / JACK-ALSA / sleep ≥ 0.5 s / repo invariant / none |
| `pass_set_delta` | must be ∅, except retirements, which are listed in `evidence/test-retirements.md` |

### Gate run

| Field | Notes |
|---|---|
| `run_url`, `engine_sha`, `ref` | the dispatch on the 009 head |
| `cuemsutils_ref`, `cuemsutils_commit`, `cuemsutils_version` | logged by the job (research R1) |
| `counts` | passed / failed / skipped / xfailed / xpassed, per job |
| `strict_xfails` | list. It must equal the allowed set |
| `coverage_combined` | ≥ 45 % |
| `conclusion` | `success` is required (SC-010) |

### Outbound document

| Kind | Path | Addressee |
|---|---|---|
| upstream report | `upstream-reports/cuems-utils-x1-x4.md` | cuems-utils maintainers |
| structure message | `upstream-reports/rc_1-mock-nodeconf-structure.md` | #24's author, `rc_1` maintainer |
| sibling notes | `upstream-reports/{cuems-frontend,cuems-editor,cuems-power-bridge,cuems-nodeconf}-engine-contracts.md` | each sibling |
| layout note | `upstream-reports/rc_1-test-layout.md` | `rc_1` maintainer (FR-059) |
| tag message | `../.xml-refactor-tag-messages/cuems-engine.txt` | maintainer (re-cuts the tag) |
