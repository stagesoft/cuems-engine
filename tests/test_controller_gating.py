# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

"""Tests for the multi-node GO gating in ControllerEngine.

Covers:
  - _collect_project_nodes (UUID extraction from cue output_names)
  - status_operation_callback per-node aggregation (armed_ready + script_finished)
  - foreign-sender filter
  - pong handling
  - _clear_playback_state + unload_project clearing
  - arm watchdog (fire + cancel)
"""

import threading
import time
from pathlib import Path
from os import environ
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock, patch

import pytest

from cuemsengine.comms.NodesHub import ActionType, OperationType, NodeOperation


CONTROLLER_UUID = 'aaaaaaaa-099f-11f0-a075-00e04c01b7e3'
SLAVE_UUID      = 'bbbbbbbb-6c5c-5016-aac6-a039c6a7d18f'
FOREIGN_UUID    = 'cccccccc-9999-9999-9999-999999999999'


@pytest.fixture(autouse=True)
def set_config_path():
    test_conf_path = Path(__file__).parent / '..' / 'dev' / 'test_xml_files'
    environ['CUEMS_CONF_PATH'] = str(test_conf_path)


@pytest.fixture
def controller():
    """Minimal ControllerEngine with the heavy deps mocked.

    Pre-populates a two-node adopted set (controller + slave) so the
    aggregation logic has something to gate on.
    """
    with patch('cuemsengine.core.BaseEngine.ConfigManager') as MockCM, \
         patch('cuemsengine.core.BaseEngine.BaseEngine.get_controller_ip',
               return_value='localhost'):
        mock_cm = MockCM.return_value
        mock_cm.node_conf = {
            'uuid': CONTROLLER_UUID,
            'mtc_port': 'MTC_MIDI_PORT',
        }
        mock_cm.library_path = str(
            Path(__file__).parent / '..' / 'dev' / 'test_xml_files'
        )
        mock_cm.tmp_path = '/tmp'
        mock_cm.network_map = {
            'node_list': [
                {'node': {'uuid': CONTROLLER_UUID, 'adopted': True}},
                {'node': {'uuid': SLAVE_UUID, 'adopted': True}},
            ],
        }

        from cuemsengine.ControllerEngine import ControllerEngine
        engine = ControllerEngine(with_mtc=False)

        engine.communications_thread = Mock()
        engine.communications_thread.broadcast_osc = Mock()
        engine.communications_thread.nng_hub = Mock()

        # Default snapshot: both nodes adopted + required.
        engine._adopted_nodes = {CONTROLLER_UUID, SLAVE_UUID}
        engine._required_nodes = {CONTROLLER_UUID, SLAVE_UUID}
        # initial-load path (vs re-arm-after-stop) so the armed_ready branch
        # takes the "All required nodes armed" log line, not the re-arm one.
        engine.go_offset = 0

        yield engine
        engine.stop()


def _armed_ready_op(sender: str) -> NodeOperation:
    return NodeOperation(
        type=OperationType.STATUS,
        action=ActionType.UPDATE,
        sender=sender,
        target='armed_ready',
        data={'armed': 'yes'},
    )


def _script_finished_op(sender: str) -> NodeOperation:
    return NodeOperation(
        type=OperationType.STATUS,
        action=ActionType.UPDATE,
        sender=sender,
        target='script_finished',
        data={'running': 'no'},
    )


def _pong_op(sender: str) -> NodeOperation:
    return NodeOperation(
        type=OperationType.STATUS,
        action=ActionType.UPDATE,
        sender=sender,
        target='pong',
        data={},
    )


# ─── _collect_project_nodes ──────────────────────────────────────────────


class TestCollectProjectNodes:
    def _fake_cue(self, output_names):
        cue = SimpleNamespace(outputs=[{'output_name': n} for n in output_names])
        return cue

    def _fake_cuelist(self, contents):
        return SimpleNamespace(contents=contents)

    def test_extracts_uuid_from_video_output_name(self, controller):
        video_name = f'{SLAVE_UUID}_2'
        cl = self._fake_cuelist([self._fake_cue([video_name])])
        assert controller._collect_project_nodes(cl) == {SLAVE_UUID}

    def test_extracts_uuid_from_dmx_output_name(self, controller):
        cl = self._fake_cuelist([self._fake_cue([SLAVE_UUID])])
        assert controller._collect_project_nodes(cl) == {SLAVE_UUID}

    def test_walks_nested_cuelists(self, controller):
        inner_cue = self._fake_cue([f'{SLAVE_UUID}_0'])
        # Use a real CueList for the isinstance check to fire.
        from cuemsutils.cues import CueList
        inner = CueList()
        inner.contents = [inner_cue]
        outer_cue = self._fake_cue([f'{CONTROLLER_UUID}_1'])
        cl = self._fake_cuelist([outer_cue, inner])
        nodes = controller._collect_project_nodes(cl)
        assert nodes == {SLAVE_UUID, CONTROLLER_UUID}

    def test_skips_malformed_output_names(self, controller):
        cl = self._fake_cuelist([self._fake_cue(['short', 'not-a-uuid-shape', ''])])
        assert controller._collect_project_nodes(cl) == set()

    def test_handles_empty_or_missing_outputs(self, controller):
        cue_no_outputs = SimpleNamespace(outputs=None)
        cue_empty_outputs = SimpleNamespace(outputs=[])
        cl = self._fake_cuelist([cue_no_outputs, cue_empty_outputs])
        assert controller._collect_project_nodes(cl) == set()


# ─── status_operation_callback: armed_ready aggregation ──────────────────


class TestArmedReadyAggregation:
    def _read_armed(self, controller):
        return controller.get_status('armed')

    def test_armed_stays_no_until_all_required_report(self, controller):
        controller.set_status('armed', 'no')

        controller.status_operation_callback(_armed_ready_op(CONTROLLER_UUID))
        assert self._read_armed(controller) == 'no'
        assert controller._armed_nodes == {CONTROLLER_UUID}

        controller.status_operation_callback(_armed_ready_op(SLAVE_UUID))
        assert self._read_armed(controller) == 'yes'
        assert controller._armed_nodes == {CONTROLLER_UUID, SLAVE_UUID}

    def test_foreign_sender_is_ignored(self, controller):
        controller.set_status('armed', 'no')
        # Sender not in _adopted_nodes — must NOT land in _armed_nodes.
        controller.status_operation_callback(_armed_ready_op(FOREIGN_UUID))
        assert controller._armed_nodes == set()
        assert self._read_armed(controller) == 'no'

    def test_idempotent_on_repeat(self, controller):
        controller.set_status('armed', 'no')
        controller.status_operation_callback(_armed_ready_op(CONTROLLER_UUID))
        controller.status_operation_callback(_armed_ready_op(CONTROLLER_UUID))
        # Set membership is idempotent.
        assert controller._armed_nodes == {CONTROLLER_UUID}
        assert self._read_armed(controller) == 'no'  # still need SLAVE

    def test_data_without_armed_yes_is_ignored(self, controller):
        controller.set_status('armed', 'no')
        op = NodeOperation(
            type=OperationType.STATUS,
            action=ActionType.UPDATE,
            sender=CONTROLLER_UUID,
            target='armed_ready',
            data={'armed': 'no'},  # not 'yes'
        )
        controller.status_operation_callback(op)
        assert controller._armed_nodes == set()
        assert self._read_armed(controller) == 'no'

    def test_re_arm_branch_when_go_offset_is_none(self, controller):
        # Re-arm-after-stop path: go_offset is None → branch restarts timecode.
        controller.go_offset = None
        controller.set_status('armed', 'no')
        with patch.object(controller, 'start_timecode') as start_tc:
            controller.status_operation_callback(_armed_ready_op(CONTROLLER_UUID))
            controller.status_operation_callback(_armed_ready_op(SLAVE_UUID))
            assert self._read_armed(controller) == 'yes'
            assert controller.go_offset == 0
            start_tc.assert_called_once()


# ─── status_operation_callback: script_finished aggregation ──────────────


class TestScriptFinishedAggregation:
    def test_running_stays_yes_until_all_required_report(self, controller):
        controller.set_status('running', 'yes')

        controller.status_operation_callback(_script_finished_op(CONTROLLER_UUID))
        assert controller.get_status('running') == 'yes'
        assert controller._finished_nodes == {CONTROLLER_UUID}

        controller.status_operation_callback(_script_finished_op(SLAVE_UUID))
        assert controller.get_status('running') == 'no'

    def test_foreign_sender_is_ignored(self, controller):
        controller.set_status('running', 'yes')
        controller.status_operation_callback(_script_finished_op(FOREIGN_UUID))
        assert controller._finished_nodes == set()
        assert controller.get_status('running') == 'yes'


# ─── pong handling ──────────────────────────────────────────────────────


class TestPongHandling:
    def test_pong_adds_sender_to_responses(self, controller):
        # Probe set itself up with these expected pongs.
        controller._pong_expected = {SLAVE_UUID}
        controller._pong_responses.clear()
        controller._pong_event.clear()

        controller.status_operation_callback(_pong_op(SLAVE_UUID))
        assert SLAVE_UUID in controller._pong_responses
        assert controller._pong_event.is_set()

    def test_pong_does_not_set_event_until_superset(self, controller):
        controller._pong_expected = {SLAVE_UUID, FOREIGN_UUID}
        controller._pong_responses.clear()
        controller._pong_event.clear()

        controller.status_operation_callback(_pong_op(SLAVE_UUID))
        assert not controller._pong_event.is_set()

        controller.status_operation_callback(_pong_op(FOREIGN_UUID))
        assert controller._pong_event.is_set()


# ─── Probe (no remote nodes shortcut) ───────────────────────────────────


def test_probe_returns_only_controller_when_no_remote_nodes(controller):
    """Degenerate cluster (controller is the only adopted node): probe
    returns immediately with just the controller's UUID, no broadcast."""
    controller.cm.network_map = {
        'node_list': [{'node': {'uuid': CONTROLLER_UUID, 'adopted': True}}],
    }
    alive = controller._probe_cluster_liveness(timeout=0.05)
    assert alive == {CONTROLLER_UUID}
    # No broadcast scheduled.
    assert (
        controller.communications_thread.nng_hub.send_operation.call_count == 0
    )


# ─── Adopted-uuids reader handles bool-typed values ─────────────────────


def test_adopted_uuids_reader_handles_python_bool(controller):
    """NetworkMap.get_nodes_by_adoption mutates `adopted` to bool. Our
    reader must still return the right set on subsequent reads (it bypasses
    strtobool intentionally)."""
    controller.cm.network_map = {
        'node_list': [
            {'node': {'uuid': CONTROLLER_UUID, 'adopted': True}},
            {'node': {'uuid': SLAVE_UUID, 'adopted': False}},
            {'node': {'uuid': FOREIGN_UUID, 'adopted': 'True'}},  # string form
        ],
    }
    assert controller._adopted_uuids_from_network_map() == {
        CONTROLLER_UUID, FOREIGN_UUID,
    }


# ─── State clearing ─────────────────────────────────────────────────────


def test_clear_playback_state_resets_armed_and_finished_sets(controller):
    controller._armed_nodes = {CONTROLLER_UUID, SLAVE_UUID}
    controller._finished_nodes = {CONTROLLER_UUID}
    controller._clear_playback_state()
    assert controller._armed_nodes == set()
    assert controller._finished_nodes == set()
    # Required / adopted stay — they belong to the loaded project.
    assert controller._required_nodes == {CONTROLLER_UUID, SLAVE_UUID}
    assert controller._adopted_nodes == {CONTROLLER_UUID, SLAVE_UUID}


def test_unload_project_clears_required_and_adopted(controller):
    controller.set_status('running', 'no')  # so unload doesn't reject
    controller._armed_nodes = {CONTROLLER_UUID}

    controller.unload_project(None)

    assert controller._required_nodes == set()
    assert controller._adopted_nodes == set()
    assert controller._armed_nodes == set()


# ─── Arm watchdog ───────────────────────────────────────────────────────


class TestArmWatchdog:
    def test_fires_when_required_not_met(self, controller, monkeypatch):
        monkeypatch.setattr(controller, '_ARM_WATCHDOG_S', 0.05)
        fired = threading.Event()

        def fake_logger_error(msg):
            if 'Load stalled' in msg:
                fired.set()

        with patch(
            'cuemsengine.ControllerEngine.Logger.error', side_effect=fake_logger_error
        ):
            controller._armed_nodes = {CONTROLLER_UUID}  # missing SLAVE
            controller._arm_arm_watchdog()
            assert fired.wait(timeout=1.0), 'watchdog did not fire'

    def test_cancelled_does_not_fire(self, controller, monkeypatch):
        monkeypatch.setattr(controller, '_ARM_WATCHDOG_S', 0.05)
        fired = threading.Event()

        def fake_logger_error(msg):
            if 'Load stalled' in msg:
                fired.set()

        with patch(
            'cuemsengine.ControllerEngine.Logger.error', side_effect=fake_logger_error
        ):
            controller._arm_arm_watchdog()
            controller._cancel_arm_watchdog()
            # Wait past the would-have-fired window.
            time.sleep(0.15)
            assert not fired.is_set()

    def test_no_fire_when_required_met(self, controller, monkeypatch):
        monkeypatch.setattr(controller, '_ARM_WATCHDOG_S', 0.05)
        fired = threading.Event()

        def fake_logger_error(msg):
            if 'Load stalled' in msg:
                fired.set()

        with patch(
            'cuemsengine.ControllerEngine.Logger.error', side_effect=fake_logger_error
        ):
            controller._armed_nodes = {CONTROLLER_UUID, SLAVE_UUID}
            controller._arm_arm_watchdog()
            time.sleep(0.15)
            assert not fired.is_set()

    def test_armed_flip_cancels_watchdog(self, controller, monkeypatch):
        monkeypatch.setattr(controller, '_ARM_WATCHDOG_S', 0.2)
        fired = threading.Event()

        def fake_logger_error(msg):
            if 'Load stalled' in msg:
                fired.set()

        with patch(
            'cuemsengine.ControllerEngine.Logger.error', side_effect=fake_logger_error
        ):
            controller.set_status('armed', 'no')
            controller._arm_arm_watchdog()
            # Simulate both required nodes coming armed before timeout.
            controller.status_operation_callback(_armed_ready_op(CONTROLLER_UUID))
            controller.status_operation_callback(_armed_ready_op(SLAVE_UUID))
            time.sleep(0.3)
            assert controller.get_status('armed') == 'yes'
            assert not fired.is_set()
