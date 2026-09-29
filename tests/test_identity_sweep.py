# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""Identity beyond the controller's cluster paths (Group 7: FR-024, FR-025, FR-027).

Characterization first: each place an engine reads its own uuid, or an editor
cue id meets the script's ``Uuid`` cue ids, keeps behaving as it did once ids
go through ``as_id``/``id_str``. Then the NOT PROVISIONED pre-load check: a
node whose ``settings.xml`` still carries the sentinel uuid is told so,
instead of failing later with a generic "node not found".
"""

import logging
from os import environ
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from cuemsutils.tools.ConfigManager import ConfigManager
from cuemsutils.tools.identity_check import SENTINEL

from cuemsengine.comms.NodesHub import ActionType, NodeOperation, OperationType
from cuemsengine.core.BaseEngine import BaseEngine
from cuemsengine.tools.ids import as_id

from .network_map_helpers import controller_with_map, write_config_dir

FIXTURES = Path(__file__).parent / ".." / "dev" / "test_xml_files"
FIXTURE_OWN_UUID = "0367f391-ebf4-48b2-9f26-000000000001"  # a uuid4
CONTROLLER = "3f2b8c1e-5d4a-4b6e-9c7f-1a2b3c4d5e6f"
NODE = "9a8b7c6d-1e2f-4a3b-8c4d-5e6f7a8b9c0d"
CUE = "4c4c4c4c-0000-4000-8000-00000000c0e1"


@pytest.fixture
def fixture_config(monkeypatch):
    monkeypatch.setitem(environ, "CUEMS_CONF_PATH", str(FIXTURES))


def _bare_engine():
    return BaseEngine(with_cm=False, with_mtc=False, with_signals=False)


# ─── characterization (green before and after the sweep) ─────────────────


def test_node_name_is_the_own_uuid_as_text(fixture_config):
    engine = _bare_engine()
    engine.set_config_manager()
    assert type(engine.node_name) is str
    assert engine.node_name == FIXTURE_OWN_UUID


def test_dmx_player_is_named_after_the_own_uuid():
    from cuemsengine.NodeEngine import NodeEngine

    fake = SimpleNamespace(
        cm=SimpleNamespace(
            node_conf={"uuid": NODE, "dmxplayer": {"args": "", "path": "/bin/true"}}
        )
    )
    with (
        patch("cuemsengine.NodeEngine.PORT_HANDLER") as ports,
        patch("cuemsengine.NodeEngine.PLAYER_HANDLER") as players,
        patch("cuemsengine.NodeEngine.CUE_HANDLER") as cues,
    ):
        ports.assign_ports.return_value = {"dmx_player": 7001}
        NodeEngine.set_dmx_players(fake)

    kwargs = players.start_dmx_player.call_args.kwargs
    assert type(kwargs["node_uuid"]) is str
    assert kwargs["node_uuid"] == NODE
    cues.communications_thread.add_player.assert_called_once_with(
        f"dmxplayer_{NODE}", None, timeout=0.1
    )


@pytest.fixture
def controller(tmp_path, fixture_config):
    from .network_map_helpers import typed_network_map

    network_map = typed_network_map(
        tmp_path,
        [
            {"uuid": CONTROLLER, "node_role": "controller", "adopted": True},
            {"uuid": NODE, "adopted": True},
        ],
    )
    with controller_with_map(CONTROLLER, network_map) as engine:
        yield engine


def test_direct_player_route_forwards_a_str_uuid_address(controller):
    address = f"/{NODE}/audio/mixer/0/1/volume"
    hub = controller.communications_thread.nng_hub
    with patch("asyncio.run_coroutine_threadsafe"):
        controller._handle_direct_player_osc_message(address, [0.5])

    assert controller.mixer_status[f"{NODE}/0/1"] == 0.5
    (operation,), _ = hub.send_operation.call_args
    assert operation.data == {"address": address, "value": 0.5}
    assert type(operation.sender) is str and operation.sender == CONTROLLER


def _cue_op(action, data):
    return NodeOperation(
        type=OperationType.CUE, action=action, sender=NODE, target="", data=data
    )


def test_an_editor_cue_id_as_str_matches_the_scripts_uuid_cue_id(controller):
    """Nodes report cue ids as text; the script's are ``Uuid``."""
    controller.cue_status = {as_id(CUE): 0}
    controller.communications_thread.broadcast_osc.reset_mock()

    controller.cue_operation_callback(_cue_op(ActionType.ADD, {"id": CUE, "offset": 0}))

    assert len(controller.cue_status) == 1
    assert controller.cue_status[CUE] == 1
    controller.communications_thread.broadcast_osc.assert_any_call(
        f"/engine/status/cue/{CUE}", 1
    )


def test_a_cue_enabled_update_as_str_matches_the_scripts_uuid_cue_id(controller):
    controller.cue_enabled_status = {as_id(CUE): True}
    controller.communications_thread.broadcast_osc.reset_mock()

    controller.status_operation_callback(
        NodeOperation(
            type=OperationType.STATUS,
            action=ActionType.UPDATE,
            sender=NODE,
            target="cue_enabled",
            data={"cue_id": CUE, "enabled": False},
        )
    )

    assert len(controller.cue_enabled_status) == 1
    assert controller.cue_enabled_status[CUE] is False
    controller.communications_thread.broadcast_osc.assert_any_call(
        f"/engine/status/cue_enabled/{CUE}", 0
    )


# ─── FR-027 (G2): the NOT PROVISIONED sentinel ───────────────────────────


@pytest.fixture
def unprovisioned(tmp_path, monkeypatch):
    """A config dir whose settings.xml own uuid is the sentinel.

    The map names a real node, so without the pre-load check the loader fails
    later with a generic "Node with uuid … not found".
    """
    write_config_dir(tmp_path, [{"uuid": NODE, "node_role": "controller"}])
    settings = tmp_path / "settings.xml"
    settings.write_text(settings.read_text().replace(NODE, SENTINEL))
    monkeypatch.setitem(environ, "CUEMS_CONF_PATH", str(tmp_path))
    return tmp_path


def test_an_unprovisioned_node_is_named_as_such_and_exits_before_loading(
    unprovisioned, caplog
):
    constructed = []

    def spy(*args, **kwargs):
        constructed.append(kwargs.get("load_all", args[1] if len(args) > 1 else True))
        return ConfigManager(*args, **kwargs)

    engine = _bare_engine()
    with (
        patch("cuemsengine.core.BaseEngine.ConfigManager", Mock(side_effect=spy)),
        caplog.at_level(logging.ERROR),
        pytest.raises(SystemExit),
    ):
        engine.set_config_manager()

    assert True not in constructed, constructed
    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1, errors
    assert "NOT PROVISIONED" in errors[0]
    assert "cuems-init-node" in errors[0]


def test_gradient_node_name_fallback_is_text_even_for_a_typed_uuid():
    """gradient-motiond takes node_name as an OSC string ("s"): a settings uuid
    the library may one day deliver as a ``Uuid`` must still leave as text."""
    from cuemsengine.NodeEngine import NodeEngine

    fake = SimpleNamespace(
        cm=SimpleNamespace(node_network_map={}, node_uuid=as_id(NODE))
    )
    name = NodeEngine._resolve_gradient_node_name(fake)
    assert type(name) is str
    assert name == NODE
