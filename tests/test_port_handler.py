# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Regression tests for PORT_HANDLER's exclusion list (869ed9wf7).

Every test here fails on the pre-fix code. The defects they pin, in the
numbering of Plans/porthandler-exclusion-fix.md:

  D1  set_ports() early-returned on object identity, so the config path never
      populated _all_used_ports and get_free_port() excluded nothing.
  D2  get_used_ports_with_pid() only recorded a port when it could also read a
      `pid=`, which `ss` hides for other users' sockets.
  D3  ...and it keyed by PID, so a process with several ports contributed one.
  D5  assign_ports(cue=None) used the same dead path — the engine could hand
      one port to two of its own services.
  D6  Arming check_ports()'s guards crashed NodeEngine.__init__ two ways: a
      config port that happens to be bound, and two config names sharing a
      port (stock settings.xml: osc_in_port_base and the videocomposer default
      are both 7000).
  D7  Re-arm let the OLD port win, so remove_ports() freed the dead one and
      leaked the live one.
  D8  get_free_ports(n) could return the same port twice.
  D10 Two concurrent draws could return the same port.

Several tests shrink _all_available_ports to a handful of ports. Without that
they would only fail on the old code probabilistically (20 draws out of 809
collide about one time in five), which is no regression gate at all.
"""

import copy
import socket
import threading
from unittest.mock import patch

import pytest

from cuemsengine.tools.PortHandler import (
    INITIAL_PORT,
    MAX_PORT,
    PORT_HANDLER,
    port_is_bindable,
)
from cuemsengine.tools.system_ports import get_used_ports

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


def bind_udp(port: int) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("", port))
    return s


class FakeCue:
    """Stand-in for a cue: identity-hashed, like the real dict keys."""

    def __init__(self, name="cue"):
        self.name = name

    def __hash__(self):
        return id(self)

    def __eq__(self, other):
        return self is other


# --------------------------------------------------------------------------
# D1 / D5 — the exclusion list actually excludes
# --------------------------------------------------------------------------


def test_config_ports_are_excluded(handler):
    """D1: a declared config port must leave the allocatable pool."""
    handler.add_config_ports({"oscquery_ws_port": 9190, "oscquery_osc_port": 9191})

    used = handler.get_all_used_ports()
    assert 9190 in used
    assert 9191 in used
    assert 9190 not in handler._all_available_ports - used
    assert 9191 not in handler._all_available_ports - used


def test_assign_ports_config_scope_reserves(handler):
    """D5: a port assigned to a config-scope service must not be re-issued."""
    handler._all_available_ports = free_pool(6)

    mixer = handler.assign_ports(["audio_mixer"])["audio_mixer"]
    assert mixer in handler.get_all_used_ports()

    dmx = handler.assign_ports(["dmx_player"])["dmx_player"]
    assert dmx != mixer, "allocator handed the mixer's port to the dmx player"


def test_assign_ports_maps_names_by_index(handler):
    """get_free_ports() must preserve draw order — assign_ports zips by index."""
    handler._all_available_ports = free_pool(6)

    out = handler.assign_ports(["a", "b", "c"])

    assert set(out) == {"a", "b", "c"}
    assert len(set(out.values())) == 3


# --------------------------------------------------------------------------
# D6 — config registration must never raise
# --------------------------------------------------------------------------


def test_config_port_already_bound_does_not_raise(handler):
    """D6 trigger 1: a declared port that is already bound is not an error.

    On a controller the controller engine holds oscquery_ws_port while the
    node engine starts, so every `systemctl restart cuems-node-engine` hits
    this. It must not raise out of __init__.
    """
    port = next(iter(free_pool(1)))
    sock = bind_udp(port)
    try:
        handler.add_system_ports()
        assert port in handler._system_ports, "scan missed a port we hold"

        handler.add_config_ports({"oscquery_ws_port": port})  # must not raise

        assert port in handler.get_all_used_ports()
    finally:
        sock.close()


def test_two_config_names_one_port_does_not_raise(handler):
    """D6 trigger 2: two config names may share a port. Stock settings.xml
    has top-level osc_in_port_base 7000, and <videoplayer> has no osc_port so
    NodeEngine falls back to VIDEOCOMPOSER_OSC_PORT_DEFAULT — also 7000.
    """
    handler.add_config_ports({"osc_in_port_base": 7000})
    handler.add_config_ports({"videocomposer": 7000})  # must not raise

    assert 7000 in handler.get_all_used_ports()
    assert handler.get_ports(None) == {
        "osc_in_port_base": 7000,
        "videocomposer": 7000,
    }


def test_add_config_ports_is_idempotent(handler):
    """Re-submitting overlapping config never raises and never double-books."""
    for _ in range(3):
        handler.add_config_ports({"a": 9500, "b": 9501})
        handler.add_config_ports({"b": 9501, "c": 9502})

    assert handler._config_ports == {9500, 9501, 9502}
    assert handler._all_used_ports == []


def test_add_config_ports_ignores_non_numeric(handler):
    """mtc_port is an ALSA client name, not a number — must not blow up."""
    handler.add_config_ports({"mtc_port": "Midi Through Port-0", "ws": 9190})

    assert handler._config_ports == {9190}


# --------------------------------------------------------------------------
# D7 — re-arm precedence
# --------------------------------------------------------------------------


def test_rearm_keeps_new_port(handler):
    """D7: the new port must win, and remove_ports() must free the live one."""
    cue = FakeCue()

    handler.set_ports(cue, {"audio_output": 9500})
    assert handler.get_ports(cue) == {"audio_output": 9500}

    handler.set_ports(cue, {"audio_output": 9600})
    assert handler.get_ports(cue) == {"audio_output": 9600}, "re-arm kept the OLD port"
    assert handler._all_used_ports == [9600], "old port still reserved"

    handler.remove_ports(cue)
    assert handler._all_used_ports == [], "live port leaked out of the pool"


def test_set_ports_rejects_config_scope(handler):
    """Config goes through add_config_ports(), which cannot raise."""
    with pytest.raises(ValueError, match="cue-scoped"):
        handler.set_ports(None, {"a": 9500})


def test_set_ports_rejects_double_booking(handler):
    """Cue scope still guards real double-booking."""
    a, b = FakeCue("a"), FakeCue("b")
    handler.set_ports(a, {"audio_output": 9500})

    with pytest.raises(ValueError, match="already in use"):
        handler.set_ports(b, {"audio_output": 9500})

    assert handler._all_used_ports == [9500], "failed set corrupted the pool"


# --------------------------------------------------------------------------
# D8 / D10 — draws are distinct
# --------------------------------------------------------------------------


def test_get_free_ports_no_duplicates(handler):
    """D8: a batch draw must not return the same port twice."""
    handler._all_available_ports = free_pool(5)

    ports = handler.get_free_ports(5)

    assert len(set(ports)) == 5, f"duplicate ports in batch: {ports}"


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


# --------------------------------------------------------------------------
# D4 — the allocator sees what is bound now, not just at startup
# --------------------------------------------------------------------------


def test_get_free_port_skips_bound_port(handler):
    """D4: a port bound after the startup snapshot must never be handed out."""
    pool = free_pool(3)
    taken = sorted(pool)[0]
    handler._all_available_ports = pool

    handler.add_system_ports()  # snapshot BEFORE the bind
    sock = bind_udp(taken)
    try:
        for _ in range(20):
            port = handler.get_free_port()
            handler.release_pending(port)
            assert port != taken, "handed out a port bound after the snapshot"
    finally:
        sock.close()


def test_get_free_port_raises_when_nothing_bindable(handler):
    """A port must never be handed out unverified, however degraded the pool."""
    pool = free_pool(2)
    socks = [bind_udp(p) for p in pool]
    handler._all_available_ports = pool
    try:
        with pytest.raises(ValueError):
            handler.get_free_port()
    finally:
        for s in socks:
            s.close()


def test_pending_is_released(handler):
    """release_pending() gives an unregistered draw back to the pool."""
    handler._all_available_ports = free_pool(2)

    port = handler.get_free_port()
    assert port in handler._pending
    assert port in handler.get_all_used_ports()

    handler.release_pending(port)
    assert port not in handler.get_all_used_ports()


def test_store_random_port_promotes_pending(handler):
    """new_random_port() moves the draw from _pending to _random_ports."""
    handler._all_available_ports = free_pool(2)

    port = handler.new_random_port()

    assert port not in handler._pending
    assert port in handler._random_ports
    assert port in handler.get_all_used_ports()


# --------------------------------------------------------------------------
# D2 / D3 — the system scan
# --------------------------------------------------------------------------


def test_scan_reports_all_ports_of_one_process():
    """D3: a process holding several ports must contribute all of them.

    The old scan was keyed by PID (`pid_port_dict[pid] = port`), so one
    process contributed exactly one port — and an engine holds many.
    """
    socks = [bind_udp(p) for p in free_pool(3)]
    held = {s.getsockname()[1] for s in socks}
    try:
        seen = get_used_ports()
        assert held <= seen, f"scan missed {sorted(held - seen)} of {sorted(held)}"
    finally:
        for s in socks:
            s.close()


def test_scan_sees_sockets_without_pid_field():
    """D2: `ss` hides `users:(...)` for other users' sockets.

    The old parser only recorded a port from inside its `"pid=" in part`
    branch, so as a non-owner it returned nothing at all rather than a partial
    list. Canned output, because creating a foreign-user socket needs root.
    """
    canned = (
        "Netid State  Recv-Q Send-Q Local Address:Port  Peer Address:Port Process\n"
        "udp   UNCONN 0      0            0.0.0.0:9404       0.0.0.0:*\n"
        "udp   UNCONN 0      0               [::]:9929          [::]:*\n"
        "tcp   LISTEN 0      128          0.0.0.0:9190       0.0.0.0:*"
        '  users:(("cuems-engine",pid=1234,fd=7))\n'
        "tcp   LISTEN 0      128             [::]:22            [::]:*\n"
    )

    class Result:
        stdout = canned

    with patch("cuemsengine.tools.system_ports.subprocess.run", return_value=Result()):
        ports = get_used_ports()

    assert ports == {9404, 9929, 9190, 22}


def test_scan_survives_missing_ss():
    """No `ss` (minimal ISO) degrades to the old blindness, never a crash."""
    with patch(
        "cuemsengine.tools.system_ports.subprocess.run",
        side_effect=FileNotFoundError("ss"),
    ):
        assert get_used_ports() == set()
