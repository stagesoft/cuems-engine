# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, Optional

from cuemsutils.log import Logger
from cuemsutils.tools.HubServices import Message, NngBusHub

from ..osc.helpers import Node, deserialize_node, serialize_node


class ActionType(Enum):
    """The type of action to be performed."""

    ADD = "add"
    REMOVE = "remove"
    UPDATE = "update"


class OperationType(Enum):
    """The type of operation to be performed."""

    CUE = "cue"
    PLAYER = "player"
    COMMAND = "command"  # For ControllerEngine → NodeEngine command forwarding
    STATUS = "status"  # For NodeEngine → ControllerEngine status updates


@dataclass
class NodeOperation:
    """Represents an operation to be performed from/to a node."""

    type: OperationType
    action: ActionType
    sender: str
    target: str
    data: dict

    def duplicate(self):
        return self.__class__(
            type=self.type,
            action=self.action,
            sender=self.sender,
            target=self.target,
            data=self.data if self.data else {},
        )

    @staticmethod
    def from_message(message: Message):
        """
        Create a NodeOperation from a message.
        Uses sender from message data (node_id) rather than NNG address.
        """
        return NodeOperation(
            type=OperationType(message.data["type"]),
            action=ActionType(message.data["action"]),
            sender=message.data["sender"],
            target=message.data["target"],
            data=message.data["data"],
        )

    def __dict__(self):
        return {
            "type": self.type.value,
            "action": self.action.value,
            "sender": self.sender,
            "target": self.target,
            "data": self.data,
        }

    def __str__(self):
        data_str = "without" if not self.data else "with"
        return (
            f"{type(self).__name__} by {self.sender}: "
            f"{self.action.value} on {self.type.value} "
            f"{self.target} ({data_str} data)"
        )


class NodesHub(NngBusHub):
    """
    Extension of NngBusHub for transmitting pyossia player node structures.

    Nodes send player structures (player_id + root_node) to the controller.
    Players are transmitted one by one as they become available.
    This class handles transmission only - storage is left to the user.
    """

    def __init__(self, hub_address: str, mode=NngBusHub.Mode.LISTENER):
        """
        Initialize NodesHub.

        Parameters:
        - hub_address: The address for the bus communication
        - mode: LISTENER or DIALER mode

        Note: We use the base class queues (self.outgoing and self.incoming) to
        send and receive Message objects that are translated into
        NodeOperations.
        """
        super().__init__(hub_address, mode)

        # Callback for when operations are received
        self._on_operation_received: Optional[
            dict[OperationType, Callable]
        ] = None

    #########################
    # Nodes communication
    #########################
    async def get_operation(self) -> NodeOperation | None:
        """
        Get the next operation from the queue and return it as a NodeOperation
        object.
        """
        message = await self.get_message()
        if not message:
            return None
        return NodeOperation.from_message(message)

    async def send_operation(self, operation: NodeOperation):
        """
        Send an operation to the send queue.
        """
        message = Message(sender=operation.sender, data=operation.__dict__())
        await self.send_message(message)
        Logger.debug(
            f"Queued {operation.action.value} operation for"
            f"{operation.type.value} {operation.target}"
        )

    def set_receive_callbacks(
        self, callback_dict: dict[OperationType, Callable]
    ):
        """
        Set the callbacks to be invoked when nodes send operations.

        The keys of the dictionary are the operation types to perform, and the
        values are the callbacks.
        The callbacks must take the following argument: (operation:
        NodeOperation)
        """
        self._on_operation_received = callback_dict

    async def start_message_receiver(self):
        """
        Continuously receive messages and invoke callback (controller side).

        This runs in a loop, receiving messages and invoking the callback
        if set. Should be run as a background task.

        The callback receives: (sender, message)
        """
        if not self._on_operation_received:
            Logger.warning("No operation callbacks set")
            return

        while True:
            try:
                operation = await self.get_operation()

                if operation:
                    Logger.debug(f"Received {operation}")

                    # Invoke callback if set (lookup by enum, not string value)
                    message_function = self._on_operation_received.get(
                        operation.type
                    )
                    if message_function:
                        if asyncio.iscoroutinefunction(message_function):
                            await message_function(operation)
                        else:
                            message_function(operation)
                await asyncio.sleep(0.01)  # Prevent tight loop

            except Exception as e:
                Logger.error(f"{type(e)} handling {operation}: {e}")
                await asyncio.sleep(0.1)  # Back off on error
