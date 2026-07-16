# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

from os import environ
from pathlib import Path
from unittest.mock import patch

import pytest

from cuemsengine.core.BaseEngine import BaseEngine
from cuemsengine.core.EngineStatus import EngineStatus


@pytest.fixture
def base_engine(with_signals: bool = True):
    environ["CUEMS_CONF_PATH"] = str(
        Path(__file__).parent / ".." / "dev" / "test_xml_files"
    )
    return BaseEngine(with_signals=with_signals)

def test_engine_can_start_and_stop():
    from os import environ, path
    from time import sleep

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


def test_engine_initial_status(base_engine):
    assert isinstance(base_engine.status, EngineStatus)
    assert base_engine.status.armed == ""
    assert base_engine.status.deploy == ""
    assert base_engine.status.go == ""
    assert base_engine.status.gocue == ""
    assert base_engine.status.hwdiscovery == ""
    assert base_engine.status.load == ""
    assert base_engine.status.loadcue == ""
    assert base_engine.status.nextcue == ""
    assert base_engine.status.pause == ""
    assert base_engine.status.preload == ""
    assert base_engine.status.recieved == 1
    assert base_engine.status.resetall == ""
    assert base_engine.status.running == ""
    assert base_engine.status.stop == ""
    assert base_engine.status.test == ""
    assert base_engine.status.timecode == 0
    assert base_engine.status.currentcue == []


def test_set_status(base_engine):
    base_engine.set_status("load", "test")
    assert base_engine.status.load == "test"


def test_get_status(base_engine):
    base_engine.set_status("load", "test")
    assert base_engine.get_status("load") == "test"


def test_recieved_test(base_engine):
    assert base_engine.status.recieved == 1
    base_engine.set_status("test", "test")
    assert base_engine.status.test == "test"
    assert base_engine.status.recieved == 2
    base_engine.set_status("test", "test2")
    assert base_engine.status.test == "test2"
    assert base_engine.status.recieved == 3


def test_get_status_none(base_engine, caplog):
    assert base_engine.get_status("none") == "NotFound"
    assert "Property none not found in EngineStatus" in caplog.text

    try:
        base_engine.get_status("none", strict=True)
    except AttributeError as e:
        assert str(e) == "Property none not found in EngineStatus"


def test_set_status_none(base_engine, caplog):
    base_engine.set_status("none", "test")
    assert "Property none not found in EngineStatus" in caplog.text
    try:
        base_engine.set_status("none", "test", strict=True)
    except AttributeError as e:
        assert str(e) == "Property none not found in EngineStatus"


STATUSES = [
    "armed",
    "deploy",
    "go",
    "gocue",
    "hwdiscovery",
    "load",
    "loadcue",
    "nextcue",
    "pause",
    "preload",
    "recieved",
    "resetall",
    "running",
    "stop",
    "test",
    "timecode",
    "unload",
    "currentcue",
]


def test_all_statuses(base_engine):
    for i in vars(base_engine.status).keys():
        assert i[1:] in STATUSES
    assert STATUSES == base_engine.get_all_status_names()


class TestCurrentCueProperty:
    """Test the currentcue property behavior."""

    @pytest.fixture
    def status(self):
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
