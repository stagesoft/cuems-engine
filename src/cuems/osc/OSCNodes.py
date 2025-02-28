from inspect import signature
from pyossia import Node, ValueType, ossia
from typing import Union

class OSCNodes(object):
    """Manage a collection of OSC nodes.
    
    Internal static methods allow to:
        - add nodes
        - remove nodes
        - set node parameters
        - set node values
        - get node values
        - set endpoints (nodes with parameters)

    Multiple endpoints can be set simultaenously with:
        - list of paths.
        - dictionary of paths (k) and parameter arguments (v)

    Parameter arguments must be lists containing:
        - pyossia.ValueType
        - callback function (optional)
        - initial / default value (optional)
        - Note: to set a parameter value without a callback, pass None as the second argument
    
    """
    def __init__(self):
        self.device = None
        self.nodes = {}

    def set_node(self, path: str):
        """Add a new node to the device
            Node memory address is stored in self.nodes[path]
            and must be kept to access the node later
        """
        if not self.device:
            raise AttributeError("No device found")
        try:
            self.nodes[path] = self.device.add_node(path)
        except AttributeError:
            self.nodes[path] = self.device.root_node.add_node(path)

    def get_node(self, path: str):
        """Get a node from the collection
        """
        return self.nodes[path]
    
    def remove_node(self, path: str):
        """Remove a node from the collection
        """
        del self.nodes[path]

    @staticmethod
    def set_parameter(node: Node, value_type, callback = None, value = None):
        """Set a parameter to a node
        """
        if not isinstance(value_type, ValueType):
            raise ValueError("value_type must be a pyossia.ValueType")
        _ = node.create_parameter(value_type)
        _.repetition_filter = ossia.RepetitionFilter.On
        if callback:
            l = len(signature(callback).parameters)
            if l == 1:
                _.add_callback(callback)
            elif l == 2:
                _.add_callback_param(callback)
            else:
                raise ValueError("callback must have 1 or 2 parameters")
        if value:
            _.push_value(value)

    def set_value(self, node: Union[Node, str], value):
        """Set a value to a node
        """
        if isinstance(node, str):
            try:
                node = self.nodes[node]
            except KeyError:
                raise ValueError("Node not found")
        try:
            node.parameter.push_value(value)
        except Exception as e:
            print(e)
            raise ValueError(f"Could not set {str(node)} to {value}")

    def create_endpoint(self, path: str, param_args: list = None):
        """Create an endpoint as a node with parameter
        """
        self.set_node(path)
        if param_args:
            if isinstance(param_args, list):
                self.set_parameter(self.nodes[path], *param_args)

    def create_endpoints(self, paths: Union[dict, list]):
        """Create multiple endpoints
        """
        if isinstance(paths, list):
            for path in paths:
                self.create_endpoint(path)
        elif isinstance(paths, dict):
            for path, params in paths.items():
                self.create_endpoint(path, params)
