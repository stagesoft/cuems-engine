<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Contract C2: test layout and markers

**Implements** FR-047 and FR-048. **Decisions** in research R5 and R9.

## Layout

```
tests/
  __init__.py
  conftest.py        # shared fixtures + the directory-marker hook
  README.md          # the classification rule (below)
  support/           # __init__.py, helpers.py, fixtures.py, network_map_helpers.py, reader.py,
                     #   paths.py  ← DATA_DIR: the only place the data path is spelled
  data/              # ← dev/test_xml_files/* (settings, network_map, mappings, projects/…, media/ ignored)
  unit/      __init__.py, test_*.py
  integration/ __init__.py, test_*.py
  contract/  __init__.py, test_*.py
```

**Invariants** (asserted by `tests/contract/test_layout.py`, written red first):
1. No `test_*.py` and no `testdev_*.py` file sits directly in `tests/`.
2. Every collected item carries **exactly one** of the markers `unit`, `integration` or `contract`,
   and it matches the item's directory.
3. `DATA_DIR` is defined once, in `tests/support/paths.py`. No other file under `tests/` builds a
   path containing `test_xml_files` or `tests/data` by hand. The check greps the source.

## Classification rule (goes in `tests/README.md` and `CONTRIBUTORS.md`)

A test is **integration** if it does any of these:
- binds or connects a real socket (NNG, UDP, TCP, an OSCQuery or pyossia device)
- starts a real subprocess or player
- touches JACK or ALSA
- relies on a `sleep` ≥ 0.5 s for correctness

A test is **contract** if it asserts a repository or packaging invariant: the public surface,
versions, the lock, the default mappings, the changelog completeness, or this layout.

Everything else is **unit**, and a unit test that needs one of the integration resources mocks it.
`slow` stays an explicit, additional mark.

## Hook semantics (root `conftest.py`)

`pytest_collection_modifyitems` takes the first path segment under `tests/` and adds the matching
marker. An item outside the three directories raises a `pytest.UsageError` that names the file. It
never falls back to `unit` silently. `pyproject.toml` registers `unit`, `integration`, `contract`
and `slow`, and removes `cuems`. `--strict-markers` stays.

## Selection (what CI runs)

| Job | Selection |
|---|---|
| `unit` | `tests/unit tests/contract` (paths, not `-m`) |
| `integration` | `tests/integration -m "not slow"` |
| by hand on a rig | `tests/integration -m slow` |

## Move rules

- These are pure moves: `git mv`, plus import rewrites from `tests.fixtures` to
  `tests.support.fixtures`.
- The `from .conftest import …` in `test_project_go.py` is removed, because fixtures resolve by name.
- Hand-written `@pytest.mark.unit` and `@pytest.mark.integration` decorators are deleted in the same
  commit.
- **Pass-set invariant**: `pytest --collect-only -q` node ids before and after differ only by the
  path prefix and the listed retirements. The pass/fail outcome per node id is unchanged. Recorded in
  `evidence/test-layout-moves.md`.
