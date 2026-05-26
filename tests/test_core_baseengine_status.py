# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

import pytest
from unittest.mock import patch
from os import environ
from pathlib import Path

from cuemsengine.core.BaseEngine import BaseEngine


@pytest.fixture
def daemon(with_signals: bool = True):
    environ["CUEMS_CONF_PATH"] = str(
        Path(__file__).parent / ".." / "dev" / "test_xml_files"
    )
    return BaseEngine(with_signals=with_signals)


@pytest.fixture
def mock_signal():
    with patch("signal.signal") as mock_signal_obj:
        yield mock_signal_obj


def test_engine_can_start_and_stop():
    from time import sleep
    from os import path, environ
    from cuemsengine.core.BaseEngine import SHOW_LOCK_PATH

    environ["CUEMS_CONF_PATH"] = str(
        Path(__file__).parent / ".." / "dev" / "test_xml_files"
    )
    engine = BaseEngine(with_signals=False)
    engine.set_show_lock_file()
    sleep(0.05)

    assert engine.show_locked == True
    assert path.isfile(SHOW_LOCK_PATH)

    engine.stop()
    assert engine.show_locked == False
    assert engine.running == False


def test_engine_status(daemon):
    assert daemon.status.load is None
    assert daemon.status.loadcue is None
    assert daemon.status.go is None
    assert daemon.status.gocue is None
    assert daemon.status.pause is None
    assert daemon.status.stop is None
    assert daemon.status.resetall is None
    assert daemon.status.preload is None
    assert daemon.status.unload is None
    assert daemon.status.hwdiscovery is None
    assert daemon.status.deploy is None
    assert daemon.status.test is None
    assert daemon.status.timecode is None
    assert daemon.status.currentcue == []
    assert daemon.status.nextcue is None
    assert daemon.status.running is None


def test_set_status(daemon):
    daemon.set_status("load", "test")
    assert daemon.status.load == "test"


def test_get_status(daemon):
    daemon.set_status("load", "test")
    assert daemon.get_status("load") == "test"


def test_recieved_test(daemon):
    assert daemon.status.recieved == 0
    daemon.set_status("test", "test")
    assert daemon.status.test == "test"
    assert daemon.status.recieved == 1
    daemon.set_status("test", "test2")
    assert daemon.status.test == "test2"
    assert daemon.status.recieved == 2


def test_get_status_none(daemon, caplog):
    assert daemon.get_status("none") == "NotFound"
    assert "Property none not found in EngineStatus" in caplog.text

    try:
        daemon.get_status("none", strict=True)
    except AttributeError as e:
        assert str(e) == "Property none not found in EngineStatus"


def test_set_status_none(daemon, caplog):
    daemon.set_status("none", "test")
    assert "Property none not found in EngineStatus" in caplog.text
    try:
        daemon.set_status("none", "test", strict=True)
    except AttributeError as e:
        assert str(e) == "Property none not found in EngineStatus"


STATUSES = [
    "load",
    "loadcue",
    "go",
    "gocue",
    "pause",
    "stop",
    "resetall",
    "preload",
    "unload",
    "hwdiscovery",
    "deploy",
    "test",
    "timecode",
    "nextcue",
    "running",
    "recieved",
    "currentcue",
]


def test_all_statuses(daemon):
    for i in vars(daemon.status).keys():
        assert i[1:] in STATUSES
    assert STATUSES == daemon.get_all_status_names()


class TestCurrentCueProperty:
    """Test the currentcue property behavior."""

    @pytest.fixture
    def status(self):
        from cuemsengine.core.EngineStatus import EngineStatus

        return EngineStatus()

    def test_currentcue_accepts_tuple_of_two_elements(self, status):
        """Test setting currentcue with a valid tuple of 2 elements."""
        status.currentcue = ("cue_id_1", "playing")

        assert len(status.currentcue) == 1
        assert status.currentcue[0] == ["cue_id_1", "playing"]

    def test_currentcue_accepts_list_of_two_elements(self, status):
        """Test setting currentcue with a valid list of 2 elements."""
        status.currentcue = ["cue_id_2", "stopped"]

        assert len(status.currentcue) == 1
        assert status.currentcue[0] == ["cue_id_2", "stopped"]

    def test_currentcue_rejects_single_element(self, status):
        """Test that single element raises ValueError."""
        with pytest.raises(ValueError, match="must be a list or tuple of two strings"):
            status.currentcue = ["only_one"]

    def test_currentcue_rejects_three_elements(self, status):
        """Test that three elements raises ValueError."""
        with pytest.raises(ValueError, match="must be a list or tuple of two strings"):
            status.currentcue = ("one", "two", "three")

    def test_currentcue_rejects_empty(self, status):
        """Test that empty list/tuple raises ValueError."""
        with pytest.raises(ValueError, match="must be a list or tuple of two strings"):
            status.currentcue = []

    def test_currentcue_stringifies_non_string_values(self, status):
        """Test that non-string values are converted to strings."""
        # Numbers get stringified
        status.currentcue = ("cue_1", 123)
        assert status.currentcue[0] == ["cue_1", "123"]

        status.currentcue = (456, "playing")
        assert ["456", "playing"] in status.currentcue

        # Dictionary gets stringified
        status.currentcue = ("cue_dict", {"key": "value"})
        assert status.currentcue[-1][0] == "cue_dict"
        assert status.currentcue[-1][1] == "{'key': 'value'}"

        # Array gets stringified
        status.currentcue = ("cue_list", [1, 2, 3])
        assert status.currentcue[-1][0] == "cue_list"
        assert status.currentcue[-1][1] == "[1, 2, 3]"

    def test_currentcue_remove_specific_entry(self, status):
        """Test that remove_currentcue removes a specific entry by ID."""
        status.currentcue = ("cue_1", "playing")
        status.currentcue = ("cue_2", "armed")
        status.currentcue = ("cue_3", "stopped")

        assert len(status.currentcue) == 3
        assert ["cue_2", "armed"] in status.currentcue

        status.remove_currentcue("cue_2")
        assert len(status.currentcue) == 2
        assert ["cue_1", "playing"] in status.currentcue
        assert ["cue_3", "stopped"] in status.currentcue
        assert ["cue_2", "armed"] not in status.currentcue

        status.remove_currentcue("cue_3")
        assert len(status.currentcue) == 1
        assert ["cue_1", "playing"] in status.currentcue
        assert ["cue_3", "stopped"] not in status.currentcue

    def test_currentcue_deleter_clears_all(self, status):
        """Test that del status.currentcue clears all entries."""
        status.currentcue = ("cue_1", "playing")
        status.currentcue = ("cue_2", "armed")
        status.currentcue = ("cue_3", "stopped")

        assert len(status.currentcue) == 3

        del status.currentcue
        assert status.currentcue == []

    def test_currentcue_updates_existing_entry(self, status):
        """Test that setting same cue_id updates the value."""
        status.currentcue = ("cue_1", "armed")
        status.currentcue = ("cue_1", "playing")

        assert len(status.currentcue) == 1
        assert status.currentcue[0] == ["cue_1", "playing"]

    def test_currentcue_multiple_entries(self, status):
        """Test adding multiple different cue entries."""
        status.currentcue = ("cue_1", "playing")
        status.currentcue = ("cue_2", "armed")
        status.currentcue = ("cue_3", "stopped")

        assert len(status.currentcue) == 3
        assert ["cue_1", "playing"] in status.currentcue
        assert ["cue_2", "armed"] in status.currentcue
        assert ["cue_3", "stopped"] in status.currentcue

    def test_currentcue_update_preserves_other_entries(self, status):
        """Test that updating one entry doesn't affect others."""
        status.currentcue = ("cue_1", "playing")
        status.currentcue = ("cue_2", "armed")
        status.currentcue = ("cue_1", "finished")

        assert len(status.currentcue) == 2
        assert ["cue_1", "finished"] in status.currentcue
        assert ["cue_2", "armed"] in status.currentcue
