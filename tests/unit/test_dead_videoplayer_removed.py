# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""The dead ``VideoPlayer`` class stays deleted (869f8v8yv, e890954).

Nothing ever started it: the engine drives the videocomposer through
``VideoClient`` and ``VideoOutput`` only. The module ``players/VideoPlayer.py``
survives for those two; the class, its export and the ``CueHandler`` slot that
held an instance went away. Nothing else exercised any of that, so this test is
the proof of the removal.
"""

import ast
import inspect

import cuemsengine.players
from cuemsengine.cues.CueHandler import CueHandler
from cuemsengine.players import VideoPlayer as video_player_module


def _defined_classes(module):
    tree = ast.parse(inspect.getsource(module))
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}


def test_the_players_package_exports_no_videoplayer():
    assert "VideoPlayer" not in cuemsengine.players.__all__
    # ``players.VideoPlayer`` is the submodule; the class must not be.
    assert not inspect.isclass(getattr(cuemsengine.players, "VideoPlayer", None))


def test_the_videoplayer_module_keeps_its_clients_and_defines_no_videoplayer():
    classes = _defined_classes(video_player_module)

    assert "VideoPlayer" not in classes
    assert {"VideoClient", "VideoOutput"} <= classes


def test_the_cue_handler_holds_no_front_video_player():
    assert "_front_video_player" not in inspect.getsource(CueHandler)
