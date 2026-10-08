# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

"""Cue names on the :9190 status channel (869fedahu).

The UI names the engine's next cue from a uuid -> name table. The engine only
ever sent the uuid, so a tab that had not opened the engine's own project
showed a raw uuid. Now the controller broadcasts one
``/engine/status/cue_name/<uuid>`` per cue at load and replays them to late
joiners, like ``cue/`` and ``cue_enabled/``.

Pinned here, in order of importance:

* names are sent AFTER ``/engine/status/load <project>``: duplicated projects
  share cue uuids, so a client must be able to treat a change of ``load`` as
  "new table" and refill it from the burst that follows;
* a second load with no unload in between replaces the map, and the shared
  uuid ends up with the new project's name;
* the late-join dump carries them, after ``cue_enabled`` and before ``mixer``;
* unload empties the map;
* the existing ``cue/`` and ``cue_enabled/`` bursts are untouched.

Pure unit tests: no MTC master, no NNG, no sockets, no subprocess. Safe to run
on a live rig.
"""

import asyncio
import uuid
from os import environ
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from cuemsutils.cues import ActionCue, AudioCue, CueList, DmxCue, VideoCue

from cuemsengine.osc.WebSocketOscHandler import build_osc_message

CUE_NAME = "/engine/status/cue_name/"
CUE_STATUS = "/engine/status/cue/"
CUE_ENABLED = "/engine/status/cue_enabled/"
MIXER = "/engine/status/audio/mixer/"
LOAD = "/engine/status/load"


@pytest.fixture(autouse=True)
def set_config_path():
    """Point CUEMS_CONF_PATH at test XML files."""
    test_conf_path = Path(__file__).parent / ".." / "dev" / "test_xml_files"
    environ["CUEMS_CONF_PATH"] = str(test_conf_path)


@pytest.fixture
def controller():
    """A minimal ControllerEngine with the heavy dependencies mocked out."""
    with (
        patch("cuemsengine.core.BaseEngine.ConfigManager") as MockCM,
        patch(
            "cuemsengine.core.BaseEngine.BaseEngine.get_controller_ip",
            return_value="localhost",
        ),
    ):
        mock_cm_instance = MockCM.return_value
        mock_cm_instance.node_conf = {
            "uuid": "test-controller-uuid",
            "mtc_port": "MTC_MIDI_PORT",
        }
        mock_cm_instance.library_path = str(
            Path(__file__).parent / ".." / "dev" / "test_xml_files"
        )
        mock_cm_instance.tmp_path = "/tmp"

        from cuemsengine.ControllerEngine import ControllerEngine

        engine = ControllerEngine(with_mtc=False)

        engine.communications_thread = Mock()
        engine.communications_thread.broadcast_osc = Mock()
        engine.communications_thread.nng_hub = Mock()

        engine.set_status("running", "no")
        engine.set_status("load", "")

        yield engine

        engine.stop()


def _uuid() -> str:
    return str(uuid.uuid4())


def _cue(cls, **fields):
    """A cue built the way the XML reader builds them (init_dict path)."""
    init = {"id": fields.pop("id", _uuid())}
    init.update(fields)
    return cls(init)


def _script(cuelist):
    script = Mock()
    script.cuelist = cuelist
    script.id = _uuid()
    return script


def _load(controller, project_name, cuelist):
    """Drive load_project up to and past the status bursts, nothing further.

    Everything after set_status("load") that needs a cluster, MTC or the lock
    file is stubbed; the bursts and the status messages are real.
    """

    def fake_read_script(name):
        controller.script = _script(cuelist)

    with (
        patch.object(controller, "read_script", side_effect=fake_read_script),
        patch.object(controller, "_resolve_cluster_state"),
        patch.object(controller, "_forward_load_to_nodes"),
        patch.object(controller, "start_timecode"),
        patch.object(controller, "set_show_lock_file"),
    ):
        assert controller.load_project(project_name) is True


def _sent(controller):
    """(address, value) pairs in broadcast order."""
    return [
        (c.args[0], c.args[1])
        for c in controller.communications_thread.broadcast_osc.call_args_list
    ]


def _index_of_load(sent, project_name):
    """Index of the LAST `load <project_name>` message."""
    idx = [i for i, (a, v) in enumerate(sent) if a == LOAD and v == project_name]
    assert idx, f"no {LOAD} {project_name!r} in {sent}"
    return idx[-1]


# ─── _collect_cue_names ──────────────────────────────────────────────────


class TestCollectCueNames:
    def test_walks_nested_lists_and_keeps_every_id(self, controller):
        inner = _cue(DmxCue, name="Luz 3")
        nested = _cue(CueList, name="Bloque 2", contents=[inner])
        audio = _cue(AudioCue, name="Canción ñ · 2ª")
        video = _cue(VideoCue)  # no name given: init_dict fills 'empty'
        action = _cue(ActionCue, name=None)
        top = CueList({"id": _uuid(), "contents": [audio, video, action, nested]})

        names = controller._collect_cue_names(top)

        assert {str(k): v for k, v in names.items()} == {
            str(audio.id): "Canción ñ · 2ª",
            str(video.id): "empty",
            str(action.id): "",
            str(nested.id): "Bloque 2",
            str(inner.id): "Luz 3",
        }

    def test_mirrors_collect_cue_ids(self, controller):
        """Same walk as the status map: a cue with a name but no status, or
        the reverse, would be a UI that cannot pair them."""
        inner = _cue(AudioCue, name="a")
        nested = _cue(CueList, name="l", contents=[inner, None])
        top = CueList({"id": _uuid(), "contents": [None, nested, _cue(VideoCue)]})

        ids = {str(i) for i in controller._collect_cue_ids(top)}
        names = {str(k) for k in controller._collect_cue_names(top)}
        assert names == ids


# ─── the load burst ──────────────────────────────────────────────────────


class TestLoadBurst:
    def test_one_name_per_cue_after_the_load_status(self, controller):
        a = _cue(AudioCue, name="Intro")
        b = _cue(VideoCue, name="Vídeo 1")
        _load(controller, "show_x", CueList({"id": _uuid(), "contents": [a, b]}))

        sent = _sent(controller)
        load_at = _index_of_load(sent, "show_x")
        names = [
            (i, a_, v) for i, (a_, v) in enumerate(sent) if a_.startswith(CUE_NAME)
        ]

        assert {a_[len(CUE_NAME) :]: v for _, a_, v in names} == {
            str(a.id): "Intro",
            str(b.id): "Vídeo 1",
        }
        assert all(
            i > load_at for i, _, _ in names
        ), "names must follow `load <project>` so a client can clear on load change"
        assert {str(k): v for k, v in controller.cue_names.items()} == {
            str(a.id): "Intro",
            str(b.id): "Vídeo 1",
        }

    def test_status_and_enabled_bursts_are_untouched(self, controller):
        """Regression guard: the two existing bursts keep their count and
        their place before `load`; the new one is appended, not interleaved."""
        cues = [_cue(AudioCue, name=f"c{i}") for i in range(3)]
        _load(controller, "show_x", CueList({"id": _uuid(), "contents": cues}))

        sent = _sent(controller)
        load_at = _index_of_load(sent, "show_x")
        status = [i for i, (a, _) in enumerate(sent) if a.startswith(CUE_STATUS)]
        enabled = [i for i, (a, _) in enumerate(sent) if a.startswith(CUE_ENABLED)]
        names = [i for i, (a, _) in enumerate(sent) if a.startswith(CUE_NAME)]

        assert len(status) == len(enabled) == len(names) == 3
        assert max(status) < min(enabled) < load_at < min(names)

    def test_second_load_without_unload_replaces_the_map(self, controller):
        """Duplicated projects share cue uuids. After X then Y, the shared
        uuid must carry Y's name and nothing of X must survive in the map."""
        shared = _uuid()
        only_x = _cue(AudioCue, name="Sólo X")
        _load(
            controller,
            "show_x",
            CueList(
                {
                    "id": _uuid(),
                    "contents": [_cue(AudioCue, id=shared, name="Intro"), only_x],
                }
            ),
        )
        only_y = _cue(VideoCue, name="Sólo Y")
        _load(
            controller,
            "show_y",
            CueList(
                {
                    "id": _uuid(),
                    "contents": [_cue(AudioCue, id=shared, name="Intro v2"), only_y],
                }
            ),
        )

        assert {str(k): v for k, v in controller.cue_names.items()} == {
            shared: "Intro v2",
            str(only_y.id): "Sólo Y",
        }
        sent = _sent(controller)
        load_y = _index_of_load(sent, "show_y")
        after = [(a, v) for a, v in sent[load_y + 1 :] if a.startswith(CUE_NAME)]
        assert (CUE_NAME + shared, "Intro v2") in after
        assert (CUE_NAME + shared, "Intro") not in after

    def test_a_utf8_name_survives_the_osc_round_trip(self):
        from pythonosc.osc_message import OscMessage

        name = "Canción ñ · 2ª — «fin»"
        data = build_osc_message(CUE_NAME + _uuid(), name)
        assert data is not None
        assert OscMessage(data).params == [name]


# ─── late join ───────────────────────────────────────────────────────────


class TestLateJoin:
    def _dump(self, controller):
        ws = Mock()
        sent = []

        async def fake_send(data):
            sent.append(data)

        ws.send = fake_send
        asyncio.run(controller._on_ws_client_connect(ws))
        return sent

    def test_readable_before_any_load(self, controller):
        """__init__ must define it: a browser connecting before the first load
        of a freshly restarted engine reaches _on_ws_client_connect."""
        assert controller.cue_names == {}
        sent = self._dump(controller)
        assert not any(CUE_NAME.encode() in d for d in sent)

    def test_names_are_replayed_after_enabled_and_before_mixer(self, controller):
        cid = _uuid()
        controller.cue_status = {cid: 0}
        controller.cue_enabled_status = {cid: True}
        controller.cue_names = {cid: "Intro"}
        controller.mixer_status = {"node/0/master": 0.5}

        sent = self._dump(controller)

        def first(prefix):
            hits = [i for i, d in enumerate(sent) if prefix.encode() in d]
            assert hits, f"{prefix} missing from the dump"
            return hits[0]

        assert first(CUE_ENABLED) < first(CUE_NAME) < first(MIXER)
        name_frames = [d for d in sent if (CUE_NAME + cid).encode() in d]
        assert len(name_frames) == 1
        assert "Intro".encode() in name_frames[0]


# ─── unload ──────────────────────────────────────────────────────────────


class TestUnload:
    def test_unload_empties_the_map(self, controller):
        _load(
            controller,
            "show_x",
            CueList({"id": _uuid(), "contents": [_cue(AudioCue, name="Intro")]}),
        )
        assert controller.cue_names

        with patch.object(controller, "_forward_command_to_nodes"):
            assert controller.unload_project(None) is True

        assert controller.cue_names == {}
        assert controller.cue_status == {}
        assert controller.cue_enabled_status == {}
