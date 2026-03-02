"""Parametric mock builder for cue objects used across async cue tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, PropertyMock

from cuemsutils.cues import ActionCue, AudioCue, CueList, VideoCue
from cuemsutils.cues.Cue import Cue
from cuemsutils.tools.CTimecode import CTimecode


class MockCueFactory:
    """Creates mock Cue objects with configurable attributes.

    Each preset method returns a ``MagicMock`` whose ``spec`` matches the
    real cue class so that ``isinstance`` checks and ``singledispatch``
    routing work correctly.
    """

    @staticmethod
    def _base(
        spec_class: type,
        *,
        cue_id: str = "test-cue-00",
        loaded: bool = False,
        enabled: bool = True,
        prewait: CTimecode | None = None,
        postwait: CTimecode | None = None,
        loop: int = 1,
        post_go: str | None = None,
        target_object: Cue | None = None,
        local: bool = True,
        osc: Any | None = None,
        start_mtc: CTimecode | None = None,
        end_mtc: CTimecode | None = None,
        **extra: Any,
    ) -> MagicMock:
        # No spec= on MagicMock: cue classes extend dict, so spec
        # makes the mock falsy (empty dict) and restricts dunder access.
        # We rely on __class__ alone for isinstance/singledispatch.
        mock = MagicMock()
        mock.__class__ = spec_class
        mock.id = cue_id
        mock.loaded = loaded
        mock.enabled = enabled
        mock.prewait = prewait or CTimecode("0:0:0:0")
        mock.postwait = postwait or CTimecode("0:0:0:0")
        mock.loop = loop
        mock.post_go = post_go
        mock._target_object = target_object
        mock._local = local
        mock._osc = osc
        mock._start_mtc = start_mtc
        mock._end_mtc = end_mtc

        for key, value in extra.items():
            setattr(mock, key, value)

        return mock

    @classmethod
    def audio(cls, **kwargs: Any) -> MagicMock:
        """Build a mock AudioCue with sensible defaults."""
        defaults: dict[str, Any] = {
            "cue_id": "audio-cue-01",
        }
        defaults.update(kwargs)
        mock = cls._base(AudioCue, **defaults)

        if "media" not in kwargs:
            media = MagicMock()
            media.__getitem__ = MagicMock(return_value="test.wav")
            media.duration = "0:0:5:0"
            mock.media = media

        return mock

    @classmethod
    def video(cls, **kwargs: Any) -> MagicMock:
        """Build a mock VideoCue with sensible defaults."""
        defaults: dict[str, Any] = {
            "cue_id": "video-cue-01",
        }
        defaults.update(kwargs)
        mock = cls._base(VideoCue, **defaults)

        if "media" not in kwargs:
            media = MagicMock()
            media.__getitem__ = MagicMock(return_value="test.mp4")
            media.duration = "0:0:10:0"
            mock.media = media

        return mock

    @classmethod
    def action(
        cls,
        action_type: str = "play",
        action_target: Any | None = None,
        **kwargs: Any,
    ) -> MagicMock:
        """Build a mock ActionCue with sensible defaults."""
        defaults: dict[str, Any] = {
            "cue_id": "action-cue-01",
        }
        defaults.update(kwargs)
        mock = cls._base(ActionCue, **defaults)
        mock.action_type = action_type
        mock._action_target_object = action_target
        return mock

    @classmethod
    def cuelist(
        cls,
        contents: list[Any] | None = None,
        **kwargs: Any,
    ) -> MagicMock:
        """Build a mock CueList with sensible defaults."""
        defaults: dict[str, Any] = {
            "cue_id": "cuelist-01",
        }
        defaults.update(kwargs)
        mock = cls._base(CueList, **defaults)
        mock.contents = contents or []
        return mock
