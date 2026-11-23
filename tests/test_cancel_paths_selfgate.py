# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""869feynrj §4.3 (cuems-RELATIONS Plans/2026-11-03-audio-first-pass-head-
869feynrj.md, §7.1 "Engine"): every path that cancels, stops, supersedes,
disables or fades out a pass sends ``/cancelstart`` to its selfgate player,
once, under CueHandler._lock, in the section that sets the flags; never to an
older player. The rows are step 0a's inventory (baselines/869feynrj-step0/
0a-0c-inventory.md §0a.4):

  row 1  superseding GO (go() commit section)       kind cancel, old pass only
  row 2  cascade (cancel_pending_descendants)       kind cancel, by the pass
  row 3  a toggle (retake, 1amfwm7jnqf D31 c)       nothing once committed;
         a CueList child (cancel_child)             S0-1 race
  row 4  cross-node follow cancel                   cancel / stop_of_playing (D12)
  row 5  STOP (stop_all_cues), D10, S0-4            stop_of_playing, player table
  rows 10-12  ActionCue stop / pause / fade_out     S0-8 lock, D12
  row 19 any disarm                                 belt and braces, not cue_end
  rows 16 + S0-11  a CueList target                 reaches its first child
plus the fade wait before a disconnect (D12, review 4 m4), STOP's wait (m3) and
S0-9 (play no longer clears _stop_requested unlocked).
"""

import threading
from threading import Lock
from time import monotonic
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from cuemsutils.cues import AudioCue, CueList

from cuemsengine.cues import ActionHandler as AH
from cuemsengine.cues.CueHandler import CueHandler
from cuemsengine.players.AudioPlayer import AudioPlayer
from cuemsengine.players.Player import CancelAck
from cuemsengine.players.PlayerHandler import PLAYER_HANDLER
from cuemsengine.players.StartGate import START_GATE

SELFGATE = frozenset({"loop", "varispeed", "dayalign", "selfgate"})
OLD = frozenset({"loop", "varispeed", "dayalign"})


class _Proc:
    def poll(self):
        return None


class _Client:
    def __init__(self, lock):
        self.lock, self.sent = lock, []

    def set_value(self, path, value):
        self.sent.append((path, value, self.lock.locked()))

    def cancels(self):
        return [(v, locked) for p, v, locked in self.sent if p == "/cancelstart"]


def _player(caps=SELFGATE):
    p = AudioPlayer(port=0, path="cuems-audioplayer", args="", media="a.wav")
    p.caps = caps
    p.ready.set()
    p.p = _Proc()
    return p


def _audio(revealed=False, playing=True, gen=1):
    import uuid

    cue = AudioCue(
        {
            "id": str(uuid.uuid4()),
            "name": "t",
            "Media": {
                "file_name": "a.wav",
                "id": str(uuid.uuid4()),
                "duration": "00:00:01.000",
            },
        }
    )
    cue._local = True
    cue.enabled = True
    cue.loaded = True
    cue.post_go = "go"
    cue._target_object = None
    cue._stop_requested = False
    cue._go_generation = gen
    cue._revealed = revealed
    cue._playing = playing
    return cue


def _cuelist(child):
    import uuid

    cl = CueList({"id": str(uuid.uuid4()), "name": "cl", "contents": [child]})
    cl._local = True
    cl.enabled = True
    cl.loaded = True
    cl.post_go = "go"
    cl._target_object = None
    cl._stop_requested = False
    cl._go_generation = 1
    cl._revealed = False
    cl._playing = True
    return cl


def _pass(epoch, anchor_ms=0.0, layout=(), root_seq=0, mode="sequential"):
    """A chain_pass.Pass."""
    from cuemsengine.cues.chain_pass import Pass

    return Pass(
        epoch=epoch,
        anchor_ms=anchor_ms,
        layout=list(layout),
        root_seq=root_seq,
        mode=mode,
    )


def _ch():
    ch = object.__new__(CueHandler)
    ch._lock = Lock()
    ch._armed_cues = []
    ch._armed_cues_set = set()
    ch.communications_thread = MagicMock()
    ch._follow = None
    return ch


@pytest.fixture
def ch():
    return _ch()


@pytest.fixture
def players(ch):
    """attach(cue, caps, follow) registers a fake player for the cue in the
    player table and (follow=True) commits a follow, as start - F would."""
    START_GATE.autostart = False
    registered = []

    def attach(cue, caps=SELFGATE, follow=True):
        player = _player(caps)
        client = _Client(ch._lock)
        cue._osc = client
        with PLAYER_HANDLER._lock:
            PLAYER_HANDLER._cue_players[cue] = player
        registered.append(cue)
        if follow:
            START_GATE.commit_follow(cue, player, client, cue._go_generation)
        return player, client

    yield attach
    with PLAYER_HANDLER._lock:
        for cue in registered:
            PLAYER_HANDLER._cue_players.pop(cue, None)
    START_GATE.reset_for_tests()
    START_GATE.autostart = True


def _kinds(player):
    return [r.kind for r in player.cancel_records.values()]


class TestSupersedingGo:
    """Row 1: for the OLD pass, before the new thread exists."""

    def _go(self, ch, cue, **kw):
        ch.go_threaded = MagicMock()
        ch._arm_ahead = MagicMock()
        return ch.go(cue, MagicMock(), 1000.0, **kw)

    def test_an_unrevealed_pass_is_cancelled_under_the_lock(self, ch, players):
        cue = _audio(revealed=False)
        player, client = players(cue)
        assert self._go(ch, cue) is not None
        assert client.cancels() == [([1, 5], True)]
        assert _kinds(player) == ["cancel"]

    def test_a_pass_on_stage_is_left_alone(self, ch, players):
        cue = _audio(revealed=True)
        _, client = players(cue)
        self._go(ch, cue)
        assert client.cancels() == []
        assert cue._superseded_playing is True

    def test_a_refused_dispatch_sends_nothing(self, ch, players):
        cue = _audio(revealed=False)
        _, client = players(cue)
        assert self._go(ch, cue, arm_epoch=ch._disarm_epoch + 1) is None
        assert client.cancels() == []

    def test_an_older_player_gets_nothing(self, ch, players):
        cue = _audio(revealed=False)
        player, client = players(cue, caps=OLD, follow=False)
        player.may_follow = True
        self._go(ch, cue)
        assert client.cancels() == []


class TestCascade:
    """Row 2."""

    def _chain(self, b):
        """A → b, both in one pass: the walk is that pass's layout and a cue
        belongs to it while its `_pass` is the target's (Design §5)."""
        a = SimpleNamespace(
            id="A",
            post_go="go",
            _local=True,
            enabled=True,
            _target_object=b,
            _revealed=True,
        )
        b._go_epoch = 0
        p = _pass(1, 0.0, [(a, 0.0), (b, 0.0)])
        a._pass = b._pass = p
        return a

    def test_a_pending_descendant_is_cancelled(self, ch, players):
        b = _audio(revealed=False)
        player, client = players(b)
        assert ch.cancel_pending_descendants(self._chain(b)) == 1
        assert client.cancels() == [([1, 5], True)]
        assert _kinds(player) == ["cancel"]

    def test_a_descendant_on_stage_is_left_alone(self, ch, players):
        b = _audio(revealed=True)
        _, client = players(b)
        assert ch.cancel_pending_descendants(self._chain(b)) == 0
        assert client.cancels() == []

    def test_a_cuelist_descendant_reaches_its_child(self, ch, players):
        child = _audio()
        _, client = players(child)
        cl = _cuelist(child)
        cl._go_epoch = 0
        assert ch.cancel_pending_descendants(self._chain(cl)) == 1
        assert client.cancels() == [([1, 5], True)]


class TestRetake:
    """Row 3 (1amfwm7jnqf, D31 c): a toggle no longer cancels a chain cue; it
    retakes it (`CueHandler.retake`), and a retake refuses a cue that is
    decided (committed in its player, or revealed) in the same lock section
    that would replace it. So no toggle sends a /cancelstart."""

    def _armed(self, ch, cue):
        cue._pass = _pass(1, 0.0, [(cue, 0.0)])
        cue._dispatch_arrival_ms = 0.0
        cue._go_epoch = 1
        ch.go_threaded = MagicMock()
        ch._arm_ahead = MagicMock()
        ch._chain_epoch = 1
        ch._last_stop_chain_epoch = 0

    def test_a_retake_after_the_commit_sends_no_cancelstart(self, ch, players):
        """The players fixture commits the follow (start - F has passed)."""
        cue = _audio(revealed=False, playing=True)
        _, client = players(cue)
        cue._follow_committed = True
        cue._follow_gen = cue._go_generation
        self._armed(ch, cue)
        cue.enabled = False
        assert ch.retake(cue, MagicMock()) is None
        assert client.cancels() == []
        assert cue._stop_requested is False
        assert cue._go_generation == 1

    def test_a_retake_racing_a_reveal_is_refused(self, ch, players):
        """S0-1, kept: a reveal committed while the retake waits for the lock
        must win."""
        cue = _audio(revealed=False, playing=True)
        _, client = players(cue, follow=False)
        self._armed(ch, cue)
        cue.enabled = False
        result = {}
        ch._lock.acquire()
        t = threading.Thread(
            target=lambda: result.setdefault("r", ch.retake(cue, MagicMock()))
        )
        t.start()
        t.join(0.1)
        cue._revealed = True  # the reveal commit, under the lock the test holds
        ch._lock.release()
        t.join(2)
        assert result["r"] is None
        assert cue._stop_requested is False
        assert client.cancels() == []

    def test_a_retake_refuses_a_revealed_cue(self, ch, players):
        """A toggle never stops a cue on stage (A3); was
        test_enable_rejoin's test_a_playing_cue_is_never_cancelled."""
        cue = _audio(revealed=True, playing=True)
        _, client = players(cue)
        self._armed(ch, cue)
        cue.enabled = False
        assert ch.retake(cue, MagicMock()) is None
        assert cue._stop_requested is False and cue._playing is True
        assert client.cancels() == []


class TestCancelChild:
    """cancel_parked is kept, as cancel_child, for its one caller: a
    CueList's child disabled before its commit (Design §2, S89)."""

    def test_a_committed_child_is_refused_and_sends_nothing(self, ch, players):
        child = _audio(revealed=False, playing=True)
        _, client = players(child)
        child._follow_committed = True
        child._follow_gen = child._go_generation
        assert ch.cancel_child(child) is False
        assert client.cancels() == []
        assert child._stop_requested is False

    def test_a_child_before_its_commit_is_cancelled(self, ch, players):
        child = _audio(revealed=False, playing=True)
        players(child, follow=False)
        assert ch.cancel_child(child) is True
        assert child._stop_requested is True and child._playing is False


class TestFollowCancel:
    """Row 4, D12: a pending start is cancelled; a cue on stage < 2 s fades."""

    def _stop(self, ch, cue):
        ch.cancel_pending_descendants = MagicMock()
        ch._end_illumination = MagicMock()
        ch.disarm_if_unchanged = MagicMock()
        with patch("cuemsengine.cues.CueHandler.sleep"):
            return ch.stop_dispatched_follow(
                cue, cue._go_generation, ch._disarm_epoch, None, True, 2.0
            )

    def test_a_pending_start_is_cancelled(self, ch, players):
        cue = _audio(revealed=False)
        cue._revealed_at = None
        player, client = players(cue)
        assert self._stop(ch, cue)[0] == "stopped"
        assert _kinds(player) == ["cancel"] and client.cancels()[0][1] is True

    def test_a_cue_on_stage_fades(self, ch, players):
        cue = _audio(revealed=True)
        cue._revealed_at = monotonic()
        player, client = players(cue)
        assert self._stop(ch, cue)[0] == "stopped"
        assert _kinds(player) == ["stop_of_playing"]


class TestStop:
    """Row 5, D10, S0-4: STOP walks the player table; always stop_of_playing."""

    def test_every_following_selfgate_player_fades_armed_or_not(self, ch, players):
        a, b = _audio(revealed=True), _audio(revealed=False)
        pa, ca = players(a)
        pb, cb = players(b)
        ch._armed_cues = [a]  # b is out of the armed list
        ch._armed_cues_set = {a.id}
        ch.stop_all_cues()
        assert ca.cancels() == [([1, 5], True)]
        assert cb.cancels() == [([1, 5], True)]
        assert _kinds(pa) == _kinds(pb) == ["stop_of_playing"]

    def test_an_older_player_gets_nothing(self, ch, players):
        cue = _audio()
        player, client = players(cue, caps=OLD, follow=False)
        player.may_follow = True
        ch.stop_all_cues()
        assert client.cancels() == []

    def test_the_second_stop_all_cues_sends_nothing_more(self, ch, players):
        cue = _audio()
        _, client = players(cue)
        ch.stop_all_cues()
        ch.stop_all_cues()  # ready_script -> disarm_all
        assert len(client.cancels()) == 1
        with PLAYER_HANDLER._lock:  # killed by kill_all_audio_players
            PLAYER_HANDLER._cue_players.pop(cue, None)
        ch.stop_all_cues()
        assert len(client.cancels()) == 1

    @pytest.mark.parametrize("t", [-30, -10, 0, 5, 12, 25])
    def test_stop_never_warns(self, ch, players, t):
        """cancel_model FIXTURES 'STOP at start+t ms' (R4, m6): the engine
        reveals at start + 10 ms in the model; STOP is stop_of_playing
        whether or not it had, so a player that started is not a WARNING."""
        cue = _audio(revealed=t >= 10)
        player, _ = players(cue)
        ch.stop_all_cues()
        with patch("cuemsengine.players.StartGate.Logger") as log:
            START_GATE.on_line(player, "cancel", CancelAck(1, "play", 40))
        log.warning.assert_not_called()


class TestActionStops:
    """Rows 10-12, S0-8, D12: flags and /cancelstart under the lock, the
    lock released before the cascade (which takes it again)."""

    def _run(self, fn, *args):
        out = {}
        t = threading.Thread(target=lambda: out.setdefault("r", fn(*args)))
        t.start()
        t.join(3)
        assert not t.is_alive(), "deadlock: the cascade ran under the lock"
        return out["r"]

    def _target(self, ch, players, revealed):
        cue = _audio(revealed=revealed)
        cue._go_epoch = 0
        player, client = players(cue)
        ch.disarm = MagicMock()
        return cue, player, client

    @pytest.mark.parametrize(
        "revealed, kind", [(True, "stop_of_playing"), (False, "cancel")]
    )
    def test_stop(self, ch, players, revealed, kind):
        cue, player, client = self._target(ch, players, revealed)
        with patch("cuemsengine.cues.ActionHandler.time.sleep"):
            res = self._run(AH._handle_stop, ch, None, cue, MagicMock())
        assert res["status"] == "applied"
        assert client.cancels() == [([1, 5], True)] and _kinds(player) == [kind]
        assert cue._go_generation == 2
        ch.disarm.assert_called_once_with(cue, reason="stop_action")

    @pytest.mark.parametrize(
        "revealed, kind", [(True, "stop_of_playing"), (False, "cancel")]
    )
    def test_pause(self, ch, players, revealed, kind):
        cue, player, client = self._target(ch, players, revealed)
        res = self._run(AH._handle_pause, ch, None, cue, MagicMock())
        assert res["status"] == "applied"
        assert client.cancels() == [([1, 5], True)] and _kinds(player) == [kind]
        assert cue._go_generation == 1, "a pause bumps no generation"

    def test_fade_out_leaves_a_playing_target_sounding(self, ch, players):
        cue, player, client = self._target(ch, players, revealed=True)
        self._run(AH._handle_fade_out, ch, None, cue, MagicMock())
        assert client.cancels() == []

    def test_fade_out_cancels_a_pending_start(self, ch, players):
        cue, player, client = self._target(ch, players, revealed=False)
        self._run(AH._handle_fade_out, ch, None, cue, MagicMock())
        assert _kinds(player) == ["cancel"]

    def test_an_already_stopped_target_sends_nothing(self, ch, players):
        cue, player, client = self._target(ch, players, revealed=True)
        cue._stop_requested = True
        with patch("cuemsengine.cues.ActionHandler.time.sleep"):
            res = self._run(AH._handle_stop, ch, None, cue, MagicMock())
        assert res["status"] == "applied_no_change" and client.cancels() == []

    def test_a_cuelist_target_reaches_its_child(self, ch, players):
        child = _audio()
        player, client = players(child)
        cl = _cuelist(child)
        cl._go_epoch = 0
        ch.disarm = MagicMock()
        with patch("cuemsengine.cues.ActionHandler.time.sleep"):
            self._run(AH._handle_stop, ch, None, cl, MagicMock())
        assert client.cancels() == [([1, 5], True)]

    def test_play_no_longer_clears_the_stop_flag_unlocked(self, ch):
        """S0-9: go()'s commit section clears it, under the lock."""
        target = SimpleNamespace(
            id="T", _local=False, enabled=True, loaded=True, _stop_requested=True
        )
        ch.go_from = MagicMock()
        AH._handle_play(ch, None, target, MagicMock())
        assert target._stop_requested is True
        ch.go_from.assert_called_once()


class TestDisarm:
    """Row 19: any disarm of a following selfgate cue, belt and braces."""

    def _disarm(self, ch, cue, reason):
        ch._release_cue_resources = MagicMock()
        ch.disarm(cue, reason=reason)

    def test_a_disarm_cancels_a_following_player(self, ch, players):
        cue = _audio(revealed=True)
        player, client = players(cue)
        self._disarm(ch, cue, "disabled")
        assert client.cancels() == [([1, 5], True)]
        assert _kinds(player) == ["stop_of_playing"]

    def test_not_at_the_natural_end(self, ch, players):
        cue = _audio(revealed=True)
        _, client = players(cue)
        self._disarm(ch, cue, "cue_end")
        assert client.cancels() == []

    def test_not_to_an_older_player(self, ch, players):
        cue = _audio(revealed=True)
        player, client = players(cue, caps=OLD, follow=False)
        player.may_follow = True
        self._disarm(ch, cue, "stop_action")
        assert client.cancels() == []


class TestFadeBeforeTheDisconnect:
    """D12, review 4 m4: the disconnect (the first hard cut) waits transit +
    one period + fade_ms + margin after the /cancelstart."""

    def test_kill_waits_for_the_fade_then_disconnects(self):
        player = _player()
        player.p = MagicMock()
        player.p.poll.return_value = None
        player.fade_deadline = monotonic() + 0.03
        order = []
        mixer = MagicMock()
        mixer.disconnect_player.side_effect = lambda *a: order.append("disconnect")
        mixer.conn_man.port_exists.return_value = False
        saved = PLAYER_HANDLER._audio_mixer
        PLAYER_HANDLER._audio_mixer = mixer
        try:
            with patch(
                "cuemsengine.players.PlayerHandler.sleep",
                side_effect=lambda s: order.append(("sleep", s)),
            ):
                PLAYER_HANDLER._kill_audio_player(player, None, "abc-def")
        finally:
            PLAYER_HANDLER._audio_mixer = saved
        assert order[0][0] == "sleep" and 0 < order[0][1] <= 0.03
        assert order[1] == "disconnect"

    def test_nothing_to_wait_for_without_a_cancel(self):
        player = _player()
        player.p = MagicMock()
        order = []
        mixer = MagicMock()
        mixer.disconnect_player.side_effect = lambda *a: order.append("disconnect")
        mixer.conn_man.port_exists.return_value = False
        saved = PLAYER_HANDLER._audio_mixer
        PLAYER_HANDLER._audio_mixer = mixer
        try:
            with patch(
                "cuemsengine.players.PlayerHandler.sleep",
                side_effect=lambda s: order.append(("sleep", s)),
            ):
                PLAYER_HANDLER._kill_audio_player(player, None, "abc-def")
        finally:
            PLAYER_HANDLER._audio_mixer = saved
        assert order[0] == "disconnect"


class TestStopPlaybackWait:
    """m3: STOP waits max(50 ms, the longest fade still running)."""

    @pytest.mark.parametrize("pending, waited", [(0.02, 0.05), (0.09, 0.09)])
    def test_wait(self, pending, waited):
        import importlib

        NE = importlib.import_module("cuemsengine.NodeEngine")
        node = object.__new__(NE.NodeEngine)
        node.script = None
        node.set_status = MagicMock()
        node._gradient_cancel_all = MagicMock()
        node._dmx_reset = MagicMock()
        node.unload_video_devs = MagicMock()
        with (
            patch.object(NE.CUE_HANDLER, "stop_all_cues"),
            patch.object(NE.PLAYER_HANDLER, "kill_all_audio_players"),
            patch.object(NE.PLAYER_HANDLER, "cleanup_zombie_jack_clients"),
            patch.object(NE.START_GATE, "pending_fade_wait_s", return_value=pending),
            patch("cuemsengine.NodeEngine.sleep") as sleep,
        ):
            node.stop_playback()
        sleep.assert_called_once_with(waited)
