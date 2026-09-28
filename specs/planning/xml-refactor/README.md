<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# `cuems-engine` — planning bundle for the `cuemsutils` public-API migration

**Assembled** 2026-09-25 from `cuems-utils@b7db53e` (branch `feat/xml-refactor`), whose
`specs/planning/xml-rebuild/010-consumer-prompts/01-cuems-engine.md` is the upstream original.

**Purpose**: make this repository's spec-driven work **self-contained**. Everything the flow needs
is here; the sibling `cuems-utils` checkout is no longer required reading.

## Start here

Read **[`00-runnable-flow.md`](00-runnable-flow.md)** and run it. It is a complete spec-kit flow —
branch, the constitution check, the `/speckit.specify` → `implement` chain, and exit criteria. It
names the feature **`008-cuems-utils-migration`**.

The other files are what its CONTEXT block asks for, brought in-repo.

| File | What it is | Why you need it |
|---|---|---|
| [`00-runnable-flow.md`](00-runnable-flow.md) | The flow itself | The SDD |
| [`01-settled-decisions.md`](01-settled-decisions.md) | The decisions that bind **this** repository, plus FR-030a-i/ii | Do not reopen these. The full list of 36 lives upstream; this is the binding subset |
| [`02-consumer-audit-findings.md`](02-consumer-audit-findings.md) | C7 and C11 — this repository's two findings from the 2026-09-03 consumer audit | What the audit measured here, and why |
| [`03-migration-inventory.md`](03-migration-inventory.md) | Every call site, **re-measured 2026-09-25** against the live tree | Your working inventory. Every line number upstream recorded has moved |
| [`04-findings-new-to-this-pass.md`](04-findings-new-to-this-pass.md) | Five findings the upstream flow could not know | Two are live defects independent of this migration; **F2a is the three-repository branch cluster this feature's base belongs to**. Read before scoping |
| [`05-session-prompt.md`](05-session-prompt.md) | A paste-ready prompt that starts this feature in a fresh agent session or on another machine | Use it instead of explaining the above by hand. It carries the base-branch decision, the sequencing verdict, the four non-negotiables and the out-of-scope list |

## The one thing to understand before starting

**The dangerous caller class is the one that keeps working.** 007 FR-030a-ii distinguishes callers
that *stop resolving* (loud, at import) from callers that *keep resolving and become wrong* (silent,
and the suite stays green). This repository holds three of the second kind, and the reason they
matter is what the sibling `cuems-power-bridge` demonstrated in the field: the same class of defect
there resolved **zero** nodes, skipped the reachability poll entirely, and armed a relay that cut
mains power to a cluster nothing had told to shut down. It logged one INFO line.

Nothing here is that physical. But `_controller_ip_from_map` raising *"No controller node found in
network map"* on a map that plainly contains one is the same shape, and no test catches it today
because the fixtures are written in the retired vocabulary — the suite is green **because** it
certifies the defect.

This repository's own constitution already requires the discipline that finds them: **II, TDD
non-negotiable**. Every FR-030a-ii site gets a test that fails against the old value *first*. Cite
the constitution rather than re-arguing it.

## Branch base — changed from the upstream flow, by decision

Upstream flow 01 says base `feat/xml-refactor` on **`rc_1`**. That was correct on 2026-09-03 and is
not correct now: this repository has since put six commits on `feat/nodelist-modify-dispatch`,
landing the adopt/un-adopt hop and runtime cluster liveness (+432 lines in `ControllerEngine.py`,
two new test files ≈909 lines).

**Decision 2026-09-25: base on `feat/nodelist-modify-dispatch`.** Two reasons, and the second is the
load-bearing one:

1. Basing on `rc_1` abandons six unreleased commits, which then get migrated separately or land
   unmigrated.
2. **The new code is itself a migration target.** It added a *second* `get_nodes_by_adoption` call
   site (`ControllerEngine.py:287`) and two docstrings that carefully document the mutation hazard —
   it built *around* the deprecated mutating API rather than off it. Migrating from `rc_1` would
   produce a branch that conflicts with exactly the code this feature exists to replace.

**And the branch is not this repository's alone.** It is one third of an unmerged three-repository
feature from 2026-09-04, whose other halves are `cuems-editor`'s `feat/nodelist-adoption-api` and
`cuems-nodeconf`'s `feat/nodelist-modify-hardening` — with **no UI tier at all**. That makes
`cluster_status` and `cluster_warning` cross-repository contracts rather than internal names. See
`04-findings-new-to-this-pass.md` **F2a**, which also carries a reported divergence in `cuems-nodeconf`
affecting the write path this repository's `nodelist_modify` drives.

See `00-runnable-flow.md` §1.

## Freshness — every upstream line number has moved

The upstream flow measured this repository on **2026-09-03** at `rc_1`/`fc8d2bb`. Re-measured
2026-09-25 at `feat/nodelist-modify-dispatch`/`dbc9e6d`:

| | Upstream said | Measured 2026-09-25 |
|---|---|---|
| `ControllerEngine.py` length | (not recorded) | **1781 lines** |
| `NetworkMap` import | `:12` | **`:15`** |
| `get_nodes_by_adoption` | `:249` | **`:287`** — and a second call site is new |
| `_adopted_uuids_from_network_map` | `:1152-1168` | **`:1418`** |
| `BaseEngine.py` | `:33/:410/:440/:443/:433/:509-510` | **unchanged** — the file is 636 lines and the six commits did not touch it |
| `ActionHandler.py` fade sites | `:30, :516, :542, :784-785` | **`:38-39`, `:516`, `:542`, `:784-785`** — the `SUPPORTED_CUE_ACTIONS` members are two lines, not one |

`03-migration-inventory.md` carries the full re-measured table with the originals in brackets, so
the shift is visible rather than silent.

## Corrections applied on vendoring

Recorded rather than silently fixed, per the upstream convention:

1. **The branch base changed** (above). The upstream flow's §1 is superseded by
   `00-runnable-flow.md` §1; the upstream text is not edited, because it is a dated record.
2. **`find_hosts` is unreachable, and broken for a second reason.** Upstream lists
   `BaseEngine.py:440` and `:443` as two FR-030a-ii sites. Both are inside `find_hosts`, which a
   sweep of all seven ecosystem repositories shows has **no caller anywhere** — and which reads
   the node wrapper instead of the node, so it fails today, before any vocabulary question. See
   `04-findings-new-to-this-pass.md` F1. Fixing the comparison alone would leave it broken.
3. **The `cuemsutils` pin floor is further behind than upstream recorded.** Upstream noted
   `pyproject.toml >=0.1.0rc10` and `debian/control >= 0.1.0rc4` disagree. Both still say that, and
   the three landed sibling repositories have since moved to `>=0.1.0rc16,<0.1.1` — so this
   repository and `cuems-editor` are now the only two consumers whose pin cannot express the
   release gate. See `03-migration-inventory.md` §5.
4. **The test-file count moved with the six commits.** Upstream measured 43 test files under
   `tests/`; re-measured 2026-09-25 it is **45** — the two the new commits added
   (`test_nodelist_modify.py`, `test_cluster_warning.py`). Runner unchanged: `poetry run pytest`,
   `testpaths = ["tests"]`.
