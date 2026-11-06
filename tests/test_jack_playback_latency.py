# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""869feynrj §4.5d: a node's output latency from JACK at node start, through
``jack_lsp -l -p`` (step 3 on test2: the venv's JACK-Client 0.5.7 has no
``Port.get_latency_range`` and its cffi no ``jack_latency_range_t``, so the
Python query failed on every node start).

The fixture is test2 node01's real output: system:playback_1..4 at 1536
frames, analog_audio:playback_* at 1056, capture ports and the mixer's
ports excluded (only ``input,physical`` ports count): the maximum is 1536.
"""

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cuemsengine.players import JackConnectionManager as JCM

FIXTURE = Path(__file__).parent / "data" / "jack_lsp-l-node01.txt"
RUN = "cuemsengine.players.JackConnectionManager.subprocess.run"
LOG = "cuemsengine.players.JackConnectionManager.Logger"


def _manager(client=SimpleNamespace(samplerate=48000, blocksize=512)):
    m = object.__new__(JCM.JackConnectionManager)
    m.client_name = "test"
    m._client = client
    return m


def _done(text, rc=0):
    return subprocess.CompletedProcess(["jack_lsp"], rc, stdout=text, stderr="")


def test_parse_the_node01_capture():
    assert JCM.parse_jack_lsp_playback_latency(FIXTURE.read_text()) == 1536


def test_only_physical_inputs_count():
    text = (
        "a:out\n\tport playback latency = [ 9999 9999 ] frames\n"
        "\tproperties: output,physical,terminal,\n"
        "b:mix\n\tport playback latency = [ 0 4096 ] frames\n\tproperties: input,\n"
        "system:playback_1\n\tport playback latency = [ 1024 1056 ] frames\n"
        "\tproperties: input,physical,terminal,\n"
    )
    assert JCM.parse_jack_lsp_playback_latency(text) == 1056


def test_no_physical_input_is_none():
    assert JCM.parse_jack_lsp_playback_latency("x:y\n\tproperties: output,\n") is None
    assert JCM.parse_jack_lsp_playback_latency("") is None


def test_playback_latency_runs_jack_lsp_with_a_timeout():
    with patch(RUN, return_value=_done(FIXTURE.read_text())) as run:
        assert _manager().playback_latency() == (1536, 48000, 512)
    args, kwargs = run.call_args
    assert args[0][-2:] == ["-l", "-p"] and kwargs["timeout"] <= 2.0


def test_a_timeout_is_one_warning_and_none():
    with (
        patch(RUN, side_effect=subprocess.TimeoutExpired(["jack_lsp"], 2.0)),
        patch(LOG) as log,
    ):
        assert _manager().playback_latency() is None
    log.warning.assert_called_once()


def test_a_missing_binary_is_one_warning_and_none():
    with patch(RUN, side_effect=FileNotFoundError("jack_lsp")), patch(LOG) as log:
        assert _manager().playback_latency() is None
    log.warning.assert_called_once()


def test_a_failing_jack_lsp_is_none():
    with patch(RUN, return_value=_done("", rc=1)), patch(LOG) as log:
        assert _manager().playback_latency() is None
    log.warning.assert_called_once()


def test_no_jack_client_is_none():
    with patch(RUN, return_value=_done(FIXTURE.read_text())), patch(LOG):
        assert _manager(client=None).playback_latency() is None


def test_node_start_reads_it():
    """End to end: NodeEngine._init_out_latency through the real
    JackConnectionManager.playback_latency -> 1536 + 512 frames at 48 kHz."""
    import importlib
    from unittest.mock import MagicMock

    NE = importlib.import_module("cuemsengine.NodeEngine")
    node = object.__new__(NE.NodeEngine)
    node.cm = SimpleNamespace(
        node_conf={"audioplayer": {"output_latency_ms": "auto"}}, node_uuid="n"
    )
    mixer = SimpleNamespace(conn_man=_manager())
    with (
        patch(RUN, return_value=_done(FIXTURE.read_text())),
        patch.object(NE.PLAYER_HANDLER, "get_audio_mixer", return_value=mixer),
        patch.object(NE.CUE_HANDLER, "out_latency_ms", None),
        patch.object(NE.CUE_HANDLER, "communications_thread", MagicMock(), create=True),
    ):
        node._init_out_latency()
    assert abs(node._out_latency_ms - (1536 + 512) * 1000 / 48000) < 1e-6
