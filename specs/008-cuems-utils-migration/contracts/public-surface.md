# Contract — what the engine may import from `cuemsutils`

Guarded by a test (`tests/test_public_surface.py`), modelled on `cuems-nodeconf`'s
`tests/test_public_surface.py`. It scans `src/` source text, so it needs no library import to run.

## Rules

1. **No import from `cuemsutils.xml`** or any submodule of it — internal machinery (Q14,
   `__all__ == []`). Covers `from cuemsutils.xml import …`, `from cuemsutils.xml.X import …`,
   `import cuemsutils.xml…`.
2. **No import from `cuemsutils.config`** or its submodules — internal; `node` is reached via
   `cuemsutils.tools.NodeList` (its own module comment says so).
3. **No reference to** `get_nodes_by_adoption`, `partition_by_adoption`,
   `_adopted_uuids_from_network_map`, `find_hosts`, `CONTROLLER_NETWORK_FLAG`, `"NodeType."` in `src/`.

## Allowed surface used by this feature

| Import | For |
|---|---|
| `cuemsutils.cues.CuemsScript` (`.load`) | show loading (FR-007) |
| `cuemsutils.tools.ConfigManager.ConfigManager` (`.network_map`, `.load_network_map`) | node map (FR-008) |
| `cuemsutils.tools.NodeList.NodeRole`, `NodeIndex` | controller lookup (FR-005) |
| `cuemsutils.tools.CTimecode.CTimecode` | duration helper (FR-016b) — already imported |
| `cuemsutils.tools.coerce_identity` | `as_id`, re-exported by `src/cuemsengine/tools/ids.py` (cuems-utils 012, sibling-repository-updates.md §4.2; replaces the engine's mirror, 2026-09-30) |
| `cuemsutils.tools.Uuid.Uuid` | **not imported by `src/` at all** since 2026-09-30 (was: only in `tools/ids.py`, FR-029); the guard still fails on any `src/` import of it outside `tools/ids.py` |
| `cuemsutils.tools.identity_check.SENTINEL` | the NOT PROVISIONED pre-load check in `BaseEngine` (FR-027); public status to be confirmed upstream (UR-8) |

## Anti-vacuity guard

The test MUST fail if it scans zero files or finds zero `cuemsutils` imports at all — a package
rename or a wrong root would otherwise turn it silently green (the guard `cuems-nodeconf`'s test
carries for the same reason).
