# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""The mock audio players look like the real ones to the engine (d50ee4b).

The engine waits for a player's ``[OK] RUNNING!`` line before wiring it
(869fbyjzx) and gates the wiring on the player's JACK ports. A log-only mock
printed no line and owned no ports, so every audio arm on a mock box waited the
full RUNNING timeout and logged the cue as SILENT.

JACK itself is faked here: the test runs each mock's ``main()`` with a stand-in
``jack`` module and a server that returns at once, then reads back which client
and ports the mock registered and what it printed.
"""

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from cuemsengine.players.Player import READY_LINE
from cuemsengine.scripts import mock_audioplayer, mock_jack_volume

PLAYER_UUID = "3f2b8c1e-5d4a-4e6b-9a7c-0d1e2f3a4b5c"


class FakeJackClient:
    """Records what a mock registers on the JACK server."""

    created = []

    def __init__(self, name, no_start_server=False):
        self.name = name
        self.inports = MagicMock()
        self.outports = MagicMock()
        self.activate = MagicMock()
        FakeJackClient.created.append(self)

    def registered(self, kind):
        ports = self.inports if kind == "in" else self.outports
        return [call.args[0] for call in ports.register.call_args_list]


@pytest.fixture
def fake_jack(monkeypatch):
    FakeJackClient.created = []
    module = ModuleType("jack")
    module.Client = FakeJackClient
    monkeypatch.setitem(sys.modules, "jack", module)
    return FakeJackClient


@pytest.fixture
def no_jack_server(monkeypatch):
    def refuse(*args, **kwargs):
        raise RuntimeError("Could not connect to JACK server")

    module = ModuleType("jack")
    module.Client = refuse
    monkeypatch.setitem(sys.modules, "jack", module)


def run_mock(module, argv, capsys):
    """Run a mock's main() to the end of serve_forever; return its stdout."""
    with (
        patch.object(sys, "argv", ["mock"] + argv),
        patch.object(module, "BlockingOSCUDPServer"),
        patch.object(module.signal, "signal"),
        pytest.raises(SystemExit),
    ):
        module.main()
    return capsys.readouterr().out


def ready_lines(out):
    return [line for line in out.splitlines() if line.encode() == READY_LINE]


def test_audioplayer_registers_the_real_players_client_and_ports(fake_jack, capsys):
    out = run_mock(mock_audioplayer, ["--port", "7001", "--uuid", PLAYER_UUID], capsys)

    (client,) = fake_jack.created
    assert client.name == f"Audio_Player-{PLAYER_UUID}"
    assert client.registered("out") == ["outport 0", "outport 1"]
    assert client.registered("in") == []
    client.activate.assert_called_once()
    assert ready_lines(out) == [READY_LINE.decode()]


def test_jack_volume_registers_input_n_and_output_n(fake_jack, capsys):
    out = run_mock(mock_jack_volume, ["-c", "mixer_0", "-p", "7002", "-n", "3"], capsys)

    (client,) = fake_jack.created
    assert client.name == "mixer_0"
    assert client.registered("in") == ["input_1", "input_2", "input_3"]
    assert client.registered("out") == ["output_1", "output_2", "output_3"]
    client.activate.assert_called_once()
    assert ready_lines(out) == [READY_LINE.decode()]


@pytest.mark.parametrize(
    "module, argv",
    [
        (mock_audioplayer, ["--port", "7001", "--uuid", PLAYER_UUID]),
        (mock_jack_volume, ["-p", "7002"]),
    ],
    ids=["audioplayer", "jack-volume"],
)
def test_without_a_jack_server_the_mock_is_still_a_running_osc_endpoint(
    module, argv, no_jack_server, capsys
):
    out = run_mock(module, argv, capsys)

    assert ready_lines(out) == [READY_LINE.decode()]
