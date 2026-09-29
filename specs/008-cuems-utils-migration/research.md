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
`node_item["node"]` once; compares roles to `NodeRole.controller`; ~~converts `uuid` to `str` at the
single read point~~ — **superseded 2026-09-29 by R14**: ids stay as the library delivers them
(`Uuid` canonical), rendered with `str()` only at egress.

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
a `frozenset` of ids under the identity policy (R14 — originally `frozenset[str]`, superseded). Its docstring names UR-1 as the reason it exists and the public partition as
its replacement. The exit criterion is read as intended — *no workaround for the mutation survives*
— and this reading is stated in `plan.md`, not assumed.

## R11 — Upstream reports to file (FR-022)

| ID | Report | Evidence |
|---|---|---|
| UR-1 | No public, non-mutating adoption partition; `partition_by_adoption` is reachable only via internal `cuemsutils.xml.settings` | R10 |
| UR-2 | `versioning.py:30-32` comment says only `script` moves; `CURRENT_VERSION` has three schemas at 2 | spec M4 |
| UR-3 | Editable install reports `0.1.0rc12` metadata while `__version__` is `0.1.0rc16` | `evidence/baseline-environment.md` — **may be environmental** (a stale `pip install -e`); verify before filing |
| UR-4 | `Uuid` equals and hashes like `str` but defines no ordering; `sorted()` over node uuids raises | R1 |

---

# Addendum — 2026-09-29, after merging `rc_1` (`956a0f3`) at `27b27f5`

## R12 — Merge: `rc_1`, not `debian/bookworm`

`7f6e475` (`debian/bookworm`) = `rc_1` @ `956a0f3` + packaging only (`git diff --stat origin/rc_1
7f6e475`: `debian/*`, `__init__.py`/`pyproject.toml` version). Trial merges of both into
`feat/xml-refactor` were clean (`git merge-tree`); the merged tree's suite fails the same 35 test ids
as the pre-merge baseline (`comm` over the two summaries: empty both ways), 28 F / 7 E / 831 P.
**Decision**: merge `rc_1`; packaging stays on its branch. Post-merge baseline:
`evidence/baseline-suite-postmerge.txt`.

## R13 — Versioning practice and the rc3–rc6 backfill

| Release | `debian/bookworm` commit | Date | `rc_1` range shipped |
|---|---|---|---|
| rc3 | `30af517` (bump), after merge `99460bb` | 2026-04-16 | packaging line; predates tag `v0.1.0rc2` (2026-05-19, `853c67b`, not an ancestor of `30af517`) |
| rc4 | `15d50b6` | 2026-08-03 | `v0.1.0rc2..2abf26d` — 100 non-merge commits |
| rc5 | `8b57710` | 2026-08-14 | `2abf26d..fc8d2bb` — 5 |
| rc6 | `7f6e475` | 2026-09-28 | `fc8d2bb..956a0f3` — 31 |

`rc_1` stays at `0.1.0rc2`; `debian/bookworm` bumps. **Decision** (clarified): backfill rc3–rc6 in
`CHANGELOG.md` dated as above; rc7 `UNRELEASED`; `debian/changelog` untouched on this branch; drift
test checks `__init__`/`pyproject`/`CHANGELOG.md`. Prose sources: the ranges' commit messages and
`git show 7f6e475:debian/changelog` (entries `0.1.0rc3-1` … `0.1.0rc6-1`).

## R14 — Identity: what the library actually delivers

| Source | Type delivered | Measured by |
|---|---|---|
| `cue.id`, CueList id (script load) | `Uuid` | `CuemsScript.load(complex_test)` |
| map node `uuid`, uuid4 value | `Uuid` | typed `ConfigManager.load_network_map` |
| map node `uuid`, uuid1 value | **`str`** | same, with `aaaaaaaa-099f-11f0-a075-00e04c01b7e3` in map and settings |
| `node_conf["uuid"]` | `str` always | `settings.xsd:66` `NonEmptyString` |
| `output_name` | `str` (engine slices `[:36]`) | script load |
| OSC / NNG / editor ids | `str` | wire |

`Uuid` (`cuemsutils/tools/Uuid.py`): `__eq__`/`__hash__` against `str` ✓, `__str__`/`__json__` ✓;
no `__lt__`, no sequence protocol; `Uuid(x)` raises unless `UUID4_REGEX` matches. The decoder
(`cuemsutils/xml/adapters.py:112-142`, internal) returns `Uuid` for a uuid4 and the **raw `str`**
otherwise — deliberately, citing the nil uuid in real editor payloads and its FR-015.

**Decision** (clarified: `Uuid` canonical): mirror the decoder at ingress (`as_id`), render with
`str()` at egress (`id_str`), in one module — `src/cuemsengine/tools/ids.py` (the engine's existing
utilities package). `sorted(..., key=str)` everywhere ids are ordered.

**Rationale for mirroring rather than enforcing**: enforcing uuid4 at ingress (`Uuid(x)`) would
crash on inputs the library accepts, and on today's fleet ids until feature 012 re-mints them.

**Alternatives rejected**: `str` canonical (the earlier FR-009a) — fights the library's type;
values-as-delivered with no normalization — `Uuid` and `str` for one node coexist in a set only by
the grace of `__hash__`/`__eq__`, and every new operation re-opens M12.

Engine sites (post-merge coordinates): ingress — `BaseEngine.py:315`, `:325`;
`ControllerEngine.py:167`, `:281`, `:310`, `:350`, `:385`, `:472`, `:551`, `:568`, `:588`, `:609`,
`:987`, `:1422`, `:1441`, `:1458`, `:1483`; `NodeEngine.py:632`. Egress — sorts `:1557`, `:1588`,
`:1626-1627`, `:1654-1655`, `:1703`, `:1766-1767`; slices `:1488`, `BaseEngine.py:315`. Already
safe: `CueHandler.py:686` (`str(n.id)`, `rc_1` `6068dd8`), `run_cue.py:191` and
`PlayerHandler.py:486/:498` (`str(cue.id)`); `PlayerHandler.py:223/:270/:342` and
`AudioPlayer.py:31` split keys of `_audio_players_by_id`, populated with `str(cue.id)` — to be
re-verified, not changed. Test literals: 11 distinct uuids, 6 not uuid4 (`test_controller_gating.py`
×3, `test_controller_commands.py`, `test_node_comms_mixer.py`, `test_node_comms_ping.py` ×2).

## R15 — `fade_out` is not `stop`

`_handle_stop` returns `applied_no_change` when `_stop_requested` is already set and calls
`ch.disarm(target)`; `_handle_fade_out` (`ActionHandler.py:567-583`) does neither — its TODO:
*"the same zombie-process bug as the old stop handler … does not call disarm()"*. `_handle_fade_in`
diffs against `_handle_play` in comments and one log line only. **Decision**: FR-014 corrected;
T-numbered characterization asserts `stop` semantics for a converted `fade_out` (disarm called) and
records it as a behaviour change; UR-7 upstream.

## R11 addendum — upstream reports

UR-6 no public id-coercion helper (R14). UR-7 `fade_out` → `stop` is a behaviour change here (R15).
