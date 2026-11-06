# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""869feynrj §4.4 on the wire (cuems-RELATIONS
Plans/2026-11-03-audio-first-pass-head-869feynrj.md §7.1): a real pyossia
device (the engine's AudioClient) sends to a UDP socket on loopback, so the
repetition filter is what decides what leaves -- a ``Mock()`` ``_osc`` cannot
see it.

- ``/mtcfollow 1`` sent twice in a row reaches the wire twice (a superseding
  pass's re-follow), and a first ``/mtcfollow 0`` goes out;
- ``/volmaster 0.0`` as the first value reaches the wire (D7: a ``master_vol
  0`` cue played at full volume);
- ``/cancelstart <seq> <fade_ms>`` is ``,ii`` (a list like ``/loop``, never an
  Impulse), and a re-send with the same seq goes out;
- the start gate's follow commit and cancel leave in the order decided.
"""

import socket
import struct

import pyossia
import pytest

from cuemsengine.players.AudioPlayer import AudioClient, AudioPlayer
from cuemsengine.players.StartGate import StartGate
from cuemsengine.tools.PortHandler import PORT_HANDLER

pytestmark = pytest.mark.skipif(
    not hasattr(pyossia.Node, "remove_child"),
    reason=(
        "installed pyossia has no Node.remove_child — node removal is "
        "unsupported by this libossia build; update the system pyossia package"
    ),
)


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _parse(d):
    a = d[: d.index(b"\0")]
    i = (len(a) // 4 + 1) * 4
    tt = d[i : d.index(b"\0", i)]
    j = i + (len(tt) // 4 + 1) * 4
    args = []
    for t in tt[1:].decode():
        if t == "i":
            args.append(struct.unpack(">i", d[j : j + 4])[0])
        elif t == "f":
            args.append(struct.unpack(">f", d[j : j + 4])[0])
        j += 4
    return a.decode(), tt.decode(), args


@pytest.fixture
def rx_client(monkeypatch):
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(2)
    monkeypatch.setattr(PORT_HANDLER, "new_random_port", _free_port)
    client = AudioClient(player_port=rx.getsockname()[1], name="wire-selfgate")

    def recv():
        return _parse(rx.recv(2048))

    yield client, recv
    client.remove_device()
    rx.close()


def test_mtcfollow_one_twice_reaches_the_wire_twice(rx_client):
    client, recv = rx_client
    client.set_value("/mtcfollow", 1)
    assert recv() == ("/mtcfollow", ",i", [1])
    client.set_value("/mtcfollow", 1)
    assert recv() == ("/mtcfollow", ",i", [1])


def test_a_first_mtcfollow_zero_reaches_the_wire(rx_client):
    client, recv = rx_client
    client.set_value("/mtcfollow", 0)
    assert recv() == ("/mtcfollow", ",i", [0])
    client.set_value("/mtcfollow", 0)
    assert recv() == ("/mtcfollow", ",i", [0])


def test_volmaster_zero_as_first_value_reaches_the_wire(rx_client):
    """D7 (step 0d on .111: a master_vol 0 cue played at gain 0.99)."""
    client, recv = rx_client
    client.set_value("/volmaster", 0.0)
    path, tt, args = recv()
    assert (path, tt, args) == ("/volmaster", ",f", [0.0])
    client.set_value("/volmaster", 0.0)
    assert recv()[2] == [0.0]


def test_cancelstart_is_two_ints_and_a_resend_goes_out(rx_client):
    client, recv = rx_client
    client.set_value("/cancelstart", [7, 5])
    assert recv() == ("/cancelstart", ",ii", [7, 5])
    client.set_value("/cancelstart", [7, 5])
    assert recv() == ("/cancelstart", ",ii", [7, 5])


def test_gate_commit_then_cancel_leave_in_order(rx_client):
    client, recv = rx_client

    class _Cue:
        id = "wire-cue"

    player = AudioPlayer(port=0, path="cuems-audioplayer", args="", media="m.wav")
    gate = StartGate(autostart=False)
    assert gate.commit_follow(_Cue(), player, client, 1)
    assert gate.cancel(_Cue(), player, client, "cancel", fade_ms=40) is not None
    assert recv() == ("/mtcfollow", ",i", [1])
    assert recv() == ("/cancelstart", ",ii", [1, 40])
