# Controller Integration Contracts

**Date:** 2026-05-19  
**Scope:** Formal integration contracts for external hardware controller modules  
**Status:** Design artifact — defines required interfaces before any implementation begins  
**Relates to:** `specs/planning/action-handler-architecture-analysis.md` (Option C, B1, B2)

---

## Overview

External controllers (MIDI surfaces, LAN OSC controllers, USB HID devices) integrate
with the engine through **two completely separate paths** depending on the nature of
the control event:

| Event type | Path | Entry point |
|---|---|---|
| Discrete trigger (button → go/stop/fade) | Scripted-action pipeline | `ActionHandler.dispatch_action()` |
| Continuous parameter (fader → volume) | Live-control routing layer | `CueHandler.route_<namespace>_message()` |

A single controller module will typically use **both** paths. The paths must never be
merged. Routing continuous streams through `dispatch_action` invokes the full hook
pipeline on every parameter tick.

---

## Lifecycle

```
NodeEngine.set_players()
    │
    ├─► PLAYER_HANDLER.set_gradient_client(...)       # existing pattern
    ├─► PLAYER_HANDLER.set_<new_client>(...)          # future: set_midi_client, etc.
    │
    └─► ControllerModule.attach(action_handler, cue_handler, live_router)
            │
            ├─► registers node_layer hooks on action_handler (discrete feedback)
            ├─► opens hardware connection / starts listener thread
            └─► stores live_router reference for continuous events

NodeEngine.stop_playback() / shutdown
    └─► ControllerModule.detach()
            ├─► unregisters hooks
            └─► closes hardware connection / stops listener thread
```

---

## Contract 1 — `ControllerModuleProtocol`

Every hardware controller bridge (MIDI, LAN OSC, USB HID) must satisfy this protocol.

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class ControllerModuleProtocol(Protocol):
    """Interface every hardware controller bridge must implement.

    Implementations are responsible for their own threading. The engine calls
    attach() and detach() from the main thread; all callbacks into the engine
    from background threads must be thread-safe (CueHandler and ActionHandler
    are both thread-safe under Option C).
    """

    def attach(
        self,
        action_handler: "ActionHandlerProtocol",
        cue_handler: "CueHandlerProtocol",
        live_router: "LiveControlRouterProtocol",
    ) -> None:
        """Called once after NodeEngine.set_players() completes.

        The engine is fully initialised at this point: comms thread is up,
        GradientClient is bound, cue list is loaded.

        Implementations SHOULD:
        - register node_layer hooks for discrete action feedback
        - open the hardware connection (MIDI port, TCP socket, USB device)
        - start listener threads if needed
        - store references to action_handler, cue_handler, live_router for
          use in background threads

        Implementations MUST NOT:
        - trigger any cue action during attach()
        - block the calling thread for more than ~100 ms
        """
        ...

    def detach(self) -> None:
        """Called on engine shutdown or before a new project is loaded.

        Implementations MUST:
        - unregister all node_layer hooks previously registered in attach()
        - stop all background threads
        - close the hardware connection cleanly

        Implementations MUST NOT raise — log errors and continue.
        """
        ...

    @property
    def module_id(self) -> str:
        """Stable identifier for logging and hook registration (e.g. 'midi_apc40')."""
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
    ) -> dict:
        """Dispatch a discrete action without constructing an ActionCue.

        This is the primary entry point for hardware-triggered discrete events
        (button press → play, button press → stop, etc.).

        action_type must be in SUPPORTED_CUE_ACTIONS.
        target must be a live Cue object (look it up via CueHandlerProtocol.get_armed_cue_by_id
        or CueHandlerProtocol.get_cue_by_id before calling).

        Before/after/wrap hooks fire exactly as they do for script-driven actions.
        The result dict has the same shape: {status, action_type, target_id, reason}.
        """
        ...

    def register_action_hook(
        self,
        phase: "HookPhase",
        fn: "Callable[[ActionHookContext], Any]",
        *,
        source: "RegistrationLayer" = "node_layer",
        action_types: "frozenset[str] | None" = None,
    ) -> None:
        """Register a hook for controller feedback.

        Controller modules MUST use source='node_layer'.
        source='cue_layer' is reserved for show-script extensions.

        Typical use: register an 'after_dispatch' hook to update hardware
        feedback (LED state, motor fader position) after an action completes.
        """
        ...

    def unregister_action_hook(
        self,
        phase: "HookPhase",
        *,
        source: "RegistrationLayer",
        action_types: "frozenset[str] | None" = None,
    ) -> None:
        """Unregister a previously registered hook. Call during detach()."""
        ...
```

**Note:** `dispatch_action` does not exist yet on `ActionHandler`. It must be added as
part of the Option C migration (Step 3 or as a Step 3b). Its implementation is a thin
wrapper that constructs a minimal context and jumps directly to the handler dispatch
loop, skipping `ActionCue` parsing but preserving the full hook pipeline.

---

## Contract 3 — `CueHandlerProtocol`

The subset of `CueHandler` that controller modules may call.

```python
class CueHandlerProtocol(Protocol):
    """Stable API surface for external controller modules."""

    def get_armed_cue_by_id(self, cue_id: str) -> "Cue | None":
        """Return the currently armed cue with this UUID, or None."""
        ...

    def get_cue_by_id(self, cue_id: str) -> "Cue | None":
        """Return any cue in the loaded project by UUID (armed or not), or None.

        Not yet implemented — add alongside controller integration.
        """
        ...

    def arm(self, cue: "Cue", *, init: bool = False) -> None:
        """Arm a cue (load it). Idempotent if already armed."""
        ...

    def go(self, cue: "Cue", mtc: "MtcListener", frozen_mtc_ms: float | None = None) -> None:
        """Start a cue. Requires cue to be armed first."""
        ...

    def disarm(self, cue: "Cue") -> None:
        """Stop and unload a cue."""
        ...

    def get_gradient_client(self) -> "GradientClient | None":
        """Return the active GradientClient, or None if not yet initialised."""
        ...
```

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

`CueHandler.route_control_event` would dispatch to the existing `route_audio_message`,
`route_dmx_message`, and any future `route_lighting_message` / `route_midi_out_message`
based on the namespace. This replaces the current pattern where `NodeEngine` dispatches
directly to per-namespace methods — the controller module only needs one entry point.

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

---

## Integration Pattern A — MIDI Controller (Discrete Triggers)

Mapping: physical button → go/stop/fade on a named cue.

```python
class MidiControllerBridge:
    module_id = "midi_apc40"

    def attach(self, action_handler, cue_handler, live_router):
        self._ah = action_handler
        self._ch = cue_handler
        self._lr = live_router
        # Feedback: update button LEDs after every action on this module's cues
        action_handler.register_action_hook(
            "after_dispatch",
            self._on_action_complete,
            source="node_layer",
        )
        self._open_midi_port()
        self._listener = threading.Thread(target=self._midi_loop, daemon=True)
        self._listener.start()

    def detach(self):
        self._stop_event.set()
        self._listener.join(timeout=1.0)
        self._close_midi_port()
        self._ah.unregister_action_hook("after_dispatch", source="node_layer")

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

    def _on_action_complete(self, ctx: ActionHookContext):
        # Update hardware LED state based on outcome
        led_note = REVERSE_BUTTON_MAP.get((ctx.action_type, ctx.target_id))
        if led_note is not None and ctx.outcome and ctx.outcome["status"] == "applied":
            self._set_led(led_note, ON if ctx.action_type == "play" else OFF)
```

---

## Integration Pattern B — LAN OSC Controller

Mapping: OSC messages from a control surface (e.g. TouchOSC, Lemur) over UDP/TCP.

```python
class LanOscControllerBridge:
    module_id = "lan_osc_surface"

    def attach(self, action_handler, cue_handler, live_router):
        self._ah = action_handler
        self._ch = cue_handler
        self._lr = live_router
        self._server = OscServer(port=self._listen_port, handler=self._on_osc)
        self._server.start()

    def detach(self):
        self._server.stop()
        # No hooks to unregister if this module chose not to register any

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
| Import `ACTION_HANDLER` or `CUE_HANDLER` as module globals | Bypasses DI; breaks test isolation |
| Call `ActionHandler.execute_action(action_cue, ...)` with a constructed `ActionCue` | Constructing `ActionCue` with `_action_target_object` pre-set is fragile; use `dispatch_action` instead |
| Route continuous events through `dispatch_action` | Invokes full hook pipeline on every tick |
| Access `_default_result_sink`, `_hooks`, `_emit_outcome` directly | Protected implementation details, not part of the public contract |
| Register hooks with `source='cue_layer'` | That layer is reserved for show-script extensions |
| Block the engine thread in `attach()` or in hook callbacks | Hooks run synchronously in the dispatch thread |
