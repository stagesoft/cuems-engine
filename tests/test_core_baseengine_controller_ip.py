"""Phase 2 — controller IP resolution (controller.local with map fallback).

Covers BaseEngine._resolve_controller_host (mDNS, loopback-reject),
_controller_ip_from_map (network_map fallback + empty-ip guard) and the
get_controller_ip cascade that ties them together.
"""

import logging
import socket
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cuemsengine.core.BaseEngine import CONTROLLER_HOST, BaseEngine

from .fixtures import env_config_path
from .network_map_helpers import typed_network_map

CONTROLLER_A = "3f2b8c1e-5d4a-4b6e-9c7f-1a2b3c4d5e6f"
CONTROLLER_B = "5b1d2e3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f"
NODE = "9a8b7c6d-1e2f-4a3b-8c4d-5e6f7a8b9c0d"


def _bare_engine():
    """A BaseEngine with no ConfigManager/MTC/signals — just the methods."""
    return BaseEngine(with_cm=False, with_mtc=False, with_signals=False)


def _engine_with_map(tmp_path, nodes):
    """An engine whose ``cm.network_map`` is a typed map loaded from XML."""
    engine = _bare_engine()
    engine.cm = SimpleNamespace(network_map=typed_network_map(tmp_path, nodes))
    return engine


def _controller(ip, uuid=CONTROLLER_A):
    return {"uuid": uuid, "node_role": "controller", "ip": ip}


def _node(ip, uuid=NODE):
    return {"uuid": uuid, "node_role": "node", "ip": ip}


def _first_node(engine):
    return engine.cm.network_map["node_list"][0]["node"]


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
    def test_returns_controller_ip(self, env_config_path, tmp_path):
        engine = _engine_with_map(
            tmp_path, [_node("169.254.0.5"), _controller("169.254.12.139")]
        )
        assert engine._controller_ip_from_map() == "169.254.12.139"

    def test_empty_ip_raises(self, env_config_path, tmp_path):
        # The schema forbids an empty <ip> on disk; the guard covers a map
        # edited in memory after load.
        engine = _engine_with_map(tmp_path, [_controller("169.254.12.139")])
        _first_node(engine)["ip"] = ""
        with pytest.raises(ValueError, match="no <ip>"):
            engine._controller_ip_from_map()

    def test_missing_ip_key_raises(self, env_config_path, tmp_path):
        engine = _engine_with_map(tmp_path, [_controller("169.254.12.139")])
        del _first_node(engine)["ip"]
        with pytest.raises(ValueError, match="no <ip>"):
            engine._controller_ip_from_map()

    def test_no_controller_raises(self, env_config_path, tmp_path):
        """A current-vocabulary map whose nodes are all ``node_role=node``."""
        engine = _engine_with_map(
            tmp_path,
            [_node("169.254.0.5"), _node("169.254.0.6", uuid=CONTROLLER_B)],
        )
        with pytest.raises(ValueError, match="No controller node"):
            engine._controller_ip_from_map()

    def test_empty_node_list_raises(self, env_config_path):
        engine = _bare_engine()
        engine.cm = SimpleNamespace(network_map={"node_list": []})
        with pytest.raises(ValueError, match="No nodes"):
            engine._controller_ip_from_map()

    def test_no_network_map_raises(self, env_config_path):
        engine = _bare_engine()

        class _CM:
            network_map = None

        engine.cm = _CM()
        with pytest.raises(AttributeError, match="No network map"):
            engine._controller_ip_from_map()


class TestMultipleControllers:
    """FR-005a: more than one controller is logged, not refused."""

    def _engine(self, tmp_path):
        return _engine_with_map(
            tmp_path,
            [
                _node("169.254.0.5"),
                _controller("169.254.12.139", uuid=CONTROLLER_A),
                _controller("169.254.12.140", uuid=CONTROLLER_B),
            ],
        )

    def test_first_controller_in_map_order_wins(self, env_config_path, tmp_path):
        engine = self._engine(tmp_path)
        assert engine._controller_ip_from_map() == "169.254.12.139"

    def test_one_error_lists_every_controller(self, env_config_path, tmp_path, caplog):
        engine = self._engine(tmp_path)
        with caplog.at_level(logging.ERROR):
            engine._controller_ip_from_map()
        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert len(errors) == 1, [r.getMessage() for r in errors]
        message = errors[0].getMessage()
        assert f"uuid={CONTROLLER_A} ip=169.254.12.139" in message
        assert f"uuid={CONTROLLER_B} ip=169.254.12.140" in message


class TestGetControllerIpCascade:
    def test_mdns_wins_when_unicast(self, env_config_path, tmp_path):
        engine = _engine_with_map(tmp_path, [_controller("169.254.12.139")])
        with patch.object(
            engine, "_resolve_controller_host", return_value="169.254.99.1"
        ):
            assert engine.get_controller_ip() == "169.254.99.1"

    def test_falls_back_to_map_when_resolution_none(self, env_config_path, tmp_path):
        engine = _engine_with_map(tmp_path, [_controller("169.254.12.139")])
        with patch.object(engine, "_resolve_controller_host", return_value=None):
            assert engine.get_controller_ip() == "169.254.12.139"

    def test_loopback_resolution_falls_back_to_map(self, env_config_path, tmp_path):
        """End-to-end: controller-host loopback short-circuit → map <ip>."""
        engine = _engine_with_map(tmp_path, [_controller("169.254.12.139")])
        with patch(
            "cuemsengine.core.BaseEngine.socket.gethostbyname", return_value="127.0.0.1"
        ):
            assert engine.get_controller_ip() == "169.254.12.139"
