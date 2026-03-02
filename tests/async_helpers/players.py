"""Stub PlayerHandler that tracks calls without spawning subprocesses."""

from __future__ import annotations

from threading import Lock
from typing import Any
from unittest.mock import MagicMock


class MockPlayerHandler:
    """Thread-safe stand-in for ``PlayerHandler``.

    Records ``store_cue_player``, ``remove_cue_player``, ``get_cue_player``,
    ``new_audio_output``, and ``set_video_player`` calls without side-effects.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._cue_players: dict[Any, Any] = {}
        self._calls: list[tuple[str, tuple[Any, ...]]] = []

    def store_cue_player(self, cue: Any, player: Any) -> None:
        """Record a player store."""
        with self._lock:
            self._cue_players[cue] = player
            self._calls.append(("store_cue_player", (cue, player)))

    def get_cue_player(self, cue: Any) -> Any:
        """Return stored player for *cue*."""
        with self._lock:
            return self._cue_players.get(cue)

    def remove_cue_player(self, cue: Any) -> None:
        """Record a player removal and clean up cue._osc."""
        with self._lock:
            self._cue_players.pop(cue, None)
            self._calls.append(("remove_cue_player", (cue,)))
        if hasattr(cue, "_osc"):
            cue._osc = None

    def new_audio_output(self, cue: Any) -> None:
        """Record an audio output creation — no real subprocess."""
        from .osc import MockOscClient

        osc = MockOscClient()
        cue._osc = osc
        with self._lock:
            self._cue_players[cue] = MagicMock(name="AudioPlayer")
            self._calls.append(("new_audio_output", (cue,)))

    def set_video_player(self, cue: Any) -> None:
        """Record a video player assignment — no real subprocess."""
        from .osc import MockOscClient

        osc = MockOscClient()
        cue._osc = osc
        with self._lock:
            self._cue_players[cue] = MagicMock(name="VideoPlayer")
            self._calls.append(("set_video_player", (cue,)))

    def media_path(self, file_name: str) -> str:
        """Return a fake media path."""
        return f"/fake/media/{file_name}"

    # ---- assertion helpers ----

    def get_calls(self) -> list[tuple[str, tuple[Any, ...]]]:
        """Return ordered list of ``(method_name, args)``."""
        with self._lock:
            return list(self._calls)

    def was_called(self, method: str) -> bool:
        """Check if a method was called at least once."""
        with self._lock:
            return any(m == method for m, _ in self._calls)

    def call_count(self, method: str) -> int:
        """Count how many times a method was called."""
        with self._lock:
            return sum(1 for m, _ in self._calls if m == method)

    def has_player(self, cue: Any) -> bool:
        """Check if a player is still stored for *cue*."""
        with self._lock:
            return cue in self._cue_players

    def reset(self) -> None:
        """Clear all recorded state."""
        with self._lock:
            self._cue_players.clear()
            self._calls.clear()
