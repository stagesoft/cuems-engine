# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

from inspect import signature
from time import sleep
from typing import Any, Callable, Union

from cuemsutils.log import Logger, logged
from pyossia import Node, ValueType, ossia

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
        - **Note**: to set a parameter value without a callback, pass None as
          - the second argument

    """

    def __init__(self):
        self.device = None
        self.nodes = {}
        # Paths that have had a value explicitly pushed via set_value().
        # pyossia gives a freshly-created parameter a raw type-default value
        # (e.g. 0.0 for Float) with no way to tell "never set" apart from
        # "explicitly set to that same value" — this tracks it at the Python
        # level so get_value_if_set() can make that distinction.
        self._explicit_values: set[str] = set()
        # Values recorded engine-side WITHOUT an OSC push — for changes an
        # external actor performs on the player under engine command (e.g.
        # gradient-motiond driving a fade to its end_value): the parameter
        # mirror never sees them. Consulted first by get_value_if_set();
        # superseded by any later real set_value() push.
        self._recorded_values: dict[str, Any] = {}

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
        """Get a node from the collection"""
        return self.nodes[path]

    def remove_node(self, path: str):
        """Remove a node from the collection and all its children"""
        if not path or path.strip("/") == "":
            return
        self.device.root_node.remove_child(path)
        children = [k for k in self.nodes.keys() if str(k).startswith(path)]
        for key in children:
            del self.nodes[str(key)]
        explicit_values = getattr(self, "_explicit_values", None)
        if explicit_values:
            explicit_values -= {k for k in explicit_values if str(k).startswith(path)}
        recorded_values = getattr(self, "_recorded_values", None)
        if recorded_values:
            for key in [k for k in recorded_values if str(k).startswith(path)]:
                del recorded_values[key]

    def remove_device(self) -> None:
        """Remove the device and all nodes from the collection.

        Safe when ``__init__`` was skipped (e.g. tests that patch a subclass
        ``__init__``): missing ``nodes``/``device`` is a no-op, not an error.
        """
        nodes = getattr(self, "nodes", None)
        if nodes:
            for node in list(nodes.keys()):
                self.remove_node(node)
        if hasattr(self, "nodes"):
            self.nodes = {}
        if hasattr(self, "_explicit_values"):
            self._explicit_values = set()
        if hasattr(self, "_recorded_values"):
            self._recorded_values = {}
        if getattr(self, "device", None) is not None:
            del self.device
            sleep(CLEANUP_DELAY)
        self.device = None

    @staticmethod
    def set_parameter(
        node: Node,
        value_type,
        callback: Callable = None,
        value=None,
        repetition_filter=True,
    ):
        """Set a parameter to a node"""
        if not isinstance(value_type, ValueType):
            raise ValueError("value_type must be a pyossia.ValueType")
        _ = node.create_parameter(value_type)
        # Impulse parameters are fire-and-forget triggers — RepetitionFilter
        # must always be OFF, otherwise ossia silently drops repeated sends.
        if value_type == ValueType.Impulse:
            repetition_filter = False
        _.repetition_filter = (
            ossia.RepetitionFilter.On
            if repetition_filter
            else ossia.RepetitionFilter.Off
        )
        _.access_mode = ossia.AccessMode.Bi
        if callback:
            cb_params = len(signature(callback).parameters)
            if cb_params == 1:
                _.add_callback(callback)
            elif cb_params == 2:
                _.add_callback_param(callback)
            else:
                raise ValueError("callback must have 1 or 2 parameters")
        if value:
            _.value = value

    def set_node_callback(self, node: Node, callback: Callable) -> None:
        """Set a callback to a node"""
        Logger.debug(f"Setting callback for node {str(node)}")
        cb_params = len(signature(callback).parameters)
        if cb_params == 1:
            node.parameter.add_callback(callback)
        elif cb_params == 2:
            node.parameter.add_callback_param(callback)
        else:
            raise ValueError(f"callback must have 1 or 2 parameters, not {cb_params}")

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
        path = node if isinstance(node, str) else None
        if isinstance(node, str):
            try:
                node = self.nodes[node]
            except KeyError:
                raise ValueError("Node not found")
        # Impulse parameters: pyossia rejects None — use True to trigger the
        # send
        if node.parameter.value_type == ValueType.Impulse:
            node.parameter.push_value(True)
            return
        node.parameter.push_value(value)
        stored = node.parameter.value
        # Float parameters go through float32 (OSC wire format), so an exact
        # Python float64 equality check produces false negatives (e.g. 0.66).
        # Use a tolerance-based comparison for floats; strict equality for all
        # others.
        if isinstance(value, float):
            if abs(stored - value) > 1e-5:
                raise ValueError(f"Could not set {str(node)} to {value} (got {stored})")
        elif stored != value:
            raise ValueError(f"Could not set {str(node)} to {value}")
        if path is not None:
            self._explicit_values.add(path)
            # A real push is the freshest truth — supersede any recorded value
            self._recorded_values.pop(path, None)

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

    def get_value_if_set(self, path: str):
        """Return the node's current value only if set_value(path, ...) has
        explicitly been called for it; None otherwise.

        pyossia gives a freshly-created parameter a raw type-default value
        (e.g. 0.0 for a Float) with no signal distinguishing "nothing has
        ever been pushed here" from "explicitly pushed this same value" —
        get_value() alone can't tell the two apart. Callers that need to
        fall back to some other source of truth when nothing has been
        deployed to this client yet (e.g. ActionHandler._build_fade_payload
        falling back to the CuemsScript-stored level) must use this instead
        of get_value().
        """
        if path in self._recorded_values:
            return self._recorded_values[path]
        if path not in self._explicit_values:
            return None
        return self.get_value(path)

    def record_value(self, path: str, value) -> None:
        """Record a value engine-side WITHOUT pushing it over OSC.

        For player-side changes the engine commanded but does not itself
        perform (e.g. gradient-motiond driving a fade to end_value): the
        parameter mirror never sees them, so get_value_if_set() would keep
        returning the pre-change level. A later real set_value() push
        supersedes the recorded value.
        """
        self._recorded_values[path] = value

    def create_endpoint(self, path: str, param_args: list | None = None):
        """Create an endpoint as a node with parameter"""
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
        """Create multiple endpoints"""
        if isinstance(paths, list):
            for path in paths:
                self.create_endpoint(path)
        elif isinstance(paths, dict):
            for path, params in paths.items():
                self.create_endpoint(path, params)

    def get_endpoints(self) -> dict[str, list[Any]]:
        """Get all endpoints (node paths with their parameter arguments)"""
        # endpoints_raw = self.iterate_on_children(self.device.root_node)
        Logger.info(f"Getting endpoints from device: {self.device}")
        endpoints = {}
        for path, node in self.nodes.items():
            if node.parameter:
                endpoints[path] = [
                    node.parameter.value_type,
                    None,
                    node.parameter.value,
                ]
        return endpoints

    def nodes_from_device(self, node: Node = None) -> dict[str, Node]:
        nodes = {}
        is_root = node is None
        if is_root:
            node = self.device.root_node
        Logger.debug(
            f"{self.__class__.__name__} Node {node.name} has"
            f"{len(node.children())} children"
        )
        if len(node.children()) == 0:
            if not is_root:
                nodes[str(node)] = node
            return nodes
        for n, i in enumerate[int, Node](node.children()):
            Logger.debug(f"Adding child {n} named {i.name}")
            nodes.update(self.nodes_from_device(i))
            # DEV: iteration raises RuntimeError at the end of the loop
            if n + 1 == len(node.children()):
                Logger.debug(f"All children from {node.name} added")
                break
        return nodes

    def __del__(self):
        # Destructors must not raise (pytest reports UnraisableExceptionWarning).
        try:
            self.remove_device()
        except Exception:
            pass
        del self
