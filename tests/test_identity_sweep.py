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

import json
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
    """Nodes report cue ids as text; the script's are ``Uuid``.

    A cue ADD is only honoured while the show is running (869fhjdq5).
    """
    controller.set_status("running", "yes")
    controller.cue_status = {as_id(CUE): 0}
    controller.communications_thread.broadcast_osc.reset_mock()

    controller.cue_operation_callback(_cue_op(ActionType.ADD, {"id": CUE, "offset": 0}))

    assert len(controller.cue_status) == 1
    assert controller.cue_status[CUE] == 1
    controller.communications_thread.broadcast_osc.assert_any_call(
        f"/engine/status/cue/{CUE}", 1
    )


def test_an_editor_cue_add_is_ignored_while_not_running(controller):
    """A late start report after a STOP must not leave the cue at 1."""
    controller.set_status("running", "no")
    controller.cue_status = {as_id(CUE): 0}
    controller.communications_thread.broadcast_osc.reset_mock()

    with patch("cuemsengine.ControllerEngine.Logger") as log:
        controller.cue_operation_callback(
            _cue_op(ActionType.ADD, {"id": CUE, "offset": 0})
        )

    assert controller.cue_status[CUE] == 0
    controller.communications_thread.broadcast_osc.assert_not_called()
    (message,), _ = log.debug.call_args
    assert f"Ignoring cue {ActionType.ADD} for {CUE}: not running" in message


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


# ─── 009 A-5: ids that leave the process from the absorbed release line ───
#
# The cross-node follow relay, stop_project, cue names, the unrouted-output
# report and the audio player naming arrived with the release line. Each place
# below puts an id on the wire, in an OSC address or in a JACK client name;
# fed a ``Uuid`` (what a loaded script holds), it must emit plain ``str`` text:
# a ``Uuid`` is not JSON serializable and has no ``split``.

CUE_A = "2c2c2c2c-0000-4000-8000-00000000000a"
CUE_B = "3d3d3d3d-0000-4000-8000-00000000000b"


def _is_text(value, expected):
    return type(value) is str and value == expected


def _relay():
    from cuemsengine.cues.FollowRelay import FollowRelay

    sent = []
    relay = FollowRelay(
        cue_handler=Mock(),
        node_id=NODE,
        send=sent.append,
        get_script=lambda: None,
        get_mtc=lambda: None,
        get_project_gen=lambda: 0,
        first_local=lambda cue: None,
    )
    return relay, sent


def _follow_cue():
    return SimpleNamespace(
        id=as_id(CUE_A), _target_object=SimpleNamespace(id=as_id(CUE_B))
    )


def test_follow_announce_emits_its_cue_ids_as_text():
    relay, sent = _relay()
    relay.announce(_follow_cue(), 1500.0, 7)

    (data,) = sent
    assert _is_text(data["source"], CUE_A)
    assert _is_text(data["target"], CUE_B)
    json.dumps(data)


def test_follow_cancel_emits_its_cue_ids_as_text():
    relay, sent = _relay()
    relay.cancel(_follow_cue(), 1500.0, 7, "stopped")

    (data,) = sent
    assert data["op"] == "cancel"
    assert _is_text(data["source"], CUE_A)
    assert _is_text(data["target"], CUE_B)
    json.dumps(data)


def test_a_follow_announced_with_str_ids_finds_the_scripts_uuid_cues():
    """Incoming: the controller relays ``str`` ids; the script's cues hold ``Uuid``."""
    relay, _ = _relay()
    cues = {as_id(CUE_A): SimpleNamespace(_local=False), as_id(CUE_B): object()}
    relay._get_script = lambda: SimpleNamespace(find=lambda cue_id: cues.get(cue_id))
    relay._get_mtc = lambda: object()

    with patch("cuemsengine.cues.FollowRelay.Logger") as log:
        relay.on_message(
            {
                "op": "announce",
                "origin": "other-node",
                "source": CUE_A,
                "target": CUE_B,
                "seed_ms": 1000,
                "run_seq": 1,
            }
        )

    refusals = [str(c.args[0]) for c in log.warning.call_args_list]
    assert not any("not in the loaded project" in message for message in refusals)


def _stop_project_outcome(cue_id):
    from cuemsengine.cues.ActionHandler import _handle_stop_project

    cue = SimpleNamespace(id=as_id(cue_id))
    return _handle_stop_project(Mock(), cue, None, Mock())


def test_stop_project_outcome_names_its_origin_cue_as_text():
    outcome = _stop_project_outcome(CUE_A)

    assert _is_text(outcome["origin_cue_id"], CUE_A)
    json.dumps(outcome)


def test_stop_project_status_op_carries_the_cue_as_text():
    from cuemsengine.NodeEngine import NodeEngine

    node = object.__new__(NodeEngine)
    node.cm = SimpleNamespace(node_uuid=NODE)
    node._follow_relay = SimpleNamespace(
        run_seq=5, stop_pending=False, stops_received=0
    )
    node._stop_project_watchdog = None
    with (
        patch("cuemsengine.NodeEngine.CUE_HANDLER") as cue_handler,
        patch("cuemsengine.NodeEngine.threading.Timer"),
    ):
        node._notify_stop_project(as_id(CUE_A))

    (operation,), _ = cue_handler.communications_thread.send_operation_nowait.call_args
    assert _is_text(operation.data["cue"], CUE_A)
    json.dumps(operation.data)


def test_project_status_reports_the_project_uuid_as_text(controller):
    controller.set_status("load", "my_show")
    controller.script = SimpleNamespace(id=as_id(CUE), unix_name="my_show")

    status = controller.get_project_status(None)

    assert _is_text(status["project_uuid"], CUE)
    json.dumps(status)


def test_cue_name_address_carries_the_cue_id_as_text(controller):
    controller.communications_thread.broadcast_osc.reset_mock()

    controller._broadcast_cue_name(as_id(CUE_A), "Intro")

    controller.communications_thread.broadcast_osc.assert_called_once_with(
        f"/engine/status/cue_name/{CUE_A}", "Intro"
    )


def test_unrouted_video_report_names_its_cue_as_text():
    from cuemsutils.cues import VideoCue

    from cuemsengine.NodeEngine import NodeEngine

    cue = VideoCue()
    cue.name = "Dark"
    node = object.__new__(NodeEngine)
    node.script = Mock(find=lambda cue_id: cue)
    node.outputs_map = {cue.id: ["2"]}
    with patch("cuemsengine.NodeEngine.PLAYER_HANDLER") as players:
        players.partition_cue_outputs.return_value = ([], [("2", "not driven")])
        players.driven_video_outputs.return_value = ["0=HDMI-A-1"]
        found = node.check_unrouted_video_outputs()

    (report,) = found
    assert type(report["cue_id"]) is str and report["cue_id"] == str(cue.id)
    json.dumps(found)


def test_audio_player_jack_name_is_the_cue_id_without_hyphens():
    from threading import RLock

    from cuemsutils.cues import AudioCue

    from cuemsengine.players.PlayerHandler import PlayerHandler

    handler = object.__new__(PlayerHandler)
    handler._lock = RLock()
    handler._cue_players = {}
    handler._audio_players_by_id = {}
    handler._audio_output_generator = Mock(return_value=(Mock(p=None), Mock()))
    handler._player_endpoints_generator = Mock()
    handler._audio_mixer = Mock()
    handler._audio_outputs = {"6": {"mapped_to": "system:playback_1"}}
    handler._media_folder = "/tmp"
    cue = AudioCue()
    cue.media = {"file_name": "a.wav"}
    cue.outputs = [{"output_name": f"{NODE}_6"}]

    with patch("cuemsengine.players.PlayerHandler.PORT_HANDLER") as ports:
        ports.assign_ports.return_value = {"audio_output": 9999}
        handler.new_audio_output(cue)

    name = handler._audio_mixer.connect_player_to_outputs.call_args.kwargs[
        "player_name"
    ]
    assert name == "Audio_Player-" + str(cue.id).replace("-", "")
