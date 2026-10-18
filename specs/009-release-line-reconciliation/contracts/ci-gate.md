<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Contract C1: the pre-publication CI gate (`.github/workflows/ci.yml`)

**Implements** FR-050…FR-057. **Decisions** in research R1, R2, R6 and R7.

## Interface

**File name**: `.github/workflows/ci.yml`. It is never renamed: `workflow_dispatch` resolves the file
on the default branch `main`, then runs the **ref's** version of it.

**Triggers**:

```yaml
on:
  push:          { branches: [main, rc_1, feat/xml-refactor] }
  pull_request:  { branches: [main, rc_1, feat/xml-refactor] }
  workflow_dispatch:
    inputs:
      cuemsutils_ref:
        description: "cuems-utils git ref (tag/branch/sha) to install cuemsutils from"
        required: false
        default: "xml-refactor-merge-candidate"
```

Push and PR runs use the same default, through `${{ inputs.cuemsutils_ref || 'xml-refactor-merge-candidate' }}`.

## Jobs

| Job | `needs` | Container | Must do | Must not do |
|---|---|---|---|---|
| `lint` | — | ubuntu-latest | `black --check src/ tests/`, `isort --check src/ tests/`, `flake8 src/` (unchanged) | — |
| `unit` | `lint` | `debian:bookworm` | full-history checkout plus the release-ref fetch (R2); the dependency install sequence below; `pytest tests/unit tests/contract -n auto --cov=src --cov-report=` with `COVERAGE_FILE=.coverage.unit`; upload `.coverage.unit` and the JUnit XML | pass `--cov-fail-under` |
| `integration` | `lint` | `debian:bookworm` | the dependency install sequence; `pytest tests/integration -m "not slow" --cov=src --cov-report=` with `COVERAGE_FILE=.coverage.integration`; upload `.coverage.integration` and the JUnit XML | run `slow` tests |
| `coverage` | `unit`, `integration` | `debian:bookworm` | `coverage combine`; `coverage report --fail-under=45`; `coverage xml`; badge **only if** `push` and the ref is `main` or `rc_1` | push a badge on a dispatch or any other ref |
| `gate-summary` | all (`if: always()`) | ubuntu-latest | write `$GITHUB_STEP_SUMMARY` (below) | — |

**Dependency install sequence** (identical in `unit` and `integration`; research R1):

1. `poetry add --lock "git+https://github.com/stagesoft/cuems-utils.git#${CUEMSUTILS_REF}"`
2. `poetry install --with dev --no-interaction` (the cache key is computed after step 1)
3. `poetry run pip install systemd-python==235` (unchanged)
4. log `resolved_reference` (from the lock) and `cuemsutils.__version__`
5. `git checkout -- pyproject.toml poetry.lock && git diff --exit-code`

**Permissions**: `contents: read` by default. `contents: write` **only** on `coverage`.

## Gate summary (the record that evidence links to)

The summary carries the following, each as a line or a table:

- the engine ref and SHA
- the cuemsutils ref, its resolved commit and `cuemsutils.__version__`
- per job: passed, failed, skipped, xfailed and xpassed counts, parsed from the JUnit XML
- the strict-xfail list (node ids and reasons)
- the skip list with reasons, which must show whether the changelog test ran (SC-007)
- the combined coverage %

## Acceptance

- A dispatch on the 009 head with the current utils candidate tag ends `success`. Its URL and summary
  are copied into `evidence/ci-gate.md` (SC-010).
- On a dispatch on a non-`main`/`rc_1` ref, the badge step is **skipped**, as shown in the run log.
- The strict-xfail list equals {`test_lock_is_current.py::test_poetry_lock_is_current`} ∪ X-1 tests (SC-004).
- **Expected to turn red later**: once cuems-utils' reconciled tag carries `stop_project` (and S-1's
  adaptation), re-dispatching with that ref turns the X-1 tests XPASS(strict) → red. That is the
  intended signal to drop them (FR-021 / D1).
