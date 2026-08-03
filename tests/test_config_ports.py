# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Tests for tools/config_ports.py (869ed9wf7, Part B).

These helpers moved out of NodeEngine so BaseEngine can use them without an
import cycle — both engines must exclude their declared ports from the
allocator, and only the node engine used to.

The None case matters: is_int() caught only ValueError, but an empty element
such as `<oscquery_ws_port/>` decodes to None in xmlschema and int(None) raises
TypeError. Before the move that crashed one service; after it, both.
"""

import pytest

from cuemsengine.tools.config_ports import get_config_ports, is_int


@pytest.mark.parametrize(
    "value,expected",
    [
        (9190, True),
        ("9190", True),
        (0, True),
        (None, False),  # empty <xxx_port/> element — used to raise TypeError
        ("", False),
        ("Midi Through Port-0", False),
        ([], False),
        ({}, False),
    ],
)
def test_is_int(value, expected):
    assert is_int(value) is expected


def test_is_int_does_not_raise_on_none():
    """The regression itself: int(None) raises TypeError, not ValueError."""
    assert is_int(None) is False


def test_get_config_ports_picks_numeric_port_keys():
    """Stock settings.xml shape: numeric *_port keys in, everything else out."""
    node_conf = {
        "oscquery_ws_port": 9190,
        "oscquery_osc_port": 9191,
        "websocket_port": 9092,
        "nng_hub_port": 9093,
        "osc_in_port_base": 7000,
        "gradient_osc_port": 7100,
        "mtc_port": "Midi Through Port-0",  # a port key, but not a number
        "uuid": "abc-123",  # not a port key
        "load_timeout": 15000,  # not a port key
    }

    assert get_config_ports(node_conf) == {
        "oscquery_ws_port": 9190,
        "oscquery_osc_port": 9191,
        "websocket_port": 9092,
        "nng_hub_port": 9093,
        "osc_in_port_base": 7000,
        "gradient_osc_port": 7100,
    }


def test_get_config_ports_skips_empty_element():
    """An empty <xxx_port/> must be skipped, not crash the engine at startup."""
    assert get_config_ports({"oscquery_ws_port": None, "nng_hub_port": 9093}) == {
        "nng_hub_port": 9093
    }


def test_get_config_ports_is_top_level_only():
    """Nested ports are invisible here — videoplayer/osc_port is registered by
    NodeEngine.set_video_players(), which is its only registration.
    """
    node_conf = {"videoplayer": {"osc_port": 7000}, "nng_hub_port": 9093}

    assert get_config_ports(node_conf) == {"nng_hub_port": 9093}


def test_get_config_ports_empty_conf():
    assert get_config_ports({}) == {}
