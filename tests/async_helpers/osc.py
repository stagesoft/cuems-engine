"""Mock OSC client that records all calls for assertion — no network I/O."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock


class MockOscClient:
    """Drop-in replacement for ``PlayerClient`` that records interactions.

    Provides ``set_value``, ``get_value``, ``get_node`` mirroring the real
    OSC client API surface used by ``run_cue`` / ``loop_cue`` / ``arm_cue``.
    """

    def __init__(self) -> None:
        self._calls: list[tuple[str, Any]] = []
        self._values: dict[str, Any] = {}
        self._nodes: dict[str, MagicMock] = {}

    def set_value(self, key: str, value: Any) -> None:
        """Record a set_value call and store the latest value."""
        self._calls.append((key, value))
        self._values[key] = value

    def get_value(self, key: str) -> Any:
        """Return the last value set for *key*, or ``None``."""
        return self._values.get(key)

    def get_node(self, key: str) -> MagicMock:
        """Return a mock node whose ``parameter.value`` is the stored value."""
        if key not in self._nodes:
            node = MagicMock()
            node.parameter.value = self._values.get(key)
            self._nodes[key] = node
        else:
            self._nodes[key].parameter.value = self._values.get(key)
        return self._nodes[key]

    # ---- assertion helpers ----

    def get_calls(self) -> list[tuple[str, Any]]:
        """Return the ordered list of ``(key, value)`` set_value calls."""
        return list(self._calls)

    def get_calls_for(self, key: str) -> list[Any]:
        """Return all values sent to a specific *key*."""
        return [v for k, v in self._calls if k == key]

    def reset(self) -> None:
        """Clear recorded state."""
        self._calls.clear()
        self._values.clear()
        self._nodes.clear()
