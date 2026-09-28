# Baseline suite — environment (FR-001)

Captured 2026-09-28T11:00:48+02:00, before any source or fixture change. Output: `baseline-suite.txt`.

| | |
|---|---|
| cuems-engine | `feat/xml-refactor` @ `afbd5cf` (= `dbc9e6d` + docs only), clean |
| Command | `poetry run pytest -q -p no:cacheprovider` |
| Python | 3.11.9 |
| cuemsutils source | **editable** — `file:///disk/Projects/StageLab/cuems-utils` (`direct_url.json`) |
| cuemsutils tree | `feat/xml-refactor` @ `0ba239b`, `git describe` `v0.1.0rc14-138-g0ba239b` |
| cuemsutils `__version__` | `0.1.0rc16` (installed dist metadata says `0.1.0rc12` — stale editable metadata) |
| `poetry.lock` | pins `cuemsutils` **0.1.0rc11** (PyPI wheel) — does **not** match this environment (M7) |
| Test files | 45 under `tests/` |

**Result**: 28 failed, 7 errors, 720 passed, 10 warnings, 86.63 s.

**Causes** (both are the library having moved past this repository's fixtures, not engine regressions):

1. `dev/test_xml_files/network_map.xml` is refused by the library: *"node 0367f391-… still carries the
   retired `<node_type>` element (value 'NodeType.master') — network_map.xsd now requires `<node_role>`
   … Run the network_map conversion (cuems-migrate-network-map)"*. Hits `test_project_load.py` (20),
   `test_core_baseengine.py` (4), `test_core_baseengine_status.py` (1 failed + 7 errors),
   `test_project_go.py` (1), and `test_default_mappings_valid.py[network_map.xml]` (1).
2. `test_default_mappings_valid.py[settings.xml]`: raw schema validation fails — *"Unexpected child with
   tag 'audio_cards'"*. `settings.xsd` is at version 2 since `cuems-utils` `782f669` (2026-09-23).
