# Controller Integration Contracts

**Date:** 2026-05-19 — revised 2026-08-10 (synced with the locked ActionHandler decision)  
**Scope:** Formal integration contracts for external hardware controller modules  
**Status:** Design artifact — defines required interfaces before any implementation begins  
**Relates to:** `specs/planning/action-handler-architecture-analysis.md` — that document is authoritative for
`ActionHandler` internals; this one is authoritative for the controller-facing surface. **They must stay in sync.**

---

## Overview

External controllers (MIDI surfaces, LAN OSC controllers, USB HID devices) integrate
with the engine through **three separate paths** depending on the nature of the event:

| Event type | Path | Entry point |
|---|---|---|
| Discrete trigger (button → go/stop/fade) | Discrete-action pipeline | `ActionHandler.dispatch_action()` |
| Continuous parameter (fader → volume) | Live-control routing layer | `CueHandler.route_<namespace>_message()` |
| Hardware feedback (LED, motor fader) | Outcome-listener list | `ActionHandler.add_outcome_listener()` |

A single controller module will typically use **all three**. The first two paths must never be
merged: routing continuous streams through `dispatch_action` invokes the full hook
pipeline on every parameter tick.

**Feedback uses listeners, not `after_dispatch` hooks.** A hook that raises rewrites the
outcome to `failed` and breaks the hook loop. The expected failure mode of an LED write is
an unplugged device — which must never turn an applied `play` into a `failed` outcome on the
Controller UI. Outcome listeners are exception-isolated and cannot alter a result. Hooks
remain available for extensions that legitimately *participate* in an outcome
(see analysis document §1 and §3.3).

**Process scope.** Controller modules live in the **node-engine process** only.
`ControllerEngine` imports neither `CueHandler` nor `ActionHandler`.

---

## Lifecycle

```
NodeEngine.set_players()
    │
    ├─► PLAYER_HANDLER.set_gradient_client(...)       # existing pattern
    ├─► PLAYER_HANDLER.set_<new_client>(...)          # future: set_midi_client, etc.
    │
    └─► ControllerModule.attach(action_handler, cue_handler, live_router, mtc)
            │
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

**Lifetime is the process, not the project.** `attach()` runs once per process and `detach()`
only at shutdown. Tying `detach()` to project load would close and reopen the hardware port on
every load — slow for MIDI devices and a common failure point. A module that needs to react to a
project change observes it through its own means; the engine does not re-attach.

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
        """Called once per process, after NodeEngine.set_players() completes.

        The engine is fully initialised at this point: comms thread is up,
        GradientClient is bound, cue list is loaded.

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

---

## Contract 2 — `ActionHandlerProtocol`

The subset of `ActionHandler` that controller modules may call. Only methods listed
here are part of the stable controller integration API. Accessing any other method
(including `_default_result_sink`, `_emit_outcome`, `_hooks`) is a contract violation.

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

        params carries the payload for actions that need more than
        (action_type, target). Required for 'fade_action'; omitting it there
        returns a 'failed' outcome naming the missing payload. Ignored by
        actions that do not read it.

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
        source='cue_layer' is reserved for show-script extensions.

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
`_start_mtc` / `_end_mtc` back:

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

**Implementation status.** `dispatch_action`, `ActionParams`, `add_outcome_listener`,
`remove_outcome_listener`, `unregister_all_hooks` and the `owner` parameter do not exist yet.
They are scheduled in the analysis document's migration path: outcome listeners at **Step 6**,
multi-owner hooks at **Step 7**, `dispatch_action` + `ActionParams` at **Step 8**.

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
one name, both consumers.

```python
class CueHandlerProtocol(Protocol):
    """Stable API surface for action dispatch and external controller modules."""

    communications_thread: "NodeCommunications | None"

    def get_armed_cue_by_id(self, cue_id: str) -> "Cue | None":
        """Return the currently armed cue with this UUID, or None."""
        ...

    def get_cue_by_id(self, cue_id: str) -> "Cue | None":
        """Return any cue in the loaded project by UUID (armed or not), or None.

        NOT YET IMPLEMENTED — add alongside controller integration.
        Today only get_armed_cue_by_id and find_armed_cue exist.
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

`communications_thread` is declared for `ActionHandler`'s internal NNG outcome delivery, which
reaches it through this protocol. Controller modules MUST NOT use it — send status through the
engine, not around it.

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

`CueHandler.route_control_event` dispatches to the existing `route_audio_message`,
`route_dmx_message`, and any future `route_lighting_message` / `route_midi_out_message`
based on the namespace. This replaces the current pattern where `NodeEngine` dispatches
directly to per-namespace methods — the controller module only needs one entry point.

**Implementation status: NOT YET IMPLEMENTED, and unowned.** Today
`NodeEngine._handle_player_control_message` dispatches straight to `route_audio_message` /
`route_dmx_message`. `route_control_event` has no step in the ActionHandler migration path —
it is a prerequisite for the first controller module and needs its own spec and branch.

---

## Contract 5 — `FadePayloadBuilderProtocol`

Replaces the `isinstance` chain in `_build_fade_payload`. Each fadeable cue type
registers its own builder. See analysis document B2 for the registry mechanism.

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

**Caller obligations — these fix live defects, they are not current behaviour.**
See analysis document §7 B2 acceptance criteria.

1. **Record `end_value` per entry, immediately after that entry's own successful send.**
   The current code dispatches every entry and only then records, so a failure at layer *N*
   loses the records for layers `0..N-1` that were already sent — their next fade then reads a
   stale `start_value`. The "leave state unchanged on failure" invariant in the current comment
   is unachievable: the OSC sends are not atomic, so those layers *are* already faded on the
   player. The engine-side record must mirror what was actually sent.
2. **The caller MUST NOT mutate returned dicts.** The builder does not retain them, but the
   current code does `entry.pop("motion_id")` in the dispatch loop and re-reads the same dicts
   in the record loop. Read `entry["motion_id"]`; do not pop.
3. Builders are stateless and registered at module load for `AudioCue` and `VideoCue`; new
   fadeable types register their own. `SUPPORTED_CUE_ACTIONS` is closed, but this registry is
   **open** — it is one of the three OCP seams named in the analysis document §3.4.

---

## Integration Pattern A — MIDI Controller (Discrete Triggers)

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
        self._ah.dispatch_action(mapping["action_type"], target, self._mtc)

    def _handle_cc(self, control: int, raw_value: int):
        mapping = CC_MAP.get(control)    # {namespace, parameter}
        if mapping is None:
            return
        normalized = raw_value / 127.0
        self._lr.route_control_event(mapping["namespace"], mapping["parameter"], normalized)

    def _on_action_complete(self, outcome: dict):
        # Outcome listener — receives the final result dict, cannot alter it.
        led_note = REVERSE_BUTTON_MAP.get((outcome["action_type"], outcome["target_id"]))
        if led_note is not None and outcome["status"] == "applied":
            self._set_led(led_note, ON if outcome["action_type"] == "play" else OFF)
```

---

## Integration Pattern B — LAN OSC Controller

Mapping: OSC messages from a control surface (e.g. TouchOSC, Lemur) over UDP/TCP.

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

---

## What Controller Modules Must NOT Do

| Prohibited | Reason |
|---|---|
| Import `CUE_HANDLER` as a module global | Bypasses DI; breaks test isolation. `ACTION_HANDLER` no longer exists. Note this is a **convention, not a mechanism**: `CUE_HANDLER` is still importable, so reviewers enforce it |
| Call `ActionHandler.execute_action(action_cue, ...)` with a constructed `ActionCue` | Constructing `ActionCue` with `_action_target_object` pre-set is fragile; use `dispatch_action` with `ActionParams` |
| Route continuous events through `dispatch_action` | Invokes full hook pipeline on every tick |
| Access `_default_result_sink`, `_hooks`, `_emit_outcome`, `_dispatch` directly | Protected implementation details. Everything a module legitimately needs is on `ActionHandlerProtocol` — there is no case where reaching past it is correct |
| Use `after_dispatch` hooks for hardware feedback | A raising hook rewrites the outcome to `failed`; an unplugged device would fail the show action. Use `add_outcome_listener` |
| Register hooks with `source='cue_layer'` | That layer is reserved for show-script extensions |
| Register hooks with the default `owner` | Owner-less registrations evict each other. Always pass `owner=self.module_id` |
| Share a `module_id` with another attached module | `unregister_all_hooks(owner)` would tear down both |
| Introduce a new action type | `SUPPORTED_CUE_ACTIONS` is deliberately closed — the vocabulary is shared with the XSD, the UI and the cross-node protocol |
| Use `CueHandlerProtocol.communications_thread` | Send status through the engine, not around it |
| Block the engine thread in `attach()`, hook callbacks, or outcome listeners | All three run synchronously in the dispatch thread |
