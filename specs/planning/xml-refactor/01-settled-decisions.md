<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# The settled decisions that bind `cuems-engine`

**Vendored** 2026-09-25 from `cuems-utils/specs/planning/xml-rebuild/xml-rebuild-07-speckit-prompts.md`
§2, which is authoritative for the full list of thirty-six (D1–D36, plus Q11→(c) and Q14→(i)).

**Do not reopen any of these.** They were settled across three clarification sessions in
`cuems-utils` features 007, 008 and 010. If a question arises that this subset does not answer, read
§2 upstream rather than inventing an answer locally — and if the answer changes, it changes there
first and propagates here, never the reverse.

---

## The eight that bind this repository

| | Decision |
|---|---|
| **D11** | The node model moved in from `cuems-nodeconf`; it lives in `cuemsutils` **only** |
| **D12** | The public surface returns **objects**, never raw dicts |
| **D15** | The public objects are `CuemsScript` (show) and `ConfigManager`/`ConfigBase` (config) |
| **D17 / D18b** | **Every** time-carrying element is `cms:CTimecodeType` and stores a `CTimecode`. `Media.duration` was promoted from a restricted string: `<duration>TC</duration>` is now `<duration><CTimecode>TC</CTimecode></duration>` in XML and `{"CTimecode": TC}` in JSON |
| **D19 / D21** | `load()` now runs T1 **and** T2. Three outcomes: an **old** document converts in memory (the file on disk is untouched); a **current but repairable** one loads with the field repaired and the repair carried in a report; an **unrepairable** one raises. A document **newer** than the library raises, distinguishably |
| **D27** | Nothing in the ecosystem releases until every consumer flow lands |
| **Q14 → (i)** | `cuemsutils.xml` is internal machinery. Do not import from it — it declares `__all__ == []` for this reason |

## The two rules from 007 that are not decisions but constraints

**FR-030a-i — the node model lives in `cuemsutils` exclusively.** No consumer re-implements or
re-tests it. **A node-model test appearing in this repository during this migration is a regression,
not coverage.** The sibling `cuems-power-bridge` carried a fourth private copy of the node-identity
model for two features precisely because nothing ever told it this rule existed; the copy, not the
vocabulary break, was the root cause of its silent failure.

**FR-030a-ii — callers that keep resolving but become wrong** are a distinct and more dangerous class
than callers that stop resolving. Nothing fails, the suite stays green, and the answer is silently
wrong. They are **searched for**, against the inventory in `03-migration-inventory.md` §1, and each
one gets a test that fails against the old value **first**. Do not wait for a red suite to surface
them; this repository's fixtures are written in the retired vocabulary, so the suite is green
*because* it certifies the defect.

---

## Two decisions this repository is executing rather than making

Restated because both are routinely misremembered.

**The `doc_version` marker is never a domain field.** It is a document property: excluded from
`spec._derive_attributes` and from every wire projection, read by a pre-validation probe before any
schema decode. The engine never sees it and must not read, write or reason about it. `script` is at
version **2**; the other five schemas are at **1**.

**The `fade_in`/`fade_out` → `play`/`stop` conversion is behaviour-preserving *because of this
repository*.** `cuems-utils` justified that transformation on the measured fact that
`ActionHandler.py` already dispatches both as stubs treated exactly that way. So deleting the two
handlers is not a behaviour change — but it is only safe **after** documents stop carrying the old
`action_type`, which is what the library's convert-on-read path guarantees. State the ordering in the
spec; do not leave it implicit.

---

## What this repository must *not* do

- **Do not add a public alias to `cuemsutils`** for anything, and do not patch that library from
  here. `cuems-nodeconf` established the precedent twice: it reported three defects and then a
  fourth upstream and left them **deliberately unpatched from the consumer side**, because the
  characterization guarantee depends on the library's files not being edited by a consumer. Both
  reports were fixed upstream inside `0.1.0rc16`. Write an upstream report; do not reach across.
- **Do not move `cuems-utils` off `0.1.0rc16`.** `0.1.1` is reserved by
  `_deprecation.REMOVAL_RELEASE` and refused outright by three consumers' `<< 0.1.1~` ceilings.
- **Do not ship from this branch alone** (D27). The coordinated merge is what the
  `xml-refactor-merge-candidate` tag marks, and three sibling repositories have already cut theirs.
  See `00-runnable-flow.md` §6.
