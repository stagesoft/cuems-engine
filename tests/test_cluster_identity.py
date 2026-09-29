# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""One identity per node across the controller's cluster sets (FR-026).

Ids reach the controller in three types at once: the map's node uuids are
``Uuid`` (the library decodes uuid4 that way), its own uuid from
``settings.xml`` is ``str``, and pong/armed/finished senders arrive over NNG
as ``str``; project nodes are sliced out of ``output_name`` as ``str``. The
GO gate's sets must hold one member per node regardless, and everything that
leaves the process (``cluster_warning``) must be ``str``.
"""

from os import environ
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cuemsengine.comms.NodesHub import ActionType, NodeOperation, OperationType

from .network_map_helpers import controller_with_map, typed_network_map

CONTROLLER = "3f2b8c1e-5d4a-4b6e-9c7f-1a2b3c4d5e6f"
PLAYING = "9a8b7c6d-1e2f-4a3b-8c4d-5e6f7a8b9c0d"  # adopted, alive, used
SILENT = "5b1d2e3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f"  # adopted, used, no pong
IDLE = "6d6d6d6d-0000-4000-8000-000000000006"  # adopted, alive, unused
UNADOPTED = "7c7c7c7c-0000-4000-8000-000000000007"  # in the map, used
# G5: a uuid4 a project still names after the node was re-minted — absent
# from the map altogether.
STALE = "8e8e8e8e-0000-4000-8000-000000000008"

ALIVE_REMOTE = (PLAYING, IDLE)


@pytest.fixture(autouse=True)
def set_config_path():
    environ["CUEMS_CONF_PATH"] = str(
        Path(__file__).parent / ".." / "dev" / "test_xml_files"
    )


@pytest.fixture
def controller(tmp_path):
    network_map = typed_network_map(
        tmp_path,
        [
            {"uuid": CONTROLLER, "node_role": "controller", "adopted": True},
            {"uuid": PLAYING, "adopted": True},
            {"uuid": SILENT, "adopted": True},
            {"uuid": IDLE, "adopted": True},
            {"uuid": UNADOPTED, "adopted": False},
        ],
    )
    with controller_with_map(CONTROLLER, network_map) as engine:
        engine.script = SimpleNamespace(
            cuelist=SimpleNamespace(
                contents=[
                    SimpleNamespace(outputs=[{"output_name": f"{CONTROLLER}_0"}]),
                    SimpleNamespace(outputs=[{"output_name": f"{PLAYING}_1"}]),
                    SimpleNamespace(outputs=[{"output_name": SILENT}]),
                    SimpleNamespace(outputs=[{"output_name": f"{UNADOPTED}_0"}]),
                    SimpleNamespace(outputs=[{"output_name": f"{STALE}_2"}]),
                ]
            )
        )
        yield engine


def _status_op(sender, target, data):
    return NodeOperation(
        type=OperationType.STATUS,
        action=ActionType.UPDATE,
        sender=sender,
        target=target,
        data=data,
    )


def _resolve(controller):
    """Run the load-time resolution; remote nodes pong back as ``str``.

    The ping is intercepted where it would leave for the NNG loop, and the
    pongs are fed through ``status_operation_callback`` — the path real replies
    take.
    """
    hub = controller.communications_thread.nng_hub

    def deliver(_coro, _loop):
        (operation,), _ = hub.send_operation.call_args
        if operation.target == "ping":
            for sender in ALIVE_REMOTE:
                controller.status_operation_callback(_status_op(sender, "pong", {}))

    # Pongs land synchronously inside the send, so the wait has nothing to
    # wait for; the silent node would otherwise cost the full probe timeout.
    with (
        patch(
            "cuemsengine.ControllerEngine.asyncio.run_coroutine_threadsafe",
            side_effect=deliver,
        ),
        patch.object(controller._pong_event, "wait"),
    ):
        controller._resolve_cluster_state()
    return controller._load_diagnosis


def test_required_holds_one_member_per_node(controller):
    _resolve(controller)
    assert controller._required_nodes == {CONTROLLER, PLAYING}
    assert len(controller._required_nodes) == 2


def test_missing_and_unreachable_are_str_and_exclude_the_controller(controller):
    diagnosis = _resolve(controller)
    assert diagnosis["missing"] == sorted([UNADOPTED, STALE])
    assert diagnosis["unreachable"] == [SILENT]
    for key in ("missing", "unreachable"):
        assert all(type(u) is str for u in diagnosis[key]), (key, diagnosis[key])
        assert CONTROLLER not in diagnosis[key]


def test_a_stale_output_prefix_is_reported_missing(controller):
    """G5: a project naming a uuid4 no longer in the map is flagged, as ``str``."""
    diagnosis = _resolve(controller)
    assert STALE in diagnosis["missing"]


def test_armed_ready_from_str_senders_opens_the_gate(controller):
    _resolve(controller)
    controller.set_status("armed", "no")
    controller.go_offset = 0
    for sender in (CONTROLLER, PLAYING):
        controller.status_operation_callback(
            _status_op(sender, "armed_ready", {"armed": "yes"})
        )
    assert len(controller._armed_nodes) == 2
    assert controller.get_status("armed") == "yes"


def test_script_finished_from_str_senders_closes_the_run(controller):
    _resolve(controller)
    controller.set_status("running", "yes")
    for sender in (CONTROLLER, PLAYING):
        controller.status_operation_callback(
            _status_op(sender, "script_finished", {"running": "no"})
        )
    assert len(controller._finished_nodes) == 2
    assert controller.get_status("running") == "no"


def test_repeated_pongs_count_once(controller):
    _resolve(controller)
    controller.status_operation_callback(_status_op(PLAYING, "pong", {}))
    assert len(controller._pong_responses) == len(ALIVE_REMOTE)
