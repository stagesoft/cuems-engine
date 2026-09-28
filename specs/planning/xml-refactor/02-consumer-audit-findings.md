<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# `cuems-engine` — the consumer-audit findings that are this repository's

**Vendored** 2026-09-25 from `cuems-utils/specs/planning/xml-rebuild/xml-rebuild-09-consumer-audit.md`
(measured 2026-09-03, `cuems-utils@b7db53e` copy). Two of the audit's twelve findings — **C7** and
**C11** — are this repository's. Both are reproduced with their original reasoning, then followed by
what has changed since.

---

## C7 — the release gate has exactly one mechanically enforced edge

Measured 2026-09-03:

| Repo | `pyproject.toml` | `debian/control` |
|---|---|---|
| `cuems-engine` | `cuemsutils = ">=0.1.0rc10"` | `cuems-utils (>= 0.1.0rc4)` |
| `cuems-editor` | `cuemsutils>=0.1.0rc10` | — |
| `cuems-nodeconf` | `cuemsutils = ">=0.1.0rc15"` | `cuems-utils (>= 0.1.0rc5)` |
| `cuems-wsclient` | `cuemsutils = ">=0.1.0rc5"` (optional) | `cuems-utils (>= 0.1.0rc5)` |
| `cuems-common` | — | `cuems-utils (>= 0.1.0rc15)`, `Breaks: cuems-nodeconf (<< 0.1.0-8)` |

Only `cuems-common` enforces anything, and only against `cuems-nodeconf` (007's FR-030d / T054a).
Three observations:

1. **A `>=` floor cannot express the gate.** The gate says "an unmigrated consumer must refuse a
   library that has moved past it" — that is an upper bound or a `Breaks`, and no consumer declares
   one. Installing `cuems-utils` rc16 beside an editor pinned `>=0.1.0rc10` succeeds, and the editor
   then fails at import (C2).
2. **`cuems-engine`'s two floors disagree** — `rc4` in `debian/control` against `rc10` in
   `pyproject.toml`. The packaged floor is six release candidates behind the source one.
3. **007 moved the mechanical demonstration here** (T054b, its guide §13): no packaging sandbox
   existed to install an out-of-order combination and watch `dpkg` refuse it. 008 then added a
   second, larger breaking change to the same gate without adding an edge. 010 both *runs* that
   demonstration and *supplies the missing edges*.

### What has changed since — re-measured 2026-09-25

**Two of the table's rows are obsolete and one name is wrong.**

- `cuems-wsclient` and `cuems-power-bridge` are **the same repository**, renamed in 2026-06. The
  audit's row is the bridge's, under its former name. It is now `>=0.1.0rc16,<0.1.1` in
  `pyproject.toml` and non-optional; its `debian/control` floor is raised but still **unbounded**.
- `cuems-nodeconf` is now `>=0.1.0rc16,<0.1.1` / `>= 0.1.0rc16`, `<< 0.1.1~` — **bounded on both
  sides**. It is the model to copy.
- `cuems-common` is now `>= 0.1.0rc16`, `<< 0.1.1~`.
- **`cuems-engine`'s two rows are unchanged**: `pyproject.toml:41` still `>=0.1.0rc10`,
  `debian/control:18` still `>= 0.1.0rc4`. Observation 2 stands exactly as written, two weeks on.

So C7's conclusion is intact but its argument is now easier: the gate is a convention three siblings
follow, and this repository is one of two holdouts. See `04-findings-new-to-this-pass.md` F4.

---

## C11 — a third document-distribution surface for the conversion

The plan describes 008's duration conversion as two paths: `postinst` (batch, via
`cuems-convert-documents`) and convert-on-load. There is a third, and it is node-to-node rather than
package-to-disk: **`cuems-engine` deploys project files across the cluster.**
`tools/CuemsDeploy.py:329` and `:649` build `/projects/<project>/script.xml` into the rsync manifest;
`NodeEngine.py:730,805` receive them.

So a controller whose library has been converted to `script` version 2 pushes version-2 documents to
every node it deploys to. A node running an older `cuemsutils` cannot read them — and unlike the
postinst case, this happens at **show-load time**, not upgrade time. The reverse order (nodes
upgraded first) is safe, because 008's ITEM E converts version-1 documents in memory.

This is a third ordering constraint alongside 007's postinst-vs-service-restart question, and it
argues the same way the cluster-upgrades-as-a-unit rule does: the deploy path gives a mixed-version
cluster a way to fail that no package manager mediates.

**Why this is the finding with the longest reach.** Every other item in this bundle is a call site.
C11 is an *operational* constraint on how a cluster is upgraded, and it cannot be discharged by
editing this repository — it has to appear in the release procedure. The spec's exit criteria must
carry it as a stated ordering ("nodes before controller"), not as a note.

### The minor half of C11, which is in the *other* repository

The audit's C11 closes with an FR-030a-ii instance in `cuems-editor`'s `repair_durations.py:87` —
a `TIMECODE_SHAPE.match(value)` guard against string values that post-008 receives dicts and
therefore silently stops catching anything. It is recorded here because it arrived in the same
finding, but it is **`cuems-editor`'s to fix**, and that repository's bundle carries it.

---

## The findings that are *not* this repository's

For orientation, so nothing is picked up by mistake — the audit's twelve headings, with the
repository each belongs to:

| | Finding | Owner | State 2026-09-25 |
|---|---|---|---|
| C1 | a sixth consumer, unlisted everywhere, already silently wrong | `cuems-power-bridge` (audited as `cuems-wsclient`) | **landed** |
| C2 | `cuems-editor` does not start against the current branch | `cuems-editor` | open |
| C3 | the shared context block's HARD CONSTRAINT contradicts 008 | `cuems-editor` / `cuems-frontend` | resolved upstream as the two-delta statement |
| C4 | the schema descriptor has no public import path | `cuems-utils` | closed by upstream wave 0 |
| C5 | the frontend template inventory undercounts, in files and in kind | `cuems-frontend` | open |
| C6 | the Avahi TXT vocabulary has two owners | `cuems-nodeconf` + `cuems-common` | **landed** |
| **C7** | the release gate has one enforced edge | **`cuems-engine`** (+ every consumer) | **open here** |
| C8 | the frontend has no coverage where 010 works hardest | `cuems-frontend` | open |
| C9 | three stale documents that are 010's own inputs | `cuems-utils` | closed |
| C10 | work landed after 008 closed, in no plan | `cuems-nodeconf` | **landed** |
| **C11** | a third document-distribution surface for the conversion | **`cuems-engine`** | **open here** |
| C12 | the zero-`node_type` criterion cannot pass as written | `cuems-utils` | open — see the exempt-set discipline in `03-migration-inventory.md` §9 |
