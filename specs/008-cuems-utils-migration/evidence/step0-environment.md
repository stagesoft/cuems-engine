# Step 0 — environment check (FR-001, T002)

Captured 2026-09-29T14:24:18+02:00, before any source or fixture change.

| Check | Expected | Observed |
|---|---|---|
| `cuemsutils.__version__` | `0.1.0rc16` | `0.1.0rc16` |
| `cuemsutils` source | `/disk/Projects/StageLab/cuems-utils/` | `/disk/Projects/StageLab/cuems-utils/src/cuemsutils/__init__.py` |
| `cuemsengine` source | this checkout's `src/` | `/disk/Projects/StageLab/cuems-engine/src/cuemsengine/__init__.py` |
| engine `HEAD` | descendant of `27b27f5` | `9c1fdc7` — descendant: yes |
| `../cuems-utils` `HEAD` | `996617f` (last verified) | `2a88a7c` — **moved** |

## G6 — the library moved (`996617f` → `2a88a7c`)

`git -C ../cuems-utils diff --stat 996617f..HEAD -- src` is **empty**: the three new commits touch
only `specs/` and docs (`2a88a7c`, `01edb01`, `2f65adc`).

Full suite re-run (`poetry run pytest -q -p no:cacheprovider`):

    ======= 28 failed, 831 passed, 10 warnings, 7 errors in 87.29s (0:01:27) =======

`comm -3` of the failing ids (short test summary) against `baseline-suite-postmerge.txt`: **empty**
— the same 35 failing ids. Proceed.
