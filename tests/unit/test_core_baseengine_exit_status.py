# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
"""The engines' exit status on SIGTERM, and the bounded comms stop on the way out.

Both units are `Restart=on-failure` with `TimeoutStopSec=10` (cuems-common). When the
comms thread ends by itself it SIGTERMs the engine. `engine.start()` blocks in
SignalEngine's run loop, so it is SignalEngine's handler that runs: it calls
`engine.stop()` and exits with `engine.exit_status()` (cuems-utils 0.1.1's hook), which
is 1 when the comms thread's `end_reason` is set (a restart) and 0 otherwise (an
operator stop must not be restarted). The comms join is bounded below TimeoutStopSec,
so systemd does not SIGKILL a shutdown that is still releasing NNG.
"""

import signal
from unittest.mock import MagicMock, patch

import pytest

from cuemsengine.comms.AsyncCommsThread import AsyncCommsThread
from cuemsengine.ControllerEngine import ControllerEngine
from cuemsengine.core.BaseEngine import COMMS_STOP_TIMEOUT, BaseEngine
from cuemsengine.NodeEngine import NodeEngine


def _comms(end_reason=None):
    thread = AsyncCommsThread()
    thread.end_reason = end_reason
    return thread


class _Engine:
    """What BaseEngine.exit_status reads."""

    exit_status = BaseEngine.exit_status
    _communications_thread = BaseEngine._communications_thread

    def __init__(self, communications_thread=None):
        if communications_thread is not None:
            self.communications_thread = communications_thread


class TestExitStatus:
    def test_comms_that_ended_by_themselves_exit_1(self):
        ended = _comms("essential task NngBusHub.start ended")
        assert _Engine(ended).exit_status() == 1

    def test_a_stopped_or_running_comms_thread_exits_0(self):
        assert _Engine(_comms()).exit_status() == 0

    def test_no_comms_thread_exits_0(self):
        assert _Engine().exit_status() == 0

    def test_a_mock_comms_thread_is_not_mistaken_for_an_ended_one(self):
        assert _Engine(MagicMock()).exit_status() == 0

    def test_the_node_engine_reads_the_cue_handler_s_thread(self):
        fake_handler = MagicMock(communications_thread=_comms("ended"))
        with patch("cuemsengine.NodeEngine.CUE_HANDLER", fake_handler):
            thread = NodeEngine._communications_thread(object())
        assert thread is fake_handler.communications_thread


class TestStopCommsIsBounded:
    def test_the_bound_is_below_the_units_timeout_stop_sec(self):
        assert COMMS_STOP_TIMEOUT < 10

    def test_controller(self):
        engine = MagicMock(with_mtc=False)
        ControllerEngine.stop_comms(engine)
        engine.communications_thread.stop.assert_called_once_with(
            timeout=COMMS_STOP_TIMEOUT
        )

    def test_node(self):
        fake_handler = MagicMock()
        engine = MagicMock()
        engine._communications_thread = lambda: NodeEngine._communications_thread(
            engine
        )
        with patch("cuemsengine.NodeEngine.CUE_HANDLER", fake_handler):
            NodeEngine.stop_comms(engine)
        fake_handler.communications_thread.stop.assert_called_once_with(
            timeout=COMMS_STOP_TIMEOUT
        )


def _controller(comms):
    engine = ControllerEngine.__new__(ControllerEngine)
    engine.with_mtc = False
    engine.running = True
    engine.communications_thread = comms
    engine.remove_show_lock_file = MagicMock()
    return engine


def _node(comms):
    engine = NodeEngine.__new__(NodeEngine)
    engine.with_mtc = False
    engine.running = True
    engine._cancel_stop_project_watchdog = MagicMock()
    engine.stop_node_engine = MagicMock()
    engine.remove_show_lock_file = MagicMock()
    return engine


@pytest.mark.parametrize("build", [_controller, _node], ids=["controller", "node"])
class TestSigterm:
    """SignalEngine.handle_terminate, the handler that runs in production."""

    def _sigterm(self, build, comms):
        engine = build(comms)
        with (
            patch(
                "cuemsengine.NodeEngine.CUE_HANDLER",
                MagicMock(communications_thread=comms),
            ),
            patch("cuemsutils.tools.SignalEngine.sleep"),
            pytest.raises(SystemExit) as exited,
        ):
            engine.handle_terminate(signal.SIGTERM, None)
        return exited.value.code, engine

    def test_after_the_comms_ended_it_exits_1(self, build):
        code, engine = self._sigterm(
            build, _comms("essential task NngBusHub.start ended")
        )
        assert code == 1
        assert engine.running is False

    def test_an_operator_sigterm_exits_0(self, build):
        code, _ = self._sigterm(build, _comms())
        assert code == 0
