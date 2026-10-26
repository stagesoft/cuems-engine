# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""The new audio endpoints on the wire (plan 869ejxng3 + 1amfwm7e6cw rev 3.14,
§4.2, §7.1): a real pyossia device (the engine's AudioClient) sends to a UDP
socket on loopback; the datagrams' type tags are what cuems-audioplayer parses
(``/loop`` as ``,iii`` or ``,i``, ``/start_tod`` as ``,i``), the repetition
filter is off (a per-pass re-send goes out), and ``num`` near 2^31 - 1
survives. ``/offset`` stays ``,f`` for old players.
"""

import socket
import struct

import pytest

from cuemsengine.players.AudioPlayer import AudioClient
from cuemsengine.tools.PortHandler import PORT_HANDLER


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
def wire(monkeypatch):
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(2)
    monkeypatch.setattr(PORT_HANDLER, "new_random_port", _free_port)
    client = AudioClient(player_port=rx.getsockname()[1], name="wire-test")

    def send(path, value):
        client.set_value(path, value)
        return _parse(rx.recv(2048))

    yield send
    client.remove_device()
    rx.close()


def test_loop_with_a_period_is_three_ints(wire):
    assert wire("/loop", [3, 576512, 48000]) == ("/loop", ",iii", [3, 576512, 48000])
    assert wire("/loop", [-1, 2147483647, 44100]) == (
        "/loop",
        ",iii",
        [-1, 2147483647, 44100],
    )


def test_loop_once_is_one_int(wire):
    assert wire("/loop", [1]) == ("/loop", ",i", [1])


def test_the_filter_is_off_a_resend_goes_out(wire):
    assert wire("/loop", [3, 19200, 48000])[2] == [3, 19200, 48000]
    assert wire("/loop", [3, 19200, 48000])[2] == [3, 19200, 48000]
    assert wire("/start_tod", 600080) == ("/start_tod", ",i", [600080])
    assert wire("/start_tod", 600080) == ("/start_tod", ",i", [600080])


def test_start_tod_edges_are_int32(wire):
    # day-align §7.2: [0, 86 399 999] always fits an int32
    assert wire("/start_tod", 86399999) == ("/start_tod", ",i", [86399999])
    assert wire("/start_tod", 0) == ("/start_tod", ",i", [0])


def test_offset_stays_float_for_old_players(wire):
    path, tt, args = wire("/offset", -600080.0)
    assert (path, tt) == ("/offset", ",f") and args[0] == -600080.0
