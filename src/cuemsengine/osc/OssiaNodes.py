from inspect import signature
from pyossia import Node, ValueType, ossia
from typing import Union, Any, Callable
from time import sleep
from cuemsutils.log import logged, Logger

CLEANUP_DELAY = 0.3
STARTUP_DELAY = 0.3

class OssiaNodes(object):
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
        - `pyossia.ValueType`
        - callback function (*optional*)
        - initial / default value (*optional*)
        - **Note**: to set a parameter value without a callback, pass None as the second argument
    
    """
    def __init__(self):
        self.device = None
        self.nodes = {}


    def iterate_on_children(self, node):
        for child in node.children():
            print(str(child))
            self.iterate_on_children(child)

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
        """Remove a node from the collection and all its children
        """
        self.device.root_node.remove_child(path)
        children = [k for k in self.nodes.keys() if str(k).startswith(path)]
        for key in children:
            del self.nodes[str(key)]

    def remove_device(self) -> None:
        """Remove the device and all nodes from the collection
        """
        node_keys = list(self.nodes.keys())
        for node in node_keys:
            self.remove_node(node)
        self.nodes = {}
        del self.device
        sleep(CLEANUP_DELAY)
        self.device = None

    @staticmethod
    def set_parameter(node: Node, value_type, callback: Callable = None, value = None):
        """Set a parameter to a node
        """
        if not isinstance(value_type, ValueType):
            raise ValueError("value_type must be a pyossia.ValueType")
        _ = node.create_parameter(value_type)
        _.repetition_filter = ossia.RepetitionFilter.On
        _.access_mode = ossia.AccessMode.Bi
        if callback:
            l = len(signature(callback).parameters)
            if l == 1:
                _.add_callback(callback)
            elif l == 2:
                _.add_callback_param(callback)
            else:
                raise ValueError("callback must have 1 or 2 parameters")
        if value:
            _.value = value

    def set_node_callback(self, node: Node, callback: Callable) -> None:
        """Set a callback to a node
        """
        Logger.debug(f"Setting callback for node {str(node)}")
        l = len(signature(callback).parameters)
        if l == 1:
            node.parameter.add_callback(callback)
        elif l == 2:
            node.parameter.add_callback_param(callback)
        else:
            raise ValueError(f"callback must have 1 or 2 parameters, not {l}")

    @logged
    def set_value(self, node: Union[Node, str], value) -> None:
        """Set a value to a node
        Parameters:
            - node: The node to set the value to
                - str: The path of the node
                - Node: The node object
            - value: The value to set to the node

        Raises:
            - ValueError: If the node is not found
            - ValueError: If the value could not be set to the node
        """
        if isinstance(node, str):
            try:
                node = self.nodes[node]
            except KeyError:
                raise ValueError("Node not found")
        node.parameter.push_value(value)
        if node.parameter.value != value:
            raise ValueError(f"Could not set {str(node)} to {value}")

    @logged
    def get_value(self, node: Union[Node, str]):
        """Get a value from a node
        Parameters:
            - node: The node to get the value from
                - str: The path of the node
                - Node: The node object

        Returns:
            - value: The value of the node
        
        Raises:
            - ValueError: If the node is not found
        """
        if isinstance(node, str):
            try:
                node = self.nodes[node]
            except KeyError:
                raise ValueError("Node not found")
        return node.parameter.value

    def create_endpoint(self, path: str, param_args: list | None = None):
        """Create an endpoint as a node with parameter
        """
        try:
        self.set_node(path)
        if param_args and isinstance(param_args, list):
            self.set_parameter(self.nodes[path], *param_args)
            Logger.debug(f"Created endpoint: {path}")
        except Exception as e:
            Logger.error(f"Failed to create endpoint {path}: {type(e).__name__}: {e}")
            raise

    @logged
    def create_endpoints(self, paths: dict[str, Any] | list[str]):
        """Create multiple endpoints
        """
        if isinstance(paths, list):
            for path in paths:
                self.create_endpoint(path)
        elif isinstance(paths, dict):
            for path, params in paths.items():
                self.create_endpoint(path, params)

    def get_endpoints(self) -> dict[str, list[Any]]:
        """Get all endpoints (node paths with their parameter arguments)
        
        """
        # endpoints_raw = self.iterate_on_children(self.device.root_node)
        Logger.info(f"Getting endpoints from device: {self.device}")
        endpoints = {}
        for path, node in self.nodes.items():
            if node.parameter:
                endpoints[path] = [node.parameter.value_type, None, node.parameter.value]
        return endpoints

    def nodes_from_device(self, node: Node = None) -> dict[str, Node]:
        nodes = {}
        if node is None:
            node = self.device.root_node
        Logger.debug(f"{self.__class__.__name__} Node {node.name} has {len(node.children())} children")
        if len(node.children()) == 0:
            nodes[str(node)] = node
            return nodes        
        for n, i in enumerate[int, Node](node.children()):
            Logger.debug(f"Adding child {n} named {i.name}")
            nodes.update(self.nodes_from_device(i))
            # DEV: iteration raises RuntimeError at the end of the loop
            if  n + 1 == len(node.children()):
                Logger.debug(f"All children from {node.name} added")
                break
        return nodes

    def __del__(self):
        self.remove_device()
        del self
