<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Environment (T001)

Recorded 2026-10-22 on branch `009-release-line-reconciliation` @ `aa0ffe6`.

| Item | Value |
|---|---|
| Python | 3.11.9 (`PYENV_VERSION=3.11.9`) |
| Test venv | `.venv-016` (`/disk/Projects/StageLab/cuems-engine/.venv-016`), cuemsutils 0.1.1 editable from `../cuems-utils` |
| Poetry | 2.4.1, in `.venv-016/bin/poetry` (not on `PATH`) |
| `../cuems-utils` HEAD | `ff84193b3beee8ed3f3ec7485621ed5dc04eb122` |
| Candidate tag commit (`xml-refactor-merge-candidate`) | `4b336cd` |
| Drift of the checkout past the tag | 133 commits (`git rev-list --count 4b336cd..HEAD` in `../cuems-utils`) |
| `cuemsutils.__version__` | 0.1.1 |
| `libmtcmaster.so.0` | **absent** (`/sbin/ldconfig` not on PATH; `cdll.LoadLibrary` is what decides, see `libmtc-stub.patch`) |
| `gh` | **not available** (PR state cannot be read; #22/#23 are merged by SHA either way, FR-006) |
| `dpkg-parsechangelog`, `unshare` | available |
| `xmllint`, `actionlint` | not found on PATH |
| `black`, `isort`, `flake8` | **not installed in `.venv-016`**; lint needs a separate tool venv (see T071 notes) |
| `pytest-xdist`, `pytest-cov` | available in `.venv-016` |

## Keyring (research R1)

Poetry in a headless job has no usable keyring backend; CI sets
`PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring`. Nothing in the working tree runs
`poetry install`/`lock`/`add` (FR-037).

## Arms

Both arm A (`e994a5e`) and the 009 head run with the libmtc stub (`libmtc-stub.patch`), applied
before a run and reverted before every commit. The `cuemsutils` checkout is 133 commits past its
tag: every captured run records its HEAD (G6).
