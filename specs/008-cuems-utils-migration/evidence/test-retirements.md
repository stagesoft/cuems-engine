# Test retirements — 008-cuems-utils-migration

Every test deleted, or rewritten so that a former assertion no longer exists (SC-006).

| Item | Reason | Date |
|---|---|---|
| `tests/test_controller_gating.py::test_adopted_uuids_reader_handles_python_bool` — rewritten as `test_registers_one_route_per_adopted_node_and_leaves_the_map_alone` (FR-009); its string-form `adopted: "True"` case deleted | Decoding `adopted` belongs to cuemsutils (FR-030a-i; clarify Q4): the typed map delivers `bool`, and the engine parses no strings. The rewritten test feeds a map loaded through `ConfigManager`. Green against unchanged `src/` (characterization); must stay green through T024 | 2026-09-29 |
| `tests/test_find_hosts_characterization.py::test_find_hosts_on_a_valid_typed_map` (temporary, T018) | `BaseEngine.find_hosts` deleted (clarify Q2, T021); its pre-deletion behaviour (M8 `AttributeError`) is recorded in `failing-first-site3-4-find-hosts.txt` | 2026-09-29 |
