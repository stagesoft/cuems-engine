# Data model — 008-cuems-utils-migration

The engine **owns none of these models**. It reads them through `cuemsutils`' public surface
(FR-030a-i). This file records the **engine-side view**: which fields the engine reads, in what
type, and the rules it applies. It adds no model of its own; a node-model test here would be a
regression.

## Node (read from `ConfigManager.network_map["node_list"][i]["node"]`)

| Field | Type as delivered (R1) | Engine reads it for | Engine rule |
|---|---|---|---|
| `uuid` | `Uuid` | OSC handler routes, adopted/alive sets, `cluster_status`, `cluster_warning` | converted with `str()` **once**, at the adoption reader and the controller lookup (FR-009a) |
| `node_role` | `NodeRole` | controller identification | compared to `NodeRole.controller` only; never to a string (FR-005, M11) |
| `ip` | `str` | controller-IP fallback | a controller without `ip` keeps raising `ValueError("Controller node in network map has no <ip>")` |
| `adopted` | `bool` | adoption set | used as-is; the engine parses no strings (FR-030a-i) |
| `online` | `bool` | **not read** after `find_hosts` is deleted | — (nodeconf's ~30 s discovery view; distinct from the engine's `alive`) |
| `mac`, `name` | `str` | not read | — |

**Wrapper rule**: `node_list` items are `{"node": node}`. Unwrap exactly once. A non-dict item or a
missing `"node"` key is skipped (today's behaviour, kept).

### Derived views (engine-internal)

- **Adopted uuids** — `frozenset[str]` of `uuid` for nodes with `adopted is True`. One reader
  (`_adopted_node_uuids`, research R10) serves OSC registration, the liveness probe, cluster-state
  resolution and `cluster_status`. Never mutates the map.
- **Controller** — `NodeIndex.from_nodes(nodes, key=uuid).controllers`:

  | Count | Result |
  |---|---|
  | 0 | `ValueError("No controller node found in network map")` (unchanged message) |
  | 1 | its `ip` |
  | >1 | structured **error** log listing every `(uuid, ip)`, then the first in map order (FR-005a) |

- **Alive uuids** — the engine's own ping/pong set. **Unchanged by this feature**; never derived
  from `online`.

## Show script (read via `CuemsScript.load(path)`)

| Aspect | Rule |
|---|---|
| Version 1 on disk | converted in memory by the library; file untouched |
| Version 2 | loaded as-is |
| Newer than the library | the library raises (`versioning.py:50-63`, *"newer than this library's current version"*); the engine lets it propagate to the load error path |
| `media.duration` | `CTimecode`, **or `None`** for an empty `<duration/>` (R4) |
| `ActionCue.action_type` | never `fade_in`/`fade_out` after conversion (script v2 forbids them) |

### Media duration rule (FR-016)

`None` → `CTimecode` zero, with a warning naming the cue; otherwise the `CTimecode` as delivered.
Applied at the five former wrap sites through one helper. No site raises for a `None` duration.

## Deployed project documents (C11)

| Document | Schema | Current version | Past v1? |
|---|---|---|---|
| `/projects/<p>/script.xml` | `script` | **2** | **yes** — the C11 constraint |
| `/projects/<p>/mappings.xml` | `project_mappings` | 1 | no |
| `/projects/<p>/settings.xml` | `project_settings` | 1 | no |

Source: `CuemsDeploy.py:647-652`; `versioning.CURRENT_VERSION`. A future bump of either v1 row
extends C11 and must update the `CHANGELOG.md` upgrade notes and the hand-off (FR-020).

## Package relations (`debian/control`, `pyproject.toml`)

| Relation | Before | After |
|---|---|---|
| `cuems-utils` / `cuemsutils` | `>= 0.1.0rc4` / `>=0.1.0rc10` (disagree) | `>= 0.1.0rc16`, `<< 0.1.1~` / `>=0.1.0rc16,<0.1.1` |
| `cuems-common` | `>= 1.0.0` | `>= 1.3.0-23~` (inherits `Breaks: cuems-nodeconf (<< 0.1.0-8)`) |
| own `Breaks:` | none | none (clarify) |
