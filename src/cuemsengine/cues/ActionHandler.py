# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""
Dedicated action-cue execution, extension hooks, and optional result sink.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Literal

from cuemsutils.cues import ActionCue
from cuemsutils.cues.Cue import Cue
from cuemsutils.log import Logger

from ..comms.NodeCommunications import NodeCommunications
from ..comms.NodesHub import ActionType, NodeOperation, OperationType
from ..players.PlayerHandler import PLAYER_HANDLER
from ..tools.MtcListener import MtcListener
from .CueHandler import CueHandler

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
    """
    Context passed to extension hooks (stable field names for integrators).
    """

    cue: ActionCue
    target: Cue | None
    mtc: MtcListener
    action_type: str
    target_id: str | None
    outcome: dict | None = None
    cue_handler: Any = None
    frozen_mtc_ms: float | None = None


class ActionHandler:
    """
    Owns ActionCue validation, default handlers, hooks, and result delivery.
    """

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
        """
        Replace result delivery; None restores default (NNG via comms thread).
        """
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
        """
        Register a hook; last registration wins for the same (phase, source,
        filter).
        """
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
        """
        Call from NodeEngine after comms are ready (extension point; default
        no-op).
        """
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

    def execute_action(
        self,
        cue: ActionCue,
        mtc: MtcListener,
        frozen_mtc_ms: float | None = None,
    ) -> dict:
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
            frozen_mtc_ms=frozen_mtc_ms,
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
            return handler(ch, cue, target, mtc, frozen_mtc_ms)

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
                f"{action_type} on {target_id} raised {type(exc).__name__}: {exc}"
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
                        f"after_dispatch hook raised {type(exc).__name__}: {exc}"
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
# Per-action helpers
# ---------------------------------------------------------------------------


def _ready_action_target(action: str, target: Cue, ch: CueHandler) -> dict | None:
    """Ensure target is enabled and loaded before dispatch; arm if needed.

    Returns a failure result dict on the first problem, or None if ready.
    """
    target_id = getattr(target, "id", None)
    if not target.enabled:
        return ActionHandler._action_result(
            "failed", action, target_id, "Target is disabled"
        )
    if not getattr(target, "loaded", False):
        try:
            ch.arm(target, init=True)
        except Exception as exc:
            return ActionHandler._action_result("failed", action, target_id, str(exc))
    if not getattr(target, "loaded", False):
        return ActionHandler._action_result(
            "failed", action, target_id, "Target could not be armed"
        )
    return None


# ---------------------------------------------------------------------------
# Per-action handlers (module-level; signature: (cue_handler, action_cue,
# target, mtc, frozen_mtc_ms))
#
# action_cue is the originating ActionCue/FadeCue (cue.action_type drives
# dispatch);
# target is the resolved cue._action_target_object. Most handlers only need
# target;
# fade_action needs both (action_cue carries fade params, target is what gets
# faded).
# ---------------------------------------------------------------------------


def _handle_play(
    ch: CueHandler,
    _action_cue: Any,
    target: Cue,
    mtc: MtcListener,
    frozen_mtc_ms: float | None = None,
) -> dict:
    target_id = target.id
    # Readiness gates the cue we would play locally. For a NON-local target,
    # go_from walks PAST it to THIS node's own local cue (which go() re-arms),
    # so don't gate on the non-local target — it can never arm here, and doing
    # so silently dropped the controller's own cues on a cross-node loop-back.
    if getattr(target, "_local", False):
        fail = _ready_action_target("play", target, ch)
        if fail is not None:
            return fail
    target._stop_requested = False
    try:
        # go_from (not go): walk the target's post_go='go' chain to THIS node's
        # first local+enabled cue. A plain go() bails when `target` is local to
        # another node, dropping this node's own cues on a cross-node loop-back
        # (circular project). See CueHandler.go_from.
        ch.go_from(target, mtc, frozen_mtc_ms)
    except Exception as exc:
        return ActionHandler._action_result("failed", "play", target_id, str(exc))
    return ActionHandler._action_result("applied", "play", target_id)


def _handle_pause(
    ch: CueHandler,
    _action_cue: Any,
    target: Cue,
    mtc: MtcListener,
    frozen_mtc_ms: float | None = None,
) -> dict:
    target_id = target.id
    if getattr(target, "_stop_requested", False):
        return ActionHandler._action_result(
            "applied_no_change", "pause", target_id, "Already stopped/paused"
        )
    target._stop_requested = True
    return ActionHandler._action_result("applied", "pause", target_id)


def _handle_stop(
    ch: CueHandler,
    _action_cue: Any,
    target: Cue,
    mtc: MtcListener,
    frozen_mtc_ms: float | None = None,
) -> dict:
    target_id = target.id
    if getattr(target, "_stop_requested", False):
        return ActionHandler._action_result(
            "applied_no_change", "stop", target_id, "Already stopped"
        )
    target._stop_requested = True
    target._go_generation = getattr(target, "_go_generation", 0) + 1
    # Allow loop_cue to see _stop_requested and exit (polls every 20ms)
    time.sleep(0.1)
    try:
        ch.disarm(target)
    except Exception as exc:
        return ActionHandler._action_result("failed", "stop", target_id, str(exc))
    return ActionHandler._action_result("applied", "stop", target_id)


def _handle_enable(
    ch: CueHandler,
    _action_cue: Any,
    target: Cue,
    mtc: MtcListener,
    frozen_mtc_ms: float | None = None,
) -> dict:
    # Pure flag flip. The arm/pre-load side effect for the newly enabled cue
    # (async ReArm) lives in NodeEngine._action_result_sink, which reacts to
    # this handler's 'applied' outcome.
    target_id = target.id
    if target.enabled:
        return ActionHandler._action_result(
            "applied_no_change", "enable", target_id, "Already enabled"
        )
    target.enabled = True
    return ActionHandler._action_result("applied", "enable", target_id)


def _handle_disable(
    ch: CueHandler,
    _action_cue: Any,
    target: Cue,
    mtc: MtcListener,
    frozen_mtc_ms: float | None = None,
) -> dict:
    # Pure flag flip. The disarm-if-idle side effect for the disabled cue
    # lives in NodeEngine._action_result_sink, which reacts to this handler's
    # 'applied' outcome (guarded by the cue's _playing lifecycle flag).
    target_id = target.id
    if not target.enabled:
        return ActionHandler._action_result(
            "applied_no_change", "disable", target_id, "Already disabled"
        )
    target.enabled = False
    return ActionHandler._action_result("applied", "disable", target_id)


def _handle_fade_in(
    ch: CueHandler,
    _action_cue: Any,
    target: Cue,
    mtc: MtcListener,
    frozen_mtc_ms: float | None = None,
) -> dict:
    # TODO: implement fade envelope; currently identical to play
    Logger.info("fade_in treated as play (fade envelope not yet implemented)")
    target_id = target.id
    # Only gate on a local target (see _handle_play) — non-local targets are
    # walked past by go_from.
    if getattr(target, "_local", False):
        fail = _ready_action_target("fade_in", target, ch)
        if fail is not None:
            return fail
    target._stop_requested = False
    try:
        # go_from (not go): same cross-node walk as play — a plain go() would
        # drop other nodes' cues on a chain owned by the target's node.
        ch.go_from(target, mtc, frozen_mtc_ms)
    except Exception as exc:
        return ActionHandler._action_result("failed", "fade_in", target_id, str(exc))
    return ActionHandler._action_result("applied", "fade_in", target_id)


def _handle_fade_out(
    ch: CueHandler,
    _action_cue: Any,
    target: Cue,
    mtc: MtcListener,
    frozen_mtc_ms: float | None = None,
) -> dict:
    # TODO: implement fade envelope; currently identical to stop.
    # Also has the same zombie-process bug as the old stop handler:
    # bumps _go_generation but does not call disarm(), so player processes
    # are not cleaned up. Fix when implementing real fade behavior.
    Logger.info("fade_out treated as stop (fade envelope not yet implemented)")
    target_id = target.id
    target._stop_requested = True
    target._go_generation = getattr(target, "_go_generation", 0) + 1
    return ActionHandler._action_result("applied", "fade_out", target_id)


def _handle_go_to(
    ch: CueHandler,
    _action_cue: Any,
    target: Cue,
    mtc: MtcListener,
    frozen_mtc_ms: float | None = None,
) -> dict:
    # TODO: implement seek/position navigation; currently only arms the target
    Logger.info("go_to only arms target (seek not yet implemented)")
    target_id = target.id
    fail = _ready_action_target("go_to", target, ch)
    if fail is not None:
        return fail
    return ActionHandler._action_result("applied", "go_to", target_id)


def _handle_fade_action(
    ch: CueHandler,
    action_cue: Any,
    target: Cue,
    mtc: MtcListener,
    frozen_mtc_ms: float | None = None,
) -> dict:
    """
    Execute a FadeCue: arm target if needed, dispatch FadeCommand, set
    _end_mtc.

    action_cue is the FadeCue (curve_type, target_value, duration). target is
    the
    resolved AudioCue/VideoCue that will be faded. The handler MUST NOT disarm
    target, set _fade_initial_volume, or call ch.go(target, mtc) — target is
    expected to be already playing. The FadeCue itself is held in the cue
    runner
    by loop_fadeCue until _end_mtc.
    """
    from cuemsutils.tools.CTimecode import CTimecode

    target_id = getattr(target, "id", None)
    motion_id = str(action_cue.id)

    fail = _ready_action_target("fade_action", target, ch)
    if fail is not None:
        return fail

    gradient_client = PLAYER_HANDLER.get_gradient_client()
    if gradient_client is None:
        Logger.error(f"FadeCue {motion_id}: GradientClient not initialised")
        return ActionHandler._action_result(
            "failed",
            "fade_action",
            target_id,
            "GradientClient not initialised",
        )

    if frozen_mtc_ms is not None:
        start_mtc_ms = int(frozen_mtc_ms)
    else:
        start_mtc_ms = mtc.main_tc.milliseconds_rounded

    try:
        payloads = _build_fade_payload(target, action_cue, start_mtc_ms, motion_id)
    except ValueError as exc:
        return ActionHandler._action_result(
            "failed", "fade_action", target_id, str(exc)
        )

    # Dispatch ALL entries before mutating anything. If any OSC send fails the
    # target / FadeCue state must remain unchanged. Failure of one layer aborts
    # the rest — the partial dispatch will be cleared by the next cancel_all
    # (project stop or load).
    for entry in payloads:
        entry_motion_id = entry.pop("motion_id")
        try:
            gradient_client.send_fade(
                motion_id=entry_motion_id,
                osc_host="127.0.0.1",
                osc_port=entry["osc_port"],
                osc_path=entry["osc_path"],
                start_value=entry["start_value"],
                end_value=entry["end_value"],
                start_mtc_ms=entry["start_mtc_ms"],
                duration_ms=entry["duration_ms"],
                curve_type=entry["curve_type"],
                curve_params_json="{}",
            )
        except Exception as exc:
            Logger.error(
                f"FadeCue {motion_id}: OSC dispatch to gradient-motiond"
                f"failed "
                f"(target={target_id} motion_id={entry_motion_id} "
                f"osc={entry['osc_path']}): {exc}"
            )
            return ActionHandler._action_result(
                "failed",
                "fade_action",
                target_id,
                f"OSC dispatch failed: {exc}",
            )

    # Set _start_mtc / _end_mtc on the FadeCue so loop_fadeCue has a real
    # end-mtc to wait on. mtc.main_tc is the live MTC ticking forward.
    framerate = mtc.main_tc.framerate
    action_cue._start_mtc = CTimecode(
        framerate=framerate, start_seconds=start_mtc_ms / 1000.0
    )
    action_cue._end_mtc = (
        action_cue._start_mtc + action_cue.duration.return_in_other_framerate(framerate)
    )

    Logger.info(
        f"FadeCue {motion_id}: dispatched {len(payloads)} start_fade(s) "
        f"target={target_id} target_value={action_cue.target_value} "
        f"duration={action_cue.duration.milliseconds_rounded}ms"
    )
    return ActionHandler._action_result("applied", "fade_action", target_id)


def _build_fade_payload(
    target_cue: Cue, fade_cue: Any, start_mtc_ms: int, motion_id: str
) -> list[dict]:
    """Build FadeCommand body dicts from target_cue + fade_cue.

    Returns a list of dicts (one per OSC endpoint). For AudioCue this is a
    single-element list; for VideoCue, one entry per layer in `_layer_ids`,
    each with its own osc_path and a layer-suffixed `motion_id` so
    gradient-motiond
    can track per-layer completion.

    Field names mirror the C++ parser at gradient-motion-engine
    src/signal/FadeCommand.cpp parseStartFade: end_value (not target_value),
    start_mtc_ms (not start_time). end_value is normalised to OSC scale
    0.0-1.0 from FadeCue.target_value's UI scale 0-100; gradient-motiond
    forwards end_value directly to OSC without further unit conversion.
    """
    from cuemsutils.cues import AudioCue, VideoCue

    curve_type = fade_cue.curve_type
    curve_type_str = (
        curve_type.value if hasattr(curve_type, "value") else str(curve_type)
    )
    duration_ms = fade_cue.duration.milliseconds_rounded
    end_value = float(fade_cue.target_value) / 100.0

    def _entry(osc_path: str, entry_motion_id: str) -> dict:
        return {
            "motion_id": entry_motion_id,
            "osc_port": target_cue._osc.remote_port,
            "osc_path": osc_path,
            "start_value": target_cue._osc.get_value(osc_path),
            "end_value": end_value,
            "start_mtc_ms": start_mtc_ms,
            "duration_ms": duration_ms,
            "curve_type": curve_type_str,
        }

    if isinstance(target_cue, AudioCue):
        return [_entry("/volmaster", motion_id)]

    if isinstance(target_cue, VideoCue):
        layer_ids = getattr(target_cue, "_layer_ids", []) or []
        if not layer_ids:
            raise ValueError(
                f"VideoCue {getattr(target_cue, 'id', None)} has no _layer_ids"
            )
        return [
            _entry(
                f"/videocomposer/layer/{layer_id}/opacity",
                f"{motion_id}_{layer_id}",
            )
            for layer_id in layer_ids
        ]

    raise ValueError(
        f"FadeCue target is not an AudioCue or VideoCue: "
        f"{type(target_cue).__name__}"
    )


_ACTION_HANDLERS: dict[
    str, Callable[[Any, Any, Cue, MtcListener, "float | None"], dict]
] = {
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
