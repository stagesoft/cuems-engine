# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

"""PORT_HANDLER test fixtures shared by the unit and integration port tests."""

import copy

import pytest

from cuemsengine.tools.PortHandler import (
    INITIAL_PORT,
    MAX_PORT,
    PORT_HANDLER,
    port_is_bindable,
)

_STATE = (
    "_ports",
    "_all_used_ports",
    "_all_available_ports",
    "_random_ports",
    "_pending",
    "_config_ports",
    "_system_ports",
)


@pytest.fixture
def handler():
    """PORT_HANDLER with its state deep-copied and restored.

    deepcopy, not a reference capture: _ports is a dict of dicts and
    _ports[None] is mutated in place, so a shallow save would alias the live
    object and restore nothing.
    """
    saved = {name: copy.deepcopy(getattr(PORT_HANDLER, name)) for name in _STATE}
    # Start from a clean slate so assertions are about this test only.
    PORT_HANDLER._ports = {None: {}}
    PORT_HANDLER._all_used_ports = []
    PORT_HANDLER._random_ports = []
    PORT_HANDLER._pending = set()
    PORT_HANDLER._config_ports = set()
    PORT_HANDLER._system_ports = set()
    yield PORT_HANDLER
    for name, value in saved.items():
        setattr(PORT_HANDLER, name, value)


def free_pool(n: int) -> set[int]:
    """n ports from the allocator's own range that are bindable right now."""
    found = []
    for port in range(INITIAL_PORT, MAX_PORT):
        if port_is_bindable(port):
            found.append(port)
            if len(found) == n:
                return set(found)
    pytest.skip(f"fewer than {n} bindable ports in {INITIAL_PORT}-{MAX_PORT}")
