"""Background asyncio event loop fixture mimicking AsyncCommsThread."""

from __future__ import annotations

import asyncio
import threading
from typing import NamedTuple


class LoopHandle(NamedTuple):
    """Reference to a running event loop and its backing thread."""

    loop: asyncio.AbstractEventLoop
    thread: threading.Thread


class EventLoopFixture:
    """Manages asyncio event loops running in background daemon threads.

    Provides helpers to create one or two loops (IPC + cue) that mirror
    the dual-loop architecture of ``AsyncCommsThread``.
    """

    @staticmethod
    def start(name: str = "test-loop") -> LoopHandle:
        """Create a new event loop running ``run_forever`` in a daemon thread."""
        loop = asyncio.new_event_loop()
        thread = threading.Thread(
            target=loop.run_forever,
            name=name,
            daemon=True,
        )
        thread.start()
        return LoopHandle(loop=loop, thread=thread)

    @staticmethod
    def stop(handle: LoopHandle, timeout: float = 2.0) -> None:
        """Gracefully stop an event loop and join its thread."""
        loop, thread = handle
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=timeout)
        if not loop.is_closed():
            loop.close()

    @classmethod
    def start_dual(cls) -> tuple[LoopHandle, LoopHandle]:
        """Create two isolated loops: ``(ipc_handle, cue_handle)``."""
        ipc = cls.start(name="ipc-loop")
        cue = cls.start(name="cue-loop")
        return ipc, cue

    @classmethod
    def stop_dual(
        cls, ipc: LoopHandle, cue: LoopHandle, timeout: float = 2.0
    ) -> None:
        """Stop both loops created by :meth:`start_dual`."""
        cls.stop(ipc, timeout=timeout)
        cls.stop(cue, timeout=timeout)
