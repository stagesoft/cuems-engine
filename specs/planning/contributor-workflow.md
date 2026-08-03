<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Contributor Workflow — Cross-Cutting Planning Document

> **Type**: Cross-cutting planning | **Scope**: All features and contributors
> **Status**: Ratified 2026-05-20 | **Owners**: Ion Reguera, Adrià Masip

This document is the authoritative source of truth for the cuems-engine contribution
workflow. `CONTRIBUTORS.md` at the repository root is a human-facing summary derived
from this document. If the two conflict, this document wins.

---

## 1. Background and Motivation

cuems-engine is live-performance software. A regression that reaches stage hardware
causes a visible, irreversible failure in front of an audience. The contribution
workflow exists to keep that surface area as small as possible while remaining open
to external contributors.

Three root causes drive the rules below:

- **Integration faults are the dominant failure mode.** The controller/node split means
  bugs that only manifest across the network boundary are the hardest to catch and the
  most damaging in production.
- **TDD discipline erodes under pressure.** In a small, fast-moving project, it is easy
  to write code first and retrofit tests. Every time this happens, confidence in the
  test suite decreases. The workflow makes TDD the only path through review.
- **Context is lost between contributors.** Decisions made in planning docs are the only
  record of why the code looks the way it does. Without a spec-first gate, that context
  is never captured.

---

## 2. Constitution Alignment

This workflow is derived from and must stay consistent with `.specify/memory/constitution.md`
(v1.1.0). The relevant constitutional mandates are:

| Constitutional Rule | Workflow Enforcement |
|---|---|
| TDD is NON-NEGOTIABLE (§II) | Failing test required before any implementation; CI blocks merge if tests fail |
| Integration & contract tests (§III) | Integration-test gate in PR checklist; real subsystems required |
| SOLID principles (§I) | Reviewers are required to flag violations; checklist item in PR template |
| YAGNI / simplicity (§IV) | Spec-first gate limits scope creep; reviewers reject speculative code |
| Observability (§V) | PR checklist requires structured logging for every new code path |
| Spec first (Development Workflow §1) | `spec.md` and `plan.md` must exist on the branch before review begins |
| Commit hygiene (Development Workflow §5) | Conventional commits enforced; force-push to `master` forbidden |
| Doc layout (Development Workflow §7) | `specs/NNN-feature/` for feature artifacts; `specs/planning/` for cross-cutting |

---

## 3. Contribution Tiers

Two tiers apply different gates. The distinction is purely about production-code scope.

### Tier 1 — Trivial (doc, typo, comment, test-only, config)

Definition: no change to any file under `src/cuemsengine/` beyond a single-line
correction. Includes: README edits, doc fixes, comment corrections, adding a test
for already-shipped behaviour, CI/CD config changes.

Gates: lint + tests pass in CI; one owner approval; no spec required.

### Tier 2 — Non-trivial (any production code change)

Definition: any addition, modification, or deletion of logic in `src/cuemsengine/`.
Includes bug fixes that change branching behaviour, new features, refactors, and
new module introductions.

Gates: spec + plan committed on branch; failing test committed before implementation;
CI green; constitution compliance declaration; one mandatory owner approval.

---

## 4. Spec-First Gate (Tier 2 only)

Before a Tier 2 PR can enter review, the following artifacts MUST be committed on
the feature branch under `specs/NNN-feature/`:

- `spec.md` — feature specification produced by `/speckit.specify`
- `plan.md` — implementation plan produced by `/speckit.plan`, with the
  Constitution Check section completed

The PR description MUST link to these files. Reviewers MUST verify the artifacts
exist and are non-trivially complete (not stubs) before approving.

Rationale: context captured at planning time is the only reliable record of intent.
A reviewer who cannot read the spec cannot meaningfully assess whether the
implementation is correct.

---

## 5. TDD Gate

For Tier 2 PRs, the git log on the feature branch MUST show a commit containing
the failing test(s) that precedes the commit containing the implementation. The
recommended commit sequence is:

```
test: add failing test for <behaviour>          ← RED  (CI expected to fail here)
feat: implement <behaviour> to pass test        ← GREEN
refactor: <optional clean-up>                   ← REFACTOR
```

The PR checklist requires the contributor to explicitly declare:
- The commit SHA of the failing-test commit.
- That CI was observed failing on that commit before implementation began.

This requirement cannot be waived by reviewers. It is a constitution violation to
approve a Tier 2 PR without this evidence.

---

## 6. Integration Test Policy

Integration tests MUST:
- Run against real subsystems (no mocks for OSC, NNG, or subprocess boundaries).
- Be tagged `@pytest.mark.integration`.
- Cover every new inter-component boundary introduced by the PR.

Integration tests MAY be excluded from the default local run (`pytest -m "not integration"`)
but MUST run in CI on the PR branch. The CI workflow runs the full suite including
integration markers.

---

## 7. Branch Naming Convention

```
feat/NNN-short-description       ← new feature (NNN = spec number)
fix/NNN-short-description        ← bug fix referencing a spec or issue
chore/short-description          ← non-production changes (CI, tooling, docs)
```

The `NNN` prefix ties the branch to the `specs/NNN-feature/` artifacts. Branches
without a valid prefix MUST NOT be merged.

---

## 8. Commit Convention

cuems-engine uses [Conventional Commits](https://www.conventionalcommits.org/) v1.0.

Allowed types: `feat`, `fix`, `test`, `refactor`, `docs`, `chore`, `ci`, `perf`.

Breaking changes: append `!` after the type and include a `BREAKING CHANGE:` footer.

Force-pushes to `master` are forbidden by branch protection. Amending published
commits on shared branches is forbidden.

---

## 9. Changelog Policy

`CHANGELOG.md` is maintained by repository owners at release time. Contributors do
not edit it directly. Instead, the PR title and body MUST contain a **Changelog
Line** — a single sentence in past tense describing the change as it would appear
in a user-facing changelog entry. Owners copy this line verbatim (or lightly edited)
into `CHANGELOG.md` when cutting a release.

Format: `[TYPE] Brief description of what changed and why it matters to users.`

Example: `[Added] FadeCue now supports per-layer opacity targets on multi-layer video cues.`

---

## 10. Developer Certificate of Origin (DCO)

cuems-engine uses the DCO rather than a CLA. Every commit MUST be signed off with:

```
git commit -s -m "feat: ..."
```

This appends `Signed-off-by: Your Name <your@email.com>` to the commit message,
asserting that you have the right to submit the work under the project licence
(GPL-3.0) per [developercertificate.org](https://developercertificate.org).

PRs containing commits without a sign-off will not be merged.

---

## 11. Review and Approval

All PRs to `master` require **at least one approval from a repository owner**
(Ion Reguera or Adrià Masip). This is enforced by a CODEOWNERS rule and GitHub
branch protection (`required_pull_request_reviews: 1`).

Owners MUST check:
1. Spec and plan exist (Tier 2) and are coherent with the implementation.
2. TDD sequence is evidenced in git log.
3. All CI gates pass (test, lint, coverage).
4. Constitution checklist items in the PR template are ticked and accurate.
5. No new runtime dependency introduced without documented justification.
6. SPDX header present on all new source files.

---

## 12. CI Gates (required to merge)

The `ci.yml` workflow runs on every PR and every push to `master` and `rc_1`.

| Gate | Tool | Blocks merge? |
|---|---|---|
| Lint — style | `black --check` | Yes |
| Lint — imports | `isort --check` | Yes |
| Lint — quality | `flake8` | Yes |
| Unit tests | `pytest -m "not integration"` | Yes |
| Integration tests | `pytest -m integration` | Yes |
| Coverage floor | `pytest --cov`, fail below 80% | Yes |

Coverage threshold is 80% and will be raised as the test suite matures.

---

## 13. Dependency Governance

No new runtime dependency (a package listed under `[tool.poetry.dependencies]`) may
be introduced without:

1. A written justification in the PR description explaining why the standard library
   and existing dependencies cannot solve the problem.
2. Explicit owner acknowledgement in the review.

Dev-only dependencies (`[tool.poetry.group.dev.dependencies]`) are lower friction
but still require a one-line justification.

---

## 14. Amendment Process

Changes to this document require:
1. A PR with the proposed change and a written rationale.
2. Approval from both owners.
3. Synchronisation of `CONTRIBUTORS.md` with the updated rules.
4. If a constitutional principle is affected: a constitutional amendment per
   `.specify/memory/constitution.md` §Governance.
