# Contract — `cluster_status` reply and `cluster_warning` broadcast (UNCHANGED)

Both are cross-repository contracts (F2a): `cuems-editor` `CuemsWsUser.py:496`, `:501` relays
`cluster_status` to the UI as `node_status`. This feature changes **what feeds them**, never their
shape. The contract test pins the shape against a map loaded **through the public surface**, which
is the case that fails today (M12).

## `cluster_status` — reply to the editor's `cluster_status` command

`ControllerEngine.get_cluster_status(value, context) -> dict`

```json
{
  "alive":      ["<uuid str>", "..."],
  "adopted":    ["<uuid str>", "..."],
  "controller": "<uuid str>"
}
```

| Invariant | Test |
|---|---|
| `alive` and `adopted` are **sorted lists of `str`** | typed-map fixture; `all(isinstance(u, str) …)` and `== sorted(…)` |
| `adopted` equals exactly the nodes with `adopted is True` in the map | two adopted + one not → two entries |
| keys are exactly `{"alive", "adopted", "controller"}` | set equality |
| cached for `CLUSTER_STATUS_CLAMP_S` (unchanged) | existing tests |

Pre-migration against a typed map: `sorted()` over `Uuid` raises `TypeError` — the failing-first case.

## `cluster_warning` — `/engine/status/cluster_warning`, JSON string

`ControllerEngine._cluster_warning_payload(diagnosis) -> str`

```json
{"load_id": 0, "project": "", "missing": [], "unreachable": []}
```

| Invariant | Test |
|---|---|
| always sent, empty lists included | existing `test_cluster_warning.py` |
| `missing`/`unreachable` contain `str` uuids; the controller's uuid is in neither | moved tests feed a typed map (clarify Q4) |
| `load_id` increments per load | existing |
