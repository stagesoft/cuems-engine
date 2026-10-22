# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""NodeEngine's output lookups ignore the mappings' inputs (35cbe78, A-7).

Inputs reuse the outputs' ``<id>`` numbering and are listed after them, so a
lookup built from every list under the node's mappings let input 0 overwrite
output 0: an audio cue on output ``<node>_0`` resolved to ``system:capture_1``,
found no mixer input for it and played SILENT.

The mappings are loaded the way the engine loads them (008): through
``ConfigManager`` into the typed ``NodeMappingType``, never as a plain dict.
"""

import shutil
from os import environ
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from cuemsutils.tools.ConfigManager import ConfigManager

FIXTURE_DIR = Path(__file__).parent.parent / "dev" / "test_xml_files"

# Inputs for the first node's video device, numbered like its outputs and
# pointing at the *other* connector, so a lookup that mixes them up shows.
VIDEO_INPUTS = (
    "<inputs><input><id>0</id><name>in0</name>"
    "<mappings><mapped_to>salida_002</mapped_to></mappings></input></inputs>"
)

REGIONS = {
    "salida_001": {"x": 0, "y": 0, "width": 1920, "height": 1080},
    "salida_002": {"x": 1920, "y": 0, "width": 1920, "height": 1080},
}


@pytest.fixture
def node(tmp_path, monkeypatch):
    """A NodeEngine over mappings whose first node lists inputs AND outputs."""
    conf = tmp_path / "conf"
    library = tmp_path / "library"
    conf.mkdir()
    (library / "projects").mkdir(parents=True)
    settings = (FIXTURE_DIR / "settings.xml").read_text()
    (conf / "settings.xml").write_text(
        settings.replace("/opt/cuems_library", str(library))
    )
    shutil.copy(FIXTURE_DIR / "network_map.xml", conf / "network_map.xml")

    mappings = (FIXTURE_DIR / "default_mappings.xml").read_text()
    video_outputs_end = mappings.index("</outputs>", mappings.index('<device class="video">'))
    video_outputs_end += len("</outputs>")
    (conf / "default_mappings.xml").write_text(
        mappings[:video_outputs_end] + VIDEO_INPUTS + mappings[video_outputs_end:]
    )
    monkeypatch.setitem(environ, "CUEMS_CONF_PATH", str(conf))

    from cuemsengine.NodeEngine import NodeEngine

    engine = object.__new__(NodeEngine)
    engine.cm = ConfigManager(config_dir=str(conf), load_all=True)
    return engine


def test_node_lists_inputs_alongside_outputs(node):
    """Guard on the arrangement: the lookups below are only a test if the
    node really lists inputs that share the outputs' numbering."""
    audio = node.cm.node_mappings.get("audio")
    video = node.cm.node_mappings.get("video")

    assert audio.get("inputs") and audio.get("outputs")
    assert video.get("inputs") and video.get("outputs")


def test_audio_output_zero_resolves_to_the_output_not_the_input(node):
    node.cm.node_hw_outputs = {"audio_outputs": []}

    with patch("cuemsengine.NodeEngine.PLAYER_HANDLER") as player_handler:
        node.set_audio_players()

    (audio_outputs,) = player_handler.set_audio_outputs.call_args.args
    assert audio_outputs["0"]["mapped_to"] == "system:playback_1"
    assert audio_outputs["1"]["mapped_to"] == "system:playback_2"
    assert "system:capture_1" not in {o["mapped_to"] for o in audio_outputs.values()}


def test_video_output_zero_resolves_to_the_output_not_the_input(node):
    node.cm.node_hw_outputs = {"video_outputs": ["salida_001", "salida_002"]}

    with (
        patch("cuemsengine.NodeEngine.PLAYER_HANDLER") as player_handler,
        patch("cuemsengine.NodeEngine.PORT_HANDLER"),
        patch(
            "cuemsengine.NodeEngine.read_display_conf",
            return_value=(REGIONS, (3840, 1080)),
        ),
    ):
        node.set_video_players()

    video_outputs = player_handler.start_video_outputs.call_args.args[0]
    assert video_outputs["0"]["mapped_to"] == "salida_001"
    assert video_outputs["0"]["x"] == 0
    assert video_outputs["1"]["mapped_to"] == "salida_002"
