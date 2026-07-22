# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

import threading
from time import sleep, time

import pytest

from cuemsengine import ControllerEngine, NodeEngine

from .conftest import engine_cleanup  # type: ignore[import-untyped]
from .fixtures import (
    mock_avahi_resolve,
    mock_config_path,
    mock_controller_ip,
    mock_deploy_success,
    mock_display_conf,
    mock_library_path,
    mock_player_clients,
    mock_player_subprocess,
    suppress_logging,
)
from .helpers import timeout

# Controller↔node load+go against live NNG/MTC — same class as
# test_project_load (excluded from fast unit runs).
pytestmark = pytest.mark.integration


@pytest.mark.slow
def test_project_go_from_controller(
    mock_config_path,
    mock_avahi_resolve,
    mock_library_path,
    mock_controller_ip,
    mock_deploy_success,
    mock_display_conf,
    mock_player_clients,
    mock_player_subprocess,
    suppress_logging,
    engine_cleanup,
):
    # ARRANGE
    controller_engine = ControllerEngine(with_mtc=True)
    engine_cleanup(controller_engine)
    controller_engine.create_timecode()
    controller_engine.set_comms()

    # NodeEngine.start() binds NNG + players (replaces set_communications),
    # then falls into BaseEngine/SignalEngine's blocking run loop (the real
    # systemd entrypoint never returns) - it must run off-thread here, same
    # as the production process. engine_cleanup's teardown calls
    # node_engine.stop() which flips SignalEngine.running=False and lets
    # the loop exit on its own.
    node_engine = NodeEngine(with_mtc=True)
    engine_cleanup(node_engine)
    node_thread = threading.Thread(target=node_engine.start, daemon=True)
    node_thread.start()
    sleep(1.5)

    # ACT - Load project (this will create player clients)
    controller_engine.load_project("complex_test")
    deadline = time() + 10.0
    while node_engine.get_status("load") != "complex_test":
        if time() > deadline:
            raise TimeoutError(
                f"node never reached load=complex_test "
                f"(got {node_engine.get_status('load')!r})"
            )
        sleep(0.01)
    # ACT
    with timeout(10):
        controller_engine.go_script("complex_test")
        sleep(1)

    # ASSERT - Verify engines loaded project
    assert node_engine.get_status("running") == "yes", "Node engine is not running"

    assert controller_engine.script is not None
    assert node_engine.script is not None
    assert controller_engine.script.name == "Test Main Script"
    assert node_engine.script.name == "Test Main Script"
    assert controller_engine.get_status("load") == "complex_test"
    assert node_engine.get_status("load") == "complex_test"

    # ASSERT - Verify player clients were mocked and recorded
    print(f"\n📊 Mock Player Clients Created:" f"{len(mock_player_clients['clients'])}")
    for client in mock_player_clients["clients"]:
        print(f"   - {client['name']} on port {client['port']}")

    assert (
        len(mock_player_clients["clients"]) > 0
    ), "Expected player clients to be created"
    client_names = {client["name"] for client in mock_player_clients["clients"]}

    # Verify we have expected player types
    has_video = any("video" in name for name in client_names)
    has_dmx = any("dmx" in name or "mixer" in name for name in client_names)
    assert has_video or has_dmx, f"Expected video or dmx players, got: {client_names}"

    # If commands were sent, verify they have correct structure
    print(f"📊 Mock Commands Recorded: {len(mock_player_clients['commands'])}")
    for cmd in mock_player_clients["commands"]:  # Show first 5
        print(f"   - {cmd['client']}: {cmd['node']} = {cmd['value']}")

    for cmd in mock_player_clients["commands"]:
        assert "client" in cmd
        assert "node" in cmd
        assert "value" in cmd
        assert "port" in cmd
