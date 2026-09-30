# Identity audit — Group 7 (T055, SC-012)

Recorded 2026-09-29 after T054 and the T055 fix. Scans (research R14) over `src/cuemsengine/`:
`sorted(`/`min(`/`max(`, `[:36]`/`[:8]`/`[-12:]`, `.split("-")`, `.join(`, `isinstance(…, str)`,
`json.dumps`, and raw ids passed as OSC/NNG arguments. 74 raw hits; the ones that do **not** touch an
id (port numbers, geometry, volumes, path joins, thread joins, DMX channel maps, comments) are
omitted below. Line numbers are current (post-T055).

**Rule**: an id enters through `as_id`, leaves through `id_str` — or the site is listed here as safe,
with the reason.

**2026-09-30**: `as_id` is now cuems-utils 012's `cuemsutils.tools.coerce_identity` (the engine's
mirror is deleted). The two agree on every input an ingress site below passes — text from JSON,
settings or an `output_name` slice, or a map `Uuid`. They differ only on a non-string, non-`Uuid`
input (the library returns it unchanged; the mirror stringified it), which no site passes.

## Passed through the helpers

| Site | What | Helper |
|---|---|---|
| `ControllerEngine.py:34` `_sorted_ids` | every sort over ids that leaves the process or reaches a log (`cluster_status`, `cluster_warning`, probe/resolve/watchdog logs) | `id_str`, then `sorted` over text |
| `ControllerEngine.py:1565` | `for uuid in sorted(adopted, key=id_str)` — ids kept for `_node_label` | `key=id_str` |
| `ControllerEngine.py:970`/`:977` | `output_name[:36]` slices a **string**, then `as_id(head)` | `as_id` at ingress |
| `ControllerEngine.py:1465`/`:1469` | `_node_label`'s `[:8]` and fallback | `id_str` |
| `ControllerEngine.py:537`, `:547`, `:569` | NNG pong / script_finished / armed_ready senders | `as_id` |
| `ControllerEngine.py:458`, `:595` | cue ids from nodes (`cue_operation_callback`, `cue_enabled`) matched against the script's `Uuid` cue ids | `as_id` |
| `ControllerEngine.py:1419` `_controller_uuid` | own uuid | `as_id`; rendered with `id_str` at `:172` (hub node id), `:343`, `:374`, `:1402` (NNG `sender`), `:1745` (`cluster_status.controller`) |
| `ControllerEngine.py:282`/`:289` | OSC route registration | `as_id` in, `f"/{id_str(u)}/*"` out |
| `ControllerEngine.py:1437`, `:1460` | map uuids in `_adopted_node_uuids` / `_node_label` | `as_id` |
| `core/BaseEngine.py:333` | `node_name` | `id_str(as_id(...))` |
| `core/BaseEngine.py:421`, `:427` | `NodeIndex` key; >1-controller error listing | `id_str` |
| `NodeEngine.py:633` | DMX player name / `node_uuid` kwarg | `id_str` |
| `NodeEngine.py:444` | **named by T055**: gradient-motiond `node_name` fallback, sent as OSC `arg_type="s"` (`GradientClient.py:51`). `str` today; a library that types the settings uuid (UR-8's ask) would put a `Uuid` on the wire | `id_str` — failing-first `failing-first-identity-gradient-node-name.txt` |
| `cues/helpers.py:19` | empty-duration warning | `id_str(cue.id)` |

## Safe as they stand — reason

| Site | Reason |
|---|---|
| `players/PlayerHandler.py:223`, `:270`, `:342` — `cue_id.split("-")` | `cue_id` is always the `str` key of `_audio_players_by_id`, populated with `str(cue.id)` at `:494` (and `:103`, `:463` read it via `str(cue.id)`) |
| `players/PlayerHandler.py:498`, `cues/run_cue.py:190` | `str(cue.id).split("-")` — explicit `str` first |
| `players/AudioPlayer.py:31` — `self.uuid.split("-")` | `self.uuid` is set from `uuid=str(cue.id)` (`PlayerHandler.py:486`) |
| `cues/CueHandler.py:683` — `", ".join(str(n.id) …)` | explicit `str` (`rc_1` `6068dd8`, the M18 fix) |
| `ControllerEngine.py:1081` — `json.dumps` of `cluster_warning` | `missing`/`unreachable` are built by `_sorted_ids` (lists of `str`); `load_id` int, `project` str |
| `ControllerEngine.py:840` — `isinstance(node_uuid, str)` | editor input validation for `nodelist_modify` (the value arrives as JSON text); it is forwarded to nodeconf as text and never compared with a map id |
| `ControllerEngine.py:303`-`:334` — direct-player OSC route (`parts[0]`) | the node uuid is parsed out of an OSC **address** (always `str`) and only goes back out as text (`mixer_status` key, status path). It never meets a typed id, so an `as_id`/`id_str` round-trip there would be a no-op; left as is (tasks.md T054 listed it — recorded here instead) |
| `comms/NodeCommunications.py` `add_cue`/`remove_cue`/`update_nextcue`/`update_cue`, `NodeEngine._notify_cue_enabled` — `cue.id` (a `Uuid`) in NNG `target`/`data` | serialized by `HubServices.send_message`'s `json.dumps`. A bare `json.dumps(Uuid)` raises, **but** `cuemsutils.tools.CTimecode` imports `json_fix`, which makes `json` honour `Uuid.__json__` process-wide, and every engine process imports `CTimecode`. Measured: `json.dumps(NodeOperation(... target=Uuid, data={"id": Uuid}).__dict__())` serializes as text once `cuemsengine` is imported. The receiver re-types with `as_id` (`ControllerEngine.py:458`, `:595`). Safe, but it rests on a library-side global patch — noted for UR-6 |
| `comms/ControllerCommunications.py:270` — `json.dumps(message)` to the editor | same `json_fix` coverage; the id-carrying replies built here are `cluster_status` (all `id_str`) and `get_project_status` (`str(self.script.id)`) |
| `NodeEngine.py:613` `sorted(display_regions.keys())` | output names from `display.conf`, not ids |

## uuid literals (FR-028)

`identity-test-literals.txt`: every uuid literal in `tests/` and in the fixtures the suite loads is a
uuid4. Exceptions, by name: the NOT PROVISIONED sentinel (nil uuid, `SENTINEL`) used by the FR-027
test, and `tests/test_ids.py`'s deliberate uuid1/nil inputs (the helpers must keep them as `str`).
Unloaded fixtures are out of scope (listed there).
