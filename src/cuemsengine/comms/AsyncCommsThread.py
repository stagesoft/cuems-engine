# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""The engine's comms thread: cuems-utils' AsyncCommsThread plus a fatal path.

The class that lived here moved to cuems-utils 0.1.1
(`cuemsutils.tools.AsyncCommsThread`; cuems-utils
`specs/planning/async-comms-thread-absorption.md`). What stays is what both
engine comms threads share: when their communications end by themselves (the
bus hub's socket closed, the editor listener failed), the engine process is
sent SIGTERM. The entry script then stops the engine as for any SIGTERM and
exits 1, so systemd's Restart=on-failure brings it back, instead of the engine
carrying on with no bus.
"""

import os
import signal
from typing import Optional

from cuemsutils.log import Logger
from cuemsutils.tools.AsyncCommsThread import (
    AsyncCommsThread as LibraryAsyncCommsThread,
)


def terminate_process() -> None:
    """Send SIGTERM to this process (patched out in tests: see tests/conftest.py)."""
    os.kill(os.getpid(), signal.SIGTERM)


class AsyncCommsThread(LibraryAsyncCommsThread):
    """Base class of ControllerCommunications and NodeCommunications."""

    def on_comms_ended(self, task: Optional[object]) -> None:
        """Stop the engine so it restarts; the communications are gone."""
        super().on_comms_ended(task)
        Logger.critical(
            f"{self.name}: communications ended ({self.end_reason}); "
            f"stopping the engine so systemd restarts it"
        )
        terminate_process()
