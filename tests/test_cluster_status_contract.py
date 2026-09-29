# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""``cluster_status`` against a map loaded through the public surface (FR-009a).

The reply is a cross-repository contract (cuems-editor relays it to the UI as
``node_status``); its shape does not change. What changes is what feeds it: a
typed map hands the engine ``Uuid`` node ids, which cannot be ordered, while
its own uuid and pong senders are ``str``. Contract:
specs/008-cuems-utils-migration/contracts/cluster-payloads.md.
"""

from os import environ
from pathlib import Path
from unittest.mock import patch

import pytest

from .network_map_helpers import controller_with_map, typed_network_map

CONTROLLER = "3f2b8c1e-5d4a-4b6e-9c7f-1a2b3c4d5e6f"
NODE_A = "9a8b7c6d-1e2f-4a3b-8c4d-5e6f7a8b9c0d"
NODE_B = "5b1d2e3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f"
UNADOPTED = "7c7c7c7c-0000-4000-8000-000000000007"


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
            {"uuid": NODE_A, "adopted": True},
            {"uuid": NODE_B, "adopted": True},
            {"uuid": UNADOPTED, "adopted": False},
        ],
    )
    with controller_with_map(CONTROLLER, network_map) as engine:
        yield engine


def _status(controller, alive):
    with patch.object(controller, "_probe_cluster_liveness", return_value=alive):
        return controller.get_cluster_status(None)


def test_shape_is_unchanged(controller):
    out = _status(controller, {CONTROLLER, NODE_A})
    assert set(out) == {
        "alive",
        "adopted",
        "controller",
        "age_s",
        "missing",
        "unreachable",
    }


def test_lists_are_sorted_str(controller):
    out = _status(controller, {CONTROLLER, NODE_A})
    for key in ("alive", "adopted"):
        assert all(type(u) is str for u in out[key]), (key, out[key])
        assert out[key] == sorted(out[key]), key


def test_adopted_is_exactly_the_adopted_nodes(controller):
    out = _status(controller, {CONTROLLER})
    assert out["adopted"] == sorted([CONTROLLER, NODE_A, NODE_B])


def test_alive_is_the_probe_result(controller):
    out = _status(controller, {CONTROLLER, NODE_A})
    assert out["alive"] == sorted([CONTROLLER, NODE_A])


def test_controller_is_its_own_uuid_as_str(controller):
    out = _status(controller, {CONTROLLER})
    assert type(out["controller"]) is str
    assert out["controller"] == CONTROLLER
