# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""Test NodeOperation communication between NodeEngine and ControllerEngine.

This test documents the expected flow of NodeOperation messages via NngHub
when cues are armed/disarmed on NodeEngine.
"""
import asyncio
import pytest
from unittest.mock import Mock, MagicMock

from cuemsengine.comms.NodesHub import ActionType, OperationType, NodeOperation


def test_player_operation_structure():
    """Test NodeOperation dataclass structure and creation."""
    # ARRANGE
    player_id = "audioplayer-12345678-aaaa-4aaa-aaaa-123456789001"
    sender_id = "0367f391-ebf4-48b2-9f26-000000000001"
    node_data = {"name": "audioplayer", "path": "/audioplayer", "children": []}

    # ACT - Create ADD operation
    add_operation = NodeOperation(
        type=OperationType.PLAYER,
        action=ActionType.ADD,
        target=player_id,
        data=node_data,
        sender=sender_id,
    )

    # ASSERT - Verify structure
    assert add_operation.action == ActionType.ADD
    assert add_operation.target == player_id
    assert add_operation.data == node_data
    assert add_operation.sender == sender_id

    # Test string representation
    str_repr = str(add_operation)
    assert sender_id in str_repr
    assert "add" in str_repr.lower()
    assert player_id in str_repr

    # ACT - Recreate as REMOVE operation
    remove_operation = add_operation.duplicate()
    remove_operation.action = ActionType.REMOVE
    remove_operation.data = None

    # ASSERT - REMOVE should not have node_data
    assert remove_operation.action == ActionType.REMOVE
    assert remove_operation.data is None


def test_action_type_enum():
    """Test ActionType enum values."""
    # ASSERT - Verify enum values
    assert ActionType.ADD.value == "add"
    assert ActionType.REMOVE.value == "remove"
    assert ActionType.UPDATE.value == "update"

    # Test enum conversion
    assert ActionType("add") == ActionType.ADD
    assert ActionType("remove") == ActionType.REMOVE
    assert ActionType("update") == ActionType.UPDATE


def test_nodes_hub_callback_signature():
    """Test that NodesHub callback has correct signature."""
    from cuemsengine.comms.NodesHub import NodesHub

    # ARRANGE - Create mock callback
    received_operations = []

    def mock_callback(operation: NodeOperation):
        """Expected callback signature for set_player_received_callback"""
        received_operations.append(operation)

    # ACT - Verify callback can be set
    hub = NodesHub("tcp://localhost:5555", mode=NodesHub.Mode.LISTENER)
    hub.set_receive_callbacks({OperationType.PLAYER: mock_callback})

    # ASSERT - Verify callback was registered
    assert hub._on_operation_received is not None
    assert hub._on_operation_received[OperationType.PLAYER] == mock_callback

    # Test callback works with NodeOperation
    test_op = NodeOperation(
        type=OperationType.PLAYER,
        action=ActionType.ADD,
        sender="test-node",
        target="test-player",
        data={"test": "data"},
    )

    mock_callback(test_op)
    assert len(received_operations) == 1
    assert received_operations[0] == test_op


def test_node_operation_serialization_format():
    """Test NodeOperation serialization via __dict__ method."""
    # ARRANGE
    player_id = "audioplayer-12345678aaaa4aaaaaa123456789001"
    sender_id = "node-001"
    node_data = {"name": "audioplayer", "path": "/audioplayer", "children": []}

    # ACT - Create NodeOperation and get dict representation
    operation = NodeOperation(
        type=OperationType.PLAYER,
        action=ActionType.ADD,
        sender=sender_id,
        target=player_id,
        data=node_data,
    )
    serialized = operation.__dict__()

    # ASSERT - Verify dict structure and values
    assert serialized == {
        "type": "player",
        "action": "add",
        "sender": sender_id,
        "target": player_id,
        "data": node_data,
    }

    # ASSERT - Verify __str__ representation
    str_repr = str(operation)
    assert (
        str_repr
        == f"NodeOperation by {sender_id}: add on player {player_id} (with data)"
    )

    # Test REMOVE operation serialization
    remove_op = operation.duplicate()
    remove_op.action = ActionType.REMOVE
    remove_op.data = None

    remove_serialized = remove_op.__dict__()
    assert remove_serialized["action"] == "remove"
    assert remove_serialized["data"] is None

    # ASSERT - Verify __str__ for REMOVE (without data)
    assert (
        str(remove_op)
        == f"NodeOperation by {sender_id}: remove on player {player_id} (without data)"
    )


class TestNodesHubIntegration:
    """Integration tests for NodesHub NNG communication."""

    def test_send_operation_from_node_to_controller(self):
        """Test that NodeOperation can be sent from DIALER to LISTENER."""
        from cuemsengine.comms.NodesHub import NodesHub

        NNG_ADDRESS = "tcp://127.0.0.1:15551"
        received_operations = []

        async def run_test():
            # ARRANGE - Create listener (controller) and dialer (node) hubs
            listener_hub = NodesHub(NNG_ADDRESS, mode=NodesHub.Mode.LISTENER)
            dialer_hub = NodesHub(NNG_ADDRESS, mode=NodesHub.Mode.DIALER)

            def on_player_received(operation: NodeOperation):
                received_operations.append(operation)

            listener_hub.set_receive_callbacks(
                {OperationType.PLAYER: on_player_received}
            )

            # ACT - Start hubs (transport + message receiver)
            listener_task = asyncio.create_task(listener_hub.start())
            receiver_task = asyncio.create_task(listener_hub.start_message_receiver())
            await asyncio.sleep(0.1)  # Allow listener to bind

            dialer_task = asyncio.create_task(dialer_hub.start())
            await asyncio.sleep(0.1)  # Allow dialer to connect

            operation = NodeOperation(
                type=OperationType.PLAYER,
                action=ActionType.ADD,
                sender="test-node-001",
                target="audioplayer-12345",
                data={"name": "audioplayer", "path": "/audioplayer"},
            )
            await dialer_hub.send_operation(operation)

            # Wait for message to be received and processed
            await asyncio.sleep(0.3)

            # Cleanup
            for task in [listener_task, dialer_task, receiver_task]:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        asyncio.run(run_test())

        # ASSERT - Verify operation was received
        assert len(received_operations) == 1
        received = received_operations[0]
        assert received.type == OperationType.PLAYER
        assert received.action == ActionType.ADD
        assert received.target == "audioplayer-12345"
        assert received.data == {"name": "audioplayer", "path": "/audioplayer"}

    def test_send_multiple_operations(self):
        """Test sending multiple operations in sequence."""
        from cuemsengine.comms.NodesHub import NodesHub

        NNG_ADDRESS = "tcp://127.0.0.1:15552"
        received_operations = []

        async def run_test():
            # ARRANGE
            listener_hub = NodesHub(NNG_ADDRESS, mode=NodesHub.Mode.LISTENER)
            dialer_hub = NodesHub(NNG_ADDRESS, mode=NodesHub.Mode.DIALER)

            def on_operation_received(operation: NodeOperation):
                received_operations.append(operation)

            listener_hub.set_receive_callbacks(
                {
                    OperationType.PLAYER: on_operation_received,
                    OperationType.CUE: on_operation_received,
                }
            )

            # Start hubs (transport + message receiver)
            listener_task = asyncio.create_task(listener_hub.start())
            receiver_task = asyncio.create_task(listener_hub.start_message_receiver())
            await asyncio.sleep(0.1)
            dialer_task = asyncio.create_task(dialer_hub.start())
            await asyncio.sleep(0.1)

            # ACT - Send multiple operations
            operations = [
                NodeOperation(
                    type=OperationType.PLAYER,
                    action=ActionType.ADD,
                    sender="node-001",
                    target="player-1",
                    data={"index": 1},
                ),
                NodeOperation(
                    type=OperationType.PLAYER,
                    action=ActionType.UPDATE,
                    sender="node-001",
                    target="player-1",
                    data={"index": 1, "updated": True},
                ),
                NodeOperation(
                    type=OperationType.PLAYER,
                    action=ActionType.REMOVE,
                    sender="node-001",
                    target="player-1",
                    data=None,
                ),
            ]

            for op in operations:
                await dialer_hub.send_operation(op)
                await asyncio.sleep(0.05)

            await asyncio.sleep(0.3)

            # Cleanup
            for task in [listener_task, dialer_task, receiver_task]:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        asyncio.run(run_test())

        # ASSERT - Verify all operations received in order
        assert len(received_operations) == 3
        assert received_operations[0].action == ActionType.ADD
        assert received_operations[1].action == ActionType.UPDATE
        assert received_operations[2].action == ActionType.REMOVE

    def test_operation_dict_serialization_roundtrip(self):
        """Test that operation serialization/deserialization preserves data integrity."""
        from cuemsengine.comms.NodesHub import NodesHub

        NNG_ADDRESS = "tcp://127.0.0.1:15553"
        received_operations = []

        async def run_test():
            # ARRANGE
            listener_hub = NodesHub(NNG_ADDRESS, mode=NodesHub.Mode.LISTENER)
            dialer_hub = NodesHub(NNG_ADDRESS, mode=NodesHub.Mode.DIALER)

            def on_operation_received(operation: NodeOperation):
                received_operations.append(operation)

            listener_hub.set_receive_callbacks(
                {OperationType.PLAYER: on_operation_received}
            )

            # Start hubs (transport + message receiver)
            listener_task = asyncio.create_task(listener_hub.start())
            receiver_task = asyncio.create_task(listener_hub.start_message_receiver())
            await asyncio.sleep(0.1)
            dialer_task = asyncio.create_task(dialer_hub.start())
            await asyncio.sleep(0.1)

            # ACT - Send operation with complex nested data
            complex_data = {
                "name": "videoplayer",
                "path": "/videoplayer",
                "children": [
                    {"name": "play", "type": "bool", "value": False},
                    {"name": "volume", "type": "float", "value": 0.75},
                ],
                "metadata": {"created": "2025-01-01", "version": 2},
            }

            operation = NodeOperation(
                type=OperationType.PLAYER,
                action=ActionType.ADD,
                sender="node-complex",
                target="videoplayer-xyz",
                data=complex_data,
            )

            await dialer_hub.send_operation(operation)
            await asyncio.sleep(0.3)

            # Cleanup
            for task in [listener_task, dialer_task, receiver_task]:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        asyncio.run(run_test())

        # ASSERT - Verify data integrity after roundtrip
        assert len(received_operations) == 1
        received = received_operations[0]
        assert received.data["name"] == "videoplayer"
        assert received.data["children"][0]["name"] == "play"
        assert received.data["metadata"]["version"] == 2


class TestCommunicationsIntegration:
    """Integration tests using ControllerCommunications and NodeCommunications."""

    def test_node_to_controller_via_communications_threads(self):
        """Test NodeOperation sent via NodeCommunications reaches ControllerCommunications."""
        from unittest.mock import patch, MagicMock, AsyncMock
        from cuemsengine.comms.ControllerCommunications import ControllerCommunications
        from cuemsengine.comms.NodeCommunications import NodeCommunications
        import time

        NNG_ADDRESS = "tcp://127.0.0.1:15561"
        received_operations = []

        def player_callback(operation: NodeOperation):
            received_operations.append(operation)

        def editor_callback(msg, ctx):
            pass  # Stub

        # Mock IPC communicators with async methods
        mock_comm = MagicMock()
        mock_comm.responder_connect = AsyncMock()
        mock_comm.responder_get_request = AsyncMock(side_effect=asyncio.CancelledError)

        with patch(
            "cuemsengine.comms.ControllerCommunications.Communicator",
            return_value=mock_comm,
        ):
            # ARRANGE - Create communications threads
            controller = ControllerCommunications(
                NNG_ADDRESS,
                editor_callback=editor_callback,
                player_operation_callback=player_callback,
            )
            node = NodeCommunications(NNG_ADDRESS, node_id="test-node-001")

            # Start controller thread (which starts the NNG listener)
            controller.start()
            time.sleep(0.3)  # Allow controller to bind

            # Start node thread (which starts the NNG dialer)
            node.start()
            time.sleep(0.3)  # Allow node to connect

            # ACT - Send operation from node
            node.add_player("audioplayer-xyz", {"name": "audioplayer", "volume": 0.8})

            # Wait for message to be received
            time.sleep(0.5)

            # Cleanup
            node.stop()
            controller.stop()
            time.sleep(0.2)

        # ASSERT
        assert len(received_operations) == 1
        op = received_operations[0]
        assert op.type == OperationType.PLAYER
        assert op.action == ActionType.ADD
        assert op.target == "audioplayer-xyz"
        assert op.sender == "test-node-001"
        assert op.data["name"] == "audioplayer"

    def test_multiple_operations_via_communications(self):
        """Test multiple operations flow correctly through communications layer."""
        from unittest.mock import patch, MagicMock, AsyncMock
        from cuemsengine.comms.ControllerCommunications import ControllerCommunications
        from cuemsengine.comms.NodeCommunications import NodeCommunications
        import time

        NNG_ADDRESS = "tcp://127.0.0.1:15562"
        received_operations = []

        def player_callback(operation: NodeOperation):
            received_operations.append(operation)

        def editor_callback(msg, ctx):
            pass

        mock_comm = MagicMock()
        mock_comm.responder_connect = AsyncMock()
        mock_comm.responder_get_request = AsyncMock(side_effect=asyncio.CancelledError)

        with patch(
            "cuemsengine.comms.ControllerCommunications.Communicator",
            return_value=mock_comm,
        ):
            controller = ControllerCommunications(
                NNG_ADDRESS,
                editor_callback=editor_callback,
                player_operation_callback=player_callback,
            )
            node = NodeCommunications(NNG_ADDRESS, node_id="node-multi")

            controller.start()
            time.sleep(0.3)
            node.start()
            time.sleep(0.3)

            # ACT - Send multiple operations
            node.add_player("player-1", {"index": 1})
            time.sleep(0.1)
            node.add_player("player-2", {"index": 2})
            time.sleep(0.1)
            node.remove_player("player-1")

            time.sleep(0.5)

            node.stop()
            controller.stop()
            time.sleep(0.2)

        # ASSERT
        assert len(received_operations) == 3
        assert received_operations[0].action == ActionType.ADD
        assert received_operations[0].target == "player-1"
        assert received_operations[1].action == ActionType.ADD
        assert received_operations[1].target == "player-2"
        assert received_operations[2].action == ActionType.REMOVE
        assert received_operations[2].target == "player-1"

    def test_send_custom_operation_via_node_communications(self):
        """Test sending custom NodeOperation via NodeCommunications.send_operation()."""
        from unittest.mock import patch, MagicMock, AsyncMock
        from cuemsengine.comms.ControllerCommunications import ControllerCommunications
        from cuemsengine.comms.NodeCommunications import NodeCommunications
        import time

        NNG_ADDRESS = "tcp://127.0.0.1:15563"
        received_operations = []

        def player_callback(operation: NodeOperation):
            received_operations.append(operation)

        def editor_callback(msg, ctx):
            pass

        mock_comm = MagicMock()
        mock_comm.responder_connect = AsyncMock()
        mock_comm.responder_get_request = AsyncMock(side_effect=asyncio.CancelledError)

        with patch(
            "cuemsengine.comms.ControllerCommunications.Communicator",
            return_value=mock_comm,
        ):
            controller = ControllerCommunications(
                NNG_ADDRESS,
                editor_callback=editor_callback,
                player_operation_callback=player_callback,
            )
            node = NodeCommunications(NNG_ADDRESS, node_id="node-custom")

            controller.start()
            time.sleep(0.3)
            node.start()
            time.sleep(0.3)

            # ACT - Send custom operation directly
            custom_op = NodeOperation(
                type=OperationType.PLAYER,
                action=ActionType.UPDATE,
                sender="node-custom",
                target="videoplayer-001",
                data={
                    "name": "videoplayer",
                    "state": "playing",
                    "position": 12345,
                    "nested": {"key": "value"},
                },
            )
            node.send_operation(custom_op)

            time.sleep(0.5)

            node.stop()
            controller.stop()
            time.sleep(0.2)

        # ASSERT
        assert len(received_operations) == 1
        op = received_operations[0]
        assert op.action == ActionType.UPDATE
        assert op.target == "videoplayer-001"
        assert op.data["state"] == "playing"
        assert op.data["nested"]["key"] == "value"
