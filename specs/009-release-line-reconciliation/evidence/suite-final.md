<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Final suite comparison, three interleaved rounds (T070, T071, SC-003)

HEAD `e6518fb`. Arm A is `e994a5e` in a temporary worktree (removed afterwards) with the same libmtc stub.
Both arms ran with the cuems-utils checkout at `aafb3b9` (`cuemsutils` 0.1.1). Each round: arm A, then HEAD, each in two
passes (`-m "not integration"` under xdist, then `-m "integration and not slow"`).

## Round set 1: xdist default distribution (`-n auto`)

| Run | Pass 1 | Pass 2 | Failing ids |
|---|---|---|---|
| A1 | 885 passed, 1 xfailed in 15.36s  | 32 passed, 892 deselected in 7.11s  |  |
| H1 | 1448 passed, 1 xfailed in 18.86s  | 32 passed, 1455 deselected in 7.71s  |  |
| A2 | 885 passed, 1 xfailed in 14.92s  | 32 passed, 892 deselected in 7.61s  |  |
| H2 | 1 failed, 1447 passed, 1 xfailed in 20.58s  | 32 passed, 1455 deselected in 7.75s  | tests/test_port_handler.py::test_get_free_port_skips_bound_port  |
| A3 | 885 passed, 1 xfailed in 13.38s  | 32 passed, 892 deselected in 7.58s  |  |
| H3 | 1 failed, 1447 passed, 1 xfailed in 24.34s  | 32 passed, 1455 deselected in 7.18s  | tests/test_port_handler.py::test_get_free_ports_no_duplicates  |

HEAD failed in rounds 2 and 3, each time in `tests/test_port_handler.py`, a **different** test each time
(`test_get_free_port_skips_bound_port` — "Address already in use" on port 9191; `test_get_free_ports_no_duplicates`).

### It is a pre-existing race, not a regression

`test_port_handler.py` and `PortHandler.py` are untouched by 009. Its tests each ask `free_pool(n)` for the lowest bindable ports of
the allocator's range and some bind them for real, so two of its tests landing on different xdist workers collide.
Measured in isolation, `pytest tests/test_port_handler.py -n 4`:

| Tree | Runs with a failure |
|---|---|
| HEAD | 12 of 12 |
| `e994a5e` (arm A, temporary worktree) | 7 of 8 |

In the full suite it appears when xdist happens to split that file across workers; with 885 tests arm A got lucky three times,
with 1448 HEAD did not. It is not caused by a test 009 added.

## Round set 2: `--dist loadfile` (all tests of a file on one worker)

| Run | Pass 1 | Pass 2 | Failing ids |
|---|---|---|---|
| A1 | 885 passed, 1 xfailed in 19.99s  | 32 passed, 892 deselected in 7.58s  |  |
| H1 | 1448 passed, 1 xfailed in 23.30s  | 32 passed, 1455 deselected in 7.18s  |  |
| A2 | 885 passed, 1 xfailed in 19.40s  | 32 passed, 892 deselected in 7.58s  |  |
| H2 | 1448 passed, 1 xfailed in 23.27s  | 32 passed, 1455 deselected in 7.18s  |  |
| A3 | 885 passed, 1 xfailed in 19.39s  | 32 passed, 892 deselected in 7.58s  |  |
| H3 | 1448 passed, 1 xfailed in 23.19s  | 32 passed, 1455 deselected in 7.68s  |  |

Five further HEAD runs of pass 1 with `--dist loadfile`: 1448 passed, 1 xfailed each time.

**SC-003 holds with `--dist loadfile`**: HEAD's failures are the empty set in every run, a subset of arm A's (also empty). With the default distribution it
holds except for the pre-existing `test_port_handler` race above. **Consequence adopted**: the CI `unit` and `integration` jobs (T107, T108) run
`-n auto --dist loadfile`, and CONTRIBUTORS.md's testing section says to use it. Fixing the race in `test_port_handler.py` itself (random ports with a
bind retry) is left to a follow-up: it is not part of 009's scope.

## Lint (T071)

`black --check src tests`, `isort --check src tests`, `flake8 src`, run from a scratch venv with black 26.10.1, isort and flake8 7.4.1 (the repository declares them unpinned):
```
148 files would be left unchanged.
isort: clean
flake8: clean
```
