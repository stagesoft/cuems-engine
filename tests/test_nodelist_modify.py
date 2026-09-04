# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

"""Tests for the editor -> engine -> nodeconf adopt/un-adopt path.

The engine hop for `nodelist_modify` never existed on any live branch (it was
written once and archived), so the button in the UI reached
`raise ValueError("Command nodelist_modify not recognized")`. These tests pin
the behaviour of the re-landed hop, and in particular the two things that made
the archived version wrong:

* `modify_action` must actually reach nodeconf — the dispatch table calls every
  handler as `(value, context)`, so a table-registered handler receives None and
  nodeconf answers "Invalid modify_action: None" to every click.
* `request_to_nodeconf` returns None (not an exception) when nodeconf is absent,
  which is the fleet default; `.get()` on that raised AttributeError.
"""

from os import environ
from pathlib import Path
from unittest.mock import Mock, patch

import pytest


@pytest.fixture(autouse=True)
def set_config_path():
    """Point CUEMS_CONF_PATH at test XML files."""
    test_conf_path = Path(__file__).parent / ".." / "dev" / "test_xml_files"
    environ["CUEMS_CONF_PATH"] = str(test_conf_path)


@pytest.fixture
def controller():
    """A minimal ControllerEngine with the heavy dependencies mocked out."""
    with (
        patch("cuemsengine.core.BaseEngine.ConfigManager") as MockCM,
        patch(
            "cuemsengine.core.BaseEngine.BaseEngine.get_controller_ip",
            return_value="localhost",
        ),
    ):
        mock_cm_instance = MockCM.return_value
        mock_cm_instance.node_conf = {
            "uuid": "test-controller-uuid",
            "mtc_port": "MTC_MIDI_PORT",
        }
        mock_cm_instance.library_path = str(
            Path(__file__).parent / ".." / "dev" / "test_xml_files"
        )
        mock_cm_instance.tmp_path = "/tmp"

        from cuemsengine.ControllerEngine import ControllerEngine

        engine = ControllerEngine(with_mtc=False)

        engine.communications_thread = Mock()
        engine.communications_thread.broadcast_osc = Mock()
        engine.communications_thread.nng_hub = Mock()

        # No project loaded, nothing running: the setup-time state in which
        # adoption is allowed.
        engine.set_status("running", "no")
        engine.set_status("load", "")

        yield engine

        engine.stop()


NODE = "4b9b5a1e-0000-4000-8000-0123456789ab"


def _ok_reply():
    return {"OK": True}


# ─── the message that reaches nodeconf ───────────────────────────────────


class TestModifyActionReachesNodeconf:
    def test_modify_action_survives_dispatch(self, controller):
        """The whole point: modify_action must not be lost on the way down.

        A table-registered handler would be called as (value, context) and send
        modify_action=None, which nodeconf rejects for every single click.
        """
        controller.communications_thread.request_to_nodeconf.return_value = _ok_reply()
        with (
            patch.object(controller, "confirm_to_editor") as mock_confirm,
            patch.object(controller, "set_editor_request"),
            patch.object(controller, "_reload_network_map"),
        ):
            controller.handle_editor_command(
                "nodelist_modify", NODE, context="ctx", modify_action="ADD"
            )

        sent = controller.communications_thread.request_to_nodeconf.call_args[0][0]
        assert sent == {
            "action": "nodelist_modify",
            "value": NODE,
            "modify_action": "ADD",
        }
        mock_confirm.assert_called_once()
        assert mock_confirm.call_args[1]["value"] == "OK"
        assert mock_confirm.call_args[1]["type"] == "nodelist_modify"

    def test_remove_is_forwarded_too(self, controller):
        controller.communications_thread.request_to_nodeconf.return_value = _ok_reply()
        with (
            patch.object(controller, "confirm_to_editor"),
            patch.object(controller, "set_editor_request"),
            patch.object(controller, "_reload_network_map"),
        ):
            controller.handle_editor_command(
                "nodelist_modify", NODE, context="ctx", modify_action="REMOVE"
            )
        sent = controller.communications_thread.request_to_nodeconf.call_args[0][0]
        assert sent["modify_action"] == "REMOVE"

    def test_callback_forwards_modify_action_from_the_wire(self, controller):
        """editor_command_callback must pick modify_action out of the frame."""
        controller.communications_thread.request_to_nodeconf.return_value = _ok_reply()
        with (
            patch.object(controller, "confirm_to_editor"),
            patch.object(controller, "set_editor_request"),
            patch.object(controller, "_reload_network_map"),
        ):
            controller.editor_command_callback(
                {
                    "action": "nodelist_modify",
                    "value": NODE,
                    "modify_action": "ADD",
                    "action_uuid": "uuid-1",
                },
                "ctx",
            )
        sent = controller.communications_thread.request_to_nodeconf.call_args[0][0]
        assert sent["modify_action"] == "ADD"


# ─── failure paths reach the operator as a sentence ──────────────────────


class TestFailuresAreLegible:
    def test_none_reply_is_an_error_not_a_traceback(self, controller):
        """An absent nodeconf socket returns None, not an exception."""
        controller.communications_thread.request_to_nodeconf.return_value = None
        with (
            patch.object(controller, "confirm_to_editor") as mock_confirm,
            patch.object(controller, "error_to_editor") as mock_error,
        ):
            result = controller.nodelist_modify(
                {"action": "nodelist_modify", "value": NODE, "modify_action": "ADD"},
                "ctx",
            )
        assert result is False
        mock_confirm.assert_not_called()
        mock_error.assert_called_once()
        assert "not responding" in mock_error.call_args[1]["value"]
        assert mock_error.call_args[1]["action"] == "nodelist_modify"

    def test_nodeconf_error_text_is_forwarded_verbatim(self, controller):
        controller.communications_thread.request_to_nodeconf.return_value = {
            "OK": False,
            "error": "Cannot unadopt master node",
        }
        with patch.object(controller, "error_to_editor") as mock_error:
            result = controller.nodelist_modify(
                {"action": "nodelist_modify", "value": NODE, "modify_action": "REMOVE"},
                "ctx",
            )
        assert result is False
        assert mock_error.call_args[1]["value"] == "Cannot unadopt master node"

    def test_transport_exception_is_caught(self, controller):
        controller.communications_thread.request_to_nodeconf.side_effect = TimeoutError(
            "boom"
        )
        with patch.object(controller, "error_to_editor") as mock_error:
            result = controller.nodelist_modify(
                {"action": "nodelist_modify", "value": NODE, "modify_action": "ADD"},
                "ctx",
            )
        assert result is False
        assert "Could not reach cuems-nodeconf" in mock_error.call_args[1]["value"]

    def test_missing_uuid_is_refused_before_the_hop(self, controller):
        with patch.object(controller, "error_to_editor") as mock_error:
            result = controller.nodelist_modify(
                {"action": "nodelist_modify", "value": "", "modify_action": "ADD"},
                "ctx",
            )
        assert result is False
        controller.communications_thread.request_to_nodeconf.assert_not_called()
        assert "node uuid" in mock_error.call_args[1]["value"]

    def test_bad_modify_action_is_refused_before_the_hop(self, controller):
        with patch.object(controller, "error_to_editor") as mock_error:
            result = controller.nodelist_modify(
                {"action": "nodelist_modify", "value": NODE, "modify_action": "FLIP"},
                "ctx",
            )
        assert result is False
        controller.communications_thread.request_to_nodeconf.assert_not_called()
        assert "Invalid modify_action" in mock_error.call_args[1]["value"]

    def test_refusal_never_raises(self, controller):
        """A guard must not raise: the callback's except clause replies too,
        and the operator would read
        "Engine reports error: Command <class 'RuntimeError'>: ...".
        """
        controller.set_status("running", "yes")
        with patch.object(controller, "error_to_editor"):
            # No pytest.raises here on purpose — raising is the defect.
            assert (
                controller.nodelist_modify(
                    {
                        "action": "nodelist_modify",
                        "value": NODE,
                        "modify_action": "ADD",
                    },
                    "ctx",
                )
                is False
            )


# ─── the guards ──────────────────────────────────────────────────────────


class TestProjectStateGuards:
    def test_refused_while_running(self, controller):
        controller.set_status("running", "yes")
        with patch.object(controller, "error_to_editor") as mock_error:
            result = controller.nodelist_modify(
                {"action": "nodelist_modify", "value": NODE, "modify_action": "ADD"},
                "ctx",
            )
        assert result is False
        controller.communications_thread.request_to_nodeconf.assert_not_called()
        assert "while a project is running" in mock_error.call_args[1]["value"]

    def test_refused_while_merely_loaded(self, controller):
        """_required_nodes is computed once, at load_project. A REMOVE accepted
        now would leave the GO gate waiting on a node just removed.
        """
        controller.set_status("running", "no")
        controller.set_status("load", "some-project")
        with patch.object(controller, "error_to_editor") as mock_error:
            result = controller.nodelist_modify(
                {"action": "nodelist_modify", "value": NODE, "modify_action": "REMOVE"},
                "ctx",
            )
        assert result is False
        controller.communications_thread.request_to_nodeconf.assert_not_called()
        assert "while a project is loaded" in mock_error.call_args[1]["value"]

    def test_allowed_when_idle(self, controller):
        controller.communications_thread.request_to_nodeconf.return_value = _ok_reply()
        with (
            patch.object(controller, "error_to_editor") as mock_error,
            patch.object(controller, "_reload_network_map"),
        ):
            result = controller.nodelist_modify(
                {"action": "nodelist_modify", "value": NODE, "modify_action": "ADD"},
                "ctx",
            )
        assert result is True
        mock_error.assert_not_called()


# ─── the cached topology stops lying ─────────────────────────────────────


class TestTopologyReload:
    def test_success_reloads_the_map_and_reregisters_routes(self, controller):
        controller.communications_thread.request_to_nodeconf.return_value = _ok_reply()
        with (
            patch.object(controller, "_register_node_osc_handlers") as mock_reg,
            patch.object(controller, "error_to_editor"),
        ):
            result = controller.nodelist_modify(
                {"action": "nodelist_modify", "value": NODE, "modify_action": "ADD"},
                "ctx",
            )
        assert result is True
        controller.cm.load_network_map.assert_called_once()
        mock_reg.assert_called_once()

    def test_no_reload_when_nodeconf_refused(self, controller):
        controller.communications_thread.request_to_nodeconf.return_value = {
            "OK": False,
            "error": "node is offline",
        }
        with patch.object(controller, "error_to_editor"):
            controller.nodelist_modify(
                {"action": "nodelist_modify", "value": NODE, "modify_action": "ADD"},
                "ctx",
            )
        controller.cm.load_network_map.assert_not_called()

    def test_partial_success_is_reported_as_an_error(self, controller):
        """XML written by nodeconf, reload failed: the UI must not get a green
        toast over a stale engine.
        """
        controller.communications_thread.request_to_nodeconf.return_value = _ok_reply()
        with (
            patch.object(
                controller, "_reload_network_map", side_effect=OSError("permission")
            ),
            patch.object(controller, "confirm_to_editor") as mock_confirm,
            patch.object(controller, "error_to_editor") as mock_error,
        ):
            result = controller.nodelist_modify(
                {"action": "nodelist_modify", "value": NODE, "modify_action": "ADD"},
                "ctx",
            )
        assert result is False
        mock_confirm.assert_not_called()
        msg = mock_error.call_args[1]["value"]
        assert "could not reload the topology" in msg
        assert "restart cuems-controller-engine" in msg
