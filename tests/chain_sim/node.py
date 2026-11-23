# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""One simulated node of the AC2 harness: a subprocess with its own engine.

Started by `driver.py` with the multiprocessing "spawn" context, so this process
has its own `CUE_HANDLER`, `ACTION_HANDLER` (one object per process,
`cues/ActionHandler.py:883`) and script tree. The engine code is the real one
(`CueHandler`, `ActionHandler`, `FollowRelay`, the `NodeEngine` GO / toggle /
pointer paths); only what talks to a player, a socket or the wall clock is
replaced:

- **Virtual time.** The node's MTC is a fake whose value the driver sets
  (`advance`). Every `sleep` / `monotonic` an engine module imported from `time`
  is replaced by the virtual clock's, and `CueHandler._wait_mtc` waits for its
  target on that clock (plus the fixture's `late` for that cue on this node)
  instead of polling every 20 ms. After every message the node *settles*: it
  waits until every engine thread is parked on the virtual clock (or has been
  quiet for `GRACE_S` of wall time), then tells the driver the earliest instant
  one of them waits for.
- **Fake players.** `run_cue` sets the cue up (its start, `_reveal_ready`) and
  records a DMX scene send; `reveal_cue` executes an ActionCue's action and does
  nothing else; `loop_cue` holds a cue until `start + body`; an AudioCue has a
  selfgate player (its commit is real, `START_GATE` is faked); a VideoCue's
  `visible_at` commit is faked with the same flags. The arm is faked: it honours
  the fixture's `arm_ms` (the arm takes that long on this node) and `arm_fail`.
- **The bus.** The driver delivers each command as the NNG receiver does: the
  receive hook `NodeEngine._on_command_received(name, value, sent_ms=…)` on this
  process's main thread, in bus order, then (if not consumed) the command on a
  thread of its own under `_command_lock`. What the node sends (a follow
  announcement or cancel, a `stop_project` STATUS) goes back to the driver.

The patch points name today's engine internals; Step 2 of the plan may have to
move some of them as the engine changes (they are all in `_install_fakes`).
Never run on casas (house rule A12): the suite runs on a rig.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
import traceback
import uuid
from types import SimpleNamespace

GRACE_S = 0.5  # a thread that neither parks nor logs for this long is quiet
SETTLE_MAX_S = 20.0  # a settle that never ends is reported, not waited for
MIN_SLEEP_MS = 1.0  # a sleep(0) would spin: every virtual sleep is >= 1 ms
REAL_SLEEP = time.sleep
REAL_MONOTONIC = time.monotonic
NS = uuid.UUID("6f1d3c52-8a0e-4b8e-9d55-1a3f00000000")  # 1amfwm7jnqf's namespace


def cue_id(name: str) -> str:
    """The cue id of a model cue name: the same in every process."""
    return str(uuid.uuid5(NS, name))


# ---------------------------------------------------------------------------
# virtual time
# ---------------------------------------------------------------------------
class VClock:
    """The node's MTC position, in ms, set only by the driver."""

    def __init__(self, now_ms: float):
        self.now = float(now_ms)
        self.cv = threading.Condition()
        self.waits: dict[int, float] = {}
        self.activity = 0
        self.main = threading.get_ident()

    def monotonic(self) -> float:
        return self.now / 1000.0

    def sleep(self, seconds) -> None:
        if threading.get_ident() == self.main:
            # The receive hook runs here and must not block; a sleep on this
            # thread would wait for an advance only this thread can deliver.
            return
        try:
            ms = float(seconds) * 1000.0
        except (TypeError, ValueError):
            ms = 0.0
        self.wait_until(self.now + max(ms, MIN_SLEEP_MS))

    def wait_until(self, wake_ms: float, abort=None) -> None:
        me = threading.get_ident()
        with self.cv:
            self.activity += 1
            while self.now < wake_ms and not (abort is not None and abort()):
                self.waits[me] = wake_ms
                self.cv.wait()
            self.waits.pop(me, None)
            self.activity += 1

    def set(self, now_ms: float) -> None:
        with self.cv:
            self.now = max(self.now, float(now_ms))
            for ident, wake in list(self.waits.items()):
                if wake <= self.now:
                    del self.waits[ident]
            self.activity += 1
            self.cv.notify_all()

    def kick(self) -> None:
        """Something changed outside the clock: let every waiter re-check."""
        with self.cv:
            self.waits.clear()
            self.activity += 1
            self.cv.notify_all()

    def bump(self) -> None:
        with self.cv:
            self.activity += 1

    def next_wake(self):
        with self.cv:
            return min(self.waits.values()) if self.waits else None

    def settle(self) -> list:
        """Wait until every engine thread is parked on this clock. Returns the
        names of threads that were quiet but not parked (empty when clean)."""
        t0 = REAL_MONOTONIC()
        last, quiet_since = None, REAL_MONOTONIC()
        while True:
            alive = [
                t
                for t in threading.enumerate()
                if t.ident != self.main and t.is_alive()
            ]
            with self.cv:
                parked, act = set(self.waits), self.activity
            if all(t.ident in parked for t in alive):
                REAL_SLEEP(0.001)
                with self.cv:
                    if self.activity == act and set(self.waits) == parked:
                        return []
            if act != last:
                last, quiet_since = act, REAL_MONOTONIC()
            elif REAL_MONOTONIC() - quiet_since > GRACE_S:
                return [t.name for t in alive if t.ident not in parked]
            if REAL_MONOTONIC() - t0 > SETTLE_MAX_S:
                return ["SETTLE TIMEOUT"] + [
                    t.name for t in alive if t.ident not in parked
                ]
            REAL_SLEEP(0.001)


class _Tc:
    """A timecode reading: what the engine reads off `_start_mtc` / `_end_mtc`."""

    framerate = 25.0

    def __init__(self, ms: float):
        self.milliseconds_exact = float(ms)

    @property
    def milliseconds_rounded(self) -> int:
        return int(round(self.milliseconds_exact))

    @property
    def frames(self) -> int:
        return int(self.milliseconds_exact / 40.0)


class FakeMtc:
    """MtcListener as the engine reads it, on the virtual clock."""

    def __init__(self, clock: VClock):
        self._clock = clock

    @property
    def main_tc(self):
        return _Tc(self._clock.now)

    def interpolated_ms(self, now=None) -> float:
        return self._clock.now

    def is_receiving(self, max_age_s: float = 0.5) -> bool:
        return True

    def start(self):
        pass


# ---------------------------------------------------------------------------
# the script tree
# ---------------------------------------------------------------------------
def _cue_class(kind: str):
    from cuemsutils.cues import ActionCue, AudioCue, CueList, DmxCue, VideoCue

    if kind == "fade":
        try:
            from cuemsutils.cues.FadeCue import FadeCue

            return FadeCue
        except ImportError:  # an older cuems-utils: the closest is an ActionCue
            return ActionCue
    return {
        "audio": AudioCue,
        "video": VideoCue,
        "dmx": DmxCue,
        "action": ActionCue,
        "list": CueList,
    }[kind]


def _set(cue, key: str, value) -> None:
    """Through the property when it takes the value, else into the dict."""
    try:
        setattr(cue, key, value)
    except Exception:
        dict.__setitem__(cue, key, value)


def _ms(tc) -> float:
    exact = getattr(tc, "milliseconds_exact", None)
    return float(exact if exact is not None else tc.milliseconds)


def timecode(ms: float):
    """A CTimecode that reads back exactly `ms` (some cuems-utils builds read
    `start_seconds=5.0` back as 4999 ms: the next ms is tried then)."""
    from cuemsutils.tools.CTimecode import CTimecode

    if not ms:
        return CTimecode(start_seconds=0)
    total = int(round(ms))
    text = (
        f"{total // 3_600_000:02d}:{total // 60_000 % 60:02d}:"
        f"{total // 1000 % 60:02d}.{total % 1000:03d}"
    )
    tries = [lambda: CTimecode(start_timecode=text)]
    tries += [
        lambda k=k: CTimecode(start_seconds=(ms + k / 10.0) / 1000.0)
        for k in range(0, 20)
    ]
    for make in tries:
        try:
            tc = make()
        except Exception:
            continue
        if abs(_ms(tc) - ms) < 0.5:
            return tc
    raise ValueError(f"no CTimecode reads back {ms} ms")


def _make_cue(spec: dict, node: str):
    from cuemsutils.cues.Cue import Cue

    cls = _cue_class(spec["kind"])
    cue = cls.__new__(cls)
    Cue.__init__(cue)  # the base attributes: _target_object, _start_mtc, …
    _set(cue, "id", cue_id(spec["name"]))
    _set(cue, "name", spec["name"])
    _set(cue, "enabled", bool(spec["enabled"]))
    _set(cue, "post_go", spec["post_go"])
    _set(cue, "loop", 1)
    _set(cue, "prewait", timecode(spec["pre"]))
    _set(cue, "postwait", timecode(spec["post"]))
    owners = spec["node"].split("+")
    cue._local = spec["node"] == "*" or node in owners
    cue._sim_name = spec["name"]
    cue._sim_body_ms = float(spec["body"])
    cue._sim_owners = owners
    cue.loaded = False
    if len(owners) > 1:
        # cuems-utils MediaCue.get_all_output_names: an output on each owner.
        cue.get_all_output_names = lambda o=tuple(owners): list(o)
    if spec["kind"] == "action":
        _set(cue, "action_type", spec["action"])
        cue._action_target_object = None
    if spec["kind"] == "fade":
        try:
            _set(cue, "action_type", "fade_action")
        except Exception:
            pass
        cue._action_target_object = None
    return cue


class SimScript:
    """What NodeEngine reads of a loaded script."""

    def __init__(self, specs: list, node: str):
        from cuemsutils.cues import CueList

        self.name = "chain-sim"
        self.by_name: dict = {}
        top = []
        for spec in specs:
            cue = _make_cue(spec, node)
            self.by_name[spec["name"]] = cue
            top.append(cue)
            kids = []
            for kspec in spec.get("children") or []:
                kid = _make_cue(kspec, node)
                kid._sim_parent = spec["name"]
                kid._target_object = None
                _set(kid, "target", None)  # as a loaded script has it
                self.by_name[kspec["name"]] = kid
                kids.append(kid)
            if kids:
                _set(cue, "contents", kids)
        for i, spec in enumerate(specs):
            cue = self.by_name[spec["name"]]
            nxt = spec.get("link") or (
                specs[i + 1]["name"] if i + 1 < len(specs) else None
            )
            cue._target_object = self.by_name[nxt] if nxt else None
            _set(cue, "target", cue_id(nxt) if nxt else None)
            if spec["kind"] == "action" and spec.get("target"):
                cue._action_target_object = self.by_name[spec["target"]]
                try:
                    _set(cue, "action_target", cue_id(spec["target"]))
                except Exception:
                    pass
        self.cuelist = CueList.__new__(CueList)
        from cuemsutils.cues.Cue import Cue

        Cue.__init__(self.cuelist)
        _set(self.cuelist, "contents", top)
        self.by_id = {str(c.id): c for c in self.by_name.values()}

    def find(self, cid):
        return self.by_id.get(str(cid))


# ---------------------------------------------------------------------------
# the node
# ---------------------------------------------------------------------------
class SimNode:
    def __init__(self, init: dict):
        self.name = init["node"]
        self.scenario = init["scenario"]
        perturb = (self.scenario.get("perturb") or {}).get(self.name) or {}
        self.late = {k: float(v) for k, v in (perturb.get("late") or {}).items()}
        self.arm_ms = {k: float(v) for k, v in (perturb.get("arm_ms") or {}).items()}
        self.arm_fail = set(perturb.get("arm_fail") or ())
        self.rules = self.scenario.get("rules") or {}
        self.clock = VClock(init["start_ms"])
        self.mtc = FakeMtc(self.clock)
        self.journal: list = []
        self.outbox: list = []
        self.standby: list = []
        self.cmd_threads: list = []
        self._check_api()
        self._install_logging()
        self.script = SimScript(self.scenario["script"], self.name)
        self._install_fakes()
        self._build_engine()
        self._load()

    # -- the engine API this harness needs (the plan's Step 2) --------------
    @staticmethod
    def _check_api():
        missing = []
        try:
            import cuemsengine.cues.chain_pass  # noqa: F401
        except ImportError as e:
            missing.append(f"cuemsengine.cues.chain_pass ({e})")
        from cuemsengine.cues.CueHandler import CueHandler

        for attr in ("_advance_mode", "retake", "cancel_child"):
            if not hasattr(CueHandler, attr):
                missing.append(f"CueHandler.{attr}")
        if missing:
            raise RuntimeError(
                "the engine lacks the API of plan 1amfwm7jnqf (Step 2 not landed): "
                + ", ".join(missing)
            )

    def _install_logging(self):
        """Every Logger line into this node's journal, with its MTC; nothing
        to stdout or syslog. cuemsutils.log keeps one logger per module
        (main_logger, cached): Logger.log is replaced, and the cached
        loggers lose their handlers."""
        import cuemsutils.log as cl

        clock, journal = self.clock, self.journal

        def log(level, message, **kwargs):
            journal.append((clock.now, logging.getLevelName(level), str(message)))
            clock.bump()

        cl.Logger.log = staticmethod(log)
        quiet = logging.NullHandler()

        def strip(adapter):
            base = getattr(adapter, "logger", adapter)
            for h in list(base.handlers):
                base.removeHandler(h)
            base.addHandler(quiet)
            base.propagate = False
            return adapter

        for adapter in list(cl._logger_cache.values()):
            strip(adapter)
        original = cl.main_logger

        def main_logger(*a, **k):
            return strip(original(*a, **k))

        cl.main_logger = main_logger

    # -- fakes ---------------------------------------------------------------
    def _install_fakes(self):
        import cuemsengine.cues.CueHandler as CH
        from cuemsengine.cues import loop_mode
        from cuemsengine.players.PlayerHandler import PLAYER_HANDLER
        from cuemsengine.players.StartGate import START_GATE

        clock, me = self.clock, self

        # 1. the wall clock of every engine module: virtual
        shim = SimpleNamespace(
            **{k: getattr(time, k) for k in dir(time) if not k.startswith("__")}
        )
        shim.sleep, shim.monotonic = clock.sleep, clock.monotonic
        for name, mod in list(sys.modules.items()):
            if not name.startswith("cuemsengine") or mod is None:
                continue
            if getattr(mod, "sleep", None) is time.sleep:
                mod.sleep = clock.sleep
            if getattr(mod, "monotonic", None) is time.monotonic:
                mod.monotonic = clock.monotonic
            if getattr(mod, "time", None) is time:
                mod.time = shim

        # 2. the MTC wait: on the virtual clock, `late` ms late for this cue
        def wait_mtc(self_, cue, mtc, target_ms, go_gen=0, clock=None, **kw):
            late = me.late.get(getattr(cue, "_sim_name", None), 0.0)

            def gone():
                return getattr(cue, "_stop_requested", False) or (
                    getattr(cue, "_go_generation", 0) != go_gen
                )

            me.clock.wait_until(float(target_ms) + late, abort=gone)
            return "stopped" if gone() else "reached"

        CH.CueHandler._wait_mtc = wait_mtc
        # The body of a cue that has no player here (a failed arm keeps it).
        CH.CueHandler._body_ms = staticmethod(
            lambda cue: float(getattr(cue, "_sim_body_ms", 0.0))
        )
        # The advance mode: every production chain is sequential; the
        # fixture's parallel rows switch the one switch the engine has.
        mode = self.rules.get("mode") or "sequential"
        CH.CueHandler._advance_mode = staticmethod(lambda cue, m=mode: m)

        # 3. players
        selfgate = getattr(loop_mode, "CAPS_SELFGATE", "selfgate")
        audio_player = SimpleNamespace(caps=frozenset({selfgate}), sim=True)

        def fake_audio_player(cue):
            return audio_player if getattr(cue, "_local", False) else None

        PLAYER_HANDLER.audio_player = fake_audio_player
        # D25: the DMX player's capability to cancel a scene already sent. The
        # engine's check is Step 2's; the harness exposes the fact here.
        cancel = bool(self.rules.get("dmx_cancel"))
        PLAYER_HANDLER.dmx_can_cancel = lambda: cancel
        PLAYER_HANDLER.cancel_dmx_scene = lambda cue: None
        START_GATE.commit_follow = lambda cue, player, client, gen: True
        START_GATE.cancel = lambda *a, **k: "sim"

        def run_cue(cue, mtc, frozen_mtc_ms=None):
            start = float(frozen_mtc_ms) if frozen_mtc_ms is not None else clock.now
            from cuemsutils.cues import AudioCue, VideoCue

            for c in (cue, getattr(cue, "_marked_child", None)):
                if c is None:
                    continue
                c._start_mtc = _Tc(start)
                c._reveal_ready = True
                c._osc = object()
                if isinstance(c, (AudioCue, VideoCue)):
                    # the real setup puts the media's end there (run_cue)
                    c._end_mtc = _Tc(start + getattr(c, "_sim_body_ms", 0.0))
            from cuemsutils.cues import DmxCue

            if isinstance(cue, DmxCue):
                from cuemsutils.log import Logger

                Logger.info(f"SIM: DMX scene sent to the player for cue {cue.id}")

        def reveal_cue(cue, mtc, frozen_mtc_ms=None):
            from cuemsutils.cues import ActionCue

            if isinstance(cue, ActionCue) and getattr(cue, "action_type", None) not in (
                None,
                "fade_action",
            ):
                from cuemsengine.cues.ActionHandler import ACTION_HANDLER

                ACTION_HANDLER.execute_action(cue, mtc, frozen_mtc_ms)

        def loop_cue(cue, mtc, *a, **k):
            from cuemsutils.cues import ActionCue, CueList

            start_tc = getattr(cue, "_start_mtc", None)
            start = start_tc.milliseconds_exact if start_tc is not None else clock.now
            body = getattr(cue, "_sim_body_ms", 0.0)
            if isinstance(cue, CueList):
                kid = getattr(cue, "_marked_child", None)
                body = getattr(kid, "_sim_body_ms", 0.0) if kid is not None else 0.0
            elif isinstance(cue, ActionCue) and not hasattr(cue, "_sim_body_ms"):
                body = 0.0
            end = start + body
            gen = getattr(cue, "_go_generation", 0)
            CH.CUE_HANDLER._wait_mtc(cue, mtc, end, gen)
            cue._end_mtc = _Tc(end)

        CH.run_cue = run_cue
        CH.reveal_cue = reveal_cue
        CH.loop_cue = loop_cue
        CH.blank_cue = lambda *a, **k: None

        def commit_visible_at(self_, cue, target, go_gen, mtc=None):
            with self_._lock:
                if getattr(cue, "_stop_requested", False) or (
                    getattr(cue, "_go_generation", 0) != go_gen
                ):
                    return False
                cue._follow_gen = go_gen
                target._follow_committed = True
            from cuemsutils.log import Logger

            Logger.info(f"follow commit: video cue {str(target.id)[:8]} (sim)")
            return True

        CH.CueHandler._commit_visible_at = commit_visible_at
        CH.CueHandler._cancel_visible_at_locked = lambda self_, cue: False

        # 4. the arm: arm_ms / arm_fail of this node
        ch = CH.CUE_HANDLER

        def arm(cue, init=False, epoch=None, wait_report=None, *a, **k):
            from cuemsutils.log import Logger

            if cue is None or not getattr(cue, "_local", False):
                return
            name = getattr(cue, "_sim_name", None)
            if name in me.arm_fail:
                Logger.error(f"SIM: arm of {cue.id} failed")
                return
            if getattr(cue, "loaded", False) or not getattr(cue, "enabled", False):
                return
            ms = me.arm_ms.get(name, 0.0)
            if ms:
                clock.sleep(ms / 1000.0)
            cue.loaded = True
            if not ch.find_armed_cue(cue):
                ch.add_armed_cue(cue)

        def disarm(cue, reason="unspecified"):
            cue.loaded = False
            try:
                ch.remove_armed_cue(cue)
            except Exception:
                pass
            return True

        ch.arm = arm
        ch.disarm = disarm
        ch._arm_ahead = lambda *a, **k: None

    # -- the engine shell -----------------------------------------------------
    def _build_engine(self):
        import cuemsengine.cues.chain_pass as chain_pass
        from cuemsengine.cues.ActionHandler import ACTION_HANDLER
        from cuemsengine.cues.CueHandler import CUE_HANDLER
        from cuemsengine.cues.FollowRelay import FollowRelay
        from cuemsengine.NodeEngine import NodeEngine

        me, clock = self, self.clock
        comms = SimpleNamespace(
            node_id=self.name,
            add_cue=lambda *a, **k: None,
            remove_cue=lambda *a, **k: None,
            update_nextcue=lambda *a, **k: None,
            send_operation=lambda *a, **k: None,
            send_operation_nowait=lambda *a, **k: None,
        )
        CUE_HANDLER.communications_thread = comms
        CUE_HANDLER.out_latency_ms = 0.0
        if hasattr(chain_pass, "StepOrder"):
            CUE_HANDLER._steps = chain_pass.StepOrder(
                clock=clock.monotonic, sleep=clock.sleep
            )
        if getattr(ACTION_HANDLER, "_cue_handler", None) is None:
            ACTION_HANDLER._cue_handler = CUE_HANDLER

        node = object.__new__(NodeEngine)
        node.script = self.script
        node.with_mtc = True
        node.mtc_listener = self.mtc
        node.ongoing_cue = None
        node.next_cue_pointer = self.script.cuelist.contents[0]
        node.go_offset = None
        node._project_generation = 1
        node._command_lock = threading.Lock()
        node._go_what = []
        node._ui_seq = 0
        node.cm = SimpleNamespace(node_uuid=self.name, node_conf={"uuid": self.name})
        node.set_status = lambda *a, **k: None
        node.get_status = lambda *a, **k: None
        node._broadcast_nextcue = lambda *a, **k: None
        node._notify_cue_enabled = lambda *a, **k: None
        node._notify_armed_ready = lambda *a, **k: None
        node._prearm_after_advance = lambda *a, **k: None
        node._gradient_cancel_all = lambda *a, **k: None
        node._test_cancel_at = lambda *a, **k: None

        def notify_stop_project(cid):
            me.outbox.append(("stop_project", str(cid)))

        node._notify_stop_project = notify_stop_project

        def stop(value=None):
            # The STOP path without its players (stop_playback): end every pass,
            # then the re-arm of the load.
            node.set_status("running", "no")
            CUE_HANDLER.stop_all_cues()
            node.ongoing_cue = None
            me._load(rearm=True)

        node.commands_dict = {
            "go": node.go_script,
            "stop": stop,
            "cue_enabled": node._handle_cue_enabled,
        }
        relay = FollowRelay(
            CUE_HANDLER,
            node_id=self.name,
            send=lambda data: me.outbox.append(("follow", data)),
            get_script=lambda: node.script,
            get_mtc=lambda: node.mtc_listener,
            get_project_gen=lambda: node._project_generation,
            first_local=node._first_local_enabled_in_go_chain,
            sleep=clock.sleep,
        )
        node._follow_relay = relay
        CUE_HANDLER._follow = relay
        ACTION_HANDLER.set_result_sink(node._action_result_sink)
        self.node = node
        self.ch = CUE_HANDLER

    def _load(self, rearm=False):
        """What a load (or a STOP's re-arm) leaves armed: every enabled local cue
        this node can arm."""
        for cue in self.script.by_name.values():
            if not cue._local or not cue.enabled:
                continue
            if cue._sim_name in self.arm_fail:
                continue
            cue.loaded = True
            if not self.ch.find_armed_cue(cue):
                self.ch.add_armed_cue(cue)

    # -- the bus ----------------------------------------------------------------
    def bus(self, name, value, sent_ms):
        if name == "go_entry":
            # an operator GO on a named cue: setnextcue, then the GO
            self.node.next_cue_pointer = self.script.by_name[value["entry"]]
            name, value = "go", value["go"]
        consumed = False
        try:
            consumed = bool(
                self.node._on_command_received(name, value, sent_ms=sent_ms)
            )
        except Exception as e:  # NodeCommunications: never lose a command
            self.journal.append((self.clock.now, "ERROR", f"SIM: hook raised {e!r}"))
        self.clock.kick()
        if consumed:
            return

        def run():
            try:
                with self.node._command_lock:
                    self.node._run_command_locked(name, value)
            except Exception:
                self.journal.append(
                    (self.clock.now, "ERROR", "SIM: " + traceback.format_exc())
                )
            if name == "go":
                p = self.node.next_cue_pointer
                self.standby.append(getattr(p, "_sim_name", None) if p else None)

        t = threading.Thread(target=run, name=f"Cmd:{name}", daemon=True)
        t.start()
        self.cmd_threads.append(t)

    def reply(self, stuck=None):
        out, self.outbox = self.outbox, []
        return {
            "next_wake": self.clock.next_wake(),
            "outbox": out,
            "stuck": stuck or [],
            "now": self.clock.now,
        }

    def finish(self):
        return {
            "journal": list(self.journal),
            "standby": list(self.standby),
            "flags": {n: bool(c.enabled) for n, c in self.script.by_name.items()},
            "ids": {n: str(c.id) for n, c in self.script.by_name.items()},
        }


def node_main(conn) -> None:
    """The subprocess: one message in, one reply out, until "quit"."""
    sim = None
    while True:
        try:
            msg = conn.recv()
        except EOFError:
            return
        kind = msg[0]
        try:
            if kind == "init":
                sim = SimNode(msg[1])
                conn.send({"ok": True, **sim.reply(sim.clock.settle())})
            elif kind == "bus":
                _, name, value, sent_ms = msg
                sim.bus(name, value, sent_ms)
                conn.send({"ok": True, **sim.reply(sim.clock.settle())})
            elif kind == "advance":
                sim.clock.set(msg[1])
                conn.send({"ok": True, **sim.reply(sim.clock.settle())})
            elif kind == "finish":
                conn.send({"ok": True, **sim.finish()})
            elif kind == "quit":
                conn.send({"ok": True})
                return
            else:
                conn.send({"ok": False, "error": f"unknown message {kind!r}"})
        except Exception:
            conn.send({"ok": False, "error": traceback.format_exc()})
            if kind == "init":
                return
