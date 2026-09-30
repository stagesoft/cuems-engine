# Contract — the engine's identity helpers (`src/cuemsengine/tools/ids.py`)

Group 7 (FR-024–FR-029). `Uuid` canonical, **as the library delivers it**: a converged id (uuid4) is a
`Uuid`, anything else stays the raw `str`.

**Revised 2026-09-30**: `as_id` is no longer the engine's mirror of the library's internal decoder.
cuems-utils 012 publishes the rule as `cuemsutils.tools.coerce_identity`, and `tools/ids.py`
re-exports it as `as_id` (012 `sibling-repository-updates.md` §4.2; UR-6 delivered). The engine keeps
no copy, and its tests no longer re-test the rule — the library's
`tests/contract/test_published_coercion.py` does.

## `as_id` — ingress (`cuemsutils.tools.coerce_identity`)

| Input | Output |
|---|---|
| `Uuid` | unchanged |
| converged `str` (lowercase uuid4) | `Uuid(value)` |
| other non-empty `str` — uuid1, the NOT PROVISIONED sentinel, a name | `value` unchanged |
| `""`, `None` | `None` |
| anything else | returned unchanged (the old mirror stringified it; no engine ingress site passes such a value) |

## `id_str(value) -> str` — egress (the engine's own)

`str(value)`; `None` → `""`. The only way an id reaches a sort key, a slice, `.split`, `join`,
string concatenation, JSON, an OSC argument or address. The library has no equivalent.

## What the engine's tests pin (`tests/test_ids.py`)

1. `as_id is coerce_identity` — the engine delegates, it does not copy.
2. `sorted(ids, key=id_str)` never raises over mixed `Uuid`/`str`.
3. `id_str` renders a `Uuid`, a `str` and `None` as text.
