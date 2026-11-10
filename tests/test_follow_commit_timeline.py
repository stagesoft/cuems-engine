# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""869feynrj §4.2 (cuems-RELATIONS Plans/2026-11-03-audio-first-pass-head-
869feynrj.md, §7.1 "Engine"): the per-cue timeline of a selfgate AudioCue.

- setup at max(now, start - 5 s), illumination at the arrival and the follow
  commit at start label - F are taken in due-time order (N1, review 4 M3):
  prewait 0 -> the commit before the illumination; prewait >= 1 s -> lit at
  its arrival, committed at start - F; a CueList child commits at its
  PARENT's start - F (S0-11) and the parent reveals at that start (m9);
- the commit is ``/mtcfollow 1``, decided and sent under CueHandler._lock
  (S0-3), refused when the pass was stopped, superseded, or its start never
  sent (``_reveal_ready``, F11); a stale thread never sends (S0-2);
- F per node from its latency, due from the rounded label (review 4 M2): the
  rows are timeline_model.py's A2f fixtures (REALISTIC x PREWAITS), checked
  against the model's own success condition (the follow lands before the
  callback that would start the player late: lead > latency + period +
  transit);
- the reveal of a follow-committed cue sends no start and no follow, only
  ``/loop`` in wrap mode.

go_threaded runs for real (run_audioCue, run_cueList, reveal_cue included);
MTC is a fake that advances by each patched sleep, the player a real
AudioPlayer object with CAPS selfgate that never starts.
"""

import uuid
from threading import Lock
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from cuemsutils.cues import AudioCue, CueList
from cuemsutils.tools.CTimecode import CTimecode

from cuemsengine.cues import go_lead
from cuemsengine.cues.CueHandler import CueHandler, _SetupGuard
from cuemsengine.cues.run_cue import installed_guard, reveal_cue, run_cue
from cuemsengine.players.AudioPlayer import AudioPlayer
from cuemsengine.players.PlayerHandler import PLAYER_HANDLER
from cuemsengine.players.StartGate import START_GATE

SELFGATE = frozenset({"loop", "varispeed", "dayalign", "selfgate"})
OLD = frozenset({"loop", "varispeed", "dayalign"})
# timeline_model.py REALISTIC (latency, period) of a jackd -n3 / -n4 rig
REALISTIC = [(32.0, 512 / 48), (64.0, 1024 / 48), (85.3, 1024 / 48)]
PREWAITS = (0.0, 10.0, 50.0, 100.0, 119.0, 120.0, 121.0, 500.0, 2000.0)


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
    def __init__(self, mtc, lock=None):
        self.mtc, self.lock, self.sent = mtc, lock, []

    def set_value(self, path, value):
        locked = self.lock.locked() if self.lock is not None else None
        self.sent.append((self.mtc.now, path, value, locked))

    def get_node(self, path):
        last = [v for _, p, v, _ in self.sent if p == path]
        return SimpleNamespace(
            parameter=SimpleNamespace(value=last[-1] if last else None)
        )

    def times(self, path, value=None):
        return [
            t for t, p, v, _ in self.sent if p == path and (value is None or v == value)
        ]


class _Proc:
    def poll(self):
        return None


def _player(caps=SELFGATE):
    p = AudioPlayer(port=0, path="cuems-audioplayer", args="", media="a.wav")
    p.caps = caps
    p.ready.set()
    p.p = _Proc()
    return p


def _audio(prewait_ms=0.0, gen=1):
    d = {
        "id": str(uuid.uuid4()),
        "name": "t",
        "loop": 1,
        "Media": {
            "file_name": "a.wav",
            "id": str(uuid.uuid4()),
            "duration": "00:00:01.000",
        },
    }
    cue = AudioCue(d)
    cue.prewait = CTimecode(start_seconds=prewait_ms / 1000)
    cue.post_go = "pause"
    cue._local = True
    cue.loaded = True
    cue._target_object = None
    cue._stop_requested = False
    cue._go_generation = gen
    cue._revealed = False
    return cue


def _cuelist(child, prewait_ms=0.0, gen=1):
    cl = CueList({"id": str(uuid.uuid4()), "name": "cl", "contents": [child]})
    cl.prewait = CTimecode(start_seconds=prewait_ms / 1000)
    cl.post_go = "pause"
    cl._local = True
    cl.loaded = True
    cl._target_object = None
    cl._stop_requested = False
    cl._go_generation = gen
    cl._revealed = False
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
    ch.out_latency_ms = out_latency_ms
    return ch


@pytest.fixture(autouse=True)
def quiet_gate():
    START_GATE.autostart = False
    yield
    START_GATE.reset_for_tests()
    START_GATE.autostart = True


def _drive(
    ch, cue, mtc, arrival_ms, player, *, audio=None, on_sleep=None, before_reveal=None
):
    """go_threaded for real, the players patched in. Returns the events:
    {"illum": [mtc], "commit": [mtc], "reveal": [mtc]}."""
    audio = audio or cue
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
        if before_reveal is not None:
            before_reveal(c)
        return reveal_cue(c, m, start_ms)

    with (
        patch.object(
            PLAYER_HANDLER, "audio_player", lambda c: player if c is audio else None
        ),
        patch.object(PLAYER_HANDLER, "get_audio_mixer", lambda: None),
        patch("cuemsengine.cues.CueHandler.sleep", side_effect=sleep),
        patch("cuemsengine.cues.CueHandler.reveal_cue", side_effect=reveal),
        patch("cuemsengine.cues.CueHandler.loop_cue"),
        patch("cuemsengine.cues.CueHandler.blank_cue"),
    ):
        ch.go_threaded(cue, mtc, frozen_mtc_ms=arrival_ms, go_gen=cue._go_generation)
    events["commit"] = audio._osc.times("/mtcfollow", 1)
    return events


def _label(ms):
    return CTimecode(framerate=25, start_seconds=ms / 1000).milliseconds_exact


class TestOrder:
    @pytest.mark.parametrize("phase", [0.0, 7.0, 19.5, 33.0, 39.0])
    def test_operator_go_prewait_0_commits_before_lighting_and_leads(self, phase):
        """The review's missing row: an operator GO with prewait 0 commits its
        follow >= L - delta before its start, then lights at its arrival."""
        ch = _ch(out_latency_ms=42.7)
        g = 100_000.0 + phase
        lead, _, _ = go_lead.go_lead_ms({"node01": 42.7})
        anchor = go_lead.ceil_frame(g + lead)
        mtc = _Mtc(g)
        cue = _audio(0.0)
        cue._osc = _Client(mtc, ch._lock)
        ev = _drive(ch, cue, mtc, anchor, _player())
        assert len(ev["commit"]) == 1
        t_commit = ev["commit"][0]
        assert anchor - t_commit >= lead - go_lead.GO_LEAD_DELTA_MS
        assert t_commit <= ev["illum"][0]
        assert ev["illum"][0] >= anchor  # lights at its arrival = its start
        assert ev["reveal"] and ev["reveal"][0] >= anchor
        # D11: the start the player gets is the led anchor, on the 40 ms grid,
        # and not before the press + L
        (start_tod,) = [v for _, p, v, _ in cue._osc.sent if p == "/start_tod"]
        assert start_tod == round(anchor) % 86_400_000
        assert anchor % 40.0 == 0.0 and anchor >= g + lead

    def test_prewait_2s_lights_at_arrival_and_commits_at_start_minus_F(self):
        ch = _ch()
        mtc = _Mtc(1000.0)
        cue = _audio(2000.0)
        cue._osc = _Client(mtc, ch._lock)
        ev = _drive(ch, cue, mtc, 1000.0, _player())
        assert 1000.0 <= ev["illum"][0] < 1000.0 + 20
        due = _label(3000.0) - CueHandler._FOLLOW_LEAD_MS
        assert due <= ev["commit"][0] < due + 20
        assert ev["illum"][0] < ev["commit"][0]

    def test_prewait_beyond_the_setup_window_still_lights_at_arrival(self):
        """N1 / M3: with the setup first a prewait > 5 s lit seconds late."""
        ch = _ch()
        mtc = _Mtc(1000.0)
        cue = _audio(7000.0)
        cue._osc = _Client(mtc, ch._lock)
        ev = _drive(ch, cue, mtc, 1000.0, _player())
        assert 1000.0 <= ev["illum"][0] < 1020.0
        setup_t = cue._osc.times("/start_tod")[0]
        assert setup_t >= 8000.0 - CueHandler._RUN_AHEAD_MS
        assert ev["illum"][0] < setup_t < ev["commit"][0]

    def test_cuelist_child_commits_at_the_parents_start_minus_F(self):
        """S0-11: the child plays at the parent's start (its own prewait is
        ignored); review 4 m9: the parent reveals at that start, not at once."""
        ch = _ch()
        mtc = _Mtc(1000.0)
        child = _audio(9999.0)
        child._osc = _Client(mtc, ch._lock)
        parent = _cuelist(child, prewait_ms=2000.0)
        revealed_early = []

        def watch(now):
            if now < 3000.0 and parent._revealed:
                revealed_early.append(now)

        ev = _drive(ch, parent, mtc, 1000.0, _player(), audio=child, on_sleep=watch)
        due = _label(3000.0) - CueHandler._FOLLOW_LEAD_MS
        assert due <= ev["commit"][0] < due + 20
        assert ev["reveal"][0] >= 3000.0
        assert revealed_early == []

    def test_an_older_player_keeps_todays_reveal_time_follow(self):
        ch = _ch()
        mtc = _Mtc(1000.0)
        cue = _audio(2000.0)
        cue._osc = _Client(mtc, ch._lock)
        _drive(ch, cue, mtc, 1000.0, _player(OLD))
        follows = cue._osc.times("/mtcfollow", 1)
        assert len(follows) == 1 and follows[0] >= 3000.0


class TestPerNodeF:
    """timeline_model.py A2f (the rev 2.6 fix, 27/27 PASS in the model): F
    per node, due from the start label. The model's success condition is
    that the follow lands before the callback that would start the player
    late: commit lead > latency + period + transit (5 ms)."""

    @pytest.mark.parametrize("lat, per", REALISTIC)
    @pytest.mark.parametrize("prewait", PREWAITS)
    def test_commit_lead_covers_latency_and_period(self, lat, per, prewait):
        out = lat + per
        ch = _ch(out_latency_ms=out)
        lead, _, _ = go_lead.go_lead_ms({"n": out})
        g = 50_000.0 + 13.0
        anchor = go_lead.ceil_frame(g + lead)
        mtc = _Mtc(g)
        cue = _audio(prewait)
        cue._osc = _Client(mtc, ch._lock)
        ev = _drive(ch, cue, mtc, anchor, _player())
        label = _label(anchor + prewait)
        assert label - ev["commit"][0] > out + 5.0

    def test_follow_lead_values(self):
        assert go_lead.follow_lead_ms(None) == 120.0
        assert go_lead.follow_lead_ms(42.7) == 120.0
        assert go_lead.follow_lead_ms(85.3 + 1024 / 48) == pytest.approx(156.63, 0.01)


class TestCommitRefusals:
    def _ready(self):
        ch = _ch()
        mtc = _Mtc(0.0)
        cue = _audio()
        cue._osc = _Client(mtc, ch._lock)
        cue._reveal_ready = True
        cue._start_mtc = CTimecode(framerate=25, start_seconds=1.0)
        return ch, cue, _player()

    def _commit(self, ch, cue, player, gen=1):
        with patch.object(PLAYER_HANDLER, "audio_player", lambda c: player):
            return ch._commit_follow(cue, cue, gen)

    def test_commit_sends_under_the_lock(self):
        ch, cue, player = self._ready()
        assert self._commit(ch, cue, player) is True
        assert [(p, v, locked) for _, p, v, locked in cue._osc.sent] == [
            ("/mtcfollow", 1, True)
        ]
        assert player.may_follow is True and cue._follow_committed is True
        assert cue._follow_gen == 1

    def test_refused_when_stopped(self):
        ch, cue, player = self._ready()
        cue._stop_requested = True
        assert self._commit(ch, cue, player) is False
        assert cue._osc.sent == [] and player.may_follow is False

    def test_refused_when_the_generation_changed(self):
        ch, cue, player = self._ready()
        cue._go_generation = 2
        assert self._commit(ch, cue, player, gen=1) is False
        assert cue._osc.sent == []

    def test_refused_without_its_start(self):
        ch, cue, player = self._ready()
        cue._reveal_ready = False
        assert self._commit(ch, cue, player) is False
        assert cue._osc.sent == []

    def test_never_to_an_older_player(self):
        ch, cue, _ = self._ready()
        assert self._commit(ch, cue, _player(OLD)) is False
        assert cue._osc.sent == []

    def test_a_superseding_go_inside_the_commit_wait_refuses_the_old_pass(self):
        """'never by a stale thread': a superseding GO lands within 20 ms of
        the old pass's last poll before its commit."""
        ch = _ch()
        mtc = _Mtc(1000.0)
        cue = _audio(2000.0)
        cue._osc = _Client(mtc, ch._lock)
        due = _label(3000.0) - CueHandler._FOLLOW_LEAD_MS

        def supersede(now):
            if now >= due - 15 and cue._go_generation == 1:
                cue._go_generation = 2

        _drive(ch, cue, mtc, 1000.0, _player(), on_sleep=supersede)
        assert cue._osc.times("/mtcfollow") == []


class TestStaleSetup:
    """S0-2: the held setup re-checks its pass under the lock before it
    sends; a stale one sends nothing and changes nothing."""

    def _cue(self):
        mtc = _Mtc(0.0)
        cue = _audio()
        cue._osc = _Client(mtc)
        cue._start_mtc = "untouched"
        return mtc, cue

    def _run(self, cue, mtc, guard):
        with (
            patch.object(PLAYER_HANDLER, "audio_player", lambda c: _player()),
            patch.object(PLAYER_HANDLER, "get_audio_mixer", lambda: None),
            installed_guard(guard),
        ):
            run_cue(cue, mtc, 2000.0)

    def test_a_superseded_setup_sends_nothing(self):
        mtc, cue = self._cue()
        guard = _SetupGuard(Lock(), cue, go_gen=0)  # the cue is at gen 1
        self._run(cue, mtc, guard)
        assert guard.refused and cue._osc.sent == []
        assert cue._start_mtc == "untouched"

    def test_a_stopped_setup_sends_nothing(self):
        mtc, cue = self._cue()
        cue._stop_requested = True
        guard = _SetupGuard(Lock(), cue, go_gen=1)
        self._run(cue, mtc, guard)
        assert guard.refused and cue._osc.sent == []

    def test_a_current_setup_sends_under_the_lock(self):
        mtc, cue = self._cue()
        lock = Lock()
        cue._osc.lock = lock
        guard = _SetupGuard(lock, cue, go_gen=1)
        self._run(cue, mtc, guard)
        assert not guard.refused
        assert [p for _, p, _, _ in cue._osc.sent] == [
            "/start_tod",
            "/loop",
            "/volmaster",
        ]
        assert all(locked for *_, locked in cue._osc.sent)
        assert cue._reveal_ready is True and cue._follow_committed is False


class TestReveal:
    def test_follow_committed_reveal_sends_nothing_in_once_mode(self):
        mtc = _Mtc(0.0)
        cue = _audio()
        cue._osc = _Client(mtc)
        cue._reveal_ready = True
        cue._follow_committed = True
        cue._start_mtc = CTimecode(framerate=25, start_seconds=1.0)
        reveal_cue(cue, mtc, 1000.0)
        assert cue._osc.sent == []

    def test_follow_committed_reveal_resends_loop_in_wrap_mode(self):
        mtc = _Mtc(0.0)
        cue = _audio()
        cue._osc = _Client(mtc)
        cue._reveal_ready = True
        cue._follow_committed = True
        cue._wrap_requested = True
        cue._wrap_fallback = False
        cue.loop = 3
        cue._loop_period = SimpleNamespace(num=19200, den=48000)
        with patch(
            "cuemsengine.cues.run_cue.loop_mode.period_of",
            lambda c: SimpleNamespace(num=19200, den=48000),
        ):
            reveal_cue(cue, mtc, 1000.0)
        assert [(p, v) for _, p, v, _ in cue._osc.sent] == [
            ("/loop", [3, 19200, 48000])
        ]
        assert cue._wrap_reveal_t is not None


class TestPassOwnership:
    """Review of 4b4987c..c554465, fixes 2, 6, 7."""

    def test_the_reveal_uses_the_decision_taken_under_the_lock(self):
        """Fix 7: a re-GO's setup can reset _follow_committed between the
        reveal's lock section and reveal_audioCue; the reveal must keep the
        decision it took under the lock (no second start, no second follow)."""
        ch = _ch()
        mtc = _Mtc(1000.0)
        cue = _audio(2000.0)
        cue._osc = _Client(mtc, ch._lock)

        def racing_setup(c):
            c._follow_committed = False  # a re-GO's setup, after the lock

        _drive(ch, cue, mtc, 1000.0, _player(), before_reveal=racing_setup)
        assert len(cue._osc.times("/mtcfollow", 1)) == 1
        assert len(cue._osc.times("/start_tod")) == 1

    def test_a_reveal_time_follow_to_a_selfgate_player_marks_it_following(self):
        """Fix 2: when the commit did not happen (its send raised), the
        reveal's legacy /mtcfollow 1 leaves the player following: STOP, pause
        and stop must still reach it with /cancelstart."""
        ch = _ch()
        mtc = _Mtc(1000.0)
        cue = _audio(2000.0)
        player = _player()

        class _FlakyClient(_Client):
            failed = False

            def set_value(self, path, value):
                if path == "/mtcfollow" and not self.failed:
                    self.failed = True
                    raise RuntimeError("send failed")
                super().set_value(path, value)

        cue._osc = _FlakyClient(mtc, ch._lock)
        _drive(ch, cue, mtc, 1000.0, player)
        assert cue._osc.times("/mtcfollow", 1)  # the reveal's legacy follow
        assert player.may_follow is True
        assert player.follow_pass == (str(cue.id), cue._go_generation)
        assert START_GATE.cancel(cue, player, cue._osc, "stop_of_playing") is not None


class TestLegacyEndOfPass:
    """Fix 6: the end-of-pass /mtcfollow 0 compares the cue's generation with
    the PASS's own, not with the one read at loop entry: a GO landing between
    the reveal and the loop entry (H3) must not have its follow undone."""

    def _loop(self, cue_gen, pass_gen):
        from cuemsengine.cues.loop_cue import loop_cue
        from cuemsengine.cues.run_cue import installed_pass

        mtc = SimpleNamespace(main_tc=CTimecode(framerate=25, start_seconds=10.0))
        cue = _audio()
        cue._start_mtc = CTimecode(framerate=25, start_seconds=1.0)
        cue._end_mtc = CTimecode(framerate=25, start_seconds=2.0)
        cue._go_generation = cue_gen
        cue._osc = _Client(_Mtc(0.0))
        with (
            patch.object(PLAYER_HANDLER, "audio_player", lambda c: None),
            installed_pass(pass_gen, cue),
        ):
            loop_cue(cue, mtc)
        return cue._osc.times("/mtcfollow", 0)

    def test_the_owning_pass_ends_its_follow(self):
        assert len(self._loop(cue_gen=1, pass_gen=1)) == 1

    def test_a_superseded_pass_sends_no_follow_off(self):
        assert self._loop(cue_gen=2, pass_gen=1) == []


class TestCueListChildGuard:
    """Review C2 (cuems-RELATIONS baselines/869feynrj-step5/reviews/
    engine-visible-at-marked.md), the audio side of S0-11: a CueList child
    disabled (cancel_parked: the setup marked it _playing, so it is flagged),
    paused or GO'd on its own between the parent's setup and start - F gets
    no /mtcfollow 1, neither from the commit nor from the reveal."""

    def _marked(self, ch, mtc=None):
        mtc = mtc or _Mtc(0.0)
        child = _audio()
        child._osc = _Client(mtc, ch._lock)
        child._reveal_ready = True
        child._start_mtc = CTimecode(framerate=25, start_seconds=1.0)
        parent = _cuelist(child)
        ch._mark_cuelist_child(parent, 1)
        return parent, child

    def _commit(self, ch, parent, child, player):
        with patch.object(PLAYER_HANDLER, "audio_player", lambda c: player):
            return ch._commit_follow(parent, child, 1)

    def test_a_marked_child_commits(self):
        ch = _ch()
        parent, child = self._marked(ch)
        assert self._commit(ch, parent, child, _player()) is True
        assert child._osc.times("/mtcfollow", 1) == [0.0]

    def test_disabled_and_cancelled_after_the_setup(self):
        ch = _ch()
        parent, child = self._marked(ch)
        child.enabled = False
        player = _player()
        with patch.object(PLAYER_HANDLER, "audio_player", lambda c: player):
            assert ch.cancel_parked(child) is True
        assert self._commit(ch, parent, child, player) is False
        assert child._osc.times("/mtcfollow") == [] and player.may_follow is False

    def test_paused_after_the_setup(self):
        ch = _ch()
        parent, child = self._marked(ch)
        child._stop_requested = True  # what an ActionCue pause sets
        assert self._commit(ch, parent, child, _player()) is False
        assert child._osc.times("/mtcfollow") == []

    def test_a_newer_own_pass_of_the_child(self):
        ch = _ch()
        parent, child = self._marked(ch)
        child._go_generation += 1
        assert self._commit(ch, parent, child, _player()) is False

    def test_disabled_mid_window_sends_no_follow_at_all(self):
        ch = _ch()
        mtc = _Mtc(1000.0)
        child = _audio(9999.0)
        child._osc = _Client(mtc, ch._lock)
        parent = _cuelist(child, prewait_ms=2000.0)

        def disable(now):
            if now >= 2000.0 and child.enabled:
                child.enabled = False
                ch.cancel_parked(child)

        ev = _drive(ch, parent, mtc, 1000.0, _player(), audio=child, on_sleep=disable)
        assert ev["commit"] == []
        assert child._osc.times("/mtcfollow") == []

    def test_the_reveal_skips_a_child_disabled_after_the_setup(self):
        """The reveal guard, type-agnostic: an older player's child gets its
        follow at the reveal (no commit), so only the guard stops it; and
        reveal_cueList must not fall through to the next enabled child,
        which was never set up."""
        ch = _ch()
        mtc = _Mtc(1000.0)
        child = _audio(0.0)
        other = _audio(0.0)
        child._osc = _Client(mtc, ch._lock)
        other._osc = _Client(mtc, ch._lock)
        parent = CueList(
            {"id": str(uuid.uuid4()), "name": "cl", "contents": [child, other]}
        )
        parent.prewait = CTimecode(start_seconds=2.0)
        parent.post_go = "pause"
        parent._local = True
        parent.loaded = True
        parent._target_object = None
        parent._stop_requested = False
        parent._go_generation = 1
        parent._revealed = False
        # Without a commit a CueList reveals as soon as its setup is done (its
        # own _start_mtc is the cuems-utils default 0); a start of its own
        # opens the window the guard is about.
        parent._start_mtc = CTimecode(framerate=25, start_seconds=3.0)

        def disable(now):
            if now >= 2000.0 and child.enabled:
                child.enabled = False
                ch.cancel_parked(child)

        ev = _drive(
            ch, parent, mtc, 1000.0, _player(OLD), audio=child, on_sleep=disable
        )
        # The parent's pass reaches its reveal point (its reveal section sets
        # _revealed) and the guard then sends no reveal at all: without the
        # guard reveal_cue runs (ev["reveal"] not empty) and reveal_cueList
        # gives `other` a reveal-time /mtcfollow 1.
        assert parent._revealed is True
        assert ev["reveal"] == []
        assert child._osc.times("/mtcfollow") == []
        assert other._osc.sent == []
