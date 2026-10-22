<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# CI gate run (T113, T114): deferred

**Not run, by decision (maintainer, 2026-10-22).** The dispatched run waits for the coordinated re-cut of the cuems-utils
candidate tag: until the tag is re-cut on a head that carries `stop_project`, the run would only exercise the stale tag, where the
two X-1 tests are xfailed. Nothing was pushed and no workflow was dispatched.

What stands in place of the run:

- `.github/workflows/ci.yml` follows contract C1; it passes `actionlint`, parses as YAML, only `coverage` has `contents: write`, and the
  embedded gate-summary script was executed locally against a real JUnit file.
- The same commands the jobs run, locally with the libmtc stub: `pytest tests/unit tests/contract -n auto --dist loadfile` and
  `pytest tests/integration -m "not slow" --dist loadfile` (counts in `inventory-proofs.md`), plus the xfail sets against the
  candidate tag and against `feat/xml-refactor` (`strict-xfails.md`).

To close this file later: dispatch `ci.yml` on the post-merge `feat/xml-refactor` head with `cuemsutils_ref` = the re-cut tag, then record the
run URL, the engine SHA (= HEAD), the cuemsutils ref/commit/version, each job's conclusion and counts, the xfail list (only the lock test
once the tag carries `stop_project`), whether the changelog test ran or skipped, the combined coverage, and the skipped badge step.
