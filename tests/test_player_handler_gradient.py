# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>
"""Unit tests for PlayerHandler.gradient_client lifecycle — Phase 2 / T003."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def reset_player_handler():
    """Force a fresh PlayerHandler singleton for each test."""
    from cuemsengine.players.PlayerHandler import PlayerHandler
    PlayerHandler._instance = None
    yield
    PlayerHandler._instance = None


def _get_handler():
    from cuemsengine.players.PlayerHandler import PlayerHandler
    return PlayerHandler()


class TestGradientClientDefault:
    def test_gradient_client_default_none(self):
        """Freshly constructed PlayerHandler._gradient_client is None."""
        handler = _get_handler()
        assert handler.get_gradient_client() is None


class TestSetGradientClient:
    def test_set_gradient_client_constructs_client(self):
        """set_gradient_client(port, node_uuid) constructs a GradientClient."""
        from cuemsengine.players.GradientClient import GradientClient
        handler = _get_handler()
        handler.set_gradient_client(port=7200, node_uuid='node-002')
        client = handler.get_gradient_client()
        assert isinstance(client, GradientClient)

    def test_set_gradient_client_stores_correct_port(self):
        handler = _get_handler()
        handler.set_gradient_client(port=7200, node_uuid='node-002')
        assert handler.get_gradient_client()._port == 7200

    def test_set_gradient_client_stores_correct_node_uuid(self):
        handler = _get_handler()
        handler.set_gradient_client(port=7200, node_uuid='node-002')
        assert handler.get_gradient_client()._node_uuid == 'node-002'

    def test_set_gradient_client_replaces_prior_instance(self):
        """Re-calling set_gradient_client replaces the prior client (reconnection safe-guard)."""
        handler = _get_handler()
        handler.set_gradient_client(port=7100, node_uuid='node-001')
        first = handler.get_gradient_client()
        handler.set_gradient_client(port=7200, node_uuid='node-002')
        second = handler.get_gradient_client()
        assert second is not first
        assert second._port == 7200
