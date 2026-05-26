# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>


class EngineStatus:
    """
    A class that represents the status of an engine.
    """

    def __init__(self):
        # Initialize before test (test setter increments this)
        self.recieved = 0
        self.load = ""
        self.loadcue = ""
        self.go = ""
        self.gocue = ""
        self.pause = ""
        self.stop = ""
        self.resetall = ""
        self.preload = ""
        self.unload = ""
        self.hwdiscovery = ""
        self.deploy = ""
        self.test = ""
        self.timecode = 0
        self.nextcue = ""
        self.running = ""
        self.armed = ""

        del self.currentcue  # start with empty array

    @property
    def load(self) -> str | None:
        return self._load

    @load.setter
    def load(self, value: str | None) -> None:
        self._load = value

    @property
    def loadcue(self) -> str | None:
        return self._loadcue

    @loadcue.setter
    def loadcue(self, value: str | None) -> None:
        self._loadcue = value

    @property
    def go(self) -> str | None:
        return self._go

    @go.setter
    def go(self, value: str | None) -> None:
        self._go = value

    @property
    def gocue(self) -> str | None:
        return self._gocue

    @gocue.setter
    def gocue(self, value: str | None) -> None:
        self._gocue = value

    @property
    def pause(self) -> str | None:
        return self._pause

    @pause.setter
    def pause(self, value: str | None) -> None:
        self._pause = value

    @property
    def stop(self) -> str | None:
        return self._stop

    @stop.setter
    def stop(self, value: str | None) -> None:
        self._stop = value

    @property
    def resetall(self) -> str | None:
        return self._resetall

    @resetall.setter
    def resetall(self, value: str | None) -> None:
        self._resetall = value

    @property
    def preload(self) -> str | None:
        return self._preload

    @preload.setter
    def preload(self, value: str | None) -> None:
        self._preload = value

    @property
    def unload(self) -> str | None:
        return self._unload

    @unload.setter
    def unload(self, value: str | None) -> None:
        self._unload = value

    @property
    def hwdiscovery(self) -> str | None:
        return self._hwdiscovery

    @hwdiscovery.setter
    def hwdiscovery(self, value: str | None) -> None:
        self._hwdiscovery = value

    @property
    def deploy(self) -> str | None:
        return self._deploy

    @deploy.setter
    def deploy(self, value: str | None) -> None:
        self._deploy = value

    @property
    def test(self) -> str | None:
        return self._test

    @test.setter
    def test(self, value: str | None) -> None:
        self._test = value
        if value is not None:
            self.recieved += 1

    @property
    def recieved(self) -> int:
        return self._recieved

    @recieved.setter
    def recieved(self, value: int) -> None:
        self._recieved = value

    @property
    def timecode(self) -> int | None:
        return self._timecode

    @timecode.setter
    def timecode(self, value: int | None) -> None:
        self._timecode = value

    @property
    def currentcue(self) -> list[list[str, str]]:
        return self._currentcue

    @currentcue.setter
    def currentcue(self, value: list[str, str] | tuple[str, str]) -> None:
        """Set a (cue, offset) pair to the current cue list

        Args:
            value: A list or tuple of two strings

        Raises:
            ValueError: If the value is not a list or tuple of two elements

        Note:
            Non-string values are converted to strings using str().
        """
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError(
                "Current cue must be a list or tuple of two strings"
            )
        id, offset = str(value[0]), str(value[1])
        for item in self._currentcue:
            if item[0] == id:
                item[1] = offset
                return
        self._currentcue.append([id, offset])

    @currentcue.deleter
    def currentcue(self) -> None:
        """Clear all current cue entries."""
        self._currentcue = []

    def remove_currentcue(self, cue_id: str) -> None:
        """Remove a specific cue entry by its ID.

        Args:
            cue_id: The ID of the cue to remove
        """
        id = str(cue_id)
        for i, item in enumerate(self._currentcue):
            if item[0] == id:
                self._currentcue.pop(i)
                return

    @property
    def nextcue(self) -> str | None:
        return self._nextcue

    @nextcue.setter
    def nextcue(self, value: str | None) -> None:
        self._nextcue = value

    @property
    def running(self) -> int | None:
        return self._running

    @running.setter
    def running(self, value: int | None) -> None:
        self._running = value

    @property
    def armed(self) -> str | None:
        return self._armed

    @armed.setter
    def armed(self, value: str | None) -> None:
        self._armed = value
