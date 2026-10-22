# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""A node reports its own media files that differ from the project (869fat84r D20, L2).

The project stores each media file's size (``file_size``) next to its
duration. The editor corrects the project before a load when a file on the
controller changed (L1). L2 is the last defence on each node: at load, after
the media sync, the node compares its own copies with the stored sizes and
logs one ERROR per file that differs or is missing, saying the stored
duration is kept (so the nodes stay in step) and whether this load's media
sync failed. It only reports: a bug in it must never abort the load, which
has already torn the previous project down.

Design: cuems-RELATIONS Plans/2026-10-01-engine-late-go-media-probe.md §7.2.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

sys.modules.setdefault("cuemsutils.tools.Osc_nodes_hub", MagicMock())

from cuemsengine.NodeEngine import NodeEngine, own_media_size_mismatches  # noqa: E402

NE = "cuemsengine.NodeEngine"


def _cue(**media):
    cue = MagicMock()
    cue.media = dict(media)
    return cue


def _script(cues):
    """A script whose own media is {cue_id: file_name} and whose cues hold *cues*."""
    script = MagicMock()
    script.get_own_media.return_value = {
        cid: c.media.get("file_name") for cid, c in cues.items()
    }
    script.find.side_effect = lambda cid: cues[cid]
    return script


def _media(tmp_path, **files):
    folder = tmp_path / "media"
    folder.mkdir(exist_ok=True)
    for name, size in files.items():
        (folder / name).write_bytes(b"x" * size)
    return lambda name: str(folder / name)


class TestMismatches:
    def test_matching_sizes_report_nothing(self, tmp_path):
        path = _media(tmp_path, **{"a.mp4": 10})
        cues = {"c1": _cue(file_name="a.mp4", file_size=10)}
        assert own_media_size_mismatches({"c1": "a.mp4"}, cues.__getitem__, path) == []

    def test_no_stored_size_or_a_bad_value_reports_nothing(self, tmp_path):
        path = _media(tmp_path, **{"a.mp4": 10, "b.wav": 5, "c.wav": 5})
        cues = {
            "c1": _cue(file_name="a.mp4"),
            "c2": _cue(file_name="b.wav", file_size="many"),
            "c3": _cue(file_name="c.wav", file_size=0),
        }
        own = {k: v.media["file_name"] for k, v in cues.items()}
        assert own_media_size_mismatches(own, cues.__getitem__, path) == []

    def test_a_different_size_is_reported_once_per_file(self, tmp_path):
        path = _media(tmp_path, **{"a.mp4": 11})
        cues = {
            "c1": _cue(file_name="a.mp4", file_size=10),
            "c2": _cue(file_name="a.mp4", file_size=10),
        }
        own = {"c1": "a.mp4", "c2": "a.mp4"}
        assert own_media_size_mismatches(own, cues.__getitem__, path) == [
            ("a.mp4", 10, 11)
        ]

    def test_a_missing_file_is_reported(self, tmp_path):
        path = _media(tmp_path)
        cues = {"c1": _cue(file_name="gone.wav")}
        assert own_media_size_mismatches(
            {"c1": "gone.wav"}, cues.__getitem__, path
        ) == [("gone.wav", None, None)]


def _node(script, media_path):
    node = object.__new__(NodeEngine)
    node.script = script
    node.cm = MagicMock()
    return node, patch(f"{NE}.PLAYER_HANDLER.media_path", side_effect=media_path)


class TestCheckOwnMediaSizes:
    def test_a_mismatch_is_one_error_and_the_stored_duration_is_kept(self, tmp_path):
        path = _media(tmp_path, **{"a.mp4": 11})
        cue = _cue(file_name="a.mp4", file_size=10, duration="00:01:30.000")
        node, media_path = _node(_script({"c1": cue}), path)
        with media_path, patch(f"{NE}.Logger") as log:
            node.check_own_media_sizes(media_synced=True)
        errors = [str(c) for c in log.error.call_args_list]
        assert len(errors) == 1
        assert "a.mp4" in errors[0] and "10" in errors[0] and "11" in errors[0]
        assert "kept" in errors[0]
        assert "sync failed" not in errors[0]
        assert cue.media["duration"] == "00:01:30.000"

    def test_the_message_says_when_the_media_sync_failed(self, tmp_path):
        path = _media(tmp_path, **{"a.mp4": 11})
        node, media_path = _node(
            _script({"c1": _cue(file_name="a.mp4", file_size=10)}), path
        )
        with media_path, patch(f"{NE}.Logger") as log:
            node.check_own_media_sizes(media_synced=False)
        assert "sync failed" in str(log.error.call_args_list[0])

    def test_a_missing_file_is_an_error(self, tmp_path):
        path = _media(tmp_path)
        node, media_path = _node(
            _script({"c1": _cue(file_name="gone.wav", file_size=3)}), path
        )
        with media_path, patch(f"{NE}.Logger") as log:
            node.check_own_media_sizes(media_synced=True)
        assert "missing" in str(log.error.call_args_list[0])

    def test_matching_files_log_nothing(self, tmp_path):
        path = _media(tmp_path, **{"a.mp4": 10})
        node, media_path = _node(
            _script({"c1": _cue(file_name="a.mp4", file_size=10)}), path
        )
        with media_path, patch(f"{NE}.Logger") as log:
            node.check_own_media_sizes(media_synced=True)
        assert not log.error.called

    def test_an_exception_inside_is_logged_never_raised(self):
        script = MagicMock()
        script.get_own_media.side_effect = RuntimeError("boom")
        node, media_path = _node(script, lambda name: name)
        with media_path, patch(f"{NE}.Logger") as log:
            assert node.check_own_media_sizes(media_synced=True) == []
        assert log.error.called


class TestReadyProject:
    def _ready(self, deploy_ok=True, script=None):
        node = object.__new__(NodeEngine)
        node.cm = MagicMock()
        node.script = script or _script({})
        node.read_script = MagicMock()
        node.deploy_media = MagicMock(return_value=deploy_ok)
        node.ensure_video_indexes = MagicMock()
        node.map_cue_outputs = MagicMock(return_value={})
        return node

    def test_the_check_runs_after_the_media_sync_with_its_result(self):
        node = self._ready(deploy_ok=False)
        node.check_own_media_sizes = MagicMock(return_value=[])
        with patch(f"{NE}.PLAYER_HANDLER"), patch(f"{NE}.PORT_HANDLER"):
            node.ready_project("proj")
        node.check_own_media_sizes.assert_called_once_with(False)

    def test_a_failing_check_never_aborts_the_load(self):
        script = MagicMock()
        script.get_own_media.side_effect = RuntimeError("boom")
        node = self._ready(script=script)
        with (
            patch(f"{NE}.PLAYER_HANDLER"),
            patch(f"{NE}.PORT_HANDLER"),
            patch(f"{NE}.Logger"),
        ):
            node.ready_project("proj")
        node.map_cue_outputs.assert_called_once()
