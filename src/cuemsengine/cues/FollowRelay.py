# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Cross-node Auto follow (ClickUp 869fc8ytz).

An Auto follow (post_go='go_at_end') fires its target when the cue ends. Only
the nodes where the cue is local run it, so only they used to fire the follow:
a target that plays on another node never started, silently.

Now the node that owns the source ANNOUNCES the follow instant when the cue
starts (CueHandler, through `announce`), the controller relays it to every
node, and every other node pre-arms what it would start, waits for that
instant on MTC and dispatches it then, as the owner does for its own cues.
If the follow does not happen (the source was stopped, paused, faded out or
started again), the owner sends a CANCEL for the instant it announced.

This class is both halves of the node's side:
- owner: `announce` / `cancel` queue the message to the controller;
- receiver: `on_message` applies a relayed message. It is called from the
  bus receive hook, in bus order, and never waits: the pre-arm, the wait for
  the instant and the stop of a target that must not play run on their own
  threads.

One entry per source cue, in a table with its own lock. Nothing calls into
CueHandler while holding that lock; the only nesting is CueHandler._lock then
the table lock, inside the commit gate `go()` evaluates (`_gate`).

`run_seq` (the controller's run counter) is set from every GO and cleared at
STOP and load, at receipt; a message of another run is refused, and every
dispatch carries the STOP/load epochs read when its announcement arrived.

Design: cuems-RELATIONS Plans/2026-10-05-engine-cross-node-auto-follow.md.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from time import sleep
from typing import Any, Callable

from cuemsutils.cues import ActionCue, DmxCue
from cuemsutils.log import Logger

from .CueHandler import _ArmWalk

# A cancel that reaches a target which has already started stops it only if it
# started less than this ago, and only when the source was stopped or started
# again. The saved test2 runs showed commands delayed 700-800 ms on a loaded
# node, so the limit sits well above that. Ion, 2026-10-05 (D2).
FOLLOW_CANCEL_GRACE_S = 2.0
# Two announcements of the same source within this are the same follow (two
# owners of one cue announce the same instant).
FOLLOW_INSTANT_MATCH_MS = 1.0
# An announcement this late is still honoured (D7), but as an ERROR.
FOLLOW_LATE_ERROR_MS = 10_000.0
# How often the pre-arm re-checks what it would start until the instant. The
# plan said 0.5 s; test2 (2026-10-06) showed a target still playing its earlier
# pass until 0.3 s before the instant fall back to an arm at dispatch, so it
# checks faster. A round that finds everything loaded costs one chain walk.
FOLLOW_PREARM_PERIOD_S = 0.1
# Waiter MTC poll, as _wait_mtc.
FOLLOW_POLL_S = 0.02

_LIVE = ("waiting", "dispatching", "dispatched")


@dataclass(eq=False)
class _Entry:
    source_id: str
    target_id: str
    instant: float
    run_seq: int
    origins: set
    # Read once no STOP or load is pending on this node (None until then).
    arm_epoch: int | None
    stop_epoch: int | None
    project_gen: Any
    # waiting -> dispatching -> dispatched | done; any live state -> cancelled
    state: str = "waiting"
    cue: Any = None
    # When the cue went on stage in a pass still playing when the follow
    # dispatched it again (MINOR-3 of the code review).
    started_before: float | None = None
    gen: int | None = None
    disarm_epoch: int | None = None
    armed_at: float | None = None
    lookahead_done: set = field(default_factory=set)


class FollowRelay:
    def __init__(
        self,
        cue_handler,
        node_id: str,
        send: Callable[[dict], None],
        get_script: Callable[[], Any],
        get_mtc: Callable[[], Any],
        get_project_gen: Callable[[], Any],
        first_local: Callable[[Any], Any],
        spawn: Callable[..., None] | None = None,
        sleep: Callable[[float], None] = sleep,
    ):
        self._ch = cue_handler
        self.node_id = node_id
        self._send = send
        self._get_script = get_script
        self._get_mtc = get_mtc
        self._get_project_gen = get_project_gen
        self._first_local = first_local
        self._spawn = spawn or self._spawn_thread
        self._sleep = sleep
        self._prearm_sleep = sleep
        self._lock = threading.Lock()
        self._table: dict[str, _Entry] = {}
        self._run_seq: int | None = None
        self._no_run_logged = False
        # STOP/load commands received (receive hook) and applied (after the
        # node ran them). In between, this node's epochs still belong to the
        # run that is ending: nothing is announced and no epoch is read.
        self._stops_received = 0
        self._stops_applied = 0

    # ------------------------------------------------------------------
    # The run
    # ------------------------------------------------------------------

    @property
    def run_seq(self) -> int | None:
        return self._run_seq

    @property
    def stop_pending(self) -> bool:
        """A STOP or a load was received and has not run yet on this node."""
        return self._stops_received > self._stops_applied

    def stop_applied(self) -> None:
        """The node has run a STOP or a load (or refused it)."""
        with self._lock:
            self._stops_applied += 1

    def begin_run(self, value) -> None:
        """At a GO's receipt. Same run: keep the table. New run: empty it.
        A GO without an integer run_seq comes from a controller that does
        not relay follows: nothing is announced until one that does."""
        seq = value.get("run_seq") if isinstance(value, dict) else None
        if type(seq) is not int:
            seq = None
        with self._lock:
            if seq == self._run_seq:
                return
            self._run_seq = seq
            dropped = len(self._table)
            self._table.clear()
        if seq is None:
            Logger.debug("GO carries no run_seq: cross-node follows are off")
        else:
            Logger.debug(f"Follow run {seq} (dropped {dropped} pending)")

    def end_run(self, why: str) -> None:
        """At a STOP's or a load's receipt: every pending follow is gone."""
        with self._lock:
            self._stops_received += 1
            self._run_seq = None
            dropped = sum(e.state in _LIVE for e in self._table.values())
            self._table.clear()
        if dropped:
            Logger.info(f"Follow: {why} dropped {dropped} pending follow(s)")

    # ------------------------------------------------------------------
    # Owner: queue the message (never waits)
    # ------------------------------------------------------------------

    def announce(self, cue, instant_ms: float, run_seq: int) -> None:
        self._emit("announce", cue, instant_ms, run_seq)

    def cancel(self, cue, instant_ms: float, run_seq: int, reason: str) -> None:
        self._emit("cancel", cue, instant_ms, run_seq, reason)

    def _emit(self, op, cue, instant_ms, run_seq, reason=None) -> None:
        target = getattr(cue, "_target_object", None)
        data = {
            "op": op,
            "origin": self.node_id,
            "run_seq": run_seq,
            "source": str(cue.id),
            "target": str(getattr(target, "id", "")),
            "seed_ms": float(instant_ms),
        }
        if reason is not None:
            data["reason"] = reason
        try:
            self._send(data)
        except Exception as e:
            Logger.error(
                f"Follow: could not send {op} for {data['source']} -> "
                f"{data['target']} at {instant_ms:.0f}ms: {e}"
            )
            return
        Logger.info(
            f"Follow: {op} queued for {data['source']} -> {data['target']} at "
            f"{instant_ms:.0f}ms" + (f" ({reason})" if reason else "")
        )

    def warn_no_run(self) -> None:
        """The owner had a follow to announce but no run_seq: the controller
        does not relay follows (older engine). Said once."""
        if not self._no_run_logged:
            self._no_run_logged = True
            Logger.info(
                "Follow: the controller sent no run_seq with its GO; Auto "
                "follows into cues on other nodes are not announced"
            )

    # ------------------------------------------------------------------
    # Receiver: apply a relayed message (receive hook; never waits)
    # ------------------------------------------------------------------

    def on_message(self, data) -> None:
        if not isinstance(data, dict):
            Logger.warning(f"Follow: ignoring a malformed message {data!r}")
            return
        op = data.get("op")
        if op == "announce":
            self._on_announce(data)
        elif op == "cancel":
            self._on_cancel(data)
        else:
            Logger.warning(f"Follow: ignoring a message with op {op!r}")

    def _on_announce(self, data: dict) -> None:
        source_id = str(data.get("source"))
        target_id = str(data.get("target"))
        origin = data.get("origin")
        what = f"{source_id} -> {target_id} from {origin}"
        if origin == self.node_id:
            return
        script = self._get_script()
        mtc = self._get_mtc()
        source = script.find(source_id) if script is not None else None
        target = script.find(target_id) if script is not None else None
        if source is not None and getattr(source, "_local", False):
            Logger.debug(f"Follow: {what} ignored, the source is local here")
            return
        try:
            instant = float(data.get("seed_ms"))
        except (TypeError, ValueError):
            instant = None
        refuse = None
        if script is None or mtc is None:
            refuse = "no project or no timecode on this node"
        elif source is None or target is None:
            refuse = "cue not in the loaded project"
        elif instant is None:
            refuse = "no instant"
        elif self._run_seq is None or data.get("run_seq") != self._run_seq:
            refuse = (
                f"not part of this node's run (run_seq {data.get('run_seq')}, "
                f"here {self._run_seq})"
            )
        if refuse:
            Logger.warning(f"Follow: refusing announce {what}: {refuse}")
            return

        # Read before taking the table lock: nothing calls into CueHandler or
        # the engine while holding it. While a STOP or a load is pending here
        # the epochs still belong to the run that is ending: read them later.
        arm_epoch = stop_epoch = None
        if not self.stop_pending:
            arm_epoch = self._ch.arm_epoch()
            stop_epoch = self._ch._last_stop_chain_epoch
        project_gen = self._get_project_gen()
        with self._lock:
            old = self._table.get(source_id)
            if (
                old is not None
                and old.state in _LIVE
                and old.run_seq == self._run_seq
                and abs(old.instant - instant) <= FOLLOW_INSTANT_MATCH_MS
            ):
                old.origins.add(origin)
                return
            entry = _Entry(
                source_id=source_id,
                target_id=target_id,
                instant=instant,
                run_seq=self._run_seq,
                origins={origin},
                arm_epoch=arm_epoch,
                stop_epoch=stop_epoch,
                project_gen=project_gen,
            )
            self._table[source_id] = entry

        now = mtc.main_tc.milliseconds_exact
        late = now - instant
        if late > FOLLOW_LATE_ERROR_MS:
            Logger.error(
                f"Follow: announce {what} arrived {late:.0f}ms after its "
                "instant; starting it anyway, in sync with its beginning cut"
            )
        elif late > 0:
            Logger.warning(
                f"Follow: announce {what} arrived {late:.0f}ms after its "
                "instant; starting it at once"
            )
        Logger.info(f"Follow: received announce {what} at {instant:.0f}ms")
        self._spawn(f"FollowPreArm:{source_id}", self._prearm, entry)
        self._spawn(f"FollowWait:{source_id}", self._wait_and_dispatch, entry)

    def _on_cancel(self, data: dict) -> None:
        source_id = str(data.get("source"))
        origin = data.get("origin")
        reason = data.get("reason")
        if origin == self.node_id:
            return
        try:
            instant = float(data.get("seed_ms"))
        except (TypeError, ValueError):
            instant = None
        what = f"{source_id} at {instant} from {origin} ({reason})"
        with self._lock:
            e = self._table.get(source_id)
            if (
                e is None
                or instant is None
                or abs(e.instant - instant) > FOLLOW_INSTANT_MATCH_MS
                or e.state not in _LIVE
                or data.get("run_seq") != e.run_seq
            ):
                Logger.debug(f"Follow: cancel {what}: nothing pending")
                return
            if reason == "error" and origin in e.origins and len(e.origins) > 1:
                e.origins.discard(origin)
                Logger.info(f"Follow: cancel {what}: other owners remain")
                return
            state = e.state
            e.state = "cancelled"
            dispatched = (e.cue, e.gen, e.disarm_epoch, e.armed_at, e.started_before)
        if state != "dispatched":
            Logger.info(f"Follow: cancel {what} applied before the dispatch")
            return
        self._spawn(
            f"FollowStop:{source_id}", self._stop_dispatched, what, reason, *dispatched
        )

    # ------------------------------------------------------------------
    # Receiver threads
    # ------------------------------------------------------------------

    def _is_current(self, e: _Entry) -> bool:
        return (
            self._table.get(e.source_id) is e
            and e.state in _LIVE
            and self._run_seq == e.run_seq
        )

    def _current(self, e: _Entry) -> bool:
        with self._lock:
            return self._is_current(e)

    def _epochs_ready(self, e: _Entry) -> bool:
        """Read the STOP/load epochs for an entry that arrived while a STOP or
        a load was pending, once it has run. False while still pending."""
        if e.arm_epoch is not None:
            return True
        if self.stop_pending:
            return False
        arm_epoch = self._ch.arm_epoch()
        stop_epoch = self._ch._last_stop_chain_epoch
        with self._lock:
            if e.arm_epoch is None:
                e.arm_epoch, e.stop_epoch = arm_epoch, stop_epoch
        return True

    def _prearm(self, e: _Entry) -> None:
        """Until the instant, arm what this node would start, every
        FOLLOW_PREARM_PERIOD_S: `arm()` skips what is loaded, so each round
        only arms what became unloaded since -- a cue whose earlier pass has
        just ended, or a target enabled meanwhile."""

        def should_continue():
            return (
                self._current(e)
                and self._get_project_gen() == e.project_gen
                and self._ch.arm_epoch() == e.arm_epoch
            )

        mtc = self._get_mtc()
        try:
            while self._current(e) and not self._epochs_ready(e):
                if mtc is None or mtc.main_tc.milliseconds_exact >= e.instant:
                    return
                self._prearm_sleep(FOLLOW_PREARM_PERIOD_S)
            while should_continue():
                script = self._get_script()
                target = script.find(e.target_id) if script is not None else None
                cue = self._first_local(target) if target is not None else None
                if cue is not None:
                    self._arm_round(e, cue, should_continue)
                if mtc is None or mtc.main_tc.milliseconds_exact >= e.instant:
                    return
                self._prearm_sleep(FOLLOW_PREARM_PERIOD_S)
        except Exception as ex:
            Logger.error(f"Follow: pre-arm for {e.source_id} failed: {ex}")

    def _arm_round(self, e: _Entry, cue, should_continue) -> None:
        walk = _ArmWalk(should_continue=should_continue, epoch=e.arm_epoch)
        if not getattr(cue, "loaded", False):
            self._ch.arm(cue, init=True, walk=walk)
        # arm() reaches an action's target only when it arms the action itself,
        # and arm() on a loaded, disabled cue disarms it even while it plays.
        if isinstance(cue, ActionCue) and cue.action_type in ("play", "fade_action"):
            at = getattr(cue, "_action_target_object", None)
            if (
                at is not None
                and getattr(at, "enabled", False)
                and getattr(at, "_local", False)
                and not getattr(at, "loaded", False)
            ):
                self._ch.arm(at, init=True, walk=walk)
        # The lookahead once per cue, so its depth WARNING is not repeated.
        if id(cue) not in e.lookahead_done and getattr(cue, "loaded", False):
            e.lookahead_done.add(id(cue))
            self._ch._arm_ahead(
                cue, should_continue=should_continue, arm_epoch=e.arm_epoch
            )

    def _wait_and_dispatch(self, e: _Entry) -> None:
        mtc = self._get_mtc()
        script = self._get_script()
        if mtc is None or script is None:
            return
        source = script.find(e.source_id)
        target = script.find(e.target_id)
        post_ms = 0.0
        try:
            post_ms = source.postwait.milliseconds_exact
        except Exception:
            pass
        check_ms = e.instant - post_ms
        snapshot = None
        while True:
            if not self._current(e):
                return
            now = mtc.main_tc.milliseconds_exact
            if post_ms > 0 and snapshot is None and now >= check_ms:
                c = self._first_local(target)
                snapshot = (c, getattr(c, "_go_generation", 0))
            if now >= e.instant and self._epochs_ready(e):
                break
            self._sleep(FOLLOW_POLL_S)

        # The yield: a manual GO of the target during the source's postwait
        # already started it; the owner does not fire it again either.
        if snapshot is not None and snapshot[0] is not None:
            c = self._first_local(target)
            if c is snapshot[0] and getattr(c, "_go_generation", 0) != snapshot[1]:
                Logger.info(
                    f"Follow: {e.source_id} -> {e.target_id} yielded: "
                    f"{c.id} was started by a newer GO"
                )
                self._set_state(e, "done")
                return

        with self._lock:
            if not self._is_current(e):
                return
            e.state = "dispatching"
        try:
            thread = self._ch.go_from(
                target,
                mtc,
                e.instant,
                arm_epoch=e.arm_epoch,
                require_stop_epoch=e.stop_epoch,
                commit_gate=lambda cue, gen: self._gate(e, cue, gen),
            )
        except Exception as ex:
            Logger.error(
                f"Follow: dispatch of {e.source_id} -> {e.target_id} failed: {ex}"
            )
            self._set_state(e, "done", only_from="dispatching")
            return
        with self._lock:
            if e.state == "dispatching":
                e.state = "done"
                Logger.info(
                    f"Follow: {e.source_id} -> {e.target_id}: not dispatched "
                    "here (nothing local to start, or refused for a STOP)"
                )
            elif e.state == "dispatched":
                Logger.info(
                    f"Follow: dispatched {getattr(e.cue, 'id', '?')} for "
                    f"{e.source_id} at {e.instant:.0f}ms"
                    + ("" if thread is not None else " (refused)")
                )

    def _gate(self, e: _Entry, cue, gen: int) -> bool:
        """Evaluated by go() inside its commit section (CueHandler._lock held).
        Refuses an entry that was cancelled, replaced or dropped (a STOP or a
        load emptied the table), or that belongs to another run."""
        with self._lock:
            if not self._is_current(e) or e.state != "dispatching":
                return False
            e.cue = cue
            e.gen = gen
            e.disarm_epoch = self._ch._disarm_epoch
            e.armed_at = getattr(cue, "_armed_at", None)
            if getattr(cue, "_playing", False) and getattr(cue, "_revealed", False):
                # Still on stage from an earlier pass: a cancel must treat it
                # as started (go() is about to reset its reveal stamp).
                e.started_before = getattr(cue, "_revealed_at", None)
            e.state = "dispatched"
            return True

    def _set_state(self, e: _Entry, state: str, only_from: str | None = None):
        with self._lock:
            if only_from is None or e.state == only_from:
                e.state = state

    def _stop_dispatched(
        self, what, reason, cue, gen, disarm_epoch, armed_at, started_before
    ):
        may_cut = reason in ("stop", "restart")
        try:
            outcome, age = self._ch.stop_dispatched_follow(
                cue,
                gen,
                disarm_epoch,
                armed_at,
                may_cut=may_cut,
                grace_s=FOLLOW_CANCEL_GRACE_S,
                started_before=started_before,
            )
        except Exception as ex:
            Logger.error(f"Follow: cancel {what}: stopping {cue.id} failed: {ex}")
            return
        acted = isinstance(cue, (ActionCue, DmxCue)) and age is not None
        if outcome == "owned":
            Logger.info(f"Follow: cancel {what}: {cue.id} belongs to a newer GO")
        elif outcome == "stopped" and age is None:
            Logger.info(f"Follow: cancel {what}: stopped {cue.id} before it started")
        elif outcome == "stopped":
            Logger.warning(
                f"Follow: cancel {what}: stopped {cue.id} {age:.2f}s after it "
                "started"
            )
        else:
            Logger.error(
                f"Follow: cancel {what} arrived "
                + (f"{age:.2f}s " if age is not None else "")
                + f"after {cue.id} started; it was left playing"
            )
        if acted and outcome != "owned":
            Logger.error(
                f"Follow: {type(cue).__name__} {cue.id} had already acted (a DMX "
                "scene sent, an action executed); that cannot be undone"
            )

    @staticmethod
    def _spawn_thread(name: str, fn, *args) -> None:
        threading.Thread(target=fn, args=args, name=name, daemon=True).start()
