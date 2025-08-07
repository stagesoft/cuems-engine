from enum import Enum
from typing import Callable, Union
from pyossia.ossia_python import OSCDevice, OSCQueryDevice # type: ignore[attr-defined]

# Type aliases for device setup functions
ServerSetupFunction = Callable[..., bool]
ClientSetupFunction = Callable[..., Union[OSCDevice, OSCQueryDevice]]

def new_osc_device(cls) -> OSCDevice:
    """An OSC device is required to deal with a remote application using OSC protocol

    Args:
        name (str): name of the device
        host (str): host ip address
        remote_port (int): port where osc messages have to be sent to be catch by a remote client to listen to the local device
        local_port (int): port where OSC requests have to be sent by any remote client to deal with the local device

    Returns:
        OSCDevice: an OSC device
    """
    x = OSCDevice(
        "cuems",
        cls.host,
        cls.remote_port,
        cls.local_port
    )
    return x

def new_oscquery_device(cls) -> OSCQueryDevice:
    x = OSCQueryDevice(
        "cuems",
        f"ws://{cls.host}:{cls.remote_port}",
        cls.local_port
    )
    x.update()
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
        remote_port (int): port where osc messages have to be sent to be catch by a remote client to listen to the local device
        local_port (int): port where OSC requests have to be sent by any remote client to deal with the local device
        log (bool): enable protocol logging

    Returns:
        bool: True if the server has been created successfully
    """
    return cls.device.create_osc_server(
        cls.host,
        cls.remote_port,
        cls.local_port,
        cls.logging
    )

def set_oscquery_server(cls) -> bool:
    """LocalDevice.create_oscquery_server

    Make the local device able to handle oscquery request

    Args:
        osc_port (int): port where OSC requests have to be sent by any remote client to deal with the local device
        ws_port (int) port where WebSocket requests have to be sent by any remote client to deal with the local device
        log (bool): enable protocol logging

    Returns:
        bool: True if the server has been created successfully
    """
    return cls.device.create_oscquery_server(
        cls.local_port,
        cls.remote_port,
        cls.logging
    )

class ServerDevices(Enum):
    OSC = set_osc_server
    OSCQUERY = set_oscquery_server
    PYOSC = None

def include_function_endpoints(endpoints: dict, cmd_dict: dict) -> dict:
    """Include the function endpoints in the endpoints dictionary

    Args:
        endpoints (dict): the endpoints dictionary
        cmd_dict (dict): the command dictionary

    Returns:
        dict: the endpoints dictionary with the function endpoints included
    """
    for key, value in endpoints.items():
        func = cmd_dict.get(key.split('/')[-1])
        if func:
            endpoints[key] = [value[0], func]
    return endpoints
