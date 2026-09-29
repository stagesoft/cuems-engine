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

from pathlib import Path

from cuemsutils.tools.ConfigManager import ConfigManager

FIXTURES = Path(__file__).parent / ".." / "dev" / "test_xml_files"

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
    """Return ``ConfigManager.network_map`` for ``nodes``, loaded from XML."""
    write_config_dir(tmp_path, nodes)
    cm = ConfigManager(config_dir=str(tmp_path), load_all=False)
    cm.load_network_map()
    return cm.network_map


def _fixture_own_uuid(settings_xml):
    start = settings_xml.index("<uuid>") + len("<uuid>")
    return settings_xml[start : settings_xml.index("</uuid>", start)]
