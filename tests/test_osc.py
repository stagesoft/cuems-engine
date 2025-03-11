
from pyossia import ValueType

from src.cuemsengine.osc.OssiaServer import OssiaServer
from src.cuemsengine.osc.OssiaClient import OssiaClient

"""Logging testing functions"""
def print_node(node):
    print(node)
    params = node.get_parameters()
    # print(str(params)) # Parameter objects addresses
    for param in params:
        print(f"Parameter info: [node: {param.node}, value: {param.value}, value_type: {param.value_type}]")

def iterate_on_devices(node):
    print_node(node)
    for child in node.children():
        print_node(child)
        if child.children():
            iterate_on_devices(child)
        else:
            print("No children")

def print_callback(node, value):
    print(
        f"Parameter changed at {node} to {value} [node value: {node.parameter.value}]"
    )

def test_server_init(capfd):
    test_endpoints = {
        "/test1": [ValueType.Int, print_callback, 10],
        "/test2": [ValueType.Int, print_callback, 20],
        "/test3": [ValueType.Int, print_callback, 30],
        "/test4": [ValueType.Int, print_callback, 40]
    }
    os = OssiaServer(log = False, endpoints = test_endpoints)
    assert os.started == True

    out, err = capfd.readouterr()
    assert "Parameter changed at" in out
    assert len(out) > 0
    assert len(err) == 0
    assert len(os.device.root_node.children()) == 4
    out_lines = out.split("\n")
    assert out_lines[-1] == ''
    assert len(out_lines) == 5

    iterate_on_devices(os.device.root_node)
    out, err = capfd.readouterr()
    assert "Parameter changed at" not in out
    assert "Parameter info" in out
    assert "No children" in out

def test_client_init(capfd):
    test_endpoints = {
        "/test1": [ValueType.Int, print_callback],
        "/test2": [ValueType.Int, print_callback, 10],
        "/test3": [ValueType.Int, print_callback, 20],
        "/test4": [ValueType.Int, print_callback, 30]
    }
    ro = OssiaClient(
        endpoints = test_endpoints,
        # remote_type = RemoteDevices.OSCQUERY
    )

    out, err = capfd.readouterr()
    assert "Parameter changed at" in out
    assert len(out) > 0
    assert len(err) == 0
    assert len(ro.device.root_node.children()) == 4
    out_lines = out.split("\n")
    assert out_lines[-1] == ''
    assert len(out_lines) == 5

    iterate_on_devices(ro.device.root_node)
    out, err = capfd.readouterr()
    assert "Parameter changed at" not in out
    assert "Parameter info" in out
    assert "No children" in out
