"""Dedicated action-cue execution, extension hooks, and optional result sink."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Literal

from cuemsutils.cues import ActionCue
from cuemsutils.cues.Cue import Cue
from cuemsutils.log import Logger

from ..comms.NodesHub import ActionType, NodeOperation, OperationType
from ..comms.NodeCommunications import NodeCommunications
from ..tools.MtcListener import MtcListener

# Actions supported by the engine runtime.
# The XSD schema (script.xsd ActionType) also defines these not-yet-implemented
# actions: load, unload, wait, pause_project, resume_project.
SUPPORTED_CUE_ACTIONS = frozenset(
    {
        "play",
        "pause",
        "stop",
        "enable",
        "disable",
        "fade_action",
        "fade_in",
        "fade_out",
        "go_to",
    }
)

HookPhase = Literal["before_dispatch", "after_dispatch", "wrap_dispatch"]
RegistrationLayer = Literal["cue_layer", "node_layer"]

_ALL_ACTIONS: frozenset[str] = frozenset()


def _filter_matches(action_type: str, filter_key: frozenset[str]) -> bool:
    if not filter_key:
        return True
    return action_type in filter_key


@dataclass
class ActionHookContext:
    """Context passed to extension hooks (stable field names for integrators)."""

    cue: ActionCue
    target: Cue | None
    mtc: MtcListener
    action_type: str
    target_id: str | None
    outcome: dict | None = None
    cue_handler: Any = None


class ActionHandler:
    """Owns ActionCue validation, default handlers, hooks, and result delivery."""

    def __init__(self) -> None:
        self._cue_handler: Any = None
        self._lock = threading.Lock()
        self._hooks: dict[
            tuple[str, str, frozenset[str]], Callable[[ActionHookContext], Any]
        ] = {}
        self._result_sink: Callable[[dict], None] | None = None
        self._emit_enabled: bool = True

    # ---- binding ----

    def bind_cue_handler(self, cue_handler: Any) -> None:
        """Bind the singleton cue orchestrator (arm, go, armed lookups)."""
        self._cue_handler = cue_handler

    def set_result_sink(self, sink: Callable[[dict], None] | None) -> None:
        """Replace result delivery; None restores default (NNG via comms thread)."""
        with self._lock:
            self._result_sink = sink

    def set_emit_enabled(self, enabled: bool) -> None:
        """When False, suppress outcome emission (useful in tests)."""
        with self._lock:
            self._emit_enabled = enabled

    def clear_action_extensions(self) -> None:
        """Remove all hooks and custom sink (for isolated tests)."""
        with self._lock:
            self._hooks.clear()
            self._result_sink = None
            self._emit_enabled = True

    # ---- registration ----

    def register_action_hook(
        self,
        phase: HookPhase,
        fn: Callable[[ActionHookContext], Any],
        *,
        source: RegistrationLayer = "cue_layer",
        action_types: frozenset[str] | None = None,
    ) -> None:
        """Register a hook; last registration wins for the same (phase, source, filter)."""
        filter_key = action_types if action_types is not None else _ALL_ACTIONS
        key = (phase, source, filter_key)
        with self._lock:
            self._hooks[key] = fn

    def unregister_action_hook(
        self,
        phase: HookPhase,
        *,
        source: RegistrationLayer,
        action_types: frozenset[str] | None = None,
    ) -> None:
        filter_key = action_types if action_types is not None else _ALL_ACTIONS
        key = (phase, source, filter_key)
        with self._lock:
            self._hooks.pop(key, None)

    def finalize_node_layer_bindings(self) -> None:
        """Call from NodeEngine after comms are ready (extension point; default no-op)."""
        return

    # ---- hook resolution ----

    def _matching_hooks(
        self, phase: HookPhase, action_type: str
    ) -> list[tuple[str, Callable[[ActionHookContext], Any]]]:
        """Return (layer, fn) pairs: cue_layer first, then node_layer."""
        with self._lock:
            items = list(self._hooks.items())
        cue_hooks: list[tuple[str, Callable[[ActionHookContext], Any]]] = []
        node_hooks: list[tuple[str, Callable[[ActionHookContext], Any]]] = []
        for (ph, layer, filter_key), fn in items:
            if ph != phase or not _filter_matches(action_type, filter_key):
                continue
            if layer == "cue_layer":
                cue_hooks.append((layer, fn))
            else:
                node_hooks.append((layer, fn))
        return cue_hooks + node_hooks

    def _wrap_for_action(
        self, layer: RegistrationLayer, action_type: str
    ) -> Callable[..., Any] | None:
        with self._lock:
            best_specific: Callable[..., Any] | None = None
            best_all: Callable[..., Any] | None = None
            for (ph, src, filter_key), fn in self._hooks.items():
                if ph != "wrap_dispatch" or src != layer:
                    continue
                if not filter_key:
                    best_all = fn
                elif action_type in filter_key:
                    best_specific = fn
            return best_specific if best_specific is not None else best_all

    # ---- result delivery ----

    def _emit_outcome(self, outcome: dict) -> None:
        with self._lock:
            sink = self._result_sink
            emit = self._emit_enabled
        if not emit:
            return
        if sink is not None:
            try:
                sink(outcome)
            except Exception as exc:
                Logger.error(f"Custom action result sink raised: {exc}")
            return
        self._default_result_sink(outcome)

    def _default_result_sink(self, outcome: dict) -> None:
        ch = self._cue_handler
        if ch is None:
            return
        ct: NodeCommunications | None = getattr(ch, "communications_thread", None)
        if ct is None:
            return
        try:
            op = NodeOperation(
                type=OperationType.STATUS,
                action=ActionType.UPDATE,
                sender=ct.node_id,
                target="action_cue_outcome",
                data=dict(outcome),
            )
            ct.send_operation(op, timeout=0.1)
        except Exception as exc:
            Logger.debug(f"Default action outcome emit skipped: {exc}")

    # ---- main dispatch ----

    def execute_action(self, cue: ActionCue, mtc: MtcListener) -> dict:
        action_type = cue.action_type
        target = cue._action_target_object

        if action_type not in SUPPORTED_CUE_ACTIONS:
            reason = f"Unsupported action_type: {action_type!r}"
            Logger.warning(reason)
            out = self._action_result("rejected", action_type, None, reason)
            self._emit_outcome(out)
            return out

        if target is None:
            reason = (
                f"Missing target for {action_type} "
                f"(action_target={cue.action_target!r})"
            )
            Logger.warning(reason)
            out = self._action_result("rejected", action_type, None, reason)
            self._emit_outcome(out)
            return out

        target_id = getattr(target, "id", None)
        ctx = ActionHookContext(
            cue=cue,
            target=target,
            mtc=mtc,
            action_type=action_type,
            target_id=target_id,
            outcome=None,
            cue_handler=self._cue_handler,
        )

        # before_dispatch hooks
        for _layer, hook_fn in self._matching_hooks("before_dispatch", action_type):
            try:
                hook_fn(ctx)
            except Exception as exc:
                reason = f"before_dispatch hook raised {type(exc).__name__}: {exc}"
                Logger.error(reason)
                out = self._action_result("failed", action_type, target_id, reason)
                self._emit_outcome(out)
                return out

        handler = _ACTION_HANDLERS.get(action_type)
        if handler is None:
            reason = f"No handler registered for {action_type}"
            Logger.error(reason)
            out = self._action_result("failed", action_type, target_id, reason)
            self._emit_outcome(out)
            return out

        ch = self._cue_handler

        def run_default() -> dict:
            return handler(ch, target, mtc)

        def apply_wraps() -> dict:
            inner: Callable[[], dict] = run_default
            for layer in ("node_layer", "cue_layer"):
                wfn = self._wrap_for_action(layer, action_type)
                if wfn is None:
                    continue
                prev = inner

                def make_wrapped(
                    w: Callable[..., Any] = wfn, p: Callable[[], dict] = prev
                ) -> Callable[[], dict]:
                    def _w() -> dict:
                        return w(ctx, p)

                    return _w

                inner = make_wrapped()
            return inner()

        dispatch_exc: bool
        try:
            has_wrap = any(
                self._wrap_for_action(layer, action_type) is not None
                for layer in ("cue_layer", "node_layer")
            )
            if has_wrap:
                result = apply_wraps()
            else:
                result = run_default()
            dispatch_exc = False
        except Exception as exc:
            dispatch_exc = True
            reason = (
                f"{action_type} on {target_id} raised " f"{type(exc).__name__}: {exc}"
            )
            Logger.error(reason)
            result = self._action_result("failed", action_type, target_id, reason)

        ctx.outcome = result

        # after_dispatch hooks (skipped if default handler raised)
        if not dispatch_exc:
            for _layer, hook_fn in self._matching_hooks("after_dispatch", action_type):
                try:
                    hook_fn(ctx)
                except Exception as exc:
                    reason = (
                        f"after_dispatch hook raised " f"{type(exc).__name__}: {exc}"
                    )
                    Logger.error(reason)
                    result = self._action_result(
                        "failed", action_type, target_id, reason
                    )
                    ctx.outcome = result
                    break
            Logger.info(
                f'Action {action_type} on {target_id}: {result["status"]}'
                + (f' ({result["reason"]})' if result.get("reason") else "")
            )

        self._emit_outcome(result)
        return result

    @staticmethod
    def _action_result(
        status: str,
        action_type: str,
        target_id: str | None,
        reason: str | None = None,
    ) -> dict:
        return {
            "status": status,
            "action_type": action_type,
            "target_id": target_id,
            "reason": reason,
        }


# ---------------------------------------------------------------------------
# Per-action handlers (module-level; signature: (cue_handler, target, mtc))
# ---------------------------------------------------------------------------


def _handle_play(ch: Any, target: Cue, mtc: MtcListener) -> dict:
    target_id = target.id
    if not target.enabled:
        return ActionHandler._action_result(
            "failed", "play", target_id, "Target is disabled"
        )
    if not getattr(target, "loaded", False):
        ch.arm(target, init=True)
    if not getattr(target, "loaded", False):
        return ActionHandler._action_result(
            "failed", "play", target_id, "Target could not be armed"
        )
    target._stop_requested = False
    try:
        ch.go(target, mtc)
    except Exception as exc:
        return ActionHandler._action_result(
            "failed", "play", target_id, str(exc)
        )
    return ActionHandler._action_result("applied", "play", target_id)


def _handle_pause(ch: Any, target: Cue, mtc: MtcListener) -> dict:
    target_id = target.id
    if getattr(target, "_stop_requested", False):
        return ActionHandler._action_result(
            "applied_no_change", "pause", target_id, "Already stopped/paused"
        )
    target._stop_requested = True
    return ActionHandler._action_result("applied", "pause", target_id)


def _handle_stop(ch: Any, target: Cue, mtc: MtcListener) -> dict:
    target_id = target.id
    if getattr(target, "_stop_requested", False):
        return ActionHandler._action_result(
            "applied_no_change", "stop", target_id, "Already stopped"
        )
    target._stop_requested = True
    target._go_generation = getattr(target, "_go_generation", 0) + 1
    # Allow loop_cue to see _stop_requested and exit (polls every 20ms)
    time.sleep(0.1)
    ch.disarm(target)
    return ActionHandler._action_result("applied", "stop", target_id)


def _handle_enable(ch: Any, target: Cue, mtc: MtcListener) -> dict:
    target_id = target.id
    if target.enabled:
        return ActionHandler._action_result(
            "applied_no_change", "enable", target_id, "Already enabled"
        )
    target.enabled = True
    return ActionHandler._action_result("applied", "enable", target_id)


def _handle_disable(ch: Any, target: Cue, mtc: MtcListener) -> dict:
    target_id = target.id
    if not target.enabled:
        return ActionHandler._action_result(
            "applied_no_change", "disable", target_id, "Already disabled"
        )
    target.enabled = False
    return ActionHandler._action_result("applied", "disable", target_id)


def _handle_fade_in(ch: Any, target: Cue, mtc: MtcListener) -> dict:
    # TODO: implement fade envelope; currently identical to play
    Logger.info("fade_in treated as play (fade envelope not yet implemented)")
    target_id = target.id
    if not getattr(target, "loaded", False):
        ch.arm(target, init=True)
    if not getattr(target, "loaded", False):
        return ActionHandler._action_result(
            "failed", "fade_in", target_id, "Target could not be armed"
        )
    target._stop_requested = False
    ch.go(target, mtc)
    return ActionHandler._action_result("applied", "fade_in", target_id)


def _handle_fade_out(ch: Any, target: Cue, mtc: MtcListener) -> dict:
    # TODO: implement fade envelope; currently identical to stop.
    # Also has the same zombie-process bug as the old stop handler:
    # bumps _go_generation but does not call disarm(), so player processes
    # are not cleaned up. Fix when implementing real fade behavior.
    Logger.info("fade_out treated as stop (fade envelope not yet implemented)")
    target_id = target.id
    target._stop_requested = True
    target._go_generation = getattr(target, "_go_generation", 0) + 1
    return ActionHandler._action_result("applied", "fade_out", target_id)


def _handle_go_to(ch: Any, target: Cue, mtc: MtcListener) -> dict:
    # TODO: implement seek/position navigation; currently only arms the target
    Logger.info("go_to only arms target (seek not yet implemented)")
    target_id = target.id
    if not getattr(target, "loaded", False):
        ch.arm(target, init=True)
    return ActionHandler._action_result("applied", "go_to", target_id)


def _build_fade_payload(target_cue: Cue, fade_cue: Any, start_time: int) -> dict:
    """Build the body of a FadeCommand from target_cue + fade_cue.

    Envelope fields (command, fade_id, osc_host, curve_params) are added by
    NodeCommunications.send_fade_command — keep them out of this body so the
    helper stays pure data construction.
    """
    from cuemsutils.cues import AudioCue, VideoCue

    if isinstance(target_cue, AudioCue):
        osc_port = target_cue._osc.remote_port
        osc_path = "/volmaster"
    elif isinstance(target_cue, VideoCue):
        # TODO: resolve videocomposer OSC port from configuration
        osc_port = 7000
        osc_path = f"/videocomposer/layer/{target_cue._layer_ids[0]}/opacity"
    else:
        raise ValueError(
            f"FadeCue target is not an AudioCue or VideoCue: "
            f"{type(target_cue).__name__}"
        )

    start_value = target_cue._osc.get_value(osc_path)

    curve_type = fade_cue.curve_type
    curve_type_str = curve_type.value if hasattr(curve_type, "value") else str(curve_type)

    return {
        "osc_port": osc_port,
        "osc_path": osc_path,
        "start_value": start_value,
        "target_value": fade_cue.target_value,
        "start_time": start_time,
        "duration_ms": fade_cue.duration.milliseconds_rounded,
        "curve_type": curve_type_str,
    }


def _handle_fade_action(ch: Any, cue: Any, mtc: MtcListener) -> dict:
    """Execute a FadeCue: arm target_cue if needed, dispatch FadeCommand, set _end_mtc.

    The handler MUST NOT disarm target_cue, set _fade_initial_volume, or call
    ch.go(target_cue, mtc) — the target_cue is expected to be already playing.
    The FadeCue itself is held in the cue runner by loop_fadeCue until _end_mtc.
    """
    from cuemsutils.tools.CTimecode import CTimecode

    target_cue = cue._action_target_object
    target_id = getattr(target_cue, "id", None)
    fade_id = str(cue.id)

    if target_cue is None:
        return ActionHandler._action_result(
            "failed", "fade_action", target_id,
            f"FadeCue {fade_id} has no resolved action_target_object"
        )

    # Arm target_cue via general cue logic (no envelope-from-silence here).
    if not getattr(target_cue, "loaded", False):
        ch.arm(target_cue, init=True)
    if not getattr(target_cue, "loaded", False):
        return ActionHandler._action_result(
            "failed", "fade_action", target_id,
            f"Target cue {target_id} could not be armed"
        )

    start_time = mtc.timecode.milliseconds_rounded

    try:
        payload = _build_fade_payload(target_cue, cue, start_time)
    except ValueError as exc:
        return ActionHandler._action_result(
            "failed", "fade_action", target_id, str(exc)
        )

    # Dispatch FIRST. If NNG fails the target_cue state must remain unchanged.
    try:
        ch.communications_thread.send_fade_command(payload, fade_id=fade_id)
    except Exception as exc:
        Logger.error(
            f"FadeCue {fade_id}: NNG dispatch to gradient-motiond failed "
            f"(target_cue={target_id}): {exc}"
        )
        return ActionHandler._action_result(
            "failed", "fade_action", target_id,
            f"NNG dispatch failed: {exc}"
        )

    # Set _start_mtc / _end_mtc on the FadeCue so loop_fadeCue has a real
    # end-mtc to wait on. mtc.main_tc is the live MTC ticking forward.
    framerate = mtc.main_tc.framerate
    cue._start_mtc = CTimecode(framerate=framerate, start_seconds=start_time / 1000.0)
    cue._end_mtc = cue._start_mtc + cue.duration.return_in_other_framerate(framerate)

    Logger.info(
        f"FadeCue {fade_id}: dispatched start_fade "
        f"target_cue={target_id} osc={payload['osc_path']} "
        f"start={payload['start_value']} target={payload['target_value']} "
        f"duration={payload['duration_ms']}ms curve={payload['curve_type']}"
    )
    return ActionHandler._action_result("applied", "fade_action", target_id)


_ACTION_HANDLERS: dict[str, Callable[[Any, Cue, MtcListener], dict]] = {
    "play": _handle_play,
    "pause": _handle_pause,
    "stop": _handle_stop,
    "enable": _handle_enable,
    "disable": _handle_disable,
    "fade_action": _handle_fade_action,
    "fade_in": _handle_fade_in,
    "fade_out": _handle_fade_out,
    "go_to": _handle_go_to,
}

ACTION_HANDLER = ActionHandler()
