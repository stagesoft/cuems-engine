<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Work order → 009 artefacts (T117, FR-060)

The work order `specs/planning/release-line-reconciliation-0.1.1.md` (last commit recorded in `spec.md`'s header) is deleted by
T118. Each of its sections has a home here. Paths are relative to `specs/009-release-line-reconciliation/`.

| WO § | Home in 009 |
|---|---|
| 0 Decisions | `spec.md` "Decisions already taken" (D1–D5) |
| 1 Goal, scope, non-goals | `spec.md` "Context" and "Assumptions" (out of scope) |
| 2 The three lines, measured | `spec.md` M1–M8; re-measured in `evidence/remeasure-start.md` and `evidence/remeasure-handoff.md`; `research.md` R0 |
| 3 Strategy, methods, commit shape | `spec.md` FR-001, FR-005, FR-061; `evidence/merge-bookworm.md`; the commit sequence of the branch |
| 4 Inventory | `spec.md` "Inventory"; `evidence/inventory-proofs.md` (#1–#25) |
| 4.1 Stray heads and tags | `spec.md` FR-006…FR-009; `evidence/stray-head-sweep.md`; `evidence/hotfix-rc5-equivalence.md` |
| 5 Conflict resolutions | `spec.md` FR-004; `evidence/merge-bookworm.md` |
| 6.1 The merged tree versus `e994a5e` | `evidence/suite-arm-A.txt`, `suite-arm-B.txt`, `expected-reds.md`, `suite-after-adapt.txt`, `suite-final.md` |
| 6.2 Conformance and risk | `spec.md` FR-010…FR-019a; `evidence/failing-first-*.txt`; `evidence/identity-audit-009.md`; `evidence/r1-media-unset.md`, `r2-cue-names.md`, `r3-stop-project-guard.md`, `r4-one-adoption-rule.md` |
| 7.1 `debian/changelog` | `spec.md` FR-030, FR-031; `contracts/changelog-completeness.md`; `evidence/failing-first-changelog-hotfix.txt` |
| 7.2 `CHANGELOG.md` | `spec.md` FR-032, FR-033; `evidence/failing-first-changelog-md.txt`, `changelog-md-audit.md` |
| 7.3 `debian/control`, `rules`, mock | `spec.md` FR-034…FR-038; `evidence/debian-rules-audit.md`, `bookworm-build.md`, `relation-verdicts-009.txt` |
| 7.4 Things that do not move | `spec.md` "Constraints" and "Assumptions" |
| 8.1 cuems-utils | `spec.md` FR-020…FR-022; `upstream-reports/cuems-utils-x1-x4.md`; `research.md` R4; `evidence/strict-xfails.md` |
| 8.2 The other siblings | `spec.md` FR-023; `contracts/engine-wire-additions.md`; `upstream-reports/cuems-frontend-engine-contracts.md`, `cuems-editor-engine-contracts.md`, `cuems-power-bridge-engine-contracts.md`, `cuems-nodeconf-engine-contracts.md` |
| 9 Docs touched by the merge | `spec.md` FR-040, FR-041; the commit `docs(009): version claims after reconciliation` |
| 10 Acceptance criteria | `spec.md` SC-001…SC-011 |
| 11 Execution order | `plan.md` "Phases"; `tasks.md` |
| 12 Open questions | `spec.md` "Clarifications" and "Assumptions" |
| 13 Measurement recipe | `quickstart.md`; `research.md`; `evidence/environment.md` |
| 14.1 `dev/` deletions | `spec.md` FR-045; `evidence/kill-cuems-check.md`; the commit `chore(009/14.1)` |
| 14.2 Developer tools | `spec.md` FR-046; `dev/README.md`; constitution 1.2.0 |
| 14.3 `tests/` layout | `spec.md` FR-047; `contracts/test-layout.md`; `evidence/test-layout-moves.md`, `collect-before.txt`, `collect-after.txt`, `outcome-before.txt`, `outcome-after.txt`, `cleanup-check.txt`; `upstream-reports/rc_1-test-layout.md` |
| 14.4 Other stale items | `spec.md` FR-048, FR-049; `evidence/test-retirements.md` |
| 14.5 CI: the pre-publication gate | `spec.md` FR-050…FR-057; `contracts/ci-gate.md`; `research.md` R1, R2, R6, R7; `.github/workflows/ci.yml`. **The dispatched run (T113, T114) is the maintainer's: see the hand-off.** |
| 14.6 Acceptance for the cleanup phase | `spec.md` SC-009, SC-010; `evidence/cleanup-check.txt` |
| Appendix A (the specify prompt) | `spec.md` itself (the prompt produced it); not needed after the deletion |
