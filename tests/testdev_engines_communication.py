from logging import INFO
from time import sleep
from unittest.mock import patch

from cuemsengine import ControllerEngine, NodeEngine


def test_project_load_from_controller(
    mock_config_path,
    mock_avahi_resolve,
    mock_library_path,
    mock_controller_ip,
    mock_deploy_success,
    engine_cleanup,
    caplog,
):
    """Test the project load from the controller"""
    # ARRANGE
    caplog.set_level(INFO)
    controller_engine = ControllerEngine(with_mtc=False)
    controller_engine.set_comms()
    sleep(0.5)
    node_engine = NodeEngine(with_mtc=False)
    node_engine.set_oscquery_comms()
    sleep(0.5)
    # ACT
    controller_engine.load_project("empty_test")
    sleep(1)

    # ASSERT
    assert controller_engine.script is not None
    assert controller_engine.script.unix_name == "empty_test"
    assert node_engine.script is not None
    assert node_engine.script.unix_name == "empty_test"
    # assert "Project empty_test loaded" in caplog.text
    # assert "No media files to deploy" in caplog.text
    assert node_engine.get_status("load") == "empty_test"

    # CLEANUP
    engine_cleanup(controller_engine)
    engine_cleanup(node_engine)


def test_two_projects_load_from_controller(
    mock_config_path,
    mock_avahi_resolve,
    mock_library_path,
    mock_controller_ip,
    mock_deploy_success,
    mock_player_subprocess,
    engine_cleanup,
):
    """Test the project load from the controller"""
    # ARRANGE
    # from cuemsengine.cues.CueHandler import CUE_HANDLER

    controller_engine = ControllerEngine(with_mtc=False)
    controller_engine.set_comms()
    sleep(0.5)
    node_engine = NodeEngine(with_mtc=False)
    # CUE_HANDLER.set_nng_comms(node_engine.nng_hub_address, node_engine.cm.node_uuid)
    # node_engine.deploy_manager.loop = CUE_HANDLER.communications_thread.event_loop
    # node_engine.set_oscquery_comms()
    # node_engine.set_players()
    sleep(0.5)

    # ACT
    controller_engine.load_project("empty_test")
    sleep(2)
    controller_engine.load_project("complex_test")
    sleep(2)

    # ASSERT
    assert controller_engine.script is not None
    assert node_engine.script is not None
    assert controller_engine.script.name == "Test Main Script"
    assert node_engine.script.name == "Test Main Script"
    assert controller_engine.get_status("load") == "complex_test"
    assert node_engine.get_status("load") == "complex_test"

    # Assert player subprocess calls were mocked and recorded
    assert (
        len(mock_player_subprocess) > 0
    ), "Expected player subprocess calls to be recorded"
    player_types = {call["player"] for call in mock_player_subprocess}
    assert "VideoPlayer" in player_types, "Expected VideoPlayer to be called"
    # Verify each call has required fields
    for call in mock_player_subprocess:
        assert "player" in call
        assert "args" in call
        assert "pid" in call
        assert isinstance(call["args"], list), "Call args should be a list"

    # CLEANUP
    engine_cleanup(controller_engine)
    engine_cleanup(node_engine)
