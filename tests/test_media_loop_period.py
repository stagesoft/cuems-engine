# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Where a node gets a looping cue's period P from (plan 869ejxng3 +
1amfwm7e6cw rev 3.14, §4.1, D14): the editor's sidecar first, then this node's
on-disk cache, then a probe inside the load within the budget; a miss runs
legacy and is reported in ``armed_ready`` (and logged by the controller).
"""

import json
import os
import time
import uuid
import wave
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from cuemsutils.cues import AudioCue, CueList, VideoCue
from cuemsutils.tools import media_sidecars as ms

from cuemsengine.players import LoopPeriods as lp


def _wav(path, frames=24000, rate=48000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\0\0" * frames)
    return str(path)


def _period(path, num=48000, den=48000):
    st = os.stat(path)
    return ms.Period(
        num=num,
        den=den,
        rate=den,
        real_frames=None,
        fps=None,
        rule="walk",
        frames_rule=None,
        vfr=False,
        size=st.st_size,
        mtime=int(st.st_mtime),
        ffprobe="fake",
    )


def _cue(file_name, loop=-1, kind=AudioCue, local=True):
    d = {
        "id": str(uuid.uuid4()),
        "name": f"c {file_name}",
        "loop": loop,
        "Media": {
            "file_name": file_name,
            "id": str(uuid.uuid4()),
            "duration": "00:00:01.000",
        },
    }
    cue = kind(d)
    cue._local = local
    return cue


@pytest.fixture
def cache(tmp_path):
    return lp.LoopPeriodCache(str(tmp_path / "cache" / "loop-periods.json"))


# --------------------------------------------------------------------------- sources


def test_the_sidecar_comes_first(tmp_path, cache):
    f = _wav(tmp_path / "a.wav")
    ms.write_period(f, _period(f, num=11111))
    with patch.object(ms, "loop_period") as probe:
        p, source = lp.media_loop_period(f, 10, cache)
    probe.assert_not_called()
    assert (p.num, source) == (11111, "sidecar")


def test_a_real_probe_is_cached_on_disk_and_survives_a_restart(tmp_path, cache):
    f = _wav(tmp_path / "a.wav", frames=24000)
    p, source = lp.media_loop_period(f, 10, cache)  # the real ffprobe: header rule
    assert (p.num, p.den, p.rule) == (24000, 48000, "header")
    assert source.startswith("probed")
    again = lp.LoopPeriodCache(cache.path)  # a node-engine restart
    with patch.object(ms, "loop_period") as probe:
        p2, source2 = lp.media_loop_period(f, 10, again)
    probe.assert_not_called()
    assert (p2.num, source2) == (24000, "cache")
    assert not os.path.exists(ms.sidecar_path(f))  # the engine never writes one


def test_a_stale_sidecar_and_a_changed_file_are_probed_again(tmp_path, cache):
    f = _wav(tmp_path / "a.wav", frames=24000)
    ms.write_period(f, _period(f, num=11111))
    lp.media_loop_period(f, 10, cache)
    _wav(f, frames=48000)  # replaced: size changes
    p, source = lp.media_loop_period(f, 10, cache)
    assert p.num == 48000 and source.startswith("probed")
    data = json.load(open(cache.path))
    assert len([k for k in data if k.startswith(f + "|")]) == 1  # the dead entry pruned


def test_a_corrupt_cache_is_empty(tmp_path):
    path = tmp_path / "loop-periods.json"
    path.write_text("{nope")
    assert lp.LoopPeriodCache(str(path)).get(_wav(tmp_path / "a.wav")) is None


def test_an_unwritable_cache_stays_in_memory(tmp_path):
    f = _wav(tmp_path / "a.wav")
    c = lp.LoopPeriodCache("/proc/no/such/dir/loop-periods.json")
    c.put(f, _period(f))
    assert c.get(f).num == 48000


def test_a_probe_failure_is_none(tmp_path, cache):
    f = str(tmp_path / "x.wav")
    open(f, "wb").write(b"not audio")
    with patch.object(ms, "loop_period", side_effect=ms.PeriodError("no stream")):
        p, source = lp.media_loop_period(f, 10, cache)
    assert p is None and source.startswith("error")


# --------------------------------------------------------------------------- the load


def _probe(cues, tmp_path, cache, **kw):
    return lp.probe_loop_periods(cues, lambda n: str(tmp_path / n), cache, **kw)


def test_every_cue_gets_its_period_and_a_file_is_probed_once(tmp_path, cache):
    f = _wav(tmp_path / "a.wav")
    a, b = _cue("a.wav"), _cue("a.wav", loop=3)
    with patch.object(
        ms, "loop_period", side_effect=lambda p, budget_s=None: _period(p)
    ) as probe:
        legacy = _probe([a, b], tmp_path, cache)
    assert legacy == [] and probe.call_count == 1
    assert a._loop_period.num == b._loop_period.num == 48000
    assert f


def test_a_budget_miss_is_legacy_and_finished_in_the_background(tmp_path, cache):
    _wav(tmp_path / "a.wav")
    cue = _cue("a.wav")
    calls = []

    def probe(path, budget_s=None, low_priority=False):
        calls.append((budget_s, low_priority))
        if not low_priority:
            raise ms.PeriodTimeout("budget")
        return _period(path)

    with patch.object(ms, "loop_period", side_effect=probe):
        legacy = _probe([cue], tmp_path, cache)
        assert legacy == [str(cue.id)] and cue._loop_period is None
        deadline = time.monotonic() + 5
        while (
            cache.get(str(tmp_path / "a.wav")) is None and time.monotonic() < deadline
        ):
            time.sleep(0.05)
    assert cache.get(str(tmp_path / "a.wav")).num == 48000  # the next load has it
    assert calls[0][0] == lp.FILE_BUDGET_S and calls[1] == (None, True)
    assert cue._loop_period is None  # this load's mode does not change


def _costly_probe(now, cost_s, calls):
    """A probe that takes *cost_s* of the fake clock, and times out (as the real
    one does through its subprocess timeouts) when its budget is shorter."""

    def probe(path, budget_s=None, low_priority=False):
        calls.append((os.path.basename(path), budget_s, low_priority))
        if low_priority:
            return _period(path)
        if budget_s is not None and budget_s < cost_s:
            now[0] += budget_s
            raise ms.PeriodTimeout("budget")
        now[0] += cost_s
        return _period(path)

    return probe


def test_the_total_budget_is_shared(tmp_path, cache):
    for n in ("a.wav", "b.wav"):
        _wav(tmp_path / n)
    now, calls = [0.0], []
    a, b = _cue("a.wav"), _cue("b.wav")
    with patch.object(ms, "loop_period", side_effect=_costly_probe(now, 9.0, calls)):
        legacy = _probe([a, b], tmp_path, cache, clock=lambda: now[0])
    # a: 10 s per file, takes 9; b: what is left of the 15 s (6) < 9 → a miss
    assert calls[:2] == [("a.wav", 10.0, False), ("b.wav", 6.0, False)]
    assert a._loop_period is not None and b._loop_period is None
    assert legacy == [str(b.id)]


def test_an_exhausted_budget_probes_nothing_more(tmp_path, cache):
    for n in ("a.wav", "b.wav"):
        _wav(tmp_path / n)
    now, calls = [0.0], []
    a, b = _cue("a.wav"), _cue("b.wav")
    with patch.object(ms, "loop_period", side_effect=_costly_probe(now, 15.0, calls)):
        legacy = _probe(
            [a, b], tmp_path, cache, clock=lambda: now[0], file_budget_s=20.0
        )
    # a eats the whole 15 s; b is not even started inside the load
    assert [c for c in calls if not c[2]] == [("a.wav", 15.0, False)]
    assert legacy == [str(b.id)] and a._loop_period is not None


def test_a_period_beyond_int32_is_legacy(tmp_path, cache):
    _wav(tmp_path / "a.wav")
    cue = _cue("a.wav")
    with patch.object(
        ms, "loop_period", side_effect=lambda p, budget_s=None: _period(p, num=2**31)
    ):
        assert _probe([cue], tmp_path, cache) == [str(cue.id)]
    assert cue._loop_period is None


def test_nothing_is_assigned_after_the_cancel(tmp_path, cache):
    _wav(tmp_path / "a.wav")
    cue = _cue("a.wav")
    cue._loop_period = "left over from the previous load"
    stop = Event()
    stop.set()
    with patch.object(
        ms, "loop_period", side_effect=lambda p, budget_s=None: _period(p)
    ):
        _probe([cue], tmp_path, cache, cancel=stop)
    assert cue._loop_period is None


# --------------------------------------------------------------------------- NodeEngine


def _node(script):
    from cuemsengine.NodeEngine import NodeEngine

    n = NodeEngine.__new__(NodeEngine)
    n.script = script
    n._legacy_period = []
    return n


def test_the_load_walk_marks_cuelist_children_and_picks_local_looping_audio():
    top = _cue("loop.wav", loop=-1)
    once = _cue("once.wav", loop=1)
    remote = _cue("remote.wav", loop=3, local=False)
    video = _cue("v.mov", loop=-1, kind=VideoCue)
    child = _cue("child.wav", loop=-1)
    inner = CueList()
    inner.contents = [child]
    root = CueList()
    root.contents = [top, once, remote, video, inner]
    node = _node(SimpleNamespace(cuelist=root))
    found = node._loop_period_cues()
    assert found == [top]
    assert child._in_cuelist is True and top._in_cuelist is False


def test_the_probe_runs_beside_the_arm_and_fixes_the_legacy_list(tmp_path):
    from cuemsengine.players.PlayerHandler import PLAYER_HANDLER

    _wav(tmp_path / "ok.wav")
    good, bad = _cue("ok.wav"), _cue("missing.wav")
    root = CueList()
    root.contents = [good, bad]
    node = _node(SimpleNamespace(cuelist=root))
    with (
        patch.object(PLAYER_HANDLER, "media_path", lambda n: str(tmp_path / n)),
        patch.object(
            PLAYER_HANDLER,
            "_loop_period_cache",
            lp.LoopPeriodCache(str(tmp_path / "c.json")),
        ),
    ):
        probe = node._start_loop_period_probe()
        node._finish_loop_period_probe(probe)
    assert good._loop_period.num == 24000
    assert node._legacy_period == [str(bad.id)]


def test_armed_ready_carries_the_legacy_list():
    from cuemsengine.cues.CueHandler import CUE_HANDLER
    from cuemsengine.NodeEngine import NodeEngine

    n = NodeEngine.__new__(NodeEngine)
    n.cm = SimpleNamespace(node_uuid="node-1")
    comms = Mock()
    with patch.object(CUE_HANDLER, "communications_thread", comms, create=True):
        n._legacy_period = []
        n._notify_armed_ready("load")
        n._legacy_period = ["cue-a"]
        n._notify_armed_ready("re-arm")
    first, second = (c.args[0].data for c in comms.send_operation.call_args_list)
    assert first == {"armed": "yes"}  # what an old controller reads
    assert second == {"armed": "yes", "legacy_period": ["cue-a"]}


def test_ensure_video_indexes_uses_the_shared_caller():
    from cuemsengine.NodeEngine import NodeEngine
    from cuemsengine.players.PlayerHandler import PLAYER_HANDLER

    n = NodeEngine.__new__(NodeEngine)
    n.cm = Mock()
    n.script = Mock()
    n.script.get_own_media_filenames.return_value = ["a.mp4", "b.wav", "c.MKV"]
    with (
        patch.object(PLAYER_HANDLER, "media_path", lambda x: "/m/" + x),
        patch.object(ms, "ensure_video_index", return_value=[]) as ev,
    ):
        n.ensure_video_indexes()
    ev.assert_called_once_with(["/m/a.mp4", "/m/c.MKV"], timeout_s=600)


def test_the_controller_warns_about_a_legacy_node():
    from threading import Lock

    from cuemsengine.comms.NodesHub import ActionType, NodeOperation, OperationType
    from cuemsengine.ControllerEngine import ControllerEngine

    c = ControllerEngine.__new__(ControllerEngine)
    c._adopted_nodes = {"n1"}
    c._required_nodes = {"n1", "n2"}
    c._armed_nodes = set()
    c._cluster_lock = Lock()
    c.get_status = Mock(return_value="no")
    op = NodeOperation(
        type=OperationType.STATUS,
        action=ActionType.UPDATE,
        sender="n1",
        target="armed_ready",
        data={"armed": "yes", "legacy_period": ["cue-a"]},
    )
    with patch("cuemsengine.ControllerEngine.Logger") as log:
        c.status_operation_callback(op)
    warned = " ".join(str(a.args[0]) for a in log.warning.call_args_list)
    assert "n1" in warned and "cue-a" in warned and "legacy" in warned
    assert c._armed_nodes == {"n1"}  # the report never blocks the arm aggregation
