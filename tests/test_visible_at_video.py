# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""869feynrj §4.6, engine side (cuems-RELATIONS Plans/2026-11-03-audio-first-
pass-head-869feynrj.md, §7.1 "Engine"): the self-gated video reveal.

The consumer contract is the videocomposer's ``visible_at`` (branch
feat/869feynrj-visible-at, d218ad3: ``RemoteCommandRouter.cpp:134-136``,
``VideoLayer.cpp:527-567``, caps token ``utils/CapsFile.h:48``):

- with a videocomposer whose caps file lists ``visible_at``, the follow commit
  (start label - F, decided and sent under CueHandler._lock, the section the
  audio cues' ``/mtcfollow 1`` uses) sends ``visible_at 1`` to every layer of
  the VideoCue; the reveal still sends ``/visible 1`` (a healer);
- every §4.3 cancel path sends ``visible_at 0`` to the layers of a pass whose
  gate is out and that the engine has not revealed, once, under the lock
  (superseding GO, cascade, disable before the slot, cross-node follow
  cancel, STOP, ActionCue stop / pause / fade_out, any disarm, a CueList
  target's child); the engine's reveal closes the gate's account (a stop of a
  cue on stage goes through today's ``/visible 0`` + unload);
- without the token: the OSC of today, byte for byte, and one INFO line per
  load;
- the repetition filter is off for ``visible_at`` and ``/visible`` (§4.4), on
  the wire (a real VideoClient -> UDP, as tests/test_osc_wire_selfgate.py);
- the postwait tail's ``/visible 0`` (which drops a pending gate in the VC) is
  decided and sent under the lock, against this pass's generation.
"""

import socket
import struct
import threading
import uuid
from threading import Lock
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pyossia
import pytest
from cuemsutils.cues import CueList, VideoCue
from cuemsutils.tools.CTimecode import CTimecode

from cuemsengine.cues import ActionHandler as AH
from cuemsengine.cues import loop_mode
from cuemsengine.cues.CueHandler import CueHandler
from cuemsengine.cues.run_cue import reveal_cue
from cuemsengine.players.PlayerHandler import PLAYER_HANDLER
from cuemsengine.players.StartGate import START_GATE
from cuemsengine.tools.PortHandler import PORT_HANDLER

VC_NEW = frozenset({"loop_period", "visible_at"})
VC_OLD = frozenset({"loop_period"})
LAYERS = ["L1", "L2"]


def _vis_at(layer):
    return f"/videocomposer/layer/{layer}/visible_at"


def _vis(layer):
    return f"/videocomposer/layer/{layer}/visible"


# --------------------------------------------------------------------- doubles


class _Mtc:
    """MTC whose position moves by each patched sleep."""

    def __init__(self, ms):
        self.main_tc = SimpleNamespace(
            milliseconds_exact=float(ms), framerate=25, frames=int(ms // 40)
        )

    @property
    def now(self):
        return self.main_tc.milliseconds_exact

    def advance(self, seconds):
        self.main_tc.milliseconds_exact += float(seconds) * 1000.0
        self.main_tc.frames = int(self.main_tc.milliseconds_exact // 40)


class _Client:
    """Records (mtc, path, value, CueHandler._lock held) per send."""

    def __init__(self, lock, mtc=None):
        self.lock, self.mtc, self.sent = lock, mtc, []

    def set_value(self, path, value):
        now = self.mtc.now if self.mtc is not None else None
        self.sent.append((now, path, value, self.lock.locked()))

    def remove_layer_endpoints(self, layer_id):
        pass

    def wire(self):
        return [(p, v) for _, p, v, _ in self.sent]

    def visible_at(self, value=None):
        return [
            (t, p, v, locked)
            for t, p, v, locked in self.sent
            if p.endswith("/visible_at") and (value is None or v == value)
        ]


class _Out:
    def get_layer_placement(self):
        return 0, 0

    def get_layer_scale(self, w, h):
        return 1.0, 1.0


def _video(prewait_ms=0.0, gen=1, revealed=False, playing=True):
    cue = VideoCue(
        {
            "id": str(uuid.uuid4()),
            "name": "v",
            "loop": 1,
            "Media": {
                "file_name": "v.mov",
                "id": str(uuid.uuid4()),
                "duration": "00:00:01.000",
            },
        }
    )
    cue.prewait = CTimecode(start_seconds=prewait_ms / 1000)
    cue.post_go = "pause"
    cue._local = True
    cue.enabled = True
    cue.loaded = True
    cue._target_object = None
    cue._stop_requested = False
    cue._go_generation = gen
    cue._revealed = revealed
    cue._playing = playing
    cue._loop_period = None
    cue._in_cuelist = False
    cue._layer_ids = list(LAYERS)
    cue._layer_outputs = {lid: "out" for lid in LAYERS}
    return cue


def _cuelist(child, prewait_ms=0.0, gen=1):
    cl = CueList({"id": str(uuid.uuid4()), "name": "cl", "contents": [child]})
    cl.prewait = CTimecode(start_seconds=prewait_ms / 1000)
    cl.post_go = "pause"
    cl._local = True
    cl.enabled = True
    cl.loaded = True
    cl._target_object = None
    cl._stop_requested = False
    cl._go_generation = gen
    cl._revealed = False
    cl._playing = True
    return cl


def _ch(out_latency_ms=None):
    ch = object.__new__(CueHandler)
    ch._lock = Lock()
    ch._armed_cues = []
    ch._armed_cues_set = set()
    ch.communications_thread = MagicMock()
    ch.disarm = MagicMock()
    ch.go = MagicMock(return_value=None)
    ch._next_local_fire = MagicMock(return_value=(None, 0.0))
    ch._arm_ahead = MagicMock()
    ch._follow = None
    ch.out_latency_ms = out_latency_ms
    return ch


@pytest.fixture(autouse=True)
def quiet_gate():
    START_GATE.autostart = False
    yield
    START_GATE.reset_for_tests()
    START_GATE.autostart = True


def _patched(caps):
    return (
        patch.object(PLAYER_HANDLER, "_video_caps", caps),
        patch.object(PLAYER_HANDLER, "cue_media_dimensions", lambda c: (1920, 1080)),
        patch.object(
            PLAYER_HANDLER, "resolve_video_output_for_cue", lambda c, n: _Out()
        ),
        patch.object(PLAYER_HANDLER, "audio_player", lambda c: None),
    )


def _drive(ch, cue, mtc, arrival_ms, caps, *, on_sleep=None, blank=None):
    """go_threaded for real (run_videoCue, the follow commit, reveal_cue);
    loop_cue patched out. Returns {"illum": [mtc], "reveal": [mtc]}."""
    events = {"illum": [], "reveal": []}
    ch.communications_thread.add_cue.side_effect = lambda *a, **k: events[
        "illum"
    ].append(mtc.now)

    def sleep(s):
        mtc.advance(s)
        if on_sleep is not None:
            on_sleep(mtc.now)

    def reveal(c, m, start_ms):
        events["reveal"].append(mtc.now)
        return reveal_cue(c, m, start_ms)

    p1, p2, p3, p4 = _patched(caps)
    with (
        p1,
        p2,
        p3,
        p4,
        patch("cuemsengine.cues.CueHandler.sleep", side_effect=sleep),
        patch("cuemsengine.cues.CueHandler.reveal_cue", side_effect=reveal),
        patch("cuemsengine.cues.CueHandler.loop_cue"),
        patch("cuemsengine.cues.CueHandler.blank_cue", side_effect=blank),
    ):
        ch.go_threaded(cue, mtc, frozen_mtc_ms=arrival_ms, go_gen=cue._go_generation)
    return events


def _label(ms):
    return CTimecode(framerate=25, start_seconds=ms / 1000).milliseconds_exact


def _setup_wire(start_ms):
    """What run_videoCue sends per layer today (loop 1, placement known)."""
    offset = -CTimecode(framerate=25, start_seconds=start_ms / 1000).frame_number
    out = []
    for lid in LAYERS:
        lp = f"/videocomposer/layer/{lid}"
        out += [
            (f"{lp}/position", [0, 0]),
            (f"{lp}/scale", [1.0, 1.0]),
            (f"{lp}/offset", int(offset)),
            (f"{lp}/mtcfollow", 1),
        ]
    return out


# --------------------------------------------------------------- the commit


class TestFollowCommit:
    def test_visible_at_1_to_every_layer_at_start_minus_F_under_the_lock(self):
        ch = _ch()
        mtc = _Mtc(1000.0)
        cue = _video(2000.0)
        cue._osc = _Client(ch._lock, mtc)
        ev = _drive(ch, cue, mtc, 1000.0, VC_NEW)
        sent = cue._osc.visible_at(1)
        assert [p for _, p, _, _ in sent] == [_vis_at(lid) for lid in LAYERS]
        assert all(locked for *_, locked in sent)
        due = _label(3000.0) - ch._follow_lead_ms()
        assert all(due <= t < due + 20 for t, *_ in sent)
        # the same F and due rule as the audio cues' /mtcfollow 1 (§4.2)
        assert ch._follow_lead_ms() == CueHandler._FOLLOW_LEAD_MS
        # lit at its arrival, revealed at its start
        assert ev["illum"][0] < sent[0][0] < ev["reveal"][0]
        assert ev["reveal"][0] >= 3000.0

    def test_the_reveal_still_sends_visible_1_as_a_healer(self):
        ch = _ch()
        mtc = _Mtc(1000.0)
        cue = _video(2000.0)
        cue._osc = _Client(ch._lock, mtc)
        _drive(ch, cue, mtc, 1000.0, VC_NEW)
        start = _label(3000.0)
        assert cue._osc.wire() == (
            _setup_wire(start)
            + [(_vis_at(lid), 1) for lid in LAYERS]
            + [(_vis(lid), 1) for lid in LAYERS]
        )

    def test_operator_go_prewait_0_commits_right_after_the_setup(self):
        ch = _ch(out_latency_ms=42.7)
        mtc = _Mtc(100_007.0)
        anchor = 100_080.0
        cue = _video(0.0)
        cue._osc = _Client(ch._lock, mtc)
        _drive(ch, cue, mtc, anchor, VC_NEW)
        sent = cue._osc.visible_at(1)
        assert len(sent) == len(LAYERS)
        assert sent[0][0] < anchor
        follow_t = [t for t, p, *_ in cue._osc.sent if p.endswith("/mtcfollow")]
        assert max(follow_t) <= sent[0][0]

    def test_a_videocomposer_without_the_token_gets_todays_osc(self):
        """Skew (§4.6): byte for byte today's sends, no visible_at."""
        ch = _ch()
        mtc = _Mtc(1000.0)
        cue = _video(2000.0)
        cue._osc = _Client(ch._lock, mtc)
        ev = _drive(ch, cue, mtc, 1000.0, VC_OLD)
        start = _label(3000.0)
        assert cue._osc.visible_at() == []
        assert cue._osc.wire() == _setup_wire(start) + [
            (_vis(lid), 1) for lid in LAYERS
        ]
        reveals = [t for t, p, *_ in cue._osc.sent if p.endswith("/visible")]
        assert min(reveals) >= 3000.0 and ev["reveal"][0] >= 3000.0

    def test_a_dark_cue_commits_nothing(self):
        """No layer on this node (869fgq3xv): nothing to gate."""
        ch = _ch()
        mtc = _Mtc(1000.0)
        cue = _video(2000.0)
        cue._layer_ids = []
        cue._osc = _Client(ch._lock, mtc)
        _drive(ch, cue, mtc, 1000.0, VC_NEW)
        assert cue._osc.sent == []

    def test_a_pass_stopped_before_its_commit_sends_no_visible_at(self):
        ch = _ch()
        mtc = _Mtc(1000.0)
        cue = _video(2000.0)
        cue._osc = _Client(ch._lock, mtc)

        def stop(now):
            if now >= 2500.0:
                cue._stop_requested = True

        _drive(ch, cue, mtc, 1000.0, VC_NEW, on_sleep=stop)
        assert cue._osc.visible_at() == []
        assert getattr(cue, "_visible_at_gen", None) is None

    def test_the_reveal_closes_the_gates_account(self):
        """After the engine's reveal the cue is on stage: a later stop goes
        through today's /visible 0 + unload, not a visible_at 0 (whose VC
        WARNING is the race's, D5)."""
        ch = _ch()
        mtc = _Mtc(1000.0)
        cue = _video(2000.0)
        cue._osc = _Client(ch._lock, mtc)
        _drive(ch, cue, mtc, 1000.0, VC_NEW)
        assert getattr(cue, "_visible_at_gen", None) is None
        with ch._lock:
            ch.cancel_start_locked(cue, "stop_of_playing")
        assert cue._osc.visible_at(0) == []

    def test_cuelist_child_commits_at_the_parents_start_minus_F(self):
        """S0-11 / review 4 m9, as for audio: the parent reveals at the
        child's start, so a cancel still reaches the child until then."""
        ch = _ch()
        mtc = _Mtc(1000.0)
        child = _video(9999.0)
        child._osc = _Client(ch._lock, mtc)
        parent = _cuelist(child, prewait_ms=2000.0)
        revealed_early = []

        def watch(now):
            if now < 3000.0 and parent._revealed:
                revealed_early.append(now)

        ev = _drive(ch, parent, mtc, 1000.0, VC_NEW, on_sleep=watch)
        sent = child._osc.visible_at(1)
        due = _label(3000.0) - CueHandler._FOLLOW_LEAD_MS
        assert len(sent) == len(LAYERS) and due <= sent[0][0] < due + 20
        assert ev["reveal"][0] >= 3000.0 and revealed_early == []
        assert [p for _, p, v, _ in child._osc.sent if p.endswith("/visible")] == [
            _vis(lid) for lid in LAYERS
        ]


class TestCommitRefusals:
    def _ready(self):
        ch = _ch()
        cue = _video()
        cue._osc = _Client(ch._lock)
        cue._visible_at_ready = True
        cue._start_mtc = CTimecode(framerate=25, start_seconds=1.0)
        return ch, cue

    def test_commit(self):
        ch, cue = self._ready()
        assert ch._commit_follow(cue, cue, 1) is True
        assert [(p, v, locked) for _, p, v, locked in cue._osc.sent] == [
            (_vis_at(lid), 1, True) for lid in LAYERS
        ]
        assert cue._visible_at_gen == 1

    @pytest.mark.parametrize(
        "why",
        ["stopped", "superseded", "setup_not_sent"],
    )
    def test_refused(self, why):
        ch, cue = self._ready()
        if why == "stopped":
            cue._stop_requested = True
        elif why == "superseded":
            cue._go_generation = 2
        else:
            cue._visible_at_ready = False
        assert ch._commit_follow(cue, cue, 1) is False
        assert cue._osc.sent == []
        assert getattr(cue, "_visible_at_gen", None) is None

    def test_the_target_needs_the_token_layers_and_a_client(self):
        ch, cue = self._ready()
        with patch.object(PLAYER_HANDLER, "_video_caps", VC_NEW):
            assert ch._follow_commit_target(cue) is cue
            cue._layer_ids = []
            assert ch._follow_commit_target(cue) is None
            cue._layer_ids = list(LAYERS)
            cue._osc = None
            assert ch._follow_commit_target(cue) is None
        cue._osc = _Client(ch._lock)
        with patch.object(PLAYER_HANDLER, "_video_caps", VC_OLD):
            assert ch._follow_commit_target(cue) is None


# --------------------------------------------------------------- cancel paths


@pytest.fixture
def ch():
    return _ch()


@pytest.fixture
def committed(ch):
    """commit(cue[, parent]) runs this pass's follow commit, as start - F
    would; a CueList child is committed by its parent's pass."""

    def commit(cue, parent=None):
        owner = parent if parent is not None else cue
        cue._osc = _Client(ch._lock)
        cue._visible_at_ready = True
        cue._start_mtc = CTimecode(framerate=25, start_seconds=1.0)
        assert ch._commit_follow(owner, cue, owner._go_generation)
        cue._osc.sent.clear()
        return cue._osc

    return commit


def _zeros(client):
    return [(p, locked) for _, p, v, locked in client.sent if p.endswith("/visible_at")]


ZEROS = [(_vis_at(lid), True) for lid in LAYERS]


class TestSupersedingGo:
    def _go(self, ch, cue, **kw):
        ch.go_threaded = MagicMock()
        return CueHandler.go(ch, cue, MagicMock(), 1000.0, **kw)

    def test_an_unrevealed_pass_gets_visible_at_0_under_the_lock(self, ch, committed):
        cue = _video()
        client = committed(cue)
        assert self._go(ch, cue) is not None
        assert _zeros(client) == ZEROS
        assert all(v == 0 for _, p, v, _ in client.sent if p.endswith("visible_at"))
        assert cue._visible_at_gen is None

    def test_a_refused_dispatch_sends_nothing(self, ch, committed):
        cue = _video()
        client = committed(cue)
        assert self._go(ch, cue, arm_epoch=ch._disarm_epoch + 1) is None
        assert client.sent == []


class TestCascadeAndDisable:
    def _chain(self, b):
        a = SimpleNamespace(
            id="A", post_go="go", _local=True, enabled=True, _target_object=b
        )
        b._go_epoch = 0
        return a

    def test_a_pending_descendant(self, ch, committed):
        b = _video()
        client = committed(b)
        assert ch.cancel_pending_descendants(self._chain(b)) == 1
        assert _zeros(client) == ZEROS

    def test_a_descendant_on_stage_is_left_alone(self, ch, committed):
        b = _video()
        client = committed(b)
        b._revealed = True
        assert ch.cancel_pending_descendants(self._chain(b)) == 0
        assert client.sent == []

    def test_cancel_parked(self, ch, committed):
        cue = _video()
        client = committed(cue)
        assert ch.cancel_parked(cue) is True
        assert _zeros(client) == ZEROS

    def test_a_cuelist_reaches_its_committed_child(self, ch, committed):
        child = _video()
        cl = _cuelist(child)
        client = committed(child, cl)
        assert ch.cancel_parked(cl) is True
        assert _zeros(client) == ZEROS


class TestFollowCancel:
    def test_a_pending_start(self, ch, committed):
        cue = _video()
        cue._revealed_at = None
        client = committed(cue)
        ch.cancel_pending_descendants = MagicMock()
        ch._end_illumination = MagicMock()
        ch.disarm_if_unchanged = MagicMock()
        with patch("cuemsengine.cues.CueHandler.sleep"):
            out = ch.stop_dispatched_follow(
                cue, cue._go_generation, ch._disarm_epoch, None, True, 2.0
            )
        assert out[0] == "stopped"
        assert _zeros(client) == ZEROS


class TestStop:
    def test_a_pending_gate_is_dropped_at_the_flags(self, ch, committed):
        cue = _video()
        client = committed(cue)
        ch._armed_cues = [cue]
        ch._armed_cues_set = {cue.id}
        ch.stop_all_cues()
        assert _zeros(client) == ZEROS
        ch.stop_all_cues()  # ready_script -> disarm_all
        assert len(_zeros(client)) == len(LAYERS)

    def test_a_cuelist_child_is_reached_once(self, ch, committed):
        child = _video()
        cl = _cuelist(child)
        client = committed(child, cl)
        ch._armed_cues = [cl, child]
        ch._armed_cues_set = {cl.id, child.id}
        ch.stop_all_cues()
        assert _zeros(client) == ZEROS

    def test_without_a_commit_nothing(self, ch):
        cue = _video()
        cue._osc = _Client(ch._lock)
        ch._armed_cues = [cue]
        ch._armed_cues_set = {cue.id}
        ch.stop_all_cues()
        assert cue._osc.sent == []


class TestActionStops:
    def _run(self, fn, *args):
        out = {}
        t = threading.Thread(target=lambda: out.setdefault("r", fn(*args)))
        t.start()
        t.join(3)
        assert not t.is_alive(), "deadlock: the cascade ran under the lock"
        return out["r"]

    @pytest.mark.parametrize("handler", ["stop", "pause", "fade_out"])
    def test_a_pending_target(self, ch, committed, handler):
        cue = _video()
        cue._go_epoch = 0
        client = committed(cue)
        fn = {
            "stop": AH._handle_stop,
            "pause": AH._handle_pause,
            "fade_out": AH._handle_fade_out,
        }[handler]
        with patch("cuemsengine.cues.ActionHandler.time.sleep"):
            self._run(fn, ch, None, cue, MagicMock())
        assert _zeros(client) == ZEROS

    def test_a_cuelist_target_reaches_its_child(self, ch, committed):
        child = _video()
        cl = _cuelist(child)
        client = committed(child, cl)
        cl._go_epoch = 0
        with patch("cuemsengine.cues.ActionHandler.time.sleep"):
            self._run(AH._handle_stop, ch, None, cl, MagicMock())
        assert _zeros(client) == ZEROS


class TestDisarm:
    def _disarm(self, ch, cue, reason):
        with (
            patch.object(PLAYER_HANDLER, "is_layer_registered", lambda lid: True),
            patch.object(PLAYER_HANDLER, "deregister_layer", MagicMock()),
            patch.object(PLAYER_HANDLER, "remove_cue_player", MagicMock()),
        ):
            CueHandler.disarm(ch, cue, reason=reason)

    def test_visible_at_0_before_todays_hide_and_unload(self, ch, committed):
        cue = _video()
        client = committed(cue)
        self._disarm(ch, cue, "disabled")
        paths = [p for _, p, _, _ in client.sent]
        assert paths[: len(LAYERS)] == [_vis_at(lid) for lid in LAYERS]
        assert [locked for *_, locked in client.sent[: len(LAYERS)]] == [True] * 2
        assert _vis("L1") in paths and "/videocomposer/layer/unload" in paths
        assert getattr(cue, "_visible_at_gen", None) is None

    def test_not_at_the_natural_end(self, ch, committed):
        cue = _video()
        client = committed(cue)
        self._disarm(ch, cue, "cue_end")
        assert _zeros(client) == []
        # the layers are gone: nothing is left to cancel later
        assert getattr(cue, "_visible_at_gen", None) is None


class TestCancelOnce:
    def test_a_second_cancel_sends_nothing(self, ch, committed):
        cue = _video()
        client = committed(cue)
        with ch._lock:
            ch.cancel_start_locked(cue, "cancel")
            ch.cancel_start_locked(cue, "cancel")
        assert _zeros(client) == ZEROS


# ------------------------------------------------------------ postwait tail


class TestPostwaitTailBlank:
    def test_the_tail_hides_under_the_lock(self):
        """blank_cue's /visible 0 drops a pending gate in the VC: decided
        and sent under the lock, against this pass's generation."""
        ch = _ch()
        mtc = _Mtc(1000.0)
        cue = _video(0.0)
        cue.postwait = CTimecode(start_seconds=0.2)
        cue._osc = _Client(ch._lock, mtc)
        held = []
        _drive(
            ch,
            cue,
            mtc,
            1000.0,
            VC_NEW,
            blank=lambda c, m: held.append(ch._lock.locked()),
        )
        assert held == [True]

    def test_a_newer_pass_is_never_blanked(self):
        """A re-GO landing between the post-loop generation check and the
        tail (here: inside _follow_instant_ms, which runs in between) must
        not hide the new pass's layers: its gate would be dropped."""
        ch = _ch()
        mtc = _Mtc(1000.0)
        cue = _video(0.0)
        cue.postwait = CTimecode(start_seconds=0.2)
        cue._osc = _Client(ch._lock, mtc)
        held = []
        real = CueHandler._follow_instant_ms

        def newer(c, start_ms):
            c._go_generation += 1
            return real(c, start_ms)

        ch._follow_instant_ms = newer
        _drive(ch, cue, mtc, 1000.0, VC_NEW, blank=lambda c, m: held.append(True))
        assert held == []


# ------------------------------------------------------------------- the load


def _project(*cues):
    return SimpleNamespace(contents=list(cues))


class TestLoadInfo:
    def test_one_info_without_the_token_when_the_node_has_video(self):
        from cuemsengine.NodeEngine import NodeEngine

        v = _video()
        with (
            patch.object(PLAYER_HANDLER, "_video_caps", VC_OLD),
            patch("cuemsengine.NodeEngine.Logger") as log,
        ):
            NodeEngine._check_visible_at(_project(v))
        lines = [str(c.args[0]) for c in log.info.call_args_list]
        assert len(lines) == 1 and "visible_at" in lines[0]

    def test_nothing_with_the_token_or_without_local_video(self):
        from cuemsengine.NodeEngine import NodeEngine

        v = _video()
        remote = _video()
        remote._local = False
        with patch("cuemsengine.NodeEngine.Logger") as log:
            with patch.object(PLAYER_HANDLER, "_video_caps", VC_NEW):
                NodeEngine._check_visible_at(_project(v))
            with patch.object(PLAYER_HANDLER, "_video_caps", VC_OLD):
                NodeEngine._check_visible_at(_project(remote))
                NodeEngine._check_visible_at(None)
        assert log.info.call_count == 0

    def test_a_video_child_of_a_cuelist_counts(self):
        from cuemsengine.NodeEngine import NodeEngine

        with (
            patch.object(PLAYER_HANDLER, "_video_caps", frozenset()),
            patch("cuemsengine.NodeEngine.Logger") as log,
        ):
            NodeEngine._check_visible_at(_project(_cuelist(_video())))
        assert log.info.call_count == 1

    def test_the_token(self):
        assert loop_mode.VC_VISIBLE_AT == "visible_at"
        assert loop_mode.vc_visible_at(VC_NEW) is True
        assert loop_mode.vc_visible_at(VC_OLD) is False
        assert loop_mode.vc_visible_at(None) is False


# --------------------------------------------------------------------- wire


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _parse(d):
    a = d[: d.index(b"\0")]
    i = (len(a) // 4 + 1) * 4
    tt = d[i : d.index(b"\0", i)]
    j = i + (len(tt) // 4 + 1) * 4
    args = []
    for t in tt[1:].decode():
        if t == "i":
            args.append(struct.unpack(">i", d[j : j + 4])[0])
        j += 4
    return a.decode(), tt.decode(), args


@pytest.fixture
def wire(monkeypatch):
    from cuemsengine.players.VideoPlayer import VideoClient

    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    monkeypatch.setattr(PORT_HANDLER, "new_random_port", _free_port)
    client = VideoClient(player_port=rx.getsockname()[1], name="wire-visible-at")
    client.create_layer_endpoints("L1")
    # creating the endpoints pushes the initial `visible -1` and nothing else
    rx.settimeout(0.3)
    created = []
    try:
        while True:
            created.append(_parse(rx.recv(2048)))
    except socket.timeout:
        pass
    rx.settimeout(2)

    def send(path, value):
        client.set_value(path, value)
        return _parse(rx.recv(2048))

    yield send, created
    client.remove_device()
    rx.close()


@pytest.mark.skipif(
    not hasattr(pyossia.Node, "remove_child"),
    reason=(
        "installed pyossia has no Node.remove_child — node removal is "
        "unsupported by this libossia build; update the system pyossia package"
    ),
)
class TestWire:
    def test_creating_a_layer_pushes_no_visible_at(self, wire):
        _, created = wire
        assert created == [(_vis("L1"), ",i", [-1])]

    def test_visible_at_repeats_reach_the_wire(self, wire):
        send, _ = wire
        assert send(_vis_at("L1"), 1) == (_vis_at("L1"), ",i", [1])
        assert send(_vis_at("L1"), 1) == (_vis_at("L1"), ",i", [1])
        assert send(_vis_at("L1"), 0) == (_vis_at("L1"), ",i", [0])
        assert send(_vis_at("L1"), 0) == (_vis_at("L1"), ",i", [0])

    def test_a_first_visible_at_0_reaches_the_wire(self, wire):
        send, _ = wire
        assert send(_vis_at("L1"), 0) == (_vis_at("L1"), ",i", [0])

    def test_visible_repeats_reach_the_wire(self, wire):
        send, _ = wire
        assert send(_vis("L1"), 0) == (_vis("L1"), ",i", [0])
        assert send(_vis("L1"), 1) == (_vis("L1"), ",i", [1])
        assert send(_vis("L1"), 1) == (_vis("L1"), ",i", [1])
        assert send(_vis("L1"), 0) == (_vis("L1"), ",i", [0])
        assert send(_vis("L1"), 0) == (_vis("L1"), ",i", [0])
