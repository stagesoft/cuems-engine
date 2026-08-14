# Controller Integration Contracts

**Date:** 2026-05-19 — revised 2026-08-10 (synced with the locked ActionHandler decision) —
**validated 2026-08-10 against commit `e210b26`**
**Scope:** Formal integration contracts for external hardware controller modules
**Status:** Design artifact, code-validated — defines required interfaces before any implementation begins
**Relates to:** `specs/planning/action-handler-architecture-analysis.md` — that document is authoritative for
`ActionHandler` internals and carries the validation record; this one is authoritative for the controller-facing
surface. **They must stay in sync.**

> **What exists today.** Nothing in this document is implemented. Every protocol here is a target. The
> per-contract *Implementation status* notes say precisely what is missing and which migration step delivers it.
> `file.py:N` references are pinned to commit **`e210b26`**.

---

## Overview

External controllers (MIDI surfaces, LAN OSC controllers, USB HID devices) integrate
with the engine through **three separate paths** depending on the nature of the event:

| Event type | Path | Entry point | Exists? |
|---|---|---|---|
| Discrete trigger (button → go/stop/fade) | Discrete-action pipeline | `ActionHandler.dispatch_action()` | No — analysis Step 8 |
| Continuous parameter (fader → volume) | Live-control routing layer | `CueHandler.route_control_event()` | No — unowned, see Contract 4 |
| Hardware feedback (LED, motor fader) | Outcome-listener list | `ActionHandler.add_outcome_listener()` | No — analysis Step 6 |

A single controller module will typically use **all three**. The first two paths must never be
merged: routing continuous streams through `dispatch_action` invokes the full hook
pipeline on every parameter tick.

**Feedback uses listeners, not `after_dispatch` hooks.** A hook that raises rewrites the
outcome to `failed` and breaks the hook loop (`ActionHandler.py:337-347`). The expected failure mode of an LED
write is an unplugged device — which must never turn an applied `play` into a `failed` outcome on the
Controller UI. Outcome listeners are exception-isolated and cannot alter a result. Hooks
remain available for extensions that legitimately *participate* in an outcome
(see analysis document §1 and §3.3).

**Process scope.** Controller modules live in the **node-engine process** only.
`ControllerEngine.py` imports neither `CueHandler` nor `ActionHandler` — verified by grep at `e210b26`.

**Where these protocols live.** Undecided — **decision brief in analysis document §12 A**. `CueHandlerProtocol`
currently sits inside `ActionHandler.py` (as `CueOrchestrator`, renamed in analysis Step 4). The recommendation
is a single `src/cuemsengine/contracts.py`, created at Step 4, with `TYPE_CHECKING`-only imports as a hard
requirement (it is the only thing preventing a new `ActionHandler` ↔ `contracts` cycle, since
`ActionHandlerProtocol` names `ActionHookContext` / `HookPhase` / `RegistrationLayer` / `ActionParams`), and
with that hook vocabulary migrating into the same module at Step 8. **The call is needed before Step 4 starts**,
earlier than this feature — deciding late costs a second move of `CueHandlerProtocol`.

---

## Lifecycle

```
NodeEngine.start()                              # NodeEngine.py:97
    │
    ├─► CUE_HANDLER.set_nng_comms(...)          # :98  — comms thread up
    ├─► self.set_oscquery_comms()               # :101
    ├─► self.set_players()                      # :103 — GradientClient bound here
    ├─► self._setup_nng_command_callback()      # :104 — engine's own outcome listener
    │
    └─► ControllerModule.attach(action_handler, cue_handler, live_router, mtc)
            │                                   # NEW call site, AFTER :104
            ├─► action_handler.add_outcome_listener(self._on_action_complete)
            ├─► optionally registers node_layer hooks (owner=self.module_id)
            ├─► opens hardware connection / starts listener thread
            └─► stores live_router + mtc references for later events

engine shutdown
    └─► ControllerModule.detach()
            ├─► action_handler.remove_outcome_listener(...)
            ├─► action_handler.unregister_all_hooks(self.module_id)
            └─► closes hardware connection / stops listener thread
```

**`attach()` goes after `_setup_nng_command_callback()`, not inside `set_players()`.** A previous revision of
this document placed it inside `set_players()`. That ordering is wrong for one concrete reason: listeners fire
in registration order (Contract 2), and `NodeEngine._action_result_sink` — which drives the Controller UI's
`cue_enabled` sync — registers in `_setup_nng_command_callback` (`NodeEngine.py:134-137`, becoming
`add_outcome_listener` at analysis Step 6). The engine's own listener must be first.

**Lifetime is the process, not the project.** `attach()` runs once per process and `detach()`
only at shutdown. Tying `detach()` to project load would close and reopen the hardware port on
every load — slow for MIDI devices and a common failure point. A module that needs to react to a
project change observes it through its own means; the engine does not re-attach.

**No project is loaded at `attach()` time.** `NodeEngine.start()` completes the whole sequence above before any
`load` command arrives over NNG. At `attach()`:

- comms thread — **up** (`set_nng_comms` ran first),
- `GradientClient` — **bound** (`set_players` → `set_gradient_client`, `NodeEngine.py:407-413`),
- cue list — **empty**. `get_armed_cue_by_id` returns `None` for everything.

Modules MUST resolve cues lazily, at event time, never during `attach()`.

**`mtc` is supplied by `attach()`.** `dispatch_action` requires an `MtcListener` and a controller
module has no other legitimate source for one.

---

## Contract 1 — `ControllerModuleProtocol`

Every hardware controller bridge (MIDI, LAN OSC, USB HID) must satisfy this protocol.

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class ControllerModuleProtocol(Protocol):
    """Interface every hardware controller bridge must implement.

    Implementations are responsible for their own threading. The engine calls
    attach() and detach() from the main thread.

    Thread-safety, precisely: hook registration, outcome-listener registration
    and outcome delivery are guarded by ActionHandler's lock. Action *dispatch*
    is NOT serialised — execute_action / dispatch_action are not atomic, and the
    per-action handlers mutate cue state (_stop_requested, enabled,
    _go_generation) without a lock. A hardware button firing the same action on
    the same cue as the running show script is a real race. Modules MUST NOT
    assume the engine serialises them.
    """

    def attach(
        self,
        action_handler: "ActionHandlerProtocol",
        cue_handler: "CueHandlerProtocol",
        live_router: "LiveControlRouterProtocol",
        mtc: "MtcListener",
    ) -> None:
        """Called once per process, at the end of NodeEngine.start().

        Engine state at this point: the comms thread is up and the
        GradientClient is bound, but NO PROJECT IS LOADED and no cue is armed.
        Resolve cues lazily at event time, never here.

        Implementations SHOULD:
        - register an outcome listener for hardware feedback
        - register node_layer hooks ONLY if they need to participate in the
          outcome; pass owner=self.module_id
        - open the hardware connection (MIDI port, TCP socket, USB device)
        - start listener threads if needed
        - store references to action_handler, cue_handler, live_router, mtc for
          use in background threads

        Implementations MUST NOT:
        - trigger any cue action during attach()
        - look up cues during attach() — nothing is armed yet
        - block the calling thread for more than ~100 ms
        """
        ...

    def detach(self) -> None:
        """Called on engine shutdown. NOT called on project load.

        Implementations MUST:
        - remove every outcome listener registered in attach()
        - call action_handler.unregister_all_hooks(self.module_id)
        - stop all background threads
        - close the hardware connection cleanly

        Implementations MUST NOT raise — log errors and continue.
        """
        ...

    @property
    def module_id(self) -> str:
        """Stable identifier, used as the hook `owner` key and in logs
        (e.g. 'midi_apc40'). MUST be unique across attached modules — two
        modules sharing an id will unregister each other's hooks."""
        ...
```

**Implementation status: NOT IMPLEMENTED.** No controller-module registry exists on `NodeEngine`, and there is
no `attach`/`detach` call site. This is the first task of the controller-integration feature.

---

## Contract 2 — `ActionHandlerProtocol`

The subset of `ActionHandler` that controller modules may call. Only methods listed
here are part of the stable controller integration API. Accessing any other method
(including `_default_result_sink`, `_emit_outcome`, `_dispatch`, `_hooks`) is a contract violation.

```python
class ActionHandlerProtocol(Protocol):
    """Stable API surface for external controller modules."""

    def dispatch_action(
        self,
        action_type: str,
        target: "Cue",
        mtc: "MtcListener",
        frozen_mtc_ms: float | None = None,
        params: "ActionParams | None" = None,
    ) -> dict:
        """Dispatch a discrete action without constructing an ActionCue.

        This is the primary entry point for hardware-triggered discrete events
        (button press → play, button press → stop, etc.).

        action_type must be in SUPPORTED_CUE_ACTIONS — the engine's action
        vocabulary is deliberately CLOSED to runtime extension. A controller
        module cannot introduce a new action type; new actions ship in the
        engine with their schema and tests.

        target must be a live Cue object (look it up via
        CueHandlerProtocol.get_armed_cue_by_id before calling).

        frozen_mtc_ms pins the action to a specific MTC position. Hardware
        triggers normally pass None (dispatch at live MTC); it exists so a
        module echoing a scripted chain can share that chain's snapshot.

        params carries the payload for actions that need more than
        (action_type, target). Required for 'fade_action'; omitting it there
        returns a 'failed' outcome naming the missing payload. Ignored by
        actions that do not read it.

        BLOCKS. This call runs the handler synchronously on the caller's thread.
        'stop' in particular sleeps 100 ms inside the handler
        (ActionHandler.py:470) so loop_cue can observe _stop_requested before
        disarm. Do not call dispatch_action from a thread that must stay
        responsive to hardware input — hand it to a worker.

        Before/after/wrap hooks fire exactly as they do for script-driven
        actions — both entry points route through the same private _dispatch.
        The result dict has the same shape: {status, action_type, target_id, reason}.
        """
        ...

    def add_outcome_listener(self, fn: "Callable[[dict], None]") -> None:
        """Observe every action outcome. THE feedback channel for controllers.

        Listeners run after the outcome is final and after the engine's own NNG
        status delivery, in registration order. A listener exception is logged
        and swallowed — a listener can never alter or fail an outcome.

        Listeners run synchronously in the dispatch thread: do not block.
        """
        ...

    def remove_outcome_listener(self, fn: "Callable[[dict], None]") -> None:
        """Remove a previously added listener. Call during detach()."""
        ...

    def register_action_hook(
        self,
        phase: "HookPhase",
        fn: "Callable[[ActionHookContext], Any]",
        *,
        source: "RegistrationLayer" = "node_layer",
        action_types: "frozenset[str] | None" = None,
        owner: str = "default",
    ) -> None:
        """Register a hook that PARTICIPATES in the outcome.

        Use this only when the module must be able to fail or intercept an
        action. For pure feedback use add_outcome_listener: a hook that raises
        rewrites the outcome to 'failed' and breaks the hook loop.

        Controller modules MUST use source='node_layer' and owner=self.module_id.
        source='cue_layer' is reserved for show-script extensions, and is what
        CueHandler.register_action_hook forwards (it exposes no owner and is not
        a controller entry point).

        before_dispatch and after_dispatch fan out to every owner —
        cue_layer first, then node_layer, and within a layer in registration
        order. Owners never evict each other.

        wrap_dispatch accepts ONE hook per (source, action_types); a second
        registration for the same key raises ValueError. Nesting wraps from
        independent owners has no defensible ordering.
        """
        ...

    def unregister_action_hook(
        self,
        phase: "HookPhase",
        *,
        source: "RegistrationLayer",
        action_types: "frozenset[str] | None" = None,
        owner: str = "default",
    ) -> None:
        """Unregister one previously registered hook."""
        ...

    def unregister_all_hooks(self, owner: str) -> None:
        """Remove every hook registered by this owner. Call during detach() —
        this is the only safe teardown when several modules are attached."""
        ...
```

`ActionParams` is the payload object for `dispatch_action`. Its field names mirror `FadeCue`
so `_handle_fade_action` consumes it unchanged; it is mutable because that handler writes
`_start_mtc` / `_end_mtc` back (`ActionHandler.py:669-674`):

```python
@dataclass
class ActionParams:
    id: str | None = None
    curve_type: str | None = None
    target_value: float | None = None
    duration: "CTimecode | None" = None
    _start_mtc: "CTimecode | None" = None
    _end_mtc: "CTimecode | None" = None
```

**Three of the nine supported actions are stubs that still report `applied`.** Verified at `e210b26`; see
analysis document P15. A controller module must not present these as working features:

| Action | What it actually does |
|---|---|
| `fade_in` | identical to `play` — no fade envelope (`ActionHandler.py:523-524`) |
| `fade_out` | sets `_stop_requested`, bumps `_go_generation`, **never calls `disarm()`** — leaks the player process on every invocation (`ActionHandler.py:549-557`) |
| `go_to` | arms the target only — no seek or position navigation (`ActionHandler.py:567-568`) |

All three return `"applied"`, so LED feedback driven off `outcome["status"]` will light green. `fade_out`'s
missing `disarm()` is a defect its own in-code TODO acknowledges; whether it is fixed before `dispatch_action`
ships is analysis §13 Q5. Until then, map buttons to `play` / `stop` rather than `fade_in` / `fade_out`.

**`ActionParams.duration` must be non-zero.** `_build_fade_payload` raises `ValueError` on a `None`, zero or
non-numeric duration (`ActionHandler.py:719-725`) — before any OSC dispatch or mirror write — because
gradient-motiond silently drops `dur <= 0`. A hardware fade with a zero duration returns `failed`, not
`applied`.

**Implementation status.** `dispatch_action`, `ActionParams`, `add_outcome_listener`,
`remove_outcome_listener`, `unregister_all_hooks` and the `owner` parameter **do not exist yet**.
They are scheduled in the analysis document's migration path: outcome listeners at **Step 6**,
multi-owner hooks at **Step 7**, `dispatch_action` + `ActionParams` at **Step 8**. Today the outcome channel is
a single replaceable sink (`set_result_sink`, `ActionHandler.py:107`) already claimed by
`NodeEngine` (`NodeEngine.py:137`), and hook registrations evict each other — a module written against the
current code would break the Controller UI's `cue_enabled` sync.

`dispatch_action` is not a thin wrapper around `execute_action`. The pipeline body of
`execute_action` is extracted into a private `_dispatch(...)`; `execute_action` resolves and
validates an `ActionCue` and delegates, `dispatch_action` validates `action_type` / `target`
and delegates. Parity between the two is a tested requirement, not a convention.

`ActionHookContext` gains a trailing `params: ActionParams | None = None` field, and its `cue`
field widens to `ActionCue | None` (a synthetic dispatch has no cue). Both changes are additive
and source-compatible; existing field names are unchanged.

---

## Contract 3 — `CueHandlerProtocol`

The subset of `CueHandler` that controller modules may call.

This is the **same protocol** `ActionHandler` depends on internally
(`CueHandlerProtocol`, renamed from `CueOrchestrator` in analysis Step 4). One definition,
one name, both consumers — so the definition is the **union** of both consumers' needs, and it is
reproduced identically in analysis document §4.

```python
class CueHandlerProtocol(Protocol):
    """Stable API surface for action dispatch and external controller modules."""

    communications_thread: "NodeCommunications"

    def get_armed_cue_by_id(self, cue_id: str) -> "Cue | None":
        """Return the currently armed cue with this UUID, or None.

        Returns None for everything until a project is loaded — including for
        the whole duration of attach().
        """
        ...

    def get_cue_by_id(self, cue_id: str) -> "Cue | None":
        """Return any cue in the loaded project by UUID (armed or not), or None.

        NOT YET IMPLEMENTED, AND NOT A SIMPLE ADDITION. CueHandler holds no
        script reference at all — it knows only _armed_cues. The project script
        lives on NodeEngine (self.script); the lookup primitive is
        CuemsScript.find(uuid) in cuemsutils. Placing this method requires
        deciding who owns the script: see analysis document §13 Q2.

        Today only get_armed_cue_by_id (CueHandler.py:951) and
        find_armed_cue (CueHandler.py:108) exist.
        """
        ...

    def arm(self, cue: "Cue", init: bool = False) -> bool:
        """Arm a cue (load it). Idempotent if already armed. Returns success."""
        ...

    def go_from(
        self,
        start_cue: "Cue",
        mtc: "MtcListener",
        seed_ms: float | None = None,
    ) -> "Thread | None":
        """Start a cue, walking its post_go='go' chain to THIS node's first
        local+enabled cue.

        NOT `go`. A plain go() bails when start_cue is local to another node,
        dropping this node's own cues on a cross-node loop-back (circular
        project). Every action handler that starts playback uses go_from.
        go_from itself ends by delegating to self.go for the cue it finds.
        """
        ...

    def disarm(self, cue: "Cue") -> bool:
        """Stop and unload a cue. Returns success."""
        ...

    def get_gradient_client(self) -> "GradientClient | None":
        """Return the active GradientClient, or None if not yet initialised.

        NOT YET IMPLEMENTED — a forwarding accessor over
        PLAYER_HANDLER.get_gradient_client(), added in analysis Step 4.
        """
        ...
```

**Implementation status, member by member** (checked against `CueHandler` at `e210b26`):

| Member | Status |
|---|---|
| `communications_thread` | Exists as a class annotation (`:42`), bound only by `set_nng_comms()` (`:64`) |
| `arm` | Exists, `:284`, returns `bool` |
| `disarm` | Exists, `:386`, returns `bool` |
| `go_from` | Exists, `:517` |
| `get_armed_cue_by_id` | Exists, `:951` |
| `get_cue_by_id` | **Missing** |
| `get_gradient_client` | **Missing** — analysis Step 4 |

**`communications_thread` is declared but may not be bound.** The annotation at `CueHandler.py:42` creates no
attribute; `set_nng_comms()` does. `ActionHandler`'s internal NNG outcome delivery therefore reads it with
`getattr(ch, "communications_thread", None)` (`ActionHandler.py:218`) and that guard is an invariant, not an
accident (analysis §1.2, §6). **Controller modules MUST NOT use it at all** — send status through the engine,
not around it.

---

## Contract 4 — `LiveControlRouterProtocol`

The interface for routing **continuous parameter events** from hardware controllers.
Implemented by `CueHandler`; controller modules call it in their high-frequency event
loops.

```python
class LiveControlRouterProtocol(Protocol):
    """Receives real-time hardware events that are NOT scripted cue actions.

    Implementations must be thread-safe and non-blocking — this is called
    from controller listener threads, potentially hundreds of times per second.
    """

    def route_control_event(
        self,
        namespace: str,
        parameter: str,
        value: float,
    ) -> None:
        """Route a single continuous parameter event.

        namespace: 'audio', 'dmx', 'video', 'lighting', 'midi_out', etc.
        parameter: dot-separated sub-path within namespace.
                   Convention mirrors existing route_audio_message path_parts:
                   'mixer.0.master.volume', 'cue.<uuid>.0.volume', etc.
        value:     normalized float 0.0–1.0. Namespace-specific scaling is
                   the responsibility of the receiving route_*_message handler.

        Unknown namespaces are logged at DEBUG and silently dropped.
        This method MUST NOT raise.
        """
        ...
```

`CueHandler.route_control_event` dispatches to the existing `route_audio_message` (`CueHandler.py:871`),
`route_dmx_message` (`CueHandler.py:923`), and any future `route_lighting_message` /
`route_midi_out_message` based on the namespace. This replaces the current pattern where `NodeEngine`
dispatches directly to per-namespace methods — the controller module only needs one entry point.

**Implementation status: NOT IMPLEMENTED, and unowned.** Today
`NodeEngine._handle_player_control_message` (`NodeEngine.py:158`) parses an OSC address and dispatches straight
to `route_audio_message` / `route_dmx_message`. `route_control_event` has no step in the ActionHandler
migration path — it is a prerequisite for the first controller module and needs its own spec and branch.

Two details, one now resolved and one sharper than first stated — both checked against the real method bodies at
`e210b26`:

1. **The dotted `parameter` → `path_parts` mapping is a clean `split(".")` — resolved.**
   `'mixer.0.master.volume'` → `['mixer', '0', 'master', 'volume']`, exactly `route_audio_message`'s documented
   input. Two caveats to carry into the spec: the trailing `'volume'` element is **decorative** (the audio
   routes build their OSC command from `path_parts[1]` / `path_parts[2]` only), and the DMX convention differs —
   `route_dmx_message` searches for the literal `'mixer'` element and joins everything after it.
2. **The value scale is not merely unspecified — the existing receivers already disagree.**

   | Receiver | Scale handling |
   |---|---|
   | `route_audio_message`, `cue` branch (`CueHandler.py:907-916`) | clamps to 0.0–1.0; comment: "UI already sends 0.0-1.0 via `sliderToFloat()`" |
   | `route_audio_message`, `mixer` branch (`CueHandler.py:884-899`) | `float(value)` — **no clamp, no scaling** |
   | `route_dmx_message` (`CueHandler.py:923-949`) | passes `value` through **raw**, no conversion |

   So the "normalized float 0.0–1.0" specified above would break DMX unless that branch rescales. Decide once,
   in `route_control_event` — either the front door normalizes and each `route_*` rescales, or the front door is
   scale-agnostic and the namespace defines the range. Analysis document §13 Q3.

---

## Contract 5 — `FadePayloadBuilderProtocol`

Replaces the `isinstance` chain in `_build_fade_payload` (`ActionHandler.py:747`, `:752`). Each fadeable cue
type registers its own builder. See analysis document §7 B2 for the registry mechanism.

```python
class FadePayloadBuilderProtocol(Protocol):
    """Builds OSC endpoint payload dicts for a specific target cue type.

    One builder instance is registered per concrete Cue subclass that supports
    fading. The builder is stateless — it may be a class instance or a module
    with a build() function wrapped in an adapter.
    """

    def build(
        self,
        target_cue: "Cue",
        fade_cue: "Any",
        start_mtc_ms: int,
        motion_id: str,
    ) -> "list[dict]":
        """Return one payload dict per OSC endpoint that must receive the fade.

        Each dict MUST contain exactly these keys (consumed by GradientClient.send_fade):
            motion_id:    str  — unique per OSC endpoint (layer suffix for multi-layer)
            osc_port:     int  — UDP port of the target OSC server
            osc_path:     str  — OSC address (e.g. '/volmaster', '/videocomposer/layer/0/opacity')
            start_value:  float — current value at dispatch time (0.0–1.0)
            end_value:    float — target value (0.0–1.0, normalised from FadeCue.target_value/100)
            start_mtc_ms: int  — MTC snapshot at dispatch time
            duration_ms:  int  — fade duration in milliseconds
            curve_type:   str  — curve type string (e.g. 'linear', 'ease_in_out')

        Raise ValueError if the target_cue is in an invalid state (missing _osc,
        empty _layer_ids, etc.). The caller will convert ValueError to a 'failed'
        action result and abort dispatch.
        """
        ...
```

**Invariants that stay with the caller, not the builders.** The `FadeCue.duration > 0` check
(`ActionHandler.py:719-725`) is a property of the FadeCue, not of the target type. It must live in the shared
pre-builder path so every fadeable type inherits it — duplicating it per builder is how one type ends up
without it.

**Caller obligations — these fix live defects, they are not current behaviour.**
See analysis document §7 B2 acceptance criteria.

1. **Record `end_value` per entry, immediately after that entry's own successful send.**
   The current code dispatches every entry (`:630-657`) and only then records (`:663-664`), so a failure at
   layer *N* loses the records for layers `0..N-1` that were already sent — their next fade then reads a
   stale `start_value`. The "leave state unchanged on failure" invariant in the current comment (`:626-629`)
   is unachievable: the OSC sends are not atomic, so those layers *are* already faded on the
   player. The engine-side record must mirror what was actually sent.
2. **The caller MUST NOT mutate returned dicts.** The builder does not retain them, but the
   current code does `entry.pop("motion_id")` in the dispatch loop (`:631`) and re-reads the same dicts
   in the record loop (`:664`). Read `entry["motion_id"]`; do not pop.
3. Builders are stateless and registered at module load for `AudioCue` and `VideoCue`; new
   fadeable types register their own. `SUPPORTED_CUE_ACTIONS` is closed, but this registry is
   **open** — it is one of the three OCP seams named in the analysis document §3.4.
4. **Registry lookup key is undecided — decision brief in analysis document §12 B.** The current code uses
   `isinstance`; the registry sketch uses an exact `type(target_cue)` match, which would stop resolving
   subclasses. The recommendation is `functools.singledispatch` (MRO), matching the five cue registries that
   already use it, plus a WARNING when a target resolves via an ancestor rather than an exact registration.

**This whole contract is conditional on Decision B.** If `singledispatch` is chosen, `FadePayloadBuilderProtocol`
**is not needed at all** — registered functions replace builder objects, and the contract reduces to a
documented function signature plus the returned-dict key set above. It stays a `Protocol` class only if the
dict-of-builder-objects shape is chosen. Whoever decides B updates this section.

**Implementation status: NOT IMPLEMENTED.** `_build_fade_payload` is a module-level function with an
isinstance chain, and `tests/test_fade_action_handler.py` imports it directly at 11 sites. Analysis Step 10 —
separate feature branch. Note that §12 B also recommends splitting that step so the live P13 defect is fixed
immediately (B2a) rather than waiting for the registry (B2b); only B2b affects this contract.

---

## Integration Pattern A — MIDI Controller (Discrete Triggers)

Illustrative only — none of the engine API it calls exists yet.
Mapping: physical button → go/stop/fade on a named cue.

```python
class MidiControllerBridge:
    module_id = "midi_apc40"

    def attach(self, action_handler, cue_handler, live_router, mtc):
        self._ah = action_handler
        self._ch = cue_handler
        self._lr = live_router
        self._mtc = mtc
        # Feedback: update button LEDs after every action. A listener, NOT a
        # hook — an unplugged surface must not fail the action.
        action_handler.add_outcome_listener(self._on_action_complete)
        self._open_midi_port()
        self._listener = threading.Thread(target=self._midi_loop, daemon=True)
        self._listener.start()
        # No cue lookups here: nothing is armed at attach() time.

    def detach(self):
        self._stop_event.set()
        self._listener.join(timeout=1.0)
        self._close_midi_port()
        self._ah.remove_outcome_listener(self._on_action_complete)
        # Owner-scoped: never touches another attached module's hooks.
        self._ah.unregister_all_hooks(self.module_id)

    def _midi_loop(self):
        for msg in self._port:
            if self._stop_event.is_set():
                break
            if msg.type == 'note_on' and msg.velocity > 0:
                self._handle_button_press(msg.note)
            elif msg.type == 'control_change':
                # Continuous CC → live-control path, never dispatch_action
                self._handle_cc(msg.control, msg.value)

    def _handle_button_press(self, note: int):
        mapping = BUTTON_MAP.get(note)   # {action_type, cue_id}
        if mapping is None:
            return
        target = self._ch.get_armed_cue_by_id(mapping["cue_id"])
        if target is None:
            Logger.warning(f"MIDI note {note}: cue {mapping['cue_id']} not armed")
            return
        # dispatch_action BLOCKS (100 ms for 'stop'). Hand it to a worker so the
        # MIDI read loop keeps draining the port.
        self._dispatch_pool.submit(
            self._ah.dispatch_action, mapping["action_type"], target, self._mtc
        )

    def _handle_cc(self, control: int, raw_value: int):
        mapping = CC_MAP.get(control)    # {namespace, parameter}
        if mapping is None:
            return
        normalized = raw_value / 127.0
        self._lr.route_control_event(mapping["namespace"], mapping["parameter"], normalized)

    def _on_action_complete(self, outcome: dict):
        # Outcome listener — receives the final result dict, cannot alter it.
        # Runs on the dispatch thread: no blocking I/O here.
        led_note = REVERSE_BUTTON_MAP.get((outcome["action_type"], outcome["target_id"]))
        if led_note is not None and outcome["status"] == "applied":
            self._set_led(led_note, ON if outcome["action_type"] == "play" else OFF)
```

---

## Integration Pattern B — LAN OSC Controller

Illustrative only. Mapping: OSC messages from a control surface (e.g. TouchOSC, Lemur) over UDP/TCP.

```python
class LanOscControllerBridge:
    module_id = "lan_osc_surface"

    def attach(self, action_handler, cue_handler, live_router, mtc):
        self._ah = action_handler
        self._ch = cue_handler
        self._lr = live_router
        self._mtc = mtc
        self._server = OscServer(port=self._listen_port, handler=self._on_osc)
        self._server.start()

    def detach(self):
        self._server.stop()
        # Nothing to unregister: this module registered no listener and no hooks

    def _on_osc(self, address: str, *args):
        # /cue/<uuid>/go  → discrete action
        # /cue/<uuid>/stop → discrete action
        # /cue/<uuid>/volume <float> → continuous parameter
        # /mixer/<channel>/volume <float> → continuous parameter

        parts = address.lstrip("/").split("/")

        if parts[0] == "cue" and len(parts) >= 3:
            cue_id = parts[1]
            verb = parts[2]

            if verb in ("go", "stop", "pause", "enable", "disable"):
                # Discrete → dispatch_action
                target = self._ch.get_armed_cue_by_id(cue_id)
                if target is None:
                    return
                action_map = {"go": "play", "stop": "stop", "pause": "pause",
                              "enable": "enable", "disable": "disable"}
                self._ah.dispatch_action(action_map[verb], target, self._mtc)

            elif verb == "volume" and args:
                # Continuous → live-control router
                self._lr.route_control_event(
                    "audio", f"cue.{cue_id}.0.volume", float(args[0])
                )

        elif parts[0] == "mixer" and len(parts) >= 3:
            channel = parts[1]
            self._lr.route_control_event(
                "audio", f"mixer.0.{channel}.volume", float(args[0])
            )
```

The OSC verb → `action_type` map above is a module-local convention, not an engine contract: the engine's
vocabulary is `play`/`pause`/`stop`/`enable`/`disable`/`fade_in`/`fade_out`/`fade_action`/`go_to`
(`ActionHandler.py:30-42`). `load`, `unload`, `wait`, `pause_project` and `resume_project` exist in the XSD
`ActionType` enum but are **not implemented** — dispatching one returns `rejected`.

---

## What Controller Modules Must NOT Do

| Prohibited | Reason |
|---|---|
| Import `CUE_HANDLER` as a module global | Bypasses DI; breaks test isolation. `ACTION_HANDLER` no longer exists. Note this is a **convention, not a mechanism**: `CUE_HANDLER` is still importable, so reviewers enforce it |
| Call `ActionHandler.execute_action(action_cue, ...)` with a constructed `ActionCue` | Constructing `ActionCue` with `_action_target_object` pre-set is fragile; use `dispatch_action` with `ActionParams` |
| Route continuous events through `dispatch_action` | Invokes full hook pipeline on every tick, and `stop` blocks 100 ms per call |
| Call `dispatch_action` from a thread that must stay responsive | It runs the handler synchronously; `stop` sleeps 100 ms (`ActionHandler.py:470`). Use a worker |
| Access `_default_result_sink`, `_hooks`, `_emit_outcome`, `_dispatch` directly | Protected implementation details. Everything a module legitimately needs is on `ActionHandlerProtocol` — there is no case where reaching past it is correct |
| Use `after_dispatch` hooks for hardware feedback | A raising hook rewrites the outcome to `failed`; an unplugged device would fail the show action. Use `add_outcome_listener` |
| Register hooks with `source='cue_layer'` | That layer is reserved for show-script extensions |
| Register hooks with the default `owner` | Owner-less registrations evict each other. Always pass `owner=self.module_id` |
| Share a `module_id` with another attached module | `unregister_all_hooks(owner)` would tear down both |
| Introduce a new action type | `SUPPORTED_CUE_ACTIONS` is deliberately closed — the vocabulary is shared with the XSD, the UI and the cross-node protocol |
| Use `CueHandlerProtocol.communications_thread` | Send status through the engine, not around it. It is also unbound until `set_nng_comms()` runs |
| Look up or trigger cues inside `attach()` | No project is loaded and nothing is armed at that point |
| Block the engine thread in `attach()`, hook callbacks, or outcome listeners | All three run synchronously in the dispatch thread |

---

## Prerequisites Before the First Controller Module

Ordered. Nothing below is done.

0. **Decide the protocol home module** — analysis §12 A. Needed **before analysis Step 4**, not before this
   feature, because Step 4 already moves and renames `CueHandlerProtocol`.
1. **Analysis Steps 1–9** land — in particular Step 6 (outcome listeners), Step 7 (multi-owner hooks) and
   Step 8 (`dispatch_action` + `ActionParams`). Contracts 1–3 are unimplementable before them.
2. ~~Decide the protocol home module~~ — pulled forward to item 0 above.
3. **`CueHandler.get_cue_by_id`** — new method, own tests (Contract 3).
4. **`CueHandler.route_control_event`** — own spec and branch, including the dotted-path and 0–1 vs 0–100
   decisions above (Contract 4).
5. **`NodeEngine` controller-module registry** plus the `attach`/`detach` call sites at the position fixed in
   *Lifecycle*.

Contract 5 / analysis Step 10 is independent of all of the above and blocks only the next fadeable cue type.
