# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""869feynrj §4.3 "Cancel records", §4.5e, §8: the engine's per-player follow /
cancel state, the cancel records, the ack watchdog and the START lines
(players.StartGate). The scenarios are cuems-RELATIONS
baselines/869feynrj-model/cancel_model.py's B rows that live at this layer:
the ack match by seq (M1), the WARNING only for a cancel record whose player
had started (D5), none for stop_of_playing (D10/D12, m6), one re-send then
ERROR (G5, R5), a newer commit closing older records (B3/B4), a kill closing
them (B12).

The watchdog is driven by hand (``scan(now)``), on a gate built with
``autostart=False``; the players are real AudioPlayer objects that never
start, with a fake process.
"""

from time import monotonic
from unittest.mock import patch

import pytest

from cuemsengine.players.AudioPlayer import AudioPlayer
from cuemsengine.players.Player import CancelAck, LatencyLine, StartLine
from cuemsengine.players.StartGate import ACK_TIMEOUT_S, StartGate, fade_wait_ms

LOG = "cuemsengine.players.StartGate.Logger"
EPS = 1e-6  # monotonic() + 0.1 - monotonic() can read 0.0999999


class _Proc:
    def __init__(self, alive=True):
        self.alive = alive

    def poll(self):
        return None if self.alive else 0


class _Client:
    def __init__(self):
        self.sent = []

    def set_value(self, path, value):
        self.sent.append((path, value))


class _Cue:
    def __init__(self, cid="cue-1", seeded=False):
        self.id = cid
        self._pass_seeded = seeded


def _player(alive=True):
    p = AudioPlayer(port=0, path="cuems-audioplayer", args="", media="m.wav")
    p.p = _Proc(alive)
    p.caps = frozenset({"loop", "varispeed", "dayalign", "selfgate"})
    return p


@pytest.fixture
def gate():
    return StartGate(autostart=False)


def _committed(gate, cue=None, gen=1):
    cue = cue or _Cue()
    player, client = _player(), _Client()
    assert gate.commit_follow(cue, player, client, gen)
    return cue, player, client


class TestFollowCommit:
    def test_commit_sends_follow_and_marks_the_player(self, gate):
        cue, player, client = _committed(gate, gen=3)
        assert client.sent == [("/mtcfollow", 1)]
        assert player.may_follow is True
        assert player.follow_pass == ("cue-1", 3)

    def test_a_newer_commit_closes_older_records(self, gate):
        cue, player, client = _committed(gate, gen=1)
        gate.cancel(cue, player, client, "cancel")
        assert player.cancel_records
        gate.commit_follow(cue, player, client, 2)
        assert player.cancel_records == {}

    def test_follow_off_clears_may_follow(self, gate):
        cue, player, client = _committed(gate)
        assert gate.follow_off(player, client) is True
        assert client.sent[-1] == ("/mtcfollow", 0) and player.may_follow is False

    def test_follow_off_of_a_superseded_pass_sends_nothing(self, gate):
        cue, player, client = _committed(gate)
        assert gate.follow_off(player, client, still_current=lambda: False) is False
        assert client.sent == [("/mtcfollow", 1)] and player.may_follow is True


class TestSendFollow:
    """Review fix 2: the reveal's fallback /mtcfollow 1 to a selfgate player
    (its follow commit did not happen) marks it following this pass."""

    def test_marks_the_player_following_this_pass(self, gate):
        player, client = _player(), _Client()
        assert gate.send_follow(player, client, _Cue(), 7) is True
        assert client.sent == [("/mtcfollow", 1)]
        assert player.may_follow is True and player.follow_pass == ("cue-1", 7)
        assert gate.cancel(_Cue(), player, client, "stop_of_playing") is not None

    def test_a_stale_pass_sends_nothing(self, gate):
        player, client = _player(), _Client()
        assert gate.send_follow(player, client, _Cue(), 7, lambda: False) is False
        assert client.sent == [] and player.may_follow is False


class TestCancel:
    def test_cancel_sends_seq_and_fade_and_records_it(self, gate):
        cue, player, client = _committed(gate, gen=4)
        rec = gate.cancel(cue, player, client, "cancel")
        assert client.sent[-1] == ("/cancelstart", [1, 5])
        assert rec.seq == 1 and rec.kind == "cancel" and rec.pass_id == ("cue-1", 4)
        assert player.may_follow is False
        assert player.cancel_records == {1: rec}

    def test_seq_is_per_player(self, gate):
        cue, player, client = _committed(gate)
        gate.cancel(cue, player, client, "cancel")
        gate.commit_follow(cue, player, client, 2)
        rec = gate.cancel(cue, player, client, "stop_of_playing", fade_ms=40)
        assert rec.seq == 2 and client.sent[-1] == ("/cancelstart", [2, 40])
        _, other, other_client = _committed(gate, _Cue("cue-2"))
        assert gate.cancel(_Cue("cue-2"), other, other_client, "cancel").seq == 1

    def test_nothing_to_a_player_that_does_not_follow(self, gate):
        player, client = _player(), _Client()
        assert gate.cancel(_Cue(), player, client, "stop_of_playing") is None
        assert client.sent == []

    def test_a_second_cancel_sends_nothing_more(self, gate):
        """The second stop_all_cues of a STOP (S0-4) and every belt-and-braces
        path find may_follow cleared by the first cancel."""
        cue, player, client = _committed(gate)
        gate.cancel(cue, player, client, "stop_of_playing")
        assert gate.cancel(cue, player, client, "stop_of_playing") is None
        assert [m for m in client.sent if m[0] == "/cancelstart"] == [
            ("/cancelstart", [1, 5])
        ]

    def test_the_cancel_sets_the_fade_deadline(self, gate):
        cue, player, client = _committed(gate)
        player.latency = LatencyLine(1536, 48000, 512)
        t0 = monotonic()
        gate.cancel(cue, player, client, "stop_of_playing")
        # transit + one period + fade_ms + margin: >= 25 ms at 5 ms (D12, m4)
        assert fade_wait_ms(player) >= 25.0
        assert player.fade_deadline == pytest.approx(
            t0 + fade_wait_ms(player) / 1000, abs=0.01
        )
        assert 0 < gate.fade_wait_s(player) <= fade_wait_ms(player) / 1000
        assert gate.pending_fade_wait_s() > 0

    def test_fade_wait_grows_with_fade_ms(self, gate):
        p = _player()
        assert fade_wait_ms(p, 50) - fade_wait_ms(p, 5) == pytest.approx(45.0)

    def test_fade_wait_of_something_else_is_zero(self, gate):
        assert gate.fade_wait_s(object()) == 0.0
        assert gate.close_records(object()) == 0


class TestAck:
    def test_play_ack_on_a_cancel_record_warns_with_the_ms(self, gate):
        cue, player, client = _committed(gate)
        gate.cancel(cue, player, client, "cancel")
        with patch(LOG) as log:
            gate.on_line(player, "cancel", CancelAck(1, "play", 23))
        log.warning.assert_called_once()
        assert "started 23 ms before its cancel; stopped (faded)" in str(
            log.warning.call_args
        )
        assert player.cancel_records == {}

    @pytest.mark.parametrize("state", ["hold", "pastend"])
    def test_hold_or_pastend_ack_is_silent(self, gate, state):
        cue, player, client = _committed(gate)
        gate.cancel(cue, player, client, "cancel")
        with patch(LOG) as log:
            gate.on_line(player, "cancel", CancelAck(1, state, 0))
        log.warning.assert_not_called()

    def test_stop_of_playing_never_warns(self, gate):
        """STOP is always stop_of_playing (m6); D12's stops too."""
        cue, player, client = _committed(gate)
        gate.cancel(cue, player, client, "stop_of_playing")
        with patch(LOG) as log:
            gate.on_line(player, "cancel", CancelAck(1, "play", 900))
        log.warning.assert_not_called()

    def test_ack_is_matched_by_seq_not_by_age(self, gate):
        """B4 (review 4 M1): an id-less ack closed the oldest record."""
        cue, player, client = _committed(gate)
        r1 = gate.cancel(cue, player, client, "cancel")
        player.may_follow = True  # as after a re-follow without a commit
        r2 = gate.cancel(cue, player, client, "stop_of_playing")
        gate.on_line(player, "cancel", CancelAck(r2.seq, "play", 5))
        assert list(player.cancel_records) == [r1.seq]

    def test_unmatched_ack_is_ignored(self, gate):
        cue, player, client = _committed(gate)
        with patch(LOG) as log:
            gate.on_line(player, "cancel", CancelAck(9, "play", 5))
        log.warning.assert_not_called()


class TestWatchdog:
    def _cancelled(self, gate, kind="cancel"):
        cue, player, client = _committed(gate)
        rec = gate.cancel(cue, player, client, kind)
        return cue, player, client, rec

    def test_acked_within_100_ms_nothing_happens(self, gate):
        _, player, client, rec = self._cancelled(gate)
        gate.on_line(player, "cancel", CancelAck(rec.seq, "hold", 0))
        with patch(LOG) as log:
            gate.scan(rec.t_sent + 1.0)
        log.error.assert_not_called()
        assert client.sent.count(("/cancelstart", [1, 5])) == 1

    def test_no_ack_one_resend_with_the_same_seq_then_error(self, gate):
        """R5: a lost /cancelstart is re-sent once; ERROR only when the
        re-send is lost too."""
        _, player, client, rec = self._cancelled(gate)
        with patch(LOG) as log:
            gate.scan(rec.t_sent + 0.05)
            assert client.sent.count(("/cancelstart", [1, 5])) == 1
            gate.scan(rec.t_sent + ACK_TIMEOUT_S + EPS)
            assert client.sent.count(("/cancelstart", [1, 5])) == 2
            log.warning.assert_called_once()
            log.error.assert_not_called()
            gate.scan(rec.t_sent + ACK_TIMEOUT_S + 0.05)
            log.error.assert_not_called()
            gate.scan(rec.t_sent + 2 * ACK_TIMEOUT_S + 2 * EPS)
        log.error.assert_called_once()
        assert client.sent.count(("/cancelstart", [1, 5])) == 2
        assert player.cancel_records == {}

    @pytest.mark.parametrize("start_first", [True, False])
    def test_the_watchdog_ignores_the_start_cancel_order(self, gate, start_first):
        """N4: a lost cancel is caught whatever the order of START and cancel
        (the rev 2.4 detector only fired on a START after the cancel)."""
        cue, player, client = _committed(gate)
        if start_first:
            gate.on_line(player, "start", StartLine(1000, -10, 48000))
        rec = gate.cancel(cue, player, client, "cancel")
        if not start_first:
            gate.on_line(player, "start", StartLine(1000, -10, 48000))
        with patch(LOG) as log:
            gate.scan(rec.t_sent + ACK_TIMEOUT_S + EPS)
            gate.scan(rec.t_sent + 2 * ACK_TIMEOUT_S + 2 * EPS)
        assert client.sent.count(("/cancelstart", [1, 5])) == 2
        log.error.assert_called_once()

    def test_ack_after_the_resend_closes_without_error(self, gate):
        _, player, client, rec = self._cancelled(gate)
        gate.scan(rec.t_sent + ACK_TIMEOUT_S + EPS)
        with patch(LOG) as log:
            gate.on_line(player, "cancel", CancelAck(rec.seq, "play", 30))
            gate.scan(rec.t_sent + 3 * ACK_TIMEOUT_S)
        log.error.assert_not_called()
        log.warning.assert_called_once()  # the cut start (kind cancel)

    def test_a_dead_player_raises_no_error(self, gate):
        """B12: killed before its ack -- closed, no re-send, no ERROR."""
        _, player, client, rec = self._cancelled(gate)
        player.p.alive = False
        with patch(LOG) as log:
            gate.scan(rec.t_sent + 5 * ACK_TIMEOUT_S)
        log.error.assert_not_called()
        assert client.sent.count(("/cancelstart", [1, 5])) == 1

    def test_closed_records_raise_no_error(self, gate):
        _, player, client, rec = self._cancelled(gate)
        assert gate.close_records(player, "killed") == 1
        with patch(LOG) as log:
            gate.scan(rec.t_sent + 5 * ACK_TIMEOUT_S)
        log.error.assert_not_called()
        assert player.may_follow is False

    def test_a_newer_pass_is_never_faded_by_a_resend(self, gate):
        """B3: supersede at start-100 ms with a late/lost ack: the new commit
        closes the old record, so the re-send never reaches pass 2."""
        cue, player, client, rec = self._cancelled(gate)
        gate.commit_follow(cue, player, client, 2)
        gate.scan(rec.t_sent + 3 * ACK_TIMEOUT_S)
        assert client.sent.count(("/cancelstart", [1, 5])) == 1
        assert player.may_follow is True and player.follow_pass == ("cue-1", 2)

    def test_a_resend_for_a_replaced_pass_is_dropped(self, gate):
        cue, player, client, rec = self._cancelled(gate)
        player.follow_pass = ("cue-1", 99)  # replaced without a commit here
        with patch(LOG) as log:
            gate.scan(rec.t_sent + ACK_TIMEOUT_S + EPS)
        assert client.sent.count(("/cancelstart", [1, 5])) == 1
        log.error.assert_not_called()


class TestStartLines:
    """§4.5e: a START target above 3 samples is a WARNING for operator GOs
    and chain cues; for the seeded paths (go_at_end, ActionCue play/fade_in)
    an INFO and one WARNING per cue per load."""

    def test_on_time_start_is_silent(self, gate):
        cue, player, client = _committed(gate)
        with patch(LOG) as log:
            gate.on_line(player, "start", StartLine(1000, -240, 48000))
            gate.on_line(player, "start", StartLine(1000, 3, 48000))
        log.warning.assert_not_called()
        assert player.starts_since_commit == 2

    def test_late_start_warns_with_node_and_ms(self, gate):
        gate.set_node_name("node01")
        cue, player, client = _committed(gate)
        with patch(LOG) as log:
            gate.on_line(player, "start", StartLine(1000, 480, 48000))
        text = str(log.warning.call_args)
        assert "cue cue-1 on node node01 started 10.0 ms late (head lost" in text

    def test_snapped_start_is_info_head_kept(self, gate):
        """869feynrj step 5: a START with the player's snap field (late <= 2 ms,
        started at sample 0) is an INFO, never a WARNING, seeded or not."""
        gate.set_node_name("node01")
        for seeded in (False, True):
            cue, player, client = _committed(gate, _Cue(seeded=seeded))
            with patch(LOG) as log:
                gate.on_line(player, "start", StartLine(1000, 57, 44100, True))
            log.warning.assert_not_called()
            text = str(log.info.call_args)
            assert "started 1.3 ms late, head kept (snapped to sample 0" in text

    def test_seeded_late_starts_info_and_one_warning_per_load(self, gate):
        cue, player, client = _committed(gate, _Cue(seeded=True))
        with patch(LOG) as log:
            for _ in range(3):
                gate.on_line(player, "start", StartLine(1000, 480, 48000))
        assert log.warning.call_count == 1
        assert log.info.call_count == 3
        gate.reset_for_load()
        with patch(LOG) as log:
            gate.on_line(player, "start", StartLine(1000, 480, 48000))
        assert log.warning.call_count == 1

    def test_latency_lines_go_to_the_listener(self, gate):
        seen = []
        gate.set_latency_listener(lambda p, lat: seen.append(lat.out_latency_ms))
        gate.on_line(_player(), "latency", LatencyLine(1536, 48000, 512))
        assert seen == [pytest.approx(42.667, abs=1e-3)]


class TestLostFollow:
    """§8 / R5: a follow commit whose START never comes gets /mtcfollow 1
    re-sent once, with a WARNING."""

    def test_no_start_by_the_deadline_resends_the_follow(self, gate):
        cue, player, client = _committed(gate)
        now = monotonic()
        gate.expect_start(cue, player, client, now=now)
        gate.scan(now + 0.01)
        assert client.sent.count(("/mtcfollow", 1)) == 1
        with patch(LOG) as log:
            gate.scan(now + 1.0)
        assert client.sent.count(("/mtcfollow", 1)) == 2
        assert "re-sent /mtcfollow 1" in str(log.warning.call_args)
        gate.scan(now + 2.0)
        assert client.sent.count(("/mtcfollow", 1)) == 2  # once

    def test_a_start_line_satisfies_the_check(self, gate):
        cue, player, client = _committed(gate)
        now = monotonic()
        gate.expect_start(cue, player, client, now=now)
        gate.on_line(player, "start", StartLine(1000, -10, 48000))
        gate.scan(now + 1.0)
        assert client.sent.count(("/mtcfollow", 1)) == 1

    def test_a_cancelled_pass_is_not_refollowed(self, gate):
        cue, player, client = _committed(gate)
        now = monotonic()
        gate.expect_start(cue, player, client, now=now)
        gate.cancel(cue, player, client, "cancel")
        gate.scan(now + 1.0)
        assert client.sent.count(("/mtcfollow", 1)) == 1
