# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""869feynrj §4.5b-e, D8, D11 (cuems-RELATIONS Plans/2026-11-03-audio-first-
pass-head-869feynrj.md, §7.1 "Engine"): the GO lead.

- the interpolated anchor: between two whole frames it advances with the
  monotonic clock, never by more than a frame (one (value, stamp) pair);
- each node knows its output latency before any audio cue arms (settings,
  JACK), raises it from a LATENCY line, reports a new maximum (STATUS) and
  carries it in armed_ready (N3); the controller keeps the per-node maximum;
- L = max(floor, max over required nodes of latency + delta + margin),
  capped with a WARNING naming the node; a node without one does not raise
  L (INFO); the controller ships interpolated MTC + L ceiled to the frame
  (D11) and lead_ms; the node accepts it against anchor - lead_ms, falls
  back to local + L; seeds are never led (S0-13);
- the pass tag the late-START rules read (§4.5e): seeded for go_from, not
  for an operator GO, inherited by chain cues.

timeline_model.py rows: A1 (L per latency/period), A5 (an rc6-7 node's check
against a led anchor, R15), A7 (mixed cluster: one L from the slowest node),
A8 (the cap).
"""

from threading import Lock
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from cuemsengine.cues import go_lead
from cuemsengine.cues.CueHandler import CueHandler, _dispatch_tag
from cuemsengine.tools.MtcListener import MtcListener

# The step-3 constants (go_lead.py), every expectation below derives from them.
DELTA, MARGIN = go_lead.GO_LEAD_DELTA_MS, go_lead.GO_LEAD_MARGIN_MS
FLOOR, CAP = go_lead.GO_LEAD_FLOOR_MS, go_lead.GO_LEAD_MAX_MS
RIG_OUT = 32.0 + 512 / 48  # the usual rig: 1536 frames + a 512 period, 48 kHz


def _lead(*out_latencies):
    """L by the rule (plan §4.5d): max(floor, out + delta + margin), capped."""
    return min(CAP, max([FLOOR] + [o + DELTA + MARGIN for o in out_latencies]))


class TestGoLeadRule:
    def test_floor_without_latencies(self):
        assert go_lead.go_lead_ms({})[0] == go_lead.GO_LEAD_FLOOR_MS
        assert go_lead.go_lead_ms({"old": None})[0] == go_lead.GO_LEAD_FLOOR_MS

    @pytest.mark.parametrize(
        "lat, per",
        [(32.0, 512 / 48), (64.0, 1024 / 48), (85.3, 1024 / 48), (10.0, 5.3)],
    )
    def test_latency_plus_delta_plus_margin(self, lat, per):
        """timeline_model A1: L = max(floor, latency + period + delta + margin)."""
        assert go_lead.go_lead_ms({"n": lat + per})[0] == pytest.approx(
            max(FLOOR, lat + per + DELTA + MARGIN), abs=1e-9
        )

    def test_the_usual_rig_runs_on_the_floor(self):
        """Step 3 (Ion, 2026-11-06): the rig's term is 42.7 + 30 + 5 = 77.7 ms,
        under the 80 ms floor: L = 80 there."""
        assert RIG_OUT + DELTA + MARGIN == pytest.approx(77.667, abs=1e-3)
        assert go_lead.go_lead_ms({"n": RIG_OUT})[0] == FLOOR == 80.0
        assert go_lead.lead_source({"n": RIG_OUT}) is None

    def test_one_lead_from_the_slowest_node(self):
        """A7: one L per GO, from the slowest node, for the whole cluster."""
        lead, capped, _ = go_lead.go_lead_ms({"fast": 15.3, "slow": 85.3 + 21.3})
        assert lead == pytest.approx(_lead(15.3, 85.3 + 21.3)) and capped is None
        assert lead > FLOOR
        assert go_lead.lead_source({"fast": 15.3, "slow": 106.6}) == ("slow", 106.6)

    def test_cap_names_the_node(self):
        """A8: a node at 300 ms latency asks 341: capped at 250."""
        lead, capped, wanted = go_lead.go_lead_ms({"a": 42.7, "big": 321.3})
        assert lead == CAP and capped == "big"
        assert wanted == pytest.approx(321.3 + DELTA + MARGIN)

    @pytest.mark.parametrize("ms", [0.0, 1.0, 39.9, 40.0, 79240.0, 79241.5])
    def test_ceil_frame_is_on_the_grid_and_not_before(self, ms):
        c = go_lead.ceil_frame(ms)
        assert c >= ms - 1e-9 and c - ms < 40.0
        assert c / 40.0 == pytest.approx(round(c / 40.0))


class TestInterpolatedMtc:
    def _listener(self, value_ms, stamp, fps=25):
        lst = object.__new__(MtcListener)
        lst.main_tc = SimpleNamespace(milliseconds_exact=value_ms, framerate=fps)
        lst._interp_pair = (value_ms, stamp)
        return lst

    def test_advances_with_the_monotonic_clock(self):
        lst = self._listener(1000.0, stamp=50.0)
        assert lst.interpolated_ms(now=50.0) == 1000.0
        assert lst.interpolated_ms(now=50.012) == pytest.approx(1012.0)
        assert lst.interpolated_ms(now=50.039) == pytest.approx(1039.0)

    def test_never_more_than_a_frame(self):
        lst = self._listener(1000.0, stamp=50.0)
        assert lst.interpolated_ms(now=51.0) == pytest.approx(1040.0)

    def test_before_the_first_frame_it_is_main_tc(self):
        lst = object.__new__(MtcListener)
        lst.main_tc = SimpleNamespace(milliseconds_exact=777.0, framerate=25)
        assert lst.interpolated_ms() == 777.0


def _controller():
    from cuemsengine.ControllerEngine import ControllerEngine

    c = object.__new__(ControllerEngine)
    c._required_nodes = set()
    c._adopted_nodes = set()
    c._run_seq = 7
    c.script = MagicMock()
    c.get_status = MagicMock(return_value="yes")
    c.set_status = MagicMock()
    return c


class TestControllerLatency:
    def test_armed_ready_and_status_keep_the_per_node_maximum(self):
        c = _controller()
        c._adopted_nodes = {"n1"}
        c._cluster_lock = Lock()
        c._armed_nodes = set()
        c._required_nodes = {"n1", "n2"}
        op = SimpleNamespace(
            target="armed_ready",
            sender="n1",
            data={"armed": "yes", "out_latency_ms": 42.7},
        )
        c.status_operation_callback(op)
        c.status_operation_callback(
            SimpleNamespace(
                target="out_latency", sender="n1", data={"out_latency_ms": 85.3}
            )
        )
        c.status_operation_callback(
            SimpleNamespace(
                target="out_latency", sender="n1", data={"out_latency_ms": 50.0}
            )
        )
        assert c._latencies() == {"n1": 85.3}

    def test_status_from_a_foreign_node_is_ignored(self):
        c = _controller()
        c.status_operation_callback(
            SimpleNamespace(
                target="out_latency", sender="x", data={"out_latency_ms": 99.0}
            )
        )
        assert c._latencies() == {}

    def test_lead_from_required_nodes_only(self):
        c = _controller()
        c._required_nodes = {"n1"}
        c._note_node_latency("n1", 85.3)
        c._note_node_latency("not-required", 200.0)
        assert c._go_lead_ms() == pytest.approx(_lead(85.3))

    def test_a_node_without_latency_is_info_once_and_the_floor(self):
        c = _controller()
        c._required_nodes = {"old"}
        with patch("cuemsengine.ControllerEngine.Logger") as log:
            assert c._go_lead_ms() == go_lead.GO_LEAD_FLOOR_MS
            c._go_lead_ms()
        assert log.info.call_count == 1

    def test_the_cap_warns_naming_the_node_once_per_load(self):
        c = _controller()
        c._required_nodes = {"big"}
        c._note_node_latency("big", 321.3)
        with patch("cuemsengine.ControllerEngine.Logger") as log:
            assert c._go_lead_ms() == go_lead.GO_LEAD_MAX_MS
            c._go_lead_ms()
        caps = [w for w in log.warning.call_args_list if "capped" in str(w)]
        assert len(caps) == 1 and "big" in str(caps[0])
        c._reset_node_latency()
        assert c._latencies() == {}

    def test_a_lead_above_160_warns_about_older_node_engines_once_per_load(self):
        """Review fix 8 (S0-14, R15): an rc6-7 node rejects an anchor led
        more than ~200 ms (from L ~160 when its MTC is a frame behind) and
        anchors on its own MTC, L early: the whole cluster must run this
        engine."""
        c = _controller()
        c._required_nodes = {"slow"}
        slow = go_lead.OLD_NODE_ACCEPT_MS - DELTA - MARGIN + 10.0  # L = 170
        c._note_node_latency("slow", slow)
        with patch("cuemsengine.ControllerEngine.Logger") as log:
            assert c._go_lead_ms() == pytest.approx(go_lead.OLD_NODE_ACCEPT_MS + 10.0)
            c._go_lead_ms()
        old = [w for w in log.warning.call_args_list if "older node engines" in str(w)]
        assert len(old) == 1
        c._reset_node_latency()
        c._required_nodes = {"slow"}
        c._note_node_latency("slow", slow)
        with patch("cuemsengine.ControllerEngine.Logger") as log:
            c._go_lead_ms()
        assert any("older node engines" in str(w) for w in log.warning.call_args_list)

    def test_a_lead_up_to_160_does_not_warn(self):
        c = _controller()
        c._required_nodes = {"n"}
        c._note_node_latency("n", go_lead.OLD_NODE_ACCEPT_MS - DELTA - MARGIN)
        with patch("cuemsengine.ControllerEngine.Logger") as log:
            assert c._go_lead_ms() == pytest.approx(go_lead.OLD_NODE_ACCEPT_MS)
        log.warning.assert_not_called()


class TestControllerGo:
    def _go(self, c, mtc_ms, receiving=True, interp=None):
        c.mtc_listener = MagicMock()
        c.mtc_listener.main_tc.milliseconds_exact = mtc_ms
        c.mtc_listener.is_receiving.return_value = receiving
        if interp is not None:
            c.mtc_listener.interpolated_ms.return_value = interp
        with patch.object(c, "_forward_command_to_nodes") as fwd:
            c.go_script(None)
        return fwd.call_args.args[1]

    def test_ships_the_ceiled_led_anchor_and_lead_ms(self):
        """D11: the start is exact on the grid and the lead is >= L."""
        c = _controller()
        c._required_nodes = {"n1"}
        c._note_node_latency("n1", 85.3)
        value = self._go(c, 79240.0, interp=79253.0)
        lead = value["lead_ms"]
        assert lead == pytest.approx(_lead(85.3))
        assert value["go_mtc_ms"] == go_lead.ceil_frame(79253.0 + lead)
        assert value["go_mtc_ms"] >= 79253.0 + lead
        assert value["go_mtc_ms"] % 40.0 == 0.0
        assert value["run_seq"] == 7

    def test_a_dead_listener_ships_no_anchor_but_the_lead(self):
        c = _controller()
        value = self._go(c, 0.0, receiving=False)
        assert "go_mtc_ms" not in value
        assert value["lead_ms"] == go_lead.GO_LEAD_FLOOR_MS


def _node(local_ms, interp=None):
    from cuemsengine.NodeEngine import NodeEngine

    node = object.__new__(NodeEngine)
    node.mtc_listener = MagicMock()
    node.mtc_listener.main_tc.milliseconds_exact = local_ms
    node.mtc_listener.interpolated_ms.return_value = (
        interp if interp is not None else local_ms
    )
    return node


class TestNodeAnchor:
    def test_accepts_a_led_anchor(self):
        # pressed at 1000 on the usual rig: L = the floor; the node reads 1003
        lead = _lead(RIG_OUT)
        anchor = go_lead.ceil_frame(1000.0 + lead)
        node = _node(1003.0)
        assert node._resolve_go_anchor({"go_mtc_ms": anchor, "lead_ms": lead}) == anchor

    def test_checks_against_anchor_minus_lead(self):
        # without lead_ms (an older controller) the floor is assumed:
        # accepted while local - (anchor - floor) >= -200
        node = _node(1000.0)
        ok, late = 1000.0 + FLOOR + 190.0, 1000.0 + FLOOR + 210.0
        assert node._resolve_go_anchor({"go_mtc_ms": ok}) == ok  # lag -190
        assert node._resolve_go_anchor({"go_mtc_ms": late}) == go_lead.ceil_frame(
            1000.0 + FLOOR
        )  # lag -210

    def test_rc6_7_style_rejection_is_relative_to_the_lead(self):
        """timeline_model A5 / R15: a check that ignores the lead rejects an
        anchor led by more than ~200 ms; this one checks anchor - lead_ms."""
        node = _node(1000.0)
        assert (
            node._resolve_go_anchor({"go_mtc_ms": 1240.0, "lead_ms": 250.0}) == 1240.0
        )

    def test_fallback_is_local_plus_lead_ceiled(self):
        node = _node(79760.0, interp=79771.0)
        lead = _lead(85.3)
        assert node._resolve_go_anchor({"lead_ms": lead}) == go_lead.ceil_frame(
            79771.0 + lead
        )
        assert node._resolve_go_anchor(None) == go_lead.ceil_frame(79771.0 + FLOOR)


class TestSeedsAreNotLed:
    def _ch(self):
        ch = object.__new__(CueHandler)
        ch._lock = Lock()
        return ch

    def test_go_from_passes_its_seed_unchanged(self):
        ch = self._ch()
        ch.go = MagicMock(return_value=None)
        target = SimpleNamespace(_local=True, enabled=True, post_go="pause")
        ch.go_from(target, MagicMock(), 5000.0)
        assert ch.go.call_args.args[2] == 5000.0


class TestPassTag:
    """§4.5e: which late-START rule a pass gets."""

    def _go(self, cue, seeded=None):
        ch = object.__new__(CueHandler)
        ch._lock = Lock()
        ch._armed_cues = []
        ch._armed_cues_set = set()
        ch._follow = None
        ch.go_threaded = MagicMock()
        ch._arm_ahead = MagicMock()
        if seeded is None:
            ch.go(cue, MagicMock(), 1000.0)
        else:
            with _dispatch_tag(seeded):
                ch.go(cue, MagicMock(), 1000.0)

    def _cue(self):
        return SimpleNamespace(
            id="c",
            enabled=True,
            _local=True,
            loaded=True,
            _go_generation=0,
            _revealed=False,
            _playing=False,
        )

    def test_an_operator_go_is_not_seeded(self):
        cue = self._cue()
        self._go(cue)
        assert cue._pass_seeded is False

    def test_a_go_from_dispatch_is_seeded(self):
        cue = self._cue()
        self._go(cue, seeded=True)
        assert cue._pass_seeded is True


class TestNodeLatency:
    """N3: a node knows its latency before any audio cue arms (settings or
    JACK at start), raises it from a player's LATENCY line, reports a new
    maximum and carries it in armed_ready; F follows it."""

    def _node(self, override=None, jack=None):
        from cuemsengine.NodeEngine import NodeEngine

        node = object.__new__(NodeEngine)
        node.cm = SimpleNamespace(
            node_conf={"audioplayer": {"output_latency_ms": override}},
            node_uuid="node-1",
        )
        node._legacy_period = []
        mixer = MagicMock()
        mixer.conn_man.playback_latency.return_value = jack
        return node, mixer

    def _patched(self, mixer):
        from cuemsengine.cues.CueHandler import CUE_HANDLER
        from cuemsengine.players.PlayerHandler import PLAYER_HANDLER

        return (
            patch.object(PLAYER_HANDLER, "get_audio_mixer", return_value=mixer),
            patch.object(CUE_HANDLER, "out_latency_ms", None),
            patch.object(
                CUE_HANDLER, "communications_thread", MagicMock(), create=True
            ),
        )

    def test_jack_query_at_start(self):
        from cuemsengine.cues.CueHandler import CUE_HANDLER

        node, mixer = self._node(jack=(1536, 48000, 512))
        a, b, c = self._patched(mixer)
        with a, b, c:
            node._init_out_latency()
            assert node._out_latency_ms == pytest.approx(42.667, abs=1e-3)
            assert CUE_HANDLER.out_latency_ms == pytest.approx(42.667, abs=1e-3)

    def test_settings_override_plus_one_period(self):
        node, mixer = self._node(override=35, jack=(1536, 48000, 512))
        a, b, c = self._patched(mixer)
        with a, b, c:
            node._init_out_latency()
        assert node._out_latency_ms == pytest.approx(35 + 10.667, abs=1e-3)

    def test_no_source_leaves_it_unknown(self):
        node, mixer = self._node()
        a, b, c = self._patched(mixer)
        with a, b, c:
            node._init_out_latency()
        assert node._out_latency_ms is None

    def test_a_larger_latency_line_is_reported(self):
        from cuemsengine.cues.CueHandler import CUE_HANDLER
        from cuemsengine.players.Player import LatencyLine

        node, mixer = self._node(jack=(1536, 48000, 512))
        a, b, c = self._patched(mixer)
        with a, b, c:
            node._init_out_latency()
            nowait = CUE_HANDLER.communications_thread.send_operation_nowait
            assert nowait.call_count == 1  # nothing reported yet: sent
            node._on_player_latency(None, LatencyLine(1536, 48000, 512))
            assert nowait.call_count == 1  # not larger: nothing new
            node._on_player_latency(None, LatencyLine(3072, 48000, 1024))
            assert nowait.call_count == 2
            op = nowait.call_args.args[0]
            assert op.target == "out_latency"
            assert op.data == {"out_latency_ms": pytest.approx(85.333, abs=1e-3)}
            assert CUE_HANDLER.out_latency_ms == pytest.approx(85.333, abs=1e-3)

    def test_unknown_at_armed_ready_then_a_latency_line_is_reported(self):
        """N3 / review fix 4: no latency known when armed_ready went out (no
        settings, no JACK answer), then the first player's LATENCY line: the
        controller must still hear of it."""
        from cuemsengine.cues.CueHandler import CUE_HANDLER
        from cuemsengine.players.Player import LatencyLine

        node, mixer = self._node()
        a, b, c = self._patched(mixer)
        with a, b, c:
            node._init_out_latency()
            node._notify_armed_ready("arming after load")
            ready = CUE_HANDLER.communications_thread.send_operation.call_args.args[0]
            assert "out_latency_ms" not in ready.data
            node._on_player_latency(None, LatencyLine(1536, 48000, 512))
            op = CUE_HANDLER.communications_thread.send_operation_nowait.call_args.args[
                0
            ]
        assert op.target == "out_latency"
        assert op.data == {"out_latency_ms": pytest.approx(42.667, abs=1e-3)}

    def test_armed_ready_carries_it(self):
        from cuemsengine.cues.CueHandler import CUE_HANDLER

        node, mixer = self._node(jack=(1536, 48000, 512))
        a, b, c = self._patched(mixer)
        with a, b, c:
            node._init_out_latency()
            node._notify_armed_ready("test")
            op = CUE_HANDLER.communications_thread.send_operation.call_args.args[0]
        assert op.target == "armed_ready"
        assert op.data["out_latency_ms"] == pytest.approx(42.667, abs=1e-3)

    def test_unknown_warns_once_per_load(self):
        node, mixer = self._node()
        a, b, c = self._patched(mixer)
        with a, b, c, patch("cuemsengine.NodeEngine.Logger") as log:
            node._notify_armed_ready("test")
            node._notify_armed_ready("re-arm")
        assert log.warning.call_count == 1


class TestDisabledDuringAsyncArm:
    """S0-21 / review fix 3: the ReArm thread's 'disabled while arming'
    disarm leaves a playing cue alone, like every other disable path."""

    def _run(self, playing):
        import importlib

        NE = importlib.import_module("cuemsengine.NodeEngine")
        node = object.__new__(NE.NodeEngine)
        node._project_generation = 3
        cue = SimpleNamespace(id="c", enabled=False, _playing=playing)
        ch = MagicMock()
        ch.find_armed_cue.return_value = True
        with patch.object(NE, "CUE_HANDLER", ch):
            node._arm_with_enabled_guard(cue, 3, 0)
        return ch

    def test_a_playing_cue_is_not_disarmed(self):
        self._run(playing=True).disarm.assert_not_called()

    def test_an_idle_cue_is_disarmed(self):
        ch = self._run(playing=False)
        ch.disarm.assert_called_once()
