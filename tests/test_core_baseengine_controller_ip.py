"""Phase 2 — controller IP resolution (controller.local with map fallback).

Covers BaseEngine._resolve_controller_host (mDNS, loopback-reject),
_controller_ip_from_map (network_map fallback + empty-ip guard) and the
get_controller_ip cascade that ties them together.
"""

import socket
from unittest.mock import patch

import pytest

from cuemsengine.core.BaseEngine import CONTROLLER_HOST, BaseEngine

from .fixtures import env_config_path


def _bare_engine():
    """A BaseEngine with no ConfigManager/MTC/signals — just the methods."""
    return BaseEngine(with_cm=False, with_mtc=False, with_signals=False)


def _engine_with_map(node_list):
    engine = _bare_engine()

    class _CM:
        network_map = {"node_list": node_list}

    engine.cm = _CM()
    return engine


def _master(ip):
    return {"node": {"node_type": "NodeType.master", "ip": ip}}


def _slave(ip):
    return {"node": {"node_type": "NodeType.slave", "ip": ip}}


class TestResolveControllerHost:
    def test_unicast_address_is_returned(self, env_config_path):
        engine = _bare_engine()
        with patch(
            "cuemsengine.core.BaseEngine.socket.gethostbyname",
            return_value="169.254.12.139",
        ) as gh:
            assert engine._resolve_controller_host() == "169.254.12.139"
            gh.assert_called_once_with(CONTROLLER_HOST)

    def test_loopback_is_rejected(self, env_config_path):
        """controller.local → 127.0.0.1 means 'this host is the controller'."""
        engine = _bare_engine()
        with patch(
            "cuemsengine.core.BaseEngine.socket.gethostbyname", return_value="127.0.0.1"
        ):
            assert engine._resolve_controller_host() is None

    def test_unspecified_is_rejected(self, env_config_path):
        engine = _bare_engine()
        with patch(
            "cuemsengine.core.BaseEngine.socket.gethostbyname", return_value="0.0.0.0"
        ):
            assert engine._resolve_controller_host() is None

    def test_resolution_failure_returns_none(self, env_config_path):
        engine = _bare_engine()
        with patch(
            "cuemsengine.core.BaseEngine.socket.gethostbyname",
            side_effect=socket.gaierror("name or service not known"),
        ):
            assert engine._resolve_controller_host() is None

    def test_oserror_returns_none(self, env_config_path):
        engine = _bare_engine()
        with patch(
            "cuemsengine.core.BaseEngine.socket.gethostbyname",
            side_effect=OSError("boom"),
        ):
            assert engine._resolve_controller_host() is None

    def test_non_ip_result_returns_none(self, env_config_path):
        engine = _bare_engine()
        with patch(
            "cuemsengine.core.BaseEngine.socket.gethostbyname", return_value="not-an-ip"
        ):
            assert engine._resolve_controller_host() is None


class TestControllerIpFromMap:
    def test_returns_master_ip(self, env_config_path):
        engine = _engine_with_map([_slave("169.254.0.5"), _master("169.254.12.139")])
        assert engine._controller_ip_from_map() == "169.254.12.139"

    def test_empty_ip_raises(self, env_config_path):
        engine = _engine_with_map([_master("")])
        with pytest.raises(ValueError, match="no <ip>"):
            engine._controller_ip_from_map()

    def test_missing_ip_key_raises(self, env_config_path):
        engine = _engine_with_map([{"node": {"node_type": "NodeType.master"}}])
        with pytest.raises(ValueError, match="no <ip>"):
            engine._controller_ip_from_map()

    def test_no_master_raises(self, env_config_path):
        engine = _engine_with_map([_slave("169.254.0.5")])
        with pytest.raises(ValueError, match="No controller node"):
            engine._controller_ip_from_map()

    def test_empty_node_list_raises(self, env_config_path):
        engine = _engine_with_map([])
        with pytest.raises(ValueError, match="No nodes"):
            engine._controller_ip_from_map()

    def test_no_network_map_raises(self, env_config_path):
        engine = _bare_engine()

        class _CM:
            network_map = None

        engine.cm = _CM()
        with pytest.raises(AttributeError, match="No network map"):
            engine._controller_ip_from_map()


class TestGetControllerIpCascade:
    def test_mdns_wins_when_unicast(self, env_config_path):
        engine = _engine_with_map([_master("169.254.12.139")])
        with patch.object(
            engine, "_resolve_controller_host", return_value="169.254.99.1"
        ):
            assert engine.get_controller_ip() == "169.254.99.1"

    def test_falls_back_to_map_when_resolution_none(self, env_config_path):
        engine = _engine_with_map([_master("169.254.12.139")])
        with patch.object(engine, "_resolve_controller_host", return_value=None):
            assert engine.get_controller_ip() == "169.254.12.139"

    def test_loopback_resolution_falls_back_to_map(self, env_config_path):
        """End-to-end: controller-host loopback short-circuit → map <ip>."""
        engine = _engine_with_map([_master("169.254.12.139")])
        with patch(
            "cuemsengine.core.BaseEngine.socket.gethostbyname", return_value="127.0.0.1"
        ):
            assert engine.get_controller_ip() == "169.254.12.139"
