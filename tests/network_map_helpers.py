# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""Typed node maps loaded through cuemsutils' public surface.

Tests that need a network map build one here instead of stubbing the engine's
adoption reader: the map is written as XML and loaded by ``ConfigManager``, so
every field arrives in the type the library delivers (``node_role`` a
``NodeRole``, ``adopted``/``online`` ``bool``, ``uuid`` a ``Uuid`` or raw
text). Decoding is the library's business — nothing here asserts on it.
"""

from contextlib import contextmanager
from os import environ
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from cuemsutils.tools.ConfigManager import ConfigManager

FIXTURES = Path(__file__).parent / ".." / "dev" / "test_xml_files"
# The loader resolves this host's own entry, so a map needs one node even when
# a test wants nothing adopted: this one, never adopted.
UNADOPTED_SELF = "e0e0e0e0-0000-4000-8000-00000000e0e0"

_MAP_HEAD = """<?xml version='1.0' encoding='utf-8'?>
<cms:CuemsNetworkMap xmlns:cms="https://stagelab.coop/cuems/"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="https://stagelab.coop/cuems/ https://stagelab.coop/cuems/network_map.xsd">
    <node_list>
"""
_MAP_TAIL = """    </node_list>
</cms:CuemsNetworkMap>
"""
_NODE = """        <node>
            <uuid>{uuid}</uuid>
            <mac>{mac}</mac>
            <name>{name}</name>
            <node_role>{node_role}</node_role>
            <ip>{ip}</ip>
            <adopted>{adopted}</adopted>
            <online>{online}</online>
        </node>
"""


def _node_xml(index, node):
    mac = node.get("mac", f"0800276d{index:04x}")
    return _NODE.format(
        uuid=node["uuid"],
        mac=mac,
        name=node.get("name", f"{mac}._cuems_nodeconf._tcp.local."),
        node_role=node.get("node_role", "node"),
        ip=node.get("ip", f"192.168.1.{100 + index}"),
        adopted=node.get("adopted", True),
        online=node.get("online", True),
    )


def write_config_dir(tmp_path, nodes):
    """Write ``network_map.xml`` and ``settings.xml`` for ``nodes`` into ``tmp_path``.

    ``nodes`` is a list of dicts with ``uuid`` (required) and optional
    ``node_role`` (``"controller"``/``"node"``), ``ip``, ``adopted``,
    ``online``, ``mac``, ``name``. ``settings.xml`` is the engine fixture with
    the first node's uuid as this node's own.
    """
    tmp_path = Path(tmp_path)
    body = "".join(_node_xml(i, n) for i, n in enumerate(nodes))
    (tmp_path / "network_map.xml").write_text(_MAP_HEAD + body + _MAP_TAIL)
    settings = (FIXTURES / "settings.xml").read_text()
    own = _fixture_own_uuid(settings)
    (tmp_path / "settings.xml").write_text(settings.replace(own, str(nodes[0]["uuid"])))
    return tmp_path


def typed_network_map(tmp_path, nodes):
    """Return ``ConfigManager.network_map`` for ``nodes``, loaded from XML.

    ``CUEMS_CONF_PATH`` outranks ``config_dir`` in ConfigManager, and many
    tests set it to the shared fixtures, so it is pointed at ``tmp_path`` for
    the load and restored afterwards.
    """
    write_config_dir(tmp_path, nodes)
    saved = environ.get("CUEMS_CONF_PATH")
    environ["CUEMS_CONF_PATH"] = str(tmp_path)
    try:
        cm = ConfigManager(config_dir=str(tmp_path), load_all=False)
        cm.load_network_map()
    finally:
        if saved is None:
            del environ["CUEMS_CONF_PATH"]
        else:
            environ["CUEMS_CONF_PATH"] = saved
    return cm.network_map


def adopted_network_map(uuids, controller=None):
    """A typed map in which every uuid in ``uuids`` is an adopted node.

    ``controller`` (if among them) gets ``node_role=controller``. An empty
    ``uuids`` yields a map holding only ``UNADOPTED_SELF``. Built in a
    throw-away directory, for tests that have no ``tmp_path`` at hand.
    """
    nodes = [
        {
            "uuid": u,
            "node_role": "controller" if u == controller else "node",
            "adopted": True,
        }
        for u in sorted(str(u) for u in uuids)
    ] or [{"uuid": UNADOPTED_SELF, "adopted": False}]
    with TemporaryDirectory() as tmp:
        return typed_network_map(tmp, nodes)


def _fixture_own_uuid(settings_xml):
    start = settings_xml.index("<uuid>") + len("<uuid>")
    return settings_xml[start : settings_xml.index("</uuid>", start)]


@contextmanager
def controller_with_map(own_uuid, network_map):
    """A minimal ControllerEngine whose ``cm.network_map`` is ``network_map``.

    Heavy dependencies mocked as in ``tests/test_controller_gating.py``; the
    engine's own uuid (``node_conf``) is ``own_uuid``, a ``str`` as the
    settings loader delivers it.
    """
    with (
        patch("cuemsengine.core.BaseEngine.ConfigManager") as MockCM,
        patch(
            "cuemsengine.core.BaseEngine.BaseEngine.get_controller_ip",
            return_value="localhost",
        ),
    ):
        cm = MockCM.return_value
        cm.node_conf = {"uuid": own_uuid, "mtc_port": "MTC_MIDI_PORT"}
        cm.library_path = str(FIXTURES)
        cm.tmp_path = "/tmp"
        cm.network_map = network_map

        from cuemsengine.ControllerEngine import ControllerEngine

        engine = ControllerEngine(with_mtc=False)
        engine.communications_thread = Mock()
        engine.communications_thread.broadcast_osc = Mock()
        engine.communications_thread.nng_hub = Mock()
        engine.set_status("running", "no")
        engine.set_status("load", "")
        try:
            yield engine
        finally:
            engine._cancel_arm_watchdog()
            engine.stop()
