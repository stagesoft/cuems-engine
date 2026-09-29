# Contract — the engine's identity helpers (`src/cuemsengine/tools/ids.py`)

Group 7 (FR-024–FR-029). `Uuid` canonical, **as the library delivers it**: a uuid4 is a `Uuid`,
anything else stays the raw `str` — the engine mirrors `cuemsutils`' own (internal) uuid decoder
rather than enforcing uuid4 (research R14; UR-6 asks upstream for a public helper).

## `as_id(value) -> Uuid | str | None` — ingress

| Input | Output |
|---|---|
| `Uuid` | unchanged |
| `str` matching uuid4 | `Uuid(value)` |
| other non-empty `str` | `value` unchanged |
| `""`, `None` | `None` |
| anything else | `str(value)` passed through the rules above |

Never raises. Idempotent: `as_id(as_id(x)) == as_id(x)`.

## `id_str(value) -> str` — egress

`str(value)`; `None` → `""`. The only way an id reaches a sort key, a slice, `.split`, `join`,
string concatenation, JSON, an OSC argument or address.

## `is_uuid4(value) -> bool`

For FR-027's one-time warning only.

## Invariants the tests pin

1. `as_id(u) == as_id(str(u))` and `hash` equal, for every uuid4 `u` — one member per identity in
   any set.
2. `sorted(ids, key=id_str)` never raises over mixed `Uuid`/`str`.
3. A nil uuid and a uuid1 round-trip unchanged (`as_id(x) == x`, `type is str`).
4. No test here re-tests `Uuid` itself (FR-030a-i spirit): the helpers' behaviour is asserted, not
   the library class's.
