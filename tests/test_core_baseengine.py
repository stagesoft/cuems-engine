# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

from unittest.mock import Mock, patch

import pytest

from cuemsengine.core.BaseEngine import MTC_PORT, BaseEngine

from .fixtures import env_config_path, mock_config_manager

# All tests in this module are integration-class
# (excluded from fast unit tests runs).
pytestmark = pytest.mark.integration

class TestBaseEngine:
    def test_base_engine_initialization_with_all_components(self, env_config_path):
        """
        Test BaseEngine initialization with both ConfigManager and MTC listener
        """
        engine = BaseEngine(with_cm=True, with_mtc=True)

        # Check basic attributes
        assert engine.node_name == "0367f391-ebf4-48b2-9f26-000000000001"
        assert engine.mtc_port == MTC_PORT
        assert engine._timecode is None
        assert engine.go_offset == None
        assert engine.node_host == "http://000000000001.local"
        assert engine.script is None
        assert engine.stop_requested is False
        assert engine.ongoing_cue is None
        assert engine.next_cue_pointer is None

        # Verify ConfigManager was initialized
        assert hasattr(engine, "cm")

        # Verify MTC listener was initialized
        assert hasattr(engine, "mtc_listener")

    def test_base_engine_initialization_without_mtc(
        self, env_config_path, mock_config_manager
    ):
        """Test BaseEngine initialization without MTC listener"""
        engine = BaseEngine(with_cm=True, with_mtc=False)

        # Check basic attributes
        assert engine.node_name == "0367f391-ebf4-48b2-9f26-000000000001"
        assert engine.mtc_port == MTC_PORT
        assert engine._timecode is None

        # Verify ConfigManager was initialized

        # Verify MTC listener was not initialized
        assert hasattr(engine, "mtc_listener")
        assert engine.mtc_listener is None
        assert hasattr(engine, "cm")

    def test_timecode_property(self, env_config_path):
        """Test timecode property getter and setter"""
        engine = BaseEngine(with_cm=False, with_mtc=False)

        # Test initial value
        assert engine.timecode is None

        # Test setting timecode
        engine.timecode = "01:00:00:00"
        assert engine.timecode == "01:00:00:00"

        # Test timecode change callback
        mock_callback = Mock()
        engine.on_timecode_change = mock_callback  # type: ignore[attr-defined]
        engine.timecode = "02:00:00:00"
        mock_callback.assert_called_once_with("02:00:00:00")

    def test_stop_all(self, env_config_path, mock_config_manager):
        """Test stop_all method"""
        engine = BaseEngine(with_cm=True, with_mtc=True)

        engine.stop()

        assert engine.stop_requested is True
        assert engine.running is False


def test_get_status_endpoints(env_config_path):
    from cuemsengine.osc import ValueType

    engine = BaseEngine(with_cm=True, with_mtc=True)
    endpoints = engine.get_status_endpoints()
    int_statuses = ["recieved", "timecode"]
    list_statuses = ["currentcue"]
    for k, v in endpoints.items():
        status_name = k.split("/")[-1]
        assert status_name in engine.get_all_status_names()
        if status_name in int_statuses:
            assert v[0] == ValueType.Int
        elif status_name in list_statuses:
            assert v[0] == ValueType.List
        else:
            assert v[0] == ValueType.String
