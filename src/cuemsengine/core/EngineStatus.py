class EngineStatus:
    """
    A class that represents the status of an engine.
    """
    def __init__(self):
        self.load = None
        self.loadcue = None
        self.go = None
        self.gocue = None
        self.pause = None
        self.stop = None
        self.resetall = None
        self.preload = None
        self.unload = None
        self.hwdiscovery = None
        self.deploy = None
        self.test = None
        self.timecode = None
        self.currentcue = None
        self.nextcue = None
        self.running = None
        self.test_recieved = 0

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
    def deploy(self) -> str | None  :
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
            self.test_recieved += 1

    @property
    def test_recieved(self) -> int:
        return self._recieved

    @test_recieved.setter
    def test_recieved(self, value: int) -> None:
        self._recieved = value

    @property
    def timecode(self) -> int | None:
        return self._timecode

    @timecode.setter
    def timecode(self, value: int | None) -> None:
        self._timecode = value

    @property
    def currentcue(self) -> str | None:
        return self._currentcue

    @currentcue.setter
    def currentcue(self, value: str | None) -> None:
        self._currentcue = value

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
