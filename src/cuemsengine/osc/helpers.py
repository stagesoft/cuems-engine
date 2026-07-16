# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

from datetime import datetime
from enum import Enum
from time import sleep
from typing import Callable, Optional, Union

from cuemsutils.log import Logger
from pyossia import Node, ValueType

# type: ignore[attr-defined]
from pyossia.ossia_python import OSCDevice, OSCQueryDevice

# Type aliases for device setup functions
ServerSetupFunction = Callable[..., bool]
ClientSetupFunction = Callable[..., Union[OSCDevice, OSCQueryDevice]]


def new_osc_device(cls) -> OSCDevice:
    """
    An OSC device is required to deal with a remote application using OSC
    protocol

    Args:
        name (str): name of the device
        host (str): host ip address
        remote_port (int): port where osc messages have to be sent to be catch
        by a remote client to listen to the local device
        local_port (int): port where OSC requests have to be sent by any remote
        client to deal with the local device

    Returns:
        OSCDevice: an OSC device
    """
    x = OSCDevice(cls.name, cls.host, cls.remote_port, cls.local_port)
    Logger.debug(
        f"OSCDevice created: {x}, remote_port: {cls.remote_port}, local_port:"
        f"{cls.local_port}"
    )
    return x


def new_oscquery_device(cls) -> OSCQueryDevice:
    try:
        x = OSCQueryDevice(
            cls.name, f"ws://{cls.host}:{cls.remote_port}", cls.local_port
        )
    except Exception as e:
        Logger.exception(f"Failed to create OSCQueryDevice: {e}, type: {type(e)}")
        return
    Logger.info(f"Added OSCQueryDevice: {cls.name}")
    try:
        result = False
        while not result:
            result = x.update()
            sleep(0.5)
            Logger.debug(
                f"Waiting for remote device ws://{cls.host}:{cls.remote_port}"
                f"to be ready..."
            )
    except Exception as e:
        Logger.exception(f"Failed to update OSCQueryDevice: {e}, type: {type(e)}")
        return
    Logger.debug(
        f"OSCQueryDevice created: {x}, remote_port: {cls.remote_port},"
        f"local_port: {cls.local_port} {datetime.now()}"
    )
    return x


class ClientDevices(Enum):
    OSC = new_osc_device
    OSCQUERY = new_oscquery_device
    PYOSC = None


def set_osc_server(cls) -> bool:
    """LocalDevice.create_osc_server

    Make the local device able to handle osc request and emit osc message

    Args:
        host (str): host ip address
        remote_port (int): port where osc messages have to be sent to be catch
        by a remote client to listen to the local device
        local_port (int): port where OSC requests have to be sent by any remote
        client to deal with the local device
        log (bool): enable protocol logging

    Returns:
        bool: True if the server has been created successfully
    """
    Logger.debug(
        f"creating osc server for {cls.name} on {cls.host}:{cls.local_port}"
        f"-> {cls.remote_port}"
    )
    return cls.device.create_osc_server(
        cls.host, cls.remote_port, cls.local_port, cls.logging
    )


def set_oscquery_server(cls) -> bool:
    """LocalDevice.create_oscquery_server

    Make the local device able to handle oscquery request

    Args:
        osc_port (int): port where OSC requests have to be sent by any remote
        client to deal with the local device
        ws_port (int) port where WebSocket requests have to be sent by any
        remote client to deal with the local device
        log (bool): enable protocol logging

    Returns:
        bool: True if the server has been created successfully
    """
    Logger.debug(
        f"creating oscquery server on {cls.host}:{cls.remote_port} ->"
        f"{cls.local_port}"
    )

    try:
        return cls.device.create_oscquery_server(
            cls.local_port, cls.remote_port, cls.logging
        )
    except Exception as e:
        Logger.error(f"{type(e).__name__} creating oscquery server: {e}")
        raise e


class ServerDevices(Enum):
    OSC = set_osc_server
    OSCQUERY = set_oscquery_server
    PYOSC = None


# --------- HELPERS --------- #


def add_callbacks_from_dict(endpoints: dict, cmd_dict: dict[str, Callable]) -> dict:
    """Include the function endpoints in the endpoints dictionary

    Args:
        endpoints (dict): the endpoints dictionary
        cmd_dict (dict): the command dictionary

    Returns:
        dict: the endpoints dictionary with the function endpoints included
    """
    for key, value in endpoints.items():
        func = cmd_dict.get(key.split("/")[-1])
        if func:
            endpoints[key] = [value[0], func]
    return endpoints


def add_callback_to_all(endpoints: dict, func: Callable) -> dict:
    """Include the function to the endpoints dictionary

    Args:
        endpoints (dict): the endpoints dictionary
        func (Callable): the function to include
    """
    return {key: [value[0], func] for key, value in endpoints.items()}


def add_prefix_to_all(endpoints: dict, prefix: str) -> dict:
    """Add a prefix to the endpoints dictionary

    Args:
        endpoints (dict): the endpoints dictionary
        prefix (str): the prefix to add
    """
    return {prefix + key: value for key, value in endpoints.items()}


def deserialize_node(node_data: dict, parent_node: Optional[Node] = None) -> Node:
    """
    Deserialize a dictionary structure into pyossia nodes.

    Parameters:
    - node_data: The serialized node structure
    - parent_node: Optional parent node to attach to

    Returns:
    - pyossia.ossia.Node: The reconstructed node
    """
    if parent_node is None:
        raise ValueError("Parent node required for deserialization")

    # Create the node
    node = parent_node.add_node(node_data["name"])

    # Recreate parameter if it existed
    if node_data.get("parameter"):
        param_dict = node_data["parameter"]
        param = node.create_parameter(ValueType.String)  # Default type

        # Set parameter properties
        if param_dict.get("value") is not None:
            try:
                param.value = param_dict["value"]
            except Exception as e:
                Logger.warning(f"Could not set value for parameter at {node.name}: {e}")

    # Recursively create children
    for child_data in node_data.get("children", []):
        deserialize_node(child_data, node)

    return node


def serialize_node(node: Node) -> dict:
    """
    Serialize a pyossia node and its children to a dictionary structure.

    Parameters:
    - node: The pyossia node to serialize

    Returns:
    - dict: Serialized node structure
    """
    node_dict = {"name": node.name, "children": [], "parameter": None}

    # Serialize parameter if exists
    param = node.parameter
    if param:
        param_dict = {
            "access": str(param.access_mode),
            "bounding": str(param.bounding_mode),
            "type": (str(param.value_type) if hasattr(param, "value_type") else None),
        }

        # Try to get current value
        try:
            value = param.value
            # Convert value to JSON-serializable format
            if hasattr(value, "__iter__") and not isinstance(value, str):
                param_dict["value"] = list(value)
            else:
                param_dict["value"] = value
        except Exception as e:
            Logger.warning(f"Could not get value for {param.name} at {node.name}: {e}")
            param_dict["value"] = None

        # Get other parameter properties
        try:
            param_dict["domain"] = (
                str(param.domain) if hasattr(param, "domain") else None
            )
            param_dict["unit"] = str(param.unit) if hasattr(param, "unit") else None
        except Exception as e:
            Logger.warning(
                f"Could not get domain or unit for {param.name} at {node.name}: {e}"
            )
            pass

        node_dict["parameter"] = param_dict

    # Recursively serialize children
    for child in node.children():
        node_dict["children"].append(serialize_node(child))

    return node_dict
