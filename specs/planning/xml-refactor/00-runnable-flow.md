<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# `cuems-engine` — the runnable flow for `008-cuems-utils-migration`

**Derived** 2026-09-25 from `cuems-utils/specs/planning/xml-rebuild/010-consumer-prompts/01-cuems-engine.md`,
re-measured against the live tree. Where the two differ, **this file is the one to run** — the
upstream original is a dated 2026-09-03 record and is not edited.

**Feature name**: `008-cuems-utils-migration` (this repository already holds `specs/004-*`–`007-*`).
**Branch**: `feat/xml-refactor`, matching every other repository in this work.

---

## 0. State of this repository, measured 2026-09-25

| | |
|---|---|
| Current branch | `feat/nodelist-modify-dispatch` @ `dbc9e6d`, clean |
| Base for `feat/xml-refactor` | **`feat/nodelist-modify-dispatch`** — changed from upstream's `rc_1`, see §1 |
| `rc_1` | `fc8d2bb` (2026-08-14); the working branch is **6 commits ahead** of it |
| Spec-kit | **present** — `.specify/`, 14 skills including `speckit-git-*` |
| Constitution | **present** — SOLID (I) and **TDD, NON-NEGOTIABLE** (II) |
| Existing features | `specs/004-*` … `specs/007-*` → this becomes **`008-cuems-utils-migration`** |
| Tests | `poetry run pytest` — **45** test files under `tests/`, `testpaths = ["tests"]` |
| `cuemsutils` pin | `pyproject.toml:41` `>=0.1.0rc10`; `debian/control:18` `>= 0.1.0rc4` — the two disagree |
| Runs against current `cuemsutils`? | **yes, it imports** — its two deprecated paths still resolve and warn |

**Its constitution makes TDD non-negotiable.** That is not a formality here: the whole FR-030a-ii
caller class is *defined* as "a caller that keeps working and returns the wrong answer", so the only
thing that can prove one is fixed is a test written to fail against the old value first. Cite the
constitution rather than re-arguing the discipline.

---

## 1. Branch — based on `feat/nodelist-modify-dispatch`, not `rc_1`

```bash
cd /disk/Projects/StageLab/cuems-engine
git checkout feat/nodelist-modify-dispatch
git pull --ff-only                  # if a remote is configured for this branch
git checkout -b feat/xml-refactor
```

**Upstream flow 01 says `rc_1`. That is superseded, by decision taken 2026-09-25 with the
maintainer.** The reason is not convenience: the six commits on
`feat/nodelist-modify-dispatch` added a *second* `get_nodes_by_adoption` call site and two docstrings
constraining when it may be called — they built **around** the deprecated mutating API this feature
exists to replace. Branching from `rc_1` produces work that conflicts with precisely that code. See
`04-findings-new-to-this-pass.md` F2.

Spec-kit's sequential branch numbering will want its own branch. **Stay on `feat/xml-refactor`**; let
it name `specs/008-cuems-utils-migration/` only.

---

## 2. Constitution — check, do not amend

Read `.specify/memory/constitution.md`. Two clauses bind this work and neither needs changing:

- **II (TDD, non-negotiable)** — every FR-030a-ii caller gets a red test against the old value before
  the fix. This is the rule that makes the silent class findable.
- **I (SOLID)** — relevant when `find_hosts` and `_controller_ip_from_map` move from poking dicts to
  consuming typed node objects. The change is an opportunity to stop conflating map access with
  host-list construction; it is **not** a licence to rewrite `BaseEngine`.

If the migration turns out to violate the constitution, that is information: record the exception in
the spec explicitly. Do not weaken the constitution to accommodate the migration.

---

## 3. Context block — paste verbatim into `/speckit.specify` and `/speckit.plan`

Everything below resolves **inside this repository**. That is the point of the bundle: the upstream
`cuems-utils` checkout is no longer required reading.

```
CONTEXT — read all four before writing anything. They are in this repository:
  specs/planning/xml-refactor/01-settled-decisions.md        the decisions that bind this repo
  specs/planning/xml-refactor/02-consumer-audit-findings.md  C7 and C11, this repo's two findings
  specs/planning/xml-refactor/03-migration-inventory.md      THE INVENTORY — re-measured 2026-09-25
  specs/planning/xml-refactor/04-findings-new-to-this-pass.md  four findings, two of them live defects

SCOPE — five groups of work, and one decision.

  1. THE NODE VOCABULARY. BaseEngine.py:33's CONTROLLER_NETWORK_FLAG = "NodeType.master" and the
     two comparisons deriving from it (:410, :440) move onto cuemsutils.tools.NodeList.NodeRole.
     BaseEngine.py:443's node.get("online") == "True" moves onto a real bool. All four are
     FR-030a-ii sites: each gets a test that FAILS against the pre-migration value first.

  2. THE DEPRECATED IMPORTS. BaseEngine.py:17 (cuemsutils.xml.XmlReaderWriter) and
     ControllerEngine.py:15 (cuemsutils.xml.Settings.NetworkMap) move onto the public surface —
     CuemsScript for the show path, ConfigManager/ConfigBase for config. cuemsutils.xml is
     internal machinery (Q14) and both paths are removed in the release after 0.1.0rc16.

  3. THE MUTATING ADOPTION API. get_nodes_by_adoption -> partition_by_adoption at both call
     sites, and _adopted_uuids_from_network_map (ControllerEngine.py:1418, three callers) is
     DELETED, not ported — it is an inline workaround for the mutation the replacement does not
     have. The shape inverts: partition_by_adoption returns bare node objects in tuples, not
     {"node": ...} wrappers in lists. Getting that backwards yields None for every uuid and
     registers no OSC handlers, silently. Claim the simplification: the one-pass hazard and the
     "ORDER MATTERS" convention at ControllerEngine.py:938-943 cease to exist.

  4. THE DEAD FADE HANDLERS. ActionHandler.py:38-39, :516, :542, :784-785. 008's script 1->2
     conversion rewrites action_type fade_in/fade_out to play/stop, and it is behaviour-preserving
     BECAUSE this repository already dispatches both as stubs treated exactly that way. Deleting
     them is safe only after documents stop carrying the old values, which convert-on-read
     guarantees. State that ordering.

  5. THE RELEASE GATE. Reconcile pyproject.toml:41 (>=0.1.0rc10) with debian/control:18
     (>= 0.1.0rc4) AND bound both. A >= floor cannot express "refuse a library that has moved
     past me" — that is an upper bound or a Breaks:. cuems-nodeconf's debian/control:18-19 is the
     model: >= 0.1.0rc16 and << 0.1.1~.

  THE DECISION: find_hosts has NO CALLER anywhere in the seven-repository ecosystem, and it reads
  the node wrapper instead of the node, so it raises AttributeError unconditionally today —
  independent of any vocabulary question. Fix-and-wire, or delete. Decide deliberately; fixing the
  two comparisons alone leaves a broken, unreachable method that LOOKS migrated.

ORDERING THIS FEATURE MUST CARRY (C11): a controller whose library has converted to script
version 2 pushes version-2 documents to every node it deploys to, at SHOW-LOAD time, mediated by
no package manager. Nodes upgrade BEFORE the controller. This cannot be discharged by editing
this repository — it belongs in the release procedure and in the exit criteria.

OUT OF SCOPE, explicitly:
  - The node model. It lives in cuemsutils only (FR-030a-i). A node-model test appearing in this
    repository is a regression, not coverage.
  - Patching cuemsutils. Write an upstream report instead; cuems-nodeconf did this four times and
    all four were fixed upstream inside 0.1.0rc16.
  - dev/network_map.xml, dev/test_xml_files/network_map.xml, dev/CuemsEngine_old.py — non-shipped
    fixtures, enumerated as exempt BY NAME with the reason "not shipped", which is a different
    reason from "exists to detect the retired spelling". Do not merge the two categories.
  - BaseEngine.py:505's hardcoded "script.xml". Record it (cuems-editor reads the same thing from
    configuration) and leave it; it is cuems-utils feature 012's trap, not this feature's work.
```

---

## 4. The chain

```
/speckit.specify   <paste §3>
/speckit.clarify                 <- do NOT skip; §5 lists what it must force
/speckit.plan      <paste §3>
/speckit.tasks
/speckit.check-integration       <- earns its place here more than anywhere
/speckit.optimize
/speckit.implement               <- never on a red suite
/speckit.verify
```

**`check-integration` matters most in a migration**, and this is one: the failure mode is writing the
new call *alongside* the old one instead of replacing it. Run it before `implement`, not after.

**Never `/speckit.implement` on a red suite.** Capture the baseline suite result as evidence before
touching anything — `cuems-power-bridge`'s `specs/001-node-role-parser/evidence/baseline-suite.txt`
is the worked precedent, and it is what made its "green means nothing here" claim checkable.

---

## 5. What `/speckit.clarify` must force

Five questions. None has a safe default; two have no defensible one.

1. **`find_hosts`: fix-and-wire, or delete?** It has no caller and it is broken for a second,
   independent reason. This is a real decision with a real cost either way — deleting removes a
   method someone wrote on purpose; wiring it means deciding what should call it, when
   `_controller_ip_from_map` already serves the adjacent need.
2. **Do the five `CTimecode(cue.media.duration)` wraps get cleaned up?** Measured 2026-09-25: the
   wrap **is idempotent**, so they are redundant rather than broken and none is a release blocker.
   Cleaning them is in or out by decision, not by inference from a green suite.
3. **Where does the nodes-before-controller ordering live?** C11 cannot be discharged in code. Name
   the artefact — release procedure, `debian/` relation, or an exit criterion — or it will be
   discharged nowhere.
4. **Does `debian/control` get a `Breaks:` as well as an upper bound?** `cuems-common` has one
   against `cuems-nodeconf`; `cuems-nodeconf` bounds without one. Both express the gate; pick, and
   say why.
5. **What happens to the "ORDER MATTERS" calling convention's tests?** The six new commits' two test
   files characterize behaviour that depends on the mutation. When the mutation goes, those tests
   either move to the new contract or retire — and retiring a test is a recorded event, never a
   silent one.

---

## 6. Exit criteria, measured

| | Criterion |
|---|---|
| 1 | `grep -rn 'node_type\|NodeType\.' src/` returns **zero**. `dev/` is exempt **by name**, with the reason recorded per entry |
| 2 | Each of the four FR-030a-ii sites has a test that **failed** against the pre-migration value, with the failing run captured as evidence |
| 3 | `grep -rn 'from cuemsutils\.\(xml\|config\)' src/` returns **zero** — the public surface only. `cuems-nodeconf`'s `tests/test_public_surface.py` is a reusable shape for guarding this, including its guard against a package rename turning the test silently green |
| 4 | `get_nodes_by_adoption` appears **nowhere**; `_adopted_uuids_from_network_map` is deleted, not renamed |
| 5 | `pyproject.toml` and `debian/control` agree, and both bound the upper end |
| 6 | The suite is green, with the count recorded before and after — a growing suite is not a regression, and an absolute figure compares two different suites |
| 7 | A show loads and dispatches against a **converted** (version-2) `script.xml`, and against an **unconverted** version-1 one, both recorded |
| 8 | Hardware items that could not be performed are recorded as **not performed**, per entry. Silence is not an acceptable third state — this is the convention `cuems-nodeconf` and `cuems-power-bridge` both followed |

**Then, and only then, the candidate tag.** `xml-refactor-merge-candidate`, annotated and signed, on
`feat/xml-refactor`. Three siblings have already cut theirs:

| Repository | Tag at | Carries |
|---|---|---|
| `cuems-power-bridge` | `d5c4226` | features 001 + 002 |
| `cuems-common` | `3af31cc` | the `node_role` conversion, the fixed `cuems-cluster-poweroff` |
| `cuems-nodeconf` | `6c0cca7` | its own two features |
| `cuems-utils` | — | **tags last, by decision** — it is the library everything here pins |

By the shared convention the tag moves **only** when a candidate is genuinely re-cut (packaged
content changes), and a re-cut is announced to the other flows. `cuems-common`'s tag was relocated
once, 2026-09-24, and force-pushed with the maintainer's confirmation — moving a published tag
rewrites what other checkouts see, so it is a decision, not a fix.

**Nothing releases from this branch alone** (D27). And note what the tag now waits on beyond the
consumer flows: `cuems-utils` features **011–014** (`/etc/cuems` first install, uuid4 convergence,
the device-class reshape, `hardware_outputs`) are a hard successor to the consumer migration, and the
whole-system tag comes after them. See `cuems-utils/specs/planning/etc-cuems-first-install-execution.md` §8.

---

## 7. Traps

Every entry cost someone a revert or a wrong claim during this work.

**"Dead code" is not provable from one repository.** This is a library-consumer ecosystem. A grep
that finds no in-repo caller finds nothing at all — check `../cuems-editor`, `../cuems-frontend`,
`../cuems-nodeconf`, `../cuems-power-bridge`, `../cuems-common` and `../cuems-utils` before writing
"unused". Note that `cuems-wsclient` **is** `cuems-power-bridge`, the same repository renamed, which
once inflated the ecosystem count from seven to eight. F1's claim about `find_hosts` was made this
way and is only as good as that sweep.

**A green suite is evidence of nothing here.** Three fixture lines in
`tests/test_core_baseengine_controller_ip.py` are written in the retired vocabulary. The suite passes
*because* it certifies the defect. Any fixture change must re-check **which** error each negative
case now raises — the sibling `cuems-utils` had a negative fixture start failing for the wrong reason
and stay green through it.

**A test that fails for the wrong reason is worse than one that fails.** After the vocabulary change,
verify each red test is red for the value it was written to catch, not for a missing key.

**Commits are GPG-signed.** On `gpg failed to sign`, retry — never `--no-gpg-sign`.

**Planning artefacts stay in `specs/planning/`; feature artefacts in `specs/008-*/`.** This bundle is
planning. The spec, plan, tasks, research, data model, contracts, checklists and evidence go in the
numbered directory.

**Do not regenerate a golden to make a test pass.** Re-basing is a recorded, argued event. This
repository has no golden corpus of its own, but `cuems-utils`' goldens are what upstream T027 checks
this migration's payload against — do not ask for them to be re-cut.
