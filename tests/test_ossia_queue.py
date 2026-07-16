# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

from threading import Event
from time import sleep
from unittest.mock import MagicMock, Mock, patch

from pyossia import GlobalMessageQueue, ValueType

from cuemsengine.comms.NodeCommunications import NodeCommunications
from cuemsengine.osc.helpers import ClientDevices, ServerDevices
from cuemsengine.osc.OssiaClient import OssiaClient
from cuemsengine.osc.OssiaServer import OssiaServer

from .fixtures import ossia_client_factory, ossia_server_factory
from .helpers import timeout


def test_global_message_queue_receives_commands(
    ossia_server_factory, ossia_client_factory
):
    """
    Test that GlobalMessageQueue receives command messages from
    ControllerEngine
    """
    # ARRANGE
    SERVER_LOCAL = 9500
    SERVER_REMOTE = 9600
    CLIENT_LOCAL = 9501

    received_commands = []
    command_event = Event()

    def command_callback(value):
        received_commands.append(value)
        command_event.set()

    commands_dict = {"load": command_callback, "gocue": command_callback}

    # Create server (ControllerEngine-like)
    with ossia_server_factory(
        name="TestControllerServer",
        endpoints={
            "/engine/command/load": [ValueType.String, None, ""],
            "/engine/command/gocue": [ValueType.String, None, ""],
        },
        local_port=SERVER_LOCAL,
        remote_port=SERVER_REMOTE,
        server=ServerDevices.OSCQUERY,
    ) as server:
        sleep(0.5)  # Allow server to start

        # Create client (NodeEngine-like)
        with ossia_client_factory(
            endpoints={},
            remote_type=ClientDevices.OSCQUERY,
            local_port=CLIENT_LOCAL,
            remote_port=SERVER_REMOTE,
        ) as client:
            sleep(0.5)  # Allow client to connect

            # Create GlobalMessageQueue and NodeCommunications
            with patch("cuemsengine.comms.NodeCommunications.NodesHub"):
                with patch("cuemsengine.comms.NodeCommunications.PLAYER_HANDLER"):
                    node_comm = NodeCommunications(
                        hub_address="tcp://127.0.0.1:5555",
                        commands_dict=commands_dict,
                        node_id="test_node",
                    )
                    node_comm.start_oscquery_queue(client)

                    # Start queue loop in background
                    from threading import Thread

                    stop_event = Event()

                    def queue_loop():
                        while not stop_event.is_set():
                            message = node_comm.oscquery_queue.pop()
                            if message is not None:
                                parameter, value = message
                                node_comm.route_message(parameter, value)
                            else:
                                sleep(0.001)

                    queue_thread = Thread(target=queue_loop, daemon=True)
                    queue_thread.start()

                    sleep(0.5)  # Allow queue loop to start

                    # ACT: Write values from server
                    server.set_value("/engine/command/load", "test_project")
                    sleep(0.2)

                    server.set_value("/engine/command/gocue", "cue_123")
                    sleep(0.2)

                    # Wait for commands to be received
                    command_event.wait(timeout=2)

                    # Stop queue loop
                    stop_event.set()
                    queue_thread.join(timeout=1)

    # ASSERT
    assert (
        len(received_commands) >= 2
    ), f"Expected at least 2 commands, got {len(received_commands)}"
    assert "test_project" in received_commands, "load command not received"
    assert "cue_123" in received_commands, "gocue command not received"


def test_global_message_queue_filters_players_by_node_id(
    ossia_server_factory, ossia_client_factory
):
    """Test that GlobalMessageQueue filters player messages by node_id"""
    # ARRANGE
    SERVER_LOCAL = 9502
    SERVER_REMOTE = 9602
    CLIENT_LOCAL = 9503

    node_id = "node_123"
    other_node_id = "node_456"

    received_video_messages = []
    received_audio_messages = []
    received_dmx_messages = []

    mock_player_handler = MagicMock()

    def mock_route_video(path_elements, value):
        received_video_messages.append((path_elements, value))

    def mock_route_audio(path_elements, value):
        received_audio_messages.append((path_elements, value))

    def mock_route_dmx(path_elements, value):
        received_dmx_messages.append((path_elements, value))

    mock_player_handler.route_video_message = mock_route_video
    mock_player_handler.route_audio_message = mock_route_audio
    mock_player_handler.route_dmx_message = mock_route_dmx

    def player_path(node_id: str, player_type: str) -> str:
        return f"/engine/players/{node_id}/{player_type}/test/path"

    # Create server (ControllerEngine-like)
    with ossia_server_factory(
        name="TestControllerServer",
        endpoints={
            player_path(node_id, "video"): [ValueType.Float, None, 0.0],
            player_path(node_id, "audio"): [ValueType.Float, None, 0.0],
            player_path(node_id, "dmx"): [ValueType.Int, None, 0],
            player_path(other_node_id, "video"): [ValueType.Float, None, 0.0],
        },
        local_port=SERVER_LOCAL,
        remote_port=SERVER_REMOTE,
        server=ServerDevices.OSCQUERY,
    ) as server:
        sleep(0.5)  # Allow server to start

        # Create client (NodeEngine-like)
        with ossia_client_factory(
            endpoints={},
            remote_type=ClientDevices.OSCQUERY,
            local_port=CLIENT_LOCAL,
            remote_port=SERVER_REMOTE,
        ) as client:
            sleep(0.5)  # Allow client to connect

            # Create GlobalMessageQueue and NodeCommunications
            with patch("cuemsengine.comms.NodeCommunications.NodesHub"):
                with patch(
                    "cuemsengine.comms.NodeCommunications.PLAYER_HANDLER",
                    mock_player_handler,
                ):
                    node_comm = NodeCommunications(
                        hub_address="tcp://127.0.0.1:5555",
                        commands_dict={},
                        node_id=node_id,
                    )
                    node_comm.start_oscquery_queue(client)

                    # Start queue loop in background
                    from threading import Thread

                    stop_event = Event()

                    def queue_loop():
                        while not stop_event.is_set():
                            message = node_comm.oscquery_queue.pop()
                            if message is not None:
                                parameter, value = message
                                node_comm.route_message(parameter, value)
                            else:
                                sleep(0.001)

                    queue_thread = Thread(target=queue_loop, daemon=True)
                    queue_thread.start()

                    sleep(0.5)  # Allow queue loop to start

                    # ACT: Write values from server
                    # Write to this node's players (should be received)
                    server.set_value(player_path(node_id, "video"), 0.5)
                    sleep(0.2)

                    server.set_value(player_path(node_id, "audio"), 0.75)
                    sleep(0.2)

                    server.set_value(player_path(node_id, "dmx"), 255)
                    sleep(0.2)

                    # # Write to other node's players (should be filtered out)
                    # server.set_value(player_path(other_node_id, 'video'),
                    # 0.9)
                    # sleep(0.2)

                    # Stop queue loop
                    stop_event.set()
                    queue_thread.join(timeout=1)

    # ASSERT
    # Should receive messages for this node
    assert (
        len(received_video_messages) >= 1
    ), f"Expected video message, got {len(received_video_messages)}"
    assert (
        len(received_audio_messages) >= 1
    ), f"Expected audio message, got {len(received_audio_messages)}"
    assert (
        len(received_dmx_messages) >= 1
    ), f"Expected DMX message, got {len(received_dmx_messages)}"

    # Verify video message content
    video_path, video_value = received_video_messages[0]
    assert video_value == 0.5, f"Expected video value 0.5, got {video_value}"
    assert (
        "test" in video_path and "path" in video_path
    ), f"Video path incorrect: {video_path}"

    # Verify audio message content
    audio_path, audio_value = received_audio_messages[0]
    assert audio_value == 0.75, f"Expected audio value 0.75, got {audio_value}"

    # Verify DMX message content
    dmx_path, dmx_value = received_dmx_messages[0]
    assert dmx_value == 255, f"Expected DMX value 255, got {dmx_value}"

    # Verify other node's messages were filtered (not in received lists)
    # The other node's video message should not appear in
    # received_video_messages
    other_node_video_found = any(
        path == ["test", "path"] and value == 0.9
        for path, value in received_video_messages
    )
    assert (
        not other_node_video_found
    ), "Other node's video message should be filtered out"


def test_global_message_queue_ignores_unused_paths(
    ossia_server_factory, ossia_client_factory
):
    """
    Test that GlobalMessageQueue ignores paths that don't match command or
    players patterns
    """
    # ARRANGE
    SERVER_LOCAL = 9504
    SERVER_REMOTE = 9604
    CLIENT_LOCAL = 9505

    received_commands = []
    commands_dict = {"load": lambda v: received_commands.append(v)}

    # Create server (ControllerEngine-like)
    with ossia_server_factory(
        name="TestControllerServer",
        endpoints={
            "/engine/command/load": [ValueType.String, None, ""],
            "/engine/status/running": [ValueType.String, None, "no"],
            "/unused/path": [ValueType.String, None, ""],
        },
        local_port=SERVER_LOCAL,
        remote_port=SERVER_REMOTE,
        server=ServerDevices.OSCQUERY,
    ) as server:
        sleep(0.5)  # Allow server to start

        # Create client (NodeEngine-like)
        with ossia_client_factory(
            endpoints={},
            remote_type=ClientDevices.OSCQUERY,
            local_port=CLIENT_LOCAL,
            remote_port=SERVER_REMOTE,
        ) as client:
            sleep(0.5)  # Allow client to connect

            # Create GlobalMessageQueue and NodeCommunications
            with patch("cuemsengine.comms.NodeCommunications.NodesHub"):
                with patch("cuemsengine.comms.NodeCommunications.PLAYER_HANDLER"):
                    node_comm = NodeCommunications(
                        hub_address="tcp://127.0.0.1:5555",
                        commands_dict=commands_dict,
                        node_id="test_node",
                    )
                    node_comm.start_oscquery_queue(client)

                    # Start queue loop in background
                    from threading import Thread

                    stop_event = Event()

                    def queue_loop():
                        while not stop_event.is_set():
                            message = node_comm.oscquery_queue.pop()
                            if message is not None:
                                parameter, value = message
                                node_comm.route_message(parameter, value)
                            else:
                                sleep(0.001)

                    queue_thread = Thread(target=queue_loop, daemon=True)
                    queue_thread.start()

                    sleep(0.5)  # Allow queue loop to start

                    # ACT: Write values from server
                    # This should be received
                    server.set_value("/engine/command/load", "test_project")
                    sleep(0.2)

                    # These should be ignored
                    server.set_value("/engine/status/running", "yes")
                    sleep(0.2)

                    server.set_value("/unused/path", "value")
                    sleep(0.2)

                    # Stop queue loop
                    stop_event.set()
                    queue_thread.join(timeout=1)

    # ASSERT
    # Status and unused paths should not trigger commands
    assert (
        len(received_commands) == 1
    ), f"Expected only 1 command, got {len(received_commands)}"
    assert "test_project" in received_commands, "load command not received"
