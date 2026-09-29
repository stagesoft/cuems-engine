# Step 1 attribution (T005)

Run: `step1-network-map-converted.txt` — **9 failed, 7 errors, 850 passed** (baseline 28 F / 7 E /
831 P). cuems-utils `2a88a7c` (src identical to `996617f`, see `step0-environment.md`).
Converting the map cleared 19 failures (the whole `<node_type>` refusal family).

Categories: **(a)** FR-003 sites 1–2 — `No controller node found in network map` on a map that has
one; **(b)** FR-007/M9 — version-1 `script.xml` rejected (*character data between child
elements*); **(c)** the `settings.xml` fixture (T006); **(d)** M12/M16 — `sorted()` over `Uuid`.

| Test | Observed | Cat. |
|---|---|---|
| `test_core_baseengine.py::TestBaseEngine::test_base_engine_initialization_with_all_components` | `ValueError: No controller node found in network map` → `SystemExit: -1` | a |
| `test_core_baseengine.py::TestBaseEngine::test_base_engine_initialization_without_mtc` | same | a |
| `test_core_baseengine.py::TestBaseEngine::test_stop_all` | same | a |
| `test_core_baseengine.py::test_get_status_endpoints` | same | a |
| `test_core_baseengine_status.py::test_engine_can_start_and_stop` | same | a |
| `test_core_baseengine_status.py::test_engine_initial_status` (ERROR at setup) | same, in the `base_engine` fixture | a |
| `test_core_baseengine_status.py::test_set_status`, `test_get_status`, `test_recieved_test`, `test_get_status_none`, `test_set_status_none`, `test_all_statuses` (ERROR at setup) | `AssertionError` at `_pytest/fixtures.py:1221` (`assert not self._finalizers`) — pytest's fixture state left dirty by the `SystemExit` raised inside `test_engine_initial_status`'s setup; a cascade of that failure, not an independent one | a (cascade) |
| `test_default_mappings_valid.py::test_engine_xml_fixture_validates_against_schema[settings.xml-settings]` | `Unexpected child with tag 'audio_cards'` | c |
| `test_project_load.py::test_complex_project_load_on_controller` | `script is None`; editor error *character data between child elements not allowed* | b |
| `test_project_load.py::test_two_projects_load_on_controller` | same | b |
| `test_project_go.py::test_project_go_from_controller` | `TimeoutError: node never reached load=complex_test`; log *character data between child elements not allowed* | b |

No (d) failure surfaced in step 1: the fixture's controller is unreachable in the suite before the
controller lookup is fixed, so no `sorted()` over map uuids runs yet. Nothing outside (a)–(d).

## Step 2 (T006) — `settings.xml` converted to version 2

Run: `step2-settings-converted.txt` — **8 failed, 7 errors, 851 passed**. `comm -3` against step 1:
exactly one id left the failing set, `test_default_mappings_valid.py::test_engine_xml_fixture_validates_against_schema[settings.xml-settings]`
(category c). Nothing new. **Gate met**: the remaining 15 are all (a) or (b).
