# Research — 008-cuems-utils-migration

**Date**: 2026-09-28 · **Engine**: `feat/xml-refactor` @ `afbd5cf` · **Library**: editable
`../cuems-utils` `feat/xml-refactor` @ `0ba239b` (`__version__` 0.1.0rc16)

Every entry below was **measured**, and the command or probe is stated so it can be re-run. Nothing
here re-derives the planning bundle (`specs/planning/xml-refactor/`); it covers what the bundle did
not measure, or where the measurement contradicted it.

The probes load `dev/test_xml_files/` copies from the scratchpad, with `network_map.xml`'s two
`<node_type>` lines rewritten to `<node_role>controller|node</node_role>`.

---

## R1 — What does the public network map actually look like?

**Probe**: `ConfigManager(config_dir=<converted copy>, load_all=False).load_network_map()`, then
inspect `cm.network_map`.

| Aspect | Measured |
|---|---|
| Map type | `CuemsNetworkMapType` (dict-like; `["node_list"]` works) |
| `node_list` | `list` of **`{"node": node}` wrappers** — the wrapper survives the typed load |
| Node type | `cuemsutils.tools.NodeList.node` (a `ConfigDict`) |
| `node_role` | `NodeRole` enum member; `== NodeRole.controller` → `True`; `== "controller"` → **`False`** |
| `adopted`, `online` | real `bool` |
| `uuid` | `Uuid` — `== str` ✓, `hash` equal ✓, `f"/{u}/*"` formats ✓, `json.dumps` ✓, **`sorted()` raises `TypeError`** |

**Decision**: the engine reads the map through `ConfigManager.network_map` only; unwraps
`node_item["node"]` once; compares roles to `NodeRole.controller`; converts `uuid` to `str` at the
single read point.

**Rationale**: the bundle's "shape inverts" (`03-migration-inventory.md` §3) describes
`partition_by_adoption`'s *return value*. Under clarify Q1 → A there is no call to it, and the map
itself still wraps. Following the bundle literally (dropping the unwrap) is precisely what yields
`None` for every uuid. `str` conversion is not cosmetic: `get_cluster_status` returns
`sorted(adopted)` (`ControllerEngine.py:1741`), a cross-repository contract with `cuems-editor`.

**Alternatives rejected**: build a `NodeIndex` for the adoption read — `NodeIndex` has no adoption
selector (`adopt`/`unadopt`/`missing_adopted` serve a different purpose); keying it would add
machinery for a one-line filter. Keep `Uuid` objects and sort by `str` at each `sorted` call —
spreads the concern over every consumer, and misses OSC arguments.

## R2 — The controller lookup's public path

**Probe**: `NodeIndex.from_nodes([i["node"] for i in nm["node_list"]], key=lambda n: n["uuid"]).controllers`
→ one node, `ip == "192.168.1.10"`.

**Decision**: `_controller_ip_from_map` builds the index this way and reads `.controllers`
(a `tuple`). `len > 1` → structured error listing every `(uuid, ip)`, return the first (FR-005a).
`len == 0` → the existing `ValueError("No controller node found in network map")`.

**Rationale**: `controllers` is documented upstream as *"the one selection with a caller in every
repository"*; using it keeps role interpretation inside the library (FR-030a-i). Map order is
preserved by `from_nodes` (dict insertion order), so "first" is deterministic.

## R3 — The show loader

**Probe**: `XmlReaderWriter(schema_name="script", xmlfile=complex_test/script.xml).read_to_objects()`
vs `CuemsScript.load(same)`.

| Path | Version-1 `complex_test/script.xml` |
|---|---|
| `XmlReaderWriter.read_to_objects()` (today's `BaseEngine.py:509`) | **raises** `XMLSchemaValidationError` — `<duration>00:00:00.000</duration>`: *character data between child elements not allowed* |
| `CuemsScript.load(path)` | loads; 6 media durations, all `CTimecode` |

**Decision**: `read_script` calls `CuemsScript.load(xml_file)`. Keep the existing
`FileNotFoundError` pre-check and the hardcoded `"script.xml"` (FR-015).

**Rationale**: the deprecated path runs no conversion, so today's engine cannot load a version-1
show against the current library at all — a live defect, masked in the baseline by the
`network_map` refusal. `load_with_report` exists too; `load` is enough: a repair report has no
consumer in the engine (YAGNI), and conversion outcomes are logged by the library.

**Consequence for FR-002**: after converting the `network_map` fixture, the `test_project_load.py`
family fails for a *new* reason — the script. That run is FR-007's failing-first evidence and must
be named as such in `evidence/`, not mistaken for fixture fallout.

## R4 — Empty durations reach the playback path from real documents

**Probe**: convert `complex_test/script.xml` to version 2 in place
(`python -m cuemsutils.xml.convert_documents <file>` → *converted*, `doc_version="2"`, 45
`<CTimecode>` elements), replace the first `<duration><CTimecode>…</CTimecode></duration>` with
`<duration/>`, `CuemsScript.load`.

| File | First three media durations |
|---|---|
| v1 | `00:00:00.000`, `00:00:00.000`, `00:00:00.000` |
| v2 (converted) | same |
| v2 with `<duration/>` | **`None`**, `00:00:00.000`, `00:00:00.000` |

`CTimecode(None)` → `00:00:00.000`. `script.xsd`'s `CTimecodeType` is `<xs:choice minOccurs="0">`.

**Decision**: FR-016b's explicit `None` → zero with a warning, implemented once as a small helper
the five sites share (three similar blocks would be allowed; five identical ones are the threshold
the constitution's IV names). The helper returns a `CTimecode`; each site keeps its own
`return_in_other_framerate` / `milliseconds_exact` call.

**Rationale**: removing the wraps naively turns a valid document into an `AttributeError` on the
playback path. Keeping zero preserves today's behaviour exactly; the warning ends the silence
(constitution V).

## R5 — Fixture conversion tools

| Fixture | Tool | Where |
|---|---|---|
| `dev/test_xml_files/network_map.xml` (`node_type` → `node_role`) | `cuems-migrate-network-map` | `../cuems-common/usr/bin/` (not installed on this box; run from the checkout) |
| `dev/test_xml_files/settings.xml` (v1 → v2) | `python -m cuemsutils.xml.convert_documents <file>` | library entry point `cuems-convert-documents`; converts **in place** |
| a version-2 `script.xml` fixture for SC-007 | same converter, on a **copy** | new fixture, the v1 original is kept |

**Decision**: convert with the owning tools, never by hand, and record each tool's output in
`evidence/`. A hand edit would test the engine against a document no tool produces.

## R6 — The `cuems-common` floor

`git -C ../cuems-common log -S 'Breaks: cuems-nodeconf (<< 0.1.0-8)' -- debian/control` → `d92317d`
(2026-08-24). At that commit `debian/changelog`'s top is `1.3.0-22`, already released; the commit
is contained only in `007-node-model-migration` and `feat/xml-refactor`. The next entry, `1.3.0-23`,
is `UNRELEASED`.

**Decision**: `cuems-common (>= 1.3.0-23~)`. Matches `cuems-nodeconf`'s own
`Breaks: cuems-common (<< 1.3.0-23~)` — the two packages already agree on the version.

## R7 — `cuemsutils` availability, lock and CI

`pip index versions cuemsutils --pre` → latest **0.1.0rc14**; rc16 unpublished. `poetry.lock`
(tracked) pins **rc11**. CI (`.github/workflows/ci.yml:38`, `:109`) runs
`poetry install --with dev` from the lock. The siblings that already pin rc16
(`cuems-nodeconf`, `cuems-power-bridge`) commit **no** lock file.

**Decision** (clarify Q3): pin now, do not re-lock, CI red by construction until publish, recorded.
See the Complexity Tracking entry in `plan.md` — this conflicts with constitution Workflow §4.

## R8 — Fade handler removal: what a stray `fade_in` meets afterwards

`ActionHandler.py:244-245`: an `action_type` outside `SUPPORTED_CUE_ACTIONS` returns a
`failed` result, *"Unsupported action_type: 'fade_in'"*, before any dispatch. `script.xsd` v2
rejects `fade_in` outright (`:190`, FR-029a upstream). So after deletion: a converted document never
carries it; an in-memory cue carrying it fails cleanly and visibly. Tests to retire with the
handlers: `tests/test_action_cue.py:254-330` (T011/T012 classes). `test_effective_duration.py:39`
and `test_fade_action_handler.py` concern DMX fade timing and `FadeCue`, not these handlers —
untouched.

## R9 — Test files that reach deleted symbols

| File:line | Reaches | Disposition (clarify Q4) |
|---|---|---|
| `tests/test_controller_gating.py:283` | `_adopted_uuids_from_network_map` directly, string-`adopted` case | rewrite as FR-009's test; retire the string case (recorded) |
| `tests/test_cluster_warning.py:81`, `:337` | `patch.object(…, "_adopted_uuids_from_network_map")` | feed a typed map |
| `tests/test_nodelist_modify.py:410`, `:484` | same | feed a typed map |
| `tests/test_action_cue.py:254-330` | `fade_in`/`fade_out` handlers | retire with the handlers (recorded) |
| `tests/test_core_baseengine_controller_ip.py:34`, `:38`, `:101` | retired-vocabulary fixtures | convert; keep a pre-007 case only as a negative (must not resolve) |

No test references `find_hosts` or `CONTROLLER_NETWORK_FLAG` (grep over `tests/`).

## R10 — The "not renamed" exit criterion under Q1 → A

`00-runnable-flow.md` §6 criterion 4: `_adopted_uuids_from_network_map` is *"deleted, not
renamed"*. Under Q1 → A some reader of adoption must exist, because the public surface offers no
partition (UR-1).

**Decision**: one private reader, `_adopted_node_uuids()`, serves all four sites (the surviving
`get_nodes_by_adoption` site **and** the three callers). It is not a port: it drops the
string-parsing branch (the library's job, FR-030a-i), drops the "avoid the mutating method"
rationale (nothing mutates now), unifies two previously separate readers into one, and returns
`frozenset[str]` (R1). Its docstring names UR-1 as the reason it exists and the public partition as
its replacement. The exit criterion is read as intended — *no workaround for the mutation survives*
— and this reading is stated in `plan.md`, not assumed.

## R11 — Upstream reports to file (FR-022)

| ID | Report | Evidence |
|---|---|---|
| UR-1 | No public, non-mutating adoption partition; `partition_by_adoption` is reachable only via internal `cuemsutils.xml.settings` | R10 |
| UR-2 | `versioning.py:30-32` comment says only `script` moves; `CURRENT_VERSION` has three schemas at 2 | spec M4 |
| UR-3 | Editable install reports `0.1.0rc12` metadata while `__version__` is `0.1.0rc16` | `evidence/baseline-environment.md` — **may be environmental** (a stale `pip install -e`); verify before filing |
| UR-4 | `Uuid` equals and hashes like `str` but defines no ordering; `sorted()` over node uuids raises | R1 |
