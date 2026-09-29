# CI is red by construction until cuemsutils rc16 publishes (T040, FR-017a)

Recorded 2026-09-29. Engine `7146100`+worktree, cuems-utils `2a88a7c`.

## Why

- CI (`.github/workflows/ci.yml:42`, `:118`) runs `poetry install --with dev --no-interaction`,
  which installs what `poetry.lock` pins: **`cuemsutils` 0.1.0rc14** (`poetry.lock:346-347`).
- rc14 lacks the surface this branch reads — `cuemsutils.tools.NodeList.NodeRole`/`NodeIndex`,
  `CuemsScript.load` with version-1 → 2 conversion, and the versioned schemas (measured, research
  R7). The converted fixtures (`node_role`, `settings.xml` `doc_version="2"`) and the new tests
  therefore fail under rc14. **CI has been red from Phase 2 onward** (commit `984ac2b`).
- After T038 (`pyproject.toml:50` → `cuemsutils = ">=0.1.0rc16,<0.1.1"`) the lock no longer
  satisfies `pyproject.toml`, so `poetry install` refuses the stale lock outright. Measured:
  `poetry check --lock` → *Error: pyproject.toml changed significantly since poetry.lock was last
  generated. Run `poetry lock` to fix the lock file.*
- rc16 is **not published**: `pip index versions cuemsutils --pre` on 2026-09-29 lists
  `0.1.0rc14` as the latest (same as the 2026-09-28 check). This branch runs against the editable
  `../cuems-utils` checkout (`__version__` 0.1.0rc16); `poetry install`/`poetry lock` are never
  run here, since either would replace it (FR-017a).

## The one step that clears it

`poetry lock` (and commit the lock) **once rc16 is on PyPI** — then CI installs rc16 and the suite
is the one recorded in `final-suite.txt`.

## Consequence

**No pull request from this branch until that re-lock turns CI green** (FR-017a; constitution
Workflow §4).
