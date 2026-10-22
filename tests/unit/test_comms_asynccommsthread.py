# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
"""The engine's comms thread: cuems-utils' AsyncCommsThread plus a fatal path.

The class moved to cuems-utils 0.1.1 (its
`specs/planning/async-comms-thread-absorption.md`); its lifecycle and supervision are
tested there. What is the engine's, and tested here:

- when the communications end by themselves, the engine process is signalled
  (SIGTERM), so the entry script exits 1 and systemd's Restart=on-failure brings it
  back;
- which tasks are essential: the bus hub on both engines and the editor listener on
  the controller. The message receiver and the WebSocket OSC listener return early on
  purpose (no callbacks set; a server already on the port) and must not take the
  engine down.
"""

import asyncio
import signal
from unittest.mock import MagicMock, patch

from cuemsutils.tools.AsyncCommsThread import (
    AsyncCommsThread as LibraryAsyncCommsThread,
)

from cuemsengine.comms import AsyncCommsThread as module

# Bound at import, before tests/conftest.py's autouse `terminated` replaces it.
from cuemsengine.comms.AsyncCommsThread import (
    AsyncCommsThread,
)
from cuemsengine.comms.AsyncCommsThread import (
    terminate_process as real_terminate_process,
)
from cuemsengine.comms.ControllerCommunications import ControllerCommunications
from cuemsengine.comms.NodeCommunications import NodeCommunications
from cuemsengine.comms.NodesHub import OperationType


class TestAsyncCommsThread:
    def test_it_is_the_library_thread(self):
        assert issubclass(AsyncCommsThread, LibraryAsyncCommsThread)

    def test_both_engine_comms_threads_derive_from_it(self):
        assert issubclass(ControllerCommunications, AsyncCommsThread)
        assert issubclass(NodeCommunications, AsyncCommsThread)

    def test_ended_communications_terminate_the_process(self):
        thread = AsyncCommsThread()
        thread.end_reason = "essential task NngBusHub.start ended"
        with patch.object(module, "terminate_process") as terminate:
            thread.on_comms_ended(None)
        terminate.assert_called_once_with()

    def test_terminate_process_sends_sigterm_to_this_process(self):
        with (
            patch.object(module.os, "kill") as kill,
            patch.object(module.os, "getpid", return_value=4242),
        ):
            real_terminate_process()
        kill.assert_called_once_with(4242, signal.SIGTERM)


def _essential_names(thread):
    """Run create_all_tasks with every long-lived coroutine replaced by a no-op."""

    async def create():
        tasks = thread.create_all_tasks()
        await asyncio.gather(*tasks, return_exceptions=True)
        return {
            task.get_coro().__qualname__: task in thread._essential for task in tasks
        }

    return asyncio.run(create())


def _noop(name):
    async def coroutine():
        return None

    coroutine.__qualname__ = name
    return coroutine


class TestControllerCommunicationsEssentialTasks:
    def _controller(self, ws_port):
        with patch(
            "cuemsengine.comms.ControllerCommunications.Communicator",
            return_value=MagicMock(),
        ):
            controller = ControllerCommunications(
                "tcp://127.0.0.1:15599",
                editor_callback=MagicMock(),
                node_operation_callback={OperationType.PLAYER: MagicMock()},
                websocket_osc_config={"port": ws_port},
            )
        controller.editor_listener = _noop("editor_listener")
        controller._websocket_osc_task = _noop("websocket_osc_task")
        controller.nng_hub.start = _noop("hub_start")
        controller.nng_hub.start_message_receiver = _noop("message_receiver")
        return controller

    def test_the_hub_and_the_editor_listener_are_essential(self):
        essential = _essential_names(self._controller(ws_port=9190))
        assert essential == {
            "editor_listener": True,
            "hub_start": True,
            "message_receiver": False,
            "websocket_osc_task": False,
        }

    def test_without_a_websocket_port_there_is_no_websocket_task(self):
        essential = _essential_names(self._controller(ws_port=0))
        assert essential == {
            "editor_listener": True,
            "hub_start": True,
            "message_receiver": False,
        }


class TestNodeCommunicationsEssentialTasks:
    def test_the_hub_is_essential_and_the_receiver_is_not(self):
        node = NodeCommunications("tcp://127.0.0.1:15598", node_id="test-node")
        node.nng_hub.start = _noop("hub_start")
        node.nng_hub.start_message_receiver = _noop("message_receiver")
        assert _essential_names(node) == {"hub_start": True, "message_receiver": False}
