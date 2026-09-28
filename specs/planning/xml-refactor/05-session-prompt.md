<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Feature 008 — the session-start prompt

**Purpose**: start `008-cuems-utils-migration` in a fresh agent session or on a new machine without
re-deriving three weeks of audit. **Written for** an agent or contributor with no memory of the
xml-refactor work.

**Prepared** 2026-09-28, against `feat/nodelist-modify-dispatch` @ `dbc9e6d`, `cuemsutils`
`0.1.0rc16`. Mirrors the precedent `cuems-utils` set with its
`specs/planning/011-first-install-specify-prompt.md`.

---

## 1. How to run it

Paste §2 verbatim as the first message of a new session **in this repository**. Then stop at
`/speckit.clarify` — §3 lists the questions it must force, and one of them has no defensible default.

Do not begin implementing from the spec alone. Two of this feature's four FR-030a-ii sites sit inside
a method that is already broken for an unrelated reason, and treating them as ordinary comparisons
produces something that looks migrated and does not work.

---

## 2. The prompt — paste this verbatim

```text
You are picking up cuems-engine's share of the CueMS xml-refactor: feature
008-cuems-utils-migration, the migration onto cuemsutils' post-008 public API.

READ THESE FIRST, IN THIS ORDER, AND DO NOT RE-DERIVE WHAT THEY MEASURE. They are in
this repository and they are self-contained — the sibling cuems-utils checkout is
useful but not required:

  specs/planning/xml-refactor/README.md                      start here; why the base branch is what it is
  specs/planning/xml-refactor/00-runnable-flow.md             THE FLOW — branch, chain, exit criteria, traps
  specs/planning/xml-refactor/01-settled-decisions.md         8 decisions + FR-030a-i/ii. Do not reopen
  specs/planning/xml-refactor/02-consumer-audit-findings.md   C7 and C11, this repository's two
  specs/planning/xml-refactor/03-migration-inventory.md       THE INVENTORY, re-measured 2026-09-25
  specs/planning/xml-refactor/04-findings-new-to-this-pass.md 5 findings; F1 and F2a change scope

BRANCH. Base feat/xml-refactor on feat/nodelist-modify-dispatch, NOT on rc_1:

    git checkout feat/nodelist-modify-dispatch && git pull --ff-only
    git checkout -b feat/xml-refactor

The upstream flow-01 prompt in cuems-utils says rc_1. That is superseded by a recorded
decision (2026-09-25): those six commits added a SECOND get_nodes_by_adoption call site
and two docstrings constraining when it may be called, so they built AROUND the
deprecated API this feature replaces. See README.md and 04-…md F2a. Spec-kit's branch
numbering will want its own branch — stay on feat/xml-refactor and let it name
specs/008-cuems-utils-migration/ only.

CONSTITUTION: present. Check, do not amend. Principle II (TDD, non-negotiable) is what
makes this feature's central class findable — cite it rather than re-arguing it. If the
migration violates the constitution, that is information; record the exception in the
spec.

SEQUENCING, already researched so you do not have to: START NOW. cuemsutils features
011–014 do NOT block this, verified in both directions. 011 changes no API surface; 012
changes the uuid's value, not output_name's format; 014 touches nothing this repository
reads. 013 will need three small edits at NodeEngine.py:440, :441 and :550
(node_hw_outputs' per-class keys) — a file THIS FEATURE DOES NOT MODIFY, so there is no
rework. The pin this feature sets (>=0.1.0rc16,<0.1.1) stays correct across all four.
Conversely this feature IS on the critical path: BaseEngine.py:17 and
ControllerEngine.py:15 are live imports of the surface cuems-utils' US10 deletes, and
US10 is gated on a measured census of zero.

THE WORK, five groups plus one decision. 03-migration-inventory.md is authoritative:
  1. the node vocabulary — BaseEngine.py:33/:410/:440/:443 onto NodeRole and real bools
  2. the deprecated imports — BaseEngine.py:17, ControllerEngine.py:15 onto the public surface
  3. the mutating adoption API — get_nodes_by_adoption -> partition_by_adoption at both
     sites; _adopted_uuids_from_network_map (ControllerEngine.py:1418, three callers)
     DELETED, not ported. The shape INVERTS: bare node objects in tuples, not
     {"node": ...} wrappers in lists. Getting that backwards yields None for every uuid
     and registers no OSC handlers, silently
  4. the dead fade handlers — ActionHandler.py:38-39, :516, :542, :784-785
  5. the release gate — reconcile pyproject.toml:41 with debian/control:18 AND bound both

THE DECISION: find_hosts has NO CALLER anywhere in the seven-repository ecosystem, and it
reads the node WRAPPER instead of the node, so it raises AttributeError unconditionally
today — independent of any vocabulary question. Fix-and-wire, or delete. Decide
deliberately: fixing the two comparisons alone leaves a broken, unreachable method that
LOOKS migrated. See 04-…md F1.

NON-NEGOTIABLE, all four:
  - Every FR-030a-ii site gets a test that FAILS against the pre-migration value FIRST.
    A green suite is not evidence here: three fixture lines in
    tests/test_core_baseengine_controller_ip.py are written in the retired vocabulary, so
    the suite passes BECAUSE it certifies the defect.
  - Never /speckit.implement on a red suite. Capture the baseline suite result as evidence
    before touching anything.
  - Do NOT re-implement or re-test the node model here. It lives in cuemsutils exclusively
    (007 FR-030a-i). A node-model test appearing in this repository is a regression.
  - Do NOT patch cuemsutils from here. Write an upstream report; cuems-nodeconf did that
    four times and all four were fixed upstream inside 0.1.0rc16.

OUT OF SCOPE, explicitly, so it is not quietly widened:
  - NodeEngine.py's node_hw_outputs reads. That is feature 013's.
  - BaseEngine.py:505's hardcoded "script.xml" — RECORD it (cuems-editor reads the same
    thing from configuration) and leave it. It is cuems-utils feature 012's trap.
  - dev/network_map.xml, dev/test_xml_files/network_map.xml, dev/CuemsEngine_old.py —
    non-shipped, exempt BY NAME with the reason stated per entry. "Not shipped" is a
    different reason from "exists to detect the retired spelling"; do not merge the two.

ORDERING THIS FEATURE MUST CARRY (C11): a controller whose library has converted to
script version 2 pushes version-2 documents to every node it deploys to, at SHOW-LOAD
time, mediated by no package manager. Nodes upgrade BEFORE the controller. This cannot be
discharged in code — it belongs in the release procedure and in the exit criteria.

Start by reading the six files above, then run /speckit.specify using
00-runnable-flow.md §3's context block. Report what you found that the bundle does not
already say — its coordinates were measured 2026-09-25 and this repository moves.
```

---

## 3. What `/speckit.clarify` must force

Five, from `00-runnable-flow.md` §5. The first has no defensible default:

1. **`find_hosts`: fix-and-wire, or delete?**
2. **Do the five `CTimecode(cue.media.duration)` wraps get cleaned up?** Measured: the wrap **is**
   idempotent, so they are redundant rather than broken. In or out by decision, not by inference.
3. **Where does the nodes-before-controller ordering live?** Name the artefact or it lands nowhere.
4. **Does `debian/control` get a `Breaks:` as well as an upper bound?**
5. **What happens to the two test files the six new commits added**, whose subject depends on the
   mutation this feature removes? Retiring a test is a recorded event.

---

## 4. Before the first commit

- Commits are **GPG-signed**. On `gpg failed to sign`, retry — never `--no-gpg-sign`.
- Planning artefacts stay in `specs/planning/`; feature artefacts in `specs/008-*/`.
- Hardware verification: this feature's exit criterion 7 works on the existing formitgo controller,
  but a **fresh-install** path needs `cuems-utils` feature 011, which has not landed. State that
  plainly rather than leaving it silent — both landed sibling repositories followed that convention.
- Nothing ships from this branch alone (D27). Three siblings have already cut
  `xml-refactor-merge-candidate`: `cuems-power-bridge` `d5c4226`, `cuems-common` `3af31cc`,
  `cuems-nodeconf` `6c0cca7`. `cuems-utils` tags last, by decision, and the whole-system tag comes
  after its features 011–014.
