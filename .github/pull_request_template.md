## Summary

<!-- 2–5 sentences: what changed and why. -->

## Changelog Line

<!-- One sentence, past tense. Owners paste this into CHANGELOG.md at release time.
     Format: [Added|Changed|Fixed|Removed|Security|Performance] Description. -->

## Contribution Tier

- [ ] **Tier 1 — Trivial** (doc, comment, test-only, config — no `src/cuemsengine/` logic changed)
- [ ] **Tier 2 — Non-trivial** (any production code change under `src/cuemsengine/`)

---

## Tier 2 Gates (skip if Tier 1)

### Spec & Plan

- [ ] `specs/NNN-feature/spec.md` is committed on this branch: <!-- link -->
- [ ] `specs/NNN-feature/plan.md` is committed on this branch with Constitution Check completed: <!-- link -->

### TDD Evidence

- [ ] A failing test was committed **before** the implementation.
  - Failing-test commit SHA: `<!-- e.g. abc1234 -->`
  - CI was observed failing on that commit (or local pytest output confirms failure).

### Implementation Checklist

- [ ] Every new code path has structured logging (no silent failures).
- [ ] SOLID principles respected — no mixed responsibilities, dependencies injected.
- [ ] No new runtime dependency introduced. *(If one was added, justification below.)*
- [ ] All new source files carry an SPDX header.

**New dependency justification** *(delete if none)*:
> Why the standard library and existing deps cannot solve this:

---

## All PRs

### Tests & Lint

- [ ] `pytest` (full suite, including integration tests) passes locally.
- [ ] `black --check src/ tests/` passes.
- [ ] `isort --check src/ tests/` passes.
- [ ] `flake8 src/ tests/` passes.
- [ ] CI is green on this PR.

### Commits

- [ ] All commits follow Conventional Commits (`feat:`, `fix:`, `test:`, etc.).
- [ ] Every commit carries `Signed-off-by` (DCO).
- [ ] Each commit is atomic — one logical change per commit.

### Constitution Compliance

- [ ] I have read `.specify/memory/constitution.md` and this PR does not violate it.
  If it introduces a complexity exception, it is documented in the plan's
  Complexity Tracking table.

---

## Notes for Reviewers

<!-- Anything that helps the reviewer: tricky edge cases, areas of uncertainty,
     subsystems that might be affected beyond what tests cover. -->
