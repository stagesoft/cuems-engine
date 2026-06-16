# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

import signal
from contextlib import contextmanager

@contextmanager
def timeout(seconds):
    """Timeout context manager
    
    Args:
        seconds: The number of seconds to timeout
        
    Raises:
        TimeoutError: If the timeout is reached
        
    Example:
    >>> with timeout(10):
    ...     time.sleep(15)
    ...
    TimeoutError: Timeout after 10 seconds
    """
    def timeout_handler(signum, frame):
        raise TimeoutError(f"Timeout after {seconds} seconds")
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
