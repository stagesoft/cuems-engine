# ActionHandler Architecture Analysis and Refactor Plan

**Date:** 2026-05-15 — revised 2026-05-19 (post NNG→OSC migration, commit 29c28c1)  
**Scope:** `src/cuemsengine/cues/ActionHandler.py` and its call sites  
**Status:** Analysis + recommendation, not yet scheduled for implementation

---

## Context: NNG→OSC Migration (commit 29c28c1)

The fade dispatch path was migrated from NNG to direct UDP OSC via `GradientClient`
(feature 005-gradient-osc-transport). The main changes to `ActionHandler.py`:

- `_handle_fade_action` now calls `PLAYER_HANDLER.get_gradient_client().send_fade(...)` instead of `ch.communications_thread.send_fade_command(...)`
- `PLAYER_HANDLER` is now imported at module top-level (`from ..players.PlayerHandler import PLAYER_HANDLER`)
- `fade_id` renamed to `motion_id` throughout `_build_fade_payload` and `_handle_fade_action`

**NNG is NOT fully removed from this file.** `_default_result_sink` still uses
`NodeCommunications` / `NodeOperation` to send `action_cue_outcome` status messages.
The structural problems below remain valid in full. P9 is newly introduced by the migration.

---

## 1. Current State: Three Architectural Layers Tangled Together

`ActionHandler.py` currently mixes three distinct conceptual layers in a single file with no clean boundary between them.

### Layer A — The Class (`ActionHandler`)
Owns lifecycle state: hook registry, result sink, emit flag, and the cue-handler reference.  
Responsibilities: hook registration, hook resolution, result delivery, dispatch coordination.

### Layer B — The Module-Level Handler Registry
`_ACTION_HANDLERS: dict[str, Callable]` — a static mapping from action-type string to implementation function.  
`_handle_play`, `_handle_pause`, ..., `_handle_fade_action` — concrete per-action implementations.  
`_ready_action_target`, `_build_fade_payload` — shared helpers with no class affiliation.  
**Post-migration:** `_handle_fade_action` additionally reaches a second module-level singleton (`PLAYER_HANDLER`) directly.

### Layer C — The Proto-Singleton
`ACTION_HANDLER = ActionHandler()` at module level: a single instance created unconditionally at import time.  
Three separate sites configure it after creation:

| Site | What it does |
|------|--------------|
| `CueHandler.py:605` | `_ACTION_HANDLER_SINGLETON.bind_cue_handler(CUE_HANDLER)` |
| `NodeEngine.__init__` | `ACTION_HANDLER.set_result_sink(self._action_result_sink)` |
| `NodeEngine.__init__` | `ACTION_HANDLER.finalize_node_layer_bindings()` |

---

## 2. Identified Problems

### P1 — Cross-coupling via class name (not interface)
Every module-level `_handle_*` function calls `ActionHandler._action_result(...)`.  
The implementations are coupled to the class **by name**, not to a protocol or injected factory.  
This makes handlers impossible to reuse or test without importing the full class.

### P2 — `@staticmethod` that doesn't belong on the class
`_action_result` is a pure data factory with no access to `self` or `cls`.  
Being a `@staticmethod` on `ActionHandler` while being consumed primarily by module-level functions is the worst of both worlds: it's not a method (no `self` use), and it's not free (requires the class import).

### P3 — Singleton-but-not-enforced
`ACTION_HANDLER` is created unconditionally at module load, but nothing prevents `ActionHandler()` from being instantiated again.  
The singleton is implicit, undocumented, and unenforceable.

### P4 — Three-phase initialization across three files
The object's constructor leaves it in an incomplete state.  
`bind_cue_handler` must be called before any dispatch method is useful.  
`set_result_sink` must be called after comms are ready.  
This temporal coupling is invisible to the type system and silently produces broken objects if initialization order changes.

### P5 — Circular import managed by lazy imports
`CueHandler` references `ACTION_HANDLER`, and `ActionHandler` references `CueHandler` (via the bound `_cue_handler`).  
The circular dependency is broken by lazy `from .ActionHandler import ACTION_HANDLER` inside method bodies in `CueHandler` and `run_cue.py`.  
This is fragile: any new top-level import or `__init__.py` change can reintroduce the cycle.

### P6 — Test-isolation API bleeding into production
`clear_action_extensions()` and `set_emit_enabled()` exist purely to reset the singleton between tests.  
These are test concerns exposed in the production API surface.

### P7 — `NodeEngine` accesses a protected method directly
`NodeEngine._action_result_sink` calls `ACTION_HANDLER._default_result_sink(outcome)` — bypassing the public interface and coupling `NodeEngine` to implementation internals.

### P8 — `_ALL_ACTIONS` is a misleading sentinel
`_ALL_ACTIONS: frozenset[str] = frozenset()` means "no filter / match all", not "the set of all actions".  
`_filter_matches` treats empty frozenset as a wildcard, which is non-obvious to any reader.

### P9 — `_handle_fade_action` depends on a second hidden global (introduced by 29c28c1)
`_handle_fade_action` calls `PLAYER_HANDLER.get_gradient_client()` directly, where `PLAYER_HANDLER` is imported at module top-level.  
This adds a second implicit global dependency alongside the `ACTION_HANDLER` / `CUE_HANDLER` chain.  
`CueHandler` already imports `PLAYER_HANDLER` itself — so the handler function receives `ch: CueHandler` as its first argument but then bypasses it to reach `GradientClient` through a parallel global, making the `ch` injection pointless for this dependency.  
Under the proposed DI approach (Option C), `_handle_fade_action` should reach `GradientClient` through `ch` (e.g. `ch.player_handler.get_gradient_client()` or a forwarding accessor on `CueHandler`), eliminating the direct `PLAYER_HANDLER` import from `ActionHandler.py`.

---

## 3. Candidate Approaches

### Option A — Formal Singleton (Borg or `__new__` enforcement)
Make `ActionHandler` a true singleton with enforced single-instance semantics.

**Pros:** Minimal mechanical change. All existing call sites stay the same.  
**Cons:** Singletons are notoriously hard to test. Does not fix P1, P2, P4, P5, P6, P7, P9. Makes the hidden global state explicit but not better. Not recommended.

---

### Option B — Pure Static Class (all class methods / static methods)
Convert `ActionHandler` to an all-classmethod class with no instance state; use class-level variables.

**Pros:** Removes the need to instantiate; call sites use `ActionHandler.execute_action(...)` directly.  
**Cons:** Class variables have the same hidden global state problem as module globals but with more ceremony.  
Still cannot be injected, still forces test pollution, still doesn't fix P4, P5, P6, P7, P9.  
Abandoned static-class approaches are a common code smell in Python. Not recommended.

---

### Option C — Composition-Owned Instance with Constructor DI ✓ Recommended
`ActionHandler` becomes a plain class that receives its dependencies at construction time.  
`CueHandler` creates and owns the instance.  
`NodeEngine` receives it via `CueHandler`, not by importing the module singleton.

This eliminates all nine problems identified above.

**Structural changes:**

```python
# ActionHandler.py — no module-level singleton, no bind_cue_handler()
class ActionHandler:
    def __init__(
        self,
        cue_handler: "CueHandlerProtocol",
        result_sink: Callable[[dict], None] | None = None,
    ) -> None:
        self._ch = cue_handler          # set at construction, never None
        self._result_sink = result_sink # None → default NNG delivery
        self._lock = threading.Lock()
        self._hooks: dict[...] = {}
        # emit_enabled removed from prod API; control via result_sink=None in tests

# CueHandler.py — owns the instance
class CueHandler:
    def __init__(self) -> None:
        ...
        self.action_handler = ActionHandler(self)

# NodeEngine.py — receives from CueHandler, no lazy import
class NodeEngine:
    def _setup_action_handler(self) -> None:
        CUE_HANDLER.action_handler.set_result_sink(self._action_result_sink)
        CUE_HANDLER.action_handler.finalize_node_layer_bindings()
```

**Module-level helpers:**

```python
# Extract from the class — free function, no class coupling
def _make_action_result(
    status: str,
    action_type: str,
    target_id: str | None,
    reason: str | None = None,
) -> dict:
    return {"status": status, "action_type": action_type,
            "target_id": target_id, "reason": reason}

# All _handle_* functions call _make_action_result(...) directly
# No reference to ActionHandler class name needed
```

**`_handle_fade_action` routes `GradientClient` through `ch` (fixes P9):**

```python
# Instead of: gradient_client = PLAYER_HANDLER.get_gradient_client()
# Handler already receives ch: CueHandlerProtocol — protocol gains one accessor:
def _handle_fade_action(ch, action_cue, target, mtc, frozen_mtc_ms):
    gradient_client = ch.get_gradient_client()   # forwarded to PLAYER_HANDLER internally
    ...
# CueHandler.get_gradient_client() just delegates to PLAYER_HANDLER.get_gradient_client()
# PLAYER_HANDLER import stays in CueHandler (it already has it), removed from ActionHandler
```

**`NodeEngine` removes protected-method access (fixes P7):**

```python
# Instead of: ACTION_HANDLER._default_result_sink(outcome)
def _action_result_sink(self, outcome: dict) -> None:
    CUE_HANDLER.action_handler.emit_outcome(outcome)   # emit_outcome() is public
    self._maybe_notify_cue_enabled(outcome)
```

**Sentinel rename (fixes P8):**

```python
_MATCH_ALL: frozenset[str] = frozenset()   # replaces _ALL_ACTIONS
# _filter_matches(action_type, _MATCH_ALL) → True always
```

**Test isolation — no production API needed (fixes P6):**

```python
# conftest.py
@pytest.fixture
def action_handler(stub_cue_handler):
    return ActionHandler(stub_cue_handler)   # fresh instance per test, no singleton
```

---

## 4. Circular-Dependency Resolution

The circular import exists because `ActionHandler` holds a reference to `CueHandler` at runtime  
while `CueHandler` holds a reference to `ActionHandler`.  
With Option C, the import graph is:

```
CueHandler       imports  ActionHandler     (top-level, no lazy workaround needed)
ActionHandler    DOES NOT import CueHandler  (uses CueHandlerProtocol / Any annotation)
ActionHandler    DOES NOT import PLAYER_HANDLER  (GradientClient routed through ch)
```

`ActionHandler.__init__` types `cue_handler` as `Any` or a `CueHandlerProtocol`
(a `typing.Protocol` covering the methods `ActionHandler` and its handlers actually call:
`arm`, `go`, `disarm`, `communications_thread`, `get_gradient_client`).  
No runtime import of `CueHandler` or `PlayerHandler` is required inside `ActionHandler.py`.

---

## 5. Migration Path (zero-flag, backward-compatible steps)

All steps are independently releasable and tested before the next step begins.

### Step 1 — Extract `_make_action_result` free function
- Move `@staticmethod _action_result` out of the class as `_make_action_result(...)`.
- Update all call sites inside `ActionHandler.py` (both class methods and `_handle_*` functions).
- No behavior change; existing tests pass unchanged.

### Step 2 — Rename `_ALL_ACTIONS` → `_MATCH_ALL`
- Cosmetic rename; update `register_action_hook` and `_matching_hooks`.
- No behavior change.

### Step 3 — Add `CueHandlerProtocol` and constructor DI
- Define `CueHandlerProtocol` in `ActionHandler.py` (or a shared `_protocols.py`).  
  Protocol methods: `arm`, `go`, `disarm`, `communications_thread`, `get_gradient_client`.
- Add `CueHandler.get_gradient_client()` forwarding accessor (delegates to `PLAYER_HANDLER.get_gradient_client()`).
- Change `ActionHandler.__init__` to accept `cue_handler: CueHandlerProtocol`.
- Remove `bind_cue_handler()`.
- Replace `PLAYER_HANDLER.get_gradient_client()` in `_handle_fade_action` with `ch.get_gradient_client()`.  
  Remove the `from ..players.PlayerHandler import PLAYER_HANDLER` top-level import.
- Update `CueHandler.__init__` to `self.action_handler = ActionHandler(self)` and remove the  
  module-level binding at `CueHandler.py:603–605`.
- Update `run_cue.py` and `CueHandler.execute_action` to use `CUE_HANDLER.action_handler`  
  instead of importing `ACTION_HANDLER`.

### Step 4 — Remove module-level singleton
- Delete `ACTION_HANDLER = ActionHandler()` from `ActionHandler.py`.
- Update `NodeEngine` to use `CUE_HANDLER.action_handler` everywhere.
- Rename `_emit_outcome` → `emit_outcome` (make public).
- Replace `ACTION_HANDLER._default_result_sink(outcome)` in `NodeEngine` with `CUE_HANDLER.action_handler.emit_outcome(outcome)`.

### Step 5 — Remove test-pollution API
- Delete `clear_action_extensions()` and `set_emit_enabled()`.
- Update test fixtures to instantiate a fresh `ActionHandler(stub_ch)` per test.
- Confirm `test_action_cue.py` and `test_fade_action_handler.py` pass.

### Step 6 — (Optional) Formal `ActionHandlerProtocol` for NodeEngine
- Define a minimal protocol that `NodeEngine` depends on instead of the concrete class.
- Enables future alternative dispatchers without touching `NodeEngine`.

---

## 6. What Must NOT Change

- The `_ACTION_HANDLERS` dict-based registry pattern — it is clean and extensible.
- The `HookPhase` / `RegistrationLayer` hook system — the design is sound.
- The `ActionHookContext` dataclass — stable API for extension integrators.
- `_build_fade_payload` and `_ready_action_target` — module-level helpers are the right home.  
  Note: `motion_id` terminology (renamed from `fade_id` in 29c28c1) is finalized; do not revert.
- `SUPPORTED_CUE_ACTIONS` frozenset — correct scope and usage.

---

## 7. Forward-Looking Architectural Boundaries

These boundaries are assumed by Option C but not enforced by it. They must be explicitly respected when adding new modules; without them, future integrators will place code in the wrong layer.

### B1 — Scripted vs Live Control

`ActionHandler` is the scripted-action pipeline. Every call to `execute_action` represents a discrete, show-script-defined event dispatched at a specific timecode. It is **not** a general command bus.

Real-time hardware controllers (MIDI CC faders, OSC control surfaces, USB HID encoders) generate **continuous parameter streams** that must route through a separate live-control layer — the `route_audio_message` / `route_dmx_message` pattern already established on `CueHandler` and dispatched from `NodeEngine._handle_player_control_message`. New controller modules must add a `route_*` method to `CueHandler` and a new branch in `NodeEngine._handle_player_control_message` rather than feeding events into `execute_action`.

Discrete hardware triggers (button → go, button → stop) are the exception: these represent a named action on a named target and should use a new `ActionHandler.dispatch_action(action_type, target, mtc)` overload (see contracts document) rather than constructing a synthetic `ActionCue`.

The two paths must never be merged. Routing continuous streams through `execute_action` would invoke the full hook pipeline on every parameter tick — a performance and coupling disaster.

### B2 — `_build_fade_payload` Must Become a Registry Before the Next Media Type

`_build_fade_payload` currently selects OSC endpoint logic via `isinstance(target_cue, AudioCue) / isinstance(target_cue, VideoCue)`. Every new fadeable target type (EqCue, EffectCue, MidiDeviceCue, LightingCue) requires extending this if-elif chain — an Open/Closed violation.

Before any new cue type that supports fading is introduced, `_build_fade_payload` must be replaced with a per-type builder registry:

```python
_FADE_BUILDERS: dict[type, "FadePayloadBuilderProtocol"] = {}

def register_fade_builder(cue_type: type, builder: "FadePayloadBuilderProtocol") -> None:
    _FADE_BUILDERS[cue_type] = builder

def _build_fade_payload(target_cue, fade_cue, start_mtc_ms, motion_id) -> list[dict]:
    builder = _FADE_BUILDERS.get(type(target_cue))
    if builder is None:
        raise ValueError(f"No fade builder for {type(target_cue).__name__}")
    return builder.build(target_cue, fade_cue, start_mtc_ms, motion_id)
```

Existing `AudioCue` and `VideoCue` builders register themselves at module load. New types register their own. The isinstance chain disappears. Full contracts for `FadePayloadBuilderProtocol` are defined in `specs/planning/controller-integration-contracts.md`.

---

## 8. Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|-----------|
| Import order regression during Step 3 | Medium | Add a top-level import smoke test |
| `CueHandler.get_gradient_client()` accessor missing from protocol | Low | Protocol is defined in same Step 3 PR; CI catches it |
| `NodeEngine` breaking on `_default_result_sink` removal | Low | Step 4 promotes `emit_outcome()` before removing the old method |
| Test suite global state between tests | High (current) → Low (after Step 5) | Fresh instance per fixture eliminates bleed |
| `run_cue.py` singledispatch referencing wrong handler | Low | Covered by existing `test_action_cue.py` |
| `PLAYER_HANDLER` removal from ActionHandler breaking fade tests | Low | `test_fade_action_handler.py` already patches `PLAYER_HANDLER.get_gradient_client`; after Step 3 patch target changes to `stub_ch.get_gradient_client` — update test fixtures in same PR |
