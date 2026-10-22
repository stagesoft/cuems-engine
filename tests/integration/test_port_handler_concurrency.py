# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

"""PORT_HANDLER under concurrent draws (D10): real threads, real bindable ports."""

import threading

from tests.support.ports import free_pool, handler  # noqa: F401


def test_concurrent_draws_are_distinct(handler):
    """D10: get_free_port() reserves, so parallel draws cannot collide."""
    pool = free_pool(8)
    handler._all_available_ports = pool

    drawn = []
    lock = threading.Lock()

    def draw():
        port = handler.get_free_port()
        with lock:
            drawn.append(port)

    threads = [threading.Thread(target=draw) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(drawn) == 8
    assert len(set(drawn)) == 8, f"concurrent draws collided: {sorted(drawn)}"
