<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Strict xfails (T066, SC-004)

HEAD `9190e52` (+ the T059-T066 files), `pytest tests -rxX`.

## Against the candidate tag `xml-refactor-merge-candidate` (`4b336cd`), the library the CI gate defaults to

```
cuemsutils from /tmp/claude-1000/-disk-Projects-StageLab-cuems-engine/fb57d86a-231d-4f59-bb70-18714004de2e/scratchpad/utils-tag/src/cuemsutils/__init__.py
XFAIL tests/test_lock_is_current.py::test_poetry_lock_is_current - poetry.lock relocks at publication, once cuemsutils 0.1.1 is resolvable (cuems-utils 016, FR-022)
XFAIL tests/test_stop_project_xsd.py::test_a_targetless_stop_project_script_loads - cuems-utils 0.1.1 lacks rc17 stop_project — specs/009-release-line-reconciliation/upstream-reports/cuems-utils-x1-x4.md
XFAIL tests/test_stop_project_xsd.py::test_a_loaded_stop_project_script_saves_through_the_published_write_path - cuems-utils 0.1.1 lacks rc17 stop_project — specs/009-release-line-reconciliation/upstream-reports/cuems-utils-x1-x4.md
======================= 1446 passed, 3 xfailed in 24.34s =======================
```

## Against cuems-utils `feat/xml-refactor` head (the editable checkout)

```
XFAIL tests/test_lock_is_current.py::test_poetry_lock_is_current - poetry.lock relocks at publication, once cuemsutils 0.1.1 is resolvable (cuems-utils 016, FR-022)
======================= 1448 passed, 1 xfailed in 24.34s =======================
```

## Reading

- **Against the tag** the xfail set is exactly `{test_lock_is_current.py::test_poetry_lock_is_current}` ∪ the two X-1 tests, each X-1
  reason carrying the report path (SC-004). The rest of the suite (1446 tests) passes against the tag: the only thing the engine
  needs from a newer cuems-utils is `stop_project`.
- **Against the head** the X-1 tests pass for real (load and save of a targetless `stop_project` script). They are
  `xfail(strict=True)` only while the installed library refuses the fixture; this is the interim between cuems-utils landing 017
  on `feat/xml-refactor` and the candidate tag being re-cut (FR-021 resolved without a manual step: nothing to remove, the
  tests stop being xfails by themselves).
- **Deviation from T060's text, recorded**: T060 asks for unconditional `@pytest.mark.xfail(strict=True)`. Unconditional markers
  would XPASS (and, being strict, fail) on the editable checkout, which already carries the value. The `condition` is the
  library's own refusal of the fixture, so the markers never lie in either direction.

## Paths cited by the markers and the docs exist (I6)

```
ok  specs/009-release-line-reconciliation/upstream-reports/cuems-utils-x1-x4.md
ok  specs/009-release-line-reconciliation/upstream-reports/cuems-utils-x1-x4.md
ok  specs/009-release-line-reconciliation/upstream-reports/cuems-utils-x1-x4.md
```
