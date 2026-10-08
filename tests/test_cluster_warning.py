# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

"""Tests for the load-time cluster diagnosis (the "missing node" alert).

Un-adopt a node — or let it die — then load a project whose cues use its
outputs: the load answers OK, the GO gate turns green, and those cues never
fire. `_resolve_cluster_state` already knew, but only told the journal.

Two invariants are pinned here, and the second one is the important one:

* the diagnosis reaches the UI, at load and on a late join, and clears itself
  when its cause goes away;
* `required` is byte-identical to what it was before this feature. The operator
  decision was *warn loudly, never block GO*, and a plan that quietly changed
  the arm gate could turn a mute cue into a dead show.
"""

import json
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
            "uuid": CONTROLLER,
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

        engine.set_status("running", "no")
        engine.set_status("load", "")

        yield engine

        engine.stop()


CONTROLLER = "test-controller-uuid"
NODE1 = "4b9b5a1e-0000-4000-8000-000000000001"
NODE2 = "4b9b5a1e-0000-4000-8000-000000000002"


def resolve(controller, *, adopted, alive, project):
    """Run _resolve_cluster_state over a made-up cluster shape."""
    controller.script = Mock()
    with (
        patch.object(
            controller, "_adopted_uuids_from_network_map", return_value=set(adopted)
        ),
        patch.object(controller, "_probe_cluster_liveness", return_value=set(alive)),
        patch.object(
            controller, "_collect_project_nodes", return_value=set(project)
        ),
        patch.object(controller, "_arm_arm_watchdog"),
    ):
        controller._resolve_cluster_state()
    return controller._load_diagnosis


def broadcast_warnings(controller):
    """Every cluster_warning payload pushed so far, parsed."""
    return [
        json.loads(call[0][1])
        for call in controller.communications_thread.broadcast_osc.call_args_list
        if call[0][0] == "/engine/status/cluster_warning"
    ]


# ─── what the diagnosis says ─────────────────────────────────────────────


class TestDiagnosisShapes:
    def test_clean_load_says_nothing_is_wrong(self, controller):
        d = resolve(
            controller,
            adopted={CONTROLLER, NODE1},
            alive={CONTROLLER, NODE1},
            project={CONTROLLER, NODE1},
        )
        assert d["missing"] == []
        assert d["unreachable"] == []

    def test_project_node_not_in_the_cluster_is_missing(self, controller):
        """The operator un-adopted it, or it was never adopted."""
        d = resolve(
            controller,
            adopted={CONTROLLER},
            alive={CONTROLLER},
            project={CONTROLLER, NODE1},
        )
        assert d["missing"] == [NODE1]
        assert d["unreachable"] == []

    def test_adopted_but_silent_project_node_is_unreachable(self, controller):
        """It is in the map and the project uses it — it just did not answer."""
        d = resolve(
            controller,
            adopted={CONTROLLER, NODE1},
            alive={CONTROLLER},
            project={CONTROLLER, NODE1},
        )
        assert d["missing"] == []
        assert d["unreachable"] == [NODE1]

    def test_both_at_once_are_reported_separately(self, controller):
        """Two different fixes — adopt one, go switch the other on."""
        d = resolve(
            controller,
            adopted={CONTROLLER, NODE1},
            alive={CONTROLLER},
            project={CONTROLLER, NODE1, NODE2},
        )
        assert d["missing"] == [NODE2]
        assert d["unreachable"] == [NODE1]

    def test_adopted_node_the_project_does_not_use_is_not_reported(self, controller):
        """A spare node being off is not this project's problem."""
        d = resolve(
            controller,
            adopted={CONTROLLER, NODE1},
            alive={CONTROLLER},
            project={CONTROLLER},
        )
        assert d["missing"] == []
        assert d["unreachable"] == []

    def test_the_controller_is_never_missing(self, controller):
        """Its own UUID is in project and always in required; if it failed to
        answer its own probe there are much larger problems than this alert.
        """
        d = resolve(
            controller, adopted=set(), alive=set(), project={CONTROLLER, NODE1}
        )
        assert CONTROLLER not in d["missing"]
        assert CONTROLLER not in d["unreachable"]

    def test_the_diagnosis_names_the_project(self, controller):
        controller.set_status("load", "test_18")
        d = resolve(
            controller,
            adopted={CONTROLLER},
            alive={CONTROLLER},
            project={CONTROLLER, NODE1},
        )
        assert d["project"] == "test_18"


# ─── the regression guard: GO is not blocked ─────────────────────────────


class TestRequiredIsUnchanged:
    """`required` must stay exactly (adopted & alive & project) | {controller}
    in every shape. This is the whole safety argument of the feature.
    """

    @pytest.mark.parametrize(
        "adopted,alive,project",
        [
            ({CONTROLLER, NODE1}, {CONTROLLER, NODE1}, {CONTROLLER, NODE1}),
            ({CONTROLLER}, {CONTROLLER}, {CONTROLLER, NODE1}),
            ({CONTROLLER, NODE1}, {CONTROLLER}, {CONTROLLER, NODE1}),
            ({CONTROLLER, NODE1}, {CONTROLLER}, {CONTROLLER, NODE1, NODE2}),
            (set(), set(), set()),
        ],
    )
    def test_required_matches_the_original_formula(
        self, controller, adopted, alive, project
    ):
        resolve(controller, adopted=adopted, alive=alive, project=project)
        expected = (adopted & alive & project) | {CONTROLLER}
        assert controller._required_nodes == expected

    def test_an_unreachable_project_node_is_excluded_from_the_gate(self, controller):
        """The old log line claimed "GO blocked" here. It was false: the node
        is dropped from required and GO is enabled without it.
        """
        resolve(
            controller,
            adopted={CONTROLLER, NODE1},
            alive={CONTROLLER},
            project={CONTROLLER, NODE1},
        )
        assert NODE1 not in controller._required_nodes


# ─── how it reaches the UI ───────────────────────────────────────────────


class TestPush:
    def test_a_clean_load_still_broadcasts_empty_lists(self, controller):
        """A clean load after a bad one must erase the previous warning; a
        payload withheld would leave it on screen forever.
        """
        resolve(
            controller,
            adopted={CONTROLLER},
            alive={CONTROLLER},
            project={CONTROLLER},
        )
        sent = broadcast_warnings(controller)
        assert len(sent) == 1
        assert sent[0]["missing"] == []
        assert sent[0]["unreachable"] == []

    def test_the_payload_carries_the_lists(self, controller):
        resolve(
            controller,
            adopted={CONTROLLER, NODE1},
            alive={CONTROLLER},
            project={CONTROLLER, NODE1, NODE2},
        )
        sent = broadcast_warnings(controller)[-1]
        assert sent["unreachable"] == [NODE1]
        assert sent["missing"] == [NODE2]

    def test_unload_clears_it(self, controller):
        resolve(
            controller,
            adopted={CONTROLLER},
            alive={CONTROLLER},
            project={CONTROLLER, NODE1},
        )
        assert controller._load_diagnosis["missing"] == [NODE1]

        with (
            patch.object(controller, "_clear_playback_state"),
            patch.object(controller, "reset_script"),
            patch.object(controller, "_forward_command_to_nodes"),
        ):
            controller.unload_project(None)

        assert controller._load_diagnosis is None
        assert broadcast_warnings(controller)[-1]["missing"] == []

    def test_load_id_increases_so_a_retry_is_not_a_replay(self, controller):
        """Content equality cannot tell a reconnect replay from an operator
        retrying a load they have not managed to fix: the diagnosis is
        byte-identical. The id is what separates them.
        """
        first = dict(
            resolve(
                controller,
                adopted={CONTROLLER},
                alive={CONTROLLER},
                project={CONTROLLER, NODE1},
            )
        )
        second = resolve(
            controller,
            adopted={CONTROLLER},
            alive={CONTROLLER},
            project={CONTROLLER, NODE1},
        )
        assert first["missing"] == second["missing"]
        assert second["load_id"] > first["load_id"]


class TestLateJoin:
    def test_readable_before_any_load(self, controller):
        """__init__ must define it: a browser connecting before the first load
        of a freshly restarted engine reaches _on_ws_client_connect, and an
        AttributeError there would also kill the existing late-join dump.
        """
        assert controller._load_diagnosis is None
        payload = json.loads(controller._cluster_warning_payload(None))
        assert payload == {
            "load_id": 0,
            "project": "",
            "missing": [],
            "unreachable": [],
        }

    def test_a_client_connecting_after_the_load_still_gets_it(self, controller):
        import asyncio

        resolve(
            controller,
            adopted={CONTROLLER},
            alive={CONTROLLER},
            project={CONTROLLER, NODE1},
        )

        ws = Mock()
        sent = []

        async def fake_send(data):
            sent.append(data)

        ws.send = fake_send
        asyncio.run(controller._on_ws_client_connect(ws))

        assert any(b"/engine/status/cluster_warning" in d for d in sent)
        assert any(NODE1.encode() in d for d in sent)


# ─── the pull surface ────────────────────────────────────────────────────


class TestClusterStatusCarriesIt:
    def _probe(self, controller, alive, adopted):
        return (
            patch.object(controller, "_probe_cluster_liveness", return_value=alive),
            patch.object(
                controller, "_adopted_uuids_from_network_map", return_value=adopted
            ),
        )

    def test_the_two_lists_are_in_the_reply(self, controller):
        resolve(
            controller,
            adopted={CONTROLLER},
            alive={CONTROLLER},
            project={CONTROLLER, NODE1},
        )
        p1, p2 = self._probe(controller, {CONTROLLER}, {CONTROLLER})
        with p1, p2:
            out = controller.get_cluster_status(None)

        assert out["missing"] == [NODE1]
        assert out["unreachable"] == []

    def test_a_change_inside_the_clamp_window_is_served_immediately(self, controller):
        """The clamp caches the *probe*, not the diagnosis. Folding the two
        together would serve the pre-transition diagnosis for up to two seconds
        after a load or unload — a warning outliving its cause, which is the
        worst outcome this feature has.
        """
        resolve(
            controller,
            adopted={CONTROLLER},
            alive={CONTROLLER},
            project={CONTROLLER, NODE1},
        )
        p1, p2 = self._probe(controller, {CONTROLLER}, {CONTROLLER})
        with p1 as mock_probe, p2:
            first = controller.get_cluster_status(None)
            with (
                patch.object(controller, "_clear_playback_state"),
                patch.object(controller, "reset_script"),
                patch.object(controller, "_forward_command_to_nodes"),
            ):
                controller.unload_project(None)
            second = controller.get_cluster_status(None)

        assert first["missing"] == [NODE1]
        assert second["missing"] == []  # not the cached one
        assert mock_probe.call_count == 1  # and still clamped

    def test_still_never_returns_empty(self, controller):
        p1, p2 = self._probe(controller, set(), set())
        with p1, p2:
            out = controller.get_cluster_status(None)

        assert out
        assert out["missing"] == []


# ─── failure paths ───────────────────────────────────────────────────────


class TestFailedLoadLeavesNothingBehind:
    def test_a_load_that_fails_before_the_probe_clears_the_old_diagnosis(
        self, controller
    ):
        """load_project_config() and read_script() both return False further
        down. Without an early clear, the previous project's warning would sit
        on screen for a project that, to the operator, just failed to load.
        """
        resolve(
            controller,
            adopted={CONTROLLER},
            alive={CONTROLLER},
            project={CONTROLLER, NODE1},
        )
        assert controller._load_diagnosis["missing"] == [NODE1]

        controller.cm.load_project_config.side_effect = Exception("no such project")
        with (
            patch.object(controller, "_clear_playback_state"),
            patch.object(controller, "reset_script"),
            patch.object(controller, "error_to_editor"),
        ):
            result = controller.load_project("ghost_project", context="ctx")

        assert result is False
        assert controller._load_diagnosis is None
        assert broadcast_warnings(controller)[-1]["missing"] == []
