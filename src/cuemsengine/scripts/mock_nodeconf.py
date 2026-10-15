#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

"""
Mock cuems-nodeconf replacement for headless/cloud deployments.

Answers the engine's node adoption requests (nodelist_modify, relayed from the
UI) on /tmp/nodeconf.ipc exactly as cuems-nodeconf does, by flipping <adopted>
in network_map.xml, but does no discovery: no avahi, no zeroconf, and the map
is never rewritten from the network. The nodes a mock box lists (real or
invented) stay as they are, so the UI's adopt/unadopt flow works end to end
without the daemon rewriting the topology from whatever it hears on the LAN.

Same rules as cuems-nodeconf: an offline node cannot be adopted, the master
cannot be unadopted, and an unknown uuid is an error.
"""

import argparse
import asyncio
import os
import signal
import sys
import tempfile
import threading
import xml.etree.ElementTree as ET

from cuemsutils.log import Logger
from cuemsutils.tools.CommunicatorServices import Communicator

NODECONF_IPC = "/tmp/nodeconf.ipc"
DEFAULT_MAP = "/etc/cuems/network_map.xml"
NAMESPACES = {
    "cms": "https://stagelab.coop/cuems/",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}
# Element order inside <node> (network_map.xsd NodeType): <adopted> goes
# right after <ip> when a node does not carry one yet.
ADOPTED_AFTER = "ip"

for _prefix, _uri in NAMESPACES.items():
    ET.register_namespace(_prefix, _uri)

_map_lock = threading.Lock()


def _is_true(text) -> bool:
    return str(text).strip().lower() in ("true", "1", "yes")


def _validate(path: str) -> None:
    """Validate against the same network_map.xsd the engine reads with."""
    from cuemsutils.xml.XmlReaderWriter import XmlReader

    XmlReader(schema_name="network_map", xmlfile=path).validate()


def _write_atomically(tree: ET.ElementTree, path: str) -> None:
    """Write next to `path`, validate, then rename over it (keeps its mode)."""
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".network_map.", dir=directory)
    try:
        with os.fdopen(fd, "wb") as f:
            tree.write(f, encoding="utf-8", xml_declaration=True)
            f.write(b"\n")
        _validate(tmp)
        try:
            os.chmod(tmp, os.stat(path).st_mode & 0o7777)
        except FileNotFoundError:
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def set_adopted(map_path: str, node_uuid: str, adopt: bool) -> dict:
    """Adopt or unadopt one node in network_map.xml. Returns the reply."""
    with _map_lock:
        tree = ET.parse(map_path)
        for node in tree.getroot().iter("node"):
            if (node.findtext("uuid") or "").strip() != node_uuid:
                continue
            adopted_el = node.find("adopted")
            adopted = adopted_el is not None and _is_true(adopted_el.text)
            if adopt:
                if adopted:
                    return {"OK": True, "message": "Node already adopted"}
                if not _is_true(node.findtext("online")):
                    return {
                        "OK": False,
                        "error": f"Cannot adopt node {node_uuid}: node is offline",
                    }
            else:
                if (node.findtext("node_type") or "").endswith("master"):
                    return {"OK": False, "error": "Cannot unadopt master node"}
                if not adopted:
                    return {"OK": True, "message": "Node already unadopted"}

            if adopted_el is None:
                anchor = node.find(ADOPTED_AFTER)
                adopted_el = ET.Element("adopted")
                index = list(node).index(anchor) + 1 if anchor is not None else 0
                adopted_el.tail = anchor.tail if anchor is not None else None
                node.insert(index, adopted_el)
            adopted_el.text = "True" if adopt else "False"
            _write_atomically(tree, map_path)
            state = "adopted" if adopt else "unadopted"
            Logger.info(f"[mock-nodeconf] node {node_uuid} {state}")
            return {"OK": True}
    return {"OK": False, "error": f"Node {node_uuid} not found"}


def handle_request(map_path: str, message: dict) -> dict:
    """Process one engine request; every path answers (Req/Rep socket)."""
    Logger.info(f"[mock-nodeconf] request {message}")
    try:
        action = message.get("action")
        if action != "nodelist_modify":
            return {"OK": False, "error": f"unknown action: {action}"}
        node_uuid = message.get("value")
        modify_action = message.get("modify_action")
        if modify_action not in ("ADD", "REMOVE"):
            return {"OK": False, "error": f"Invalid modify_action: {modify_action}"}
        return set_adopted(map_path, node_uuid, modify_action == "ADD")
    except Exception as e:
        Logger.error(f"[mock-nodeconf] {type(e).__name__}: {e}")
        return {"OK": False, "error": f"{type(e).__name__}: {e}"}


async def _make_socket_reachable():
    """The engine may run as another user: open the socket like nodeconf."""
    for _ in range(40):
        if os.path.exists(NODECONF_IPC):
            try:
                os.chmod(NODECONF_IPC, 0o666)
            except OSError as e:
                Logger.warning(f"[mock-nodeconf] could not chmod {NODECONF_IPC}: {e}")
            return
        await asyncio.sleep(0.05)
    Logger.warning(f"[mock-nodeconf] {NODECONF_IPC} did not appear")


async def serve(map_path: str):
    comm = Communicator(NODECONF_IPC)
    asyncio.get_running_loop().create_task(_make_socket_reachable())
    Logger.info(f"[mock-nodeconf] listening on {NODECONF_IPC}, map {map_path}")
    await comm.reply(lambda message: handle_request(map_path, message))


def main():
    parser = argparse.ArgumentParser(
        description="Mock cuems-nodeconf for headless deployments"
    )
    parser.add_argument("--map", default=DEFAULT_MAP, help="network_map.xml path")
    args, _ = parser.parse_known_args()

    if not os.path.isfile(args.map):
        Logger.error(f"[mock-nodeconf] {args.map} not found")
        sys.exit(1)
    _validate(args.map)

    loop = asyncio.new_event_loop()
    task = loop.create_task(serve(args.map))
    stopping = threading.Event()

    def handle_signal(signum, frame):
        Logger.info(f"[mock-nodeconf] signal {signum}, shutting down")
        stopping.set()
        loop.call_soon_threadsafe(task.cancel)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    try:
        loop.run_until_complete(task)
    except asyncio.CancelledError:
        pass
    finally:
        loop.close()
        # A socket file left behind makes the engine wait its full IPC
        # timeout instead of refusing at once ("nodeconf is not running").
        try:
            os.unlink(NODECONF_IPC)
        except OSError:
            pass
    if not stopping.is_set():
        # Communicator.reply() only returns after logging an error: exit
        # non-zero so systemd's Restart=on-failure brings us back.
        Logger.error("[mock-nodeconf] responder stopped unexpectedly")
        sys.exit(1)
    Logger.info("[mock-nodeconf] stopped")
    sys.exit(0)


if __name__ == "__main__":
    main()
