# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""`cues/chain_pass.py`: the pure part of the Auto-continue rule (1amfwm7jnqf).

Plan: cuems-RELATIONS `Plans/2026-11-18-autocontinue-cumulative-waits.md`, rev 9.1,
AC3 (Design §1, §3, §5). The model is `baselines/autocontinue-cumulative/model/`
(`chain_model.py`); where a test transcribes it, it says which function.

- the two advance modes: `sequential` ("en serie") adds prewait + postwait,
  `parallel` ("en paralelo", the 2026-08-14 rule) adds 0; an unknown mode raises;
- `layout(entry, T, mode)` equals the model's `time_chain` for every script of
  the fixture and every entry, whatever the flags: it reads no flag;
- the flag as every node sees it (D31 d): `ui_toggle`, `common_enabled`,
  `action_toggle`, `retire`, checked at `W - 1`, `W`, `W + 1` ms;
- the node's order of steps (`StepOrder`): a step waits for every pending step
  with a smaller key, warns after 200 ms, gives up after 5 s.

Red until Step 2 adds the module.
"""

import json
import random
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cuemsengine.cues import chain_pass

FIXTURE = Path(__file__).parent / "fixtures" / "chain_scenarios.json"
W = 500.0
T0 = 100_000.0


class _Tc:
    """A prewait / postwait as the engine reads it (`.milliseconds_exact`),
    exact to the ms whatever the cuems-utils build."""

    def __init__(self, ms):
        self.milliseconds_exact = float(ms)


def _cue(name, pre=0.0, post=0.0, post_go="go", enabled=True, local=True):
    return SimpleNamespace(
        id=name,
        prewait=_Tc(pre),
        postwait=_Tc(post),
        post_go=post_go,
        enabled=enabled,
        _local=local,
        _target_object=None,
    )


def _link(*cues):
    for a, b in zip(cues, cues[1:]):
        a._target_object = b
    return list(cues)


class _NoFlags:
    """A cue whose flag and locality must not be read: the layout reads the
    script alone (D26, Design §1)."""

    def __init__(self, name, pre, post, post_go):
        self.id = name
        self.prewait = _Tc(pre)
        self.postwait = _Tc(post)
        self.post_go = post_go
        self._target_object = None

    @property
    def enabled(self):
        raise AssertionError(f"layout read the flag of {self.id}")

    @property
    def _local(self):
        raise AssertionError(f"layout read the locality of {self.id}")


# ---------------------------------------------------------------------------
# the model's arithmetic, transcribed (chain_model.advance / linked / time_chain)
# ---------------------------------------------------------------------------


def _model_advance(c, mode):
    if mode == "sequential":
        return c["pre"] + c["post"]
    if mode == "parallel":
        return 0.0
    raise ValueError(mode)


def _model_linked(script, i):
    c = script[i]
    if c["link"] is not None:
        return next(k for k, x in enumerate(script) if x["name"] == c["link"])
    return i + 1 if i + 1 < len(script) else None


def _model_time_chain(script, i0, seed, mode):
    out, arr, i, seen = [], seed, i0, set()
    while i is not None and i not in seen and len(out) < 1024:
        c = script[i]
        seen.add(i)
        out.append((c["name"], arr))
        if c["post_go"] != "go":
            break
        arr += _model_advance(c, mode)
        i = _model_linked(script, i)
    return out


def _scripts():
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))
    seen, out = set(), []
    for row in rows:
        key = json.dumps(row["script"], sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append((row["id"], row["script"]))
    return out


def _engine_script(script, cls=None, flags=None):
    """The fixture's script as engine-shaped cues linked by `_target_object`
    (the model's `link`, else the next cue)."""
    cues = []
    for n, c in enumerate(script):
        if cls is not None:
            x = cls(c["name"], c["pre"], c["post"], c["post_go"])
        else:
            x = _cue(c["name"], c["pre"], c["post"], c["post_go"])
            x.enabled = flags[n] if flags is not None else c["enabled"]
        cues.append(x)
    for i in range(len(script)):
        j = _model_linked(script, i)
        cues[i]._target_object = cues[j] if j is not None else None
    return cues


# ---------------------------------------------------------------------------
# modes and advance
# ---------------------------------------------------------------------------


class TestModes:
    def test_the_two_names(self):
        assert chain_pass.SEQUENTIAL == "sequential"
        assert chain_pass.PARALLEL == "parallel"
        assert set(chain_pass.MODES) == {"sequential", "parallel"}
        assert chain_pass.W_MS == W

    def test_sequential_adds_both_waits(self):
        assert chain_pass.advance_ms(_cue("b", 5000, 10000), "sequential") == 15000

    def test_sequential_counts_a_disabled_cue_too(self):
        """D26: disabling a cue never takes its waits away."""
        cue = _cue("b", 5000, 10000, enabled=False)
        assert chain_pass.advance_ms(cue, "sequential") == 15000

    def test_parallel_adds_nothing(self):
        assert chain_pass.advance_ms(_cue("b", 5000, 10000), "parallel") == 0.0

    @pytest.mark.parametrize("mode", ["", None, "en serie", "Sequential", "other"])
    def test_an_unknown_mode_raises(self, mode):
        with pytest.raises(ValueError):
            chain_pass.advance_ms(_cue("b", 5000, 10000), mode)


class TestCueHandlerAdvance:
    """`CueHandler._chain_advance_ms(cue, mode=None)` and `_advance_mode`
    (Scope-in 1): every production chain is `sequential`; `parallel` is
    passed by no production call (AC11)."""

    def test_the_default_mode_is_sequential_for_every_cue(self):
        from cuemsengine.cues.CueHandler import CueHandler

        cue = _cue("b", 5000, 10000)
        assert CueHandler._advance_mode(cue) == "sequential"
        assert CueHandler._chain_advance_ms(cue) == 15000

    def test_parallel_on_request(self):
        from cuemsengine.cues.CueHandler import CueHandler

        assert CueHandler._chain_advance_ms(_cue("b", 5000, 10000), "parallel") == 0
        assert (
            CueHandler._chain_advance_ms(_cue("b", 5000, 10000), mode="parallel") == 0
        )

    def test_an_unknown_mode_raises(self):
        from cuemsengine.cues.CueHandler import CueHandler

        with pytest.raises(ValueError):
            CueHandler._chain_advance_ms(_cue("b", 5000, 10000), mode="unknown")

    @pytest.mark.parametrize(
        "cls_name", ["AudioCue", "VideoCue", "DmxCue", "ActionCue", "CueList"]
    )
    def test_every_cue_type_is_sequential(self, cls_name):
        import cuemsutils.cues as cues
        from cuemsutils.tools.CTimecode import CTimecode

        from cuemsengine.cues.CueHandler import CueHandler

        cls = getattr(cues, cls_name)
        cue = cls.__new__(cls)
        cue.prewait = CTimecode(start_seconds=2)
        cue.postwait = CTimecode(start_seconds=3)
        assert CueHandler._advance_mode(cue) == "sequential"
        # Some cuems-utils builds read start_seconds back 1 ms short.
        assert CueHandler._chain_advance_ms(cue) == pytest.approx(5000, abs=2)


# ---------------------------------------------------------------------------
# layout
# ---------------------------------------------------------------------------


class TestLayout:
    def test_ions_chain(self):
        """Spec table: A 0/0, B 5/10, C 2/0, D 3/0 arrive at 0, 0, 15, 17 and
        start at 0, 5, 17, 20."""
        a, b, c, d = _link(
            _cue("A"),
            _cue("B", 5000, 10000),
            _cue("C", 2000),
            _cue("D", 3000, 0, "pause"),
        )
        got = chain_pass.layout(a, T0, "sequential")
        assert [(x.id, t - T0) for x, t in got] == [
            ("A", 0),
            ("B", 0),
            ("C", 15000),
            ("D", 17000),
        ]
        starts = [t + x.prewait.milliseconds_exact - T0 for x, t in got]
        assert starts == [0, 5000, 17000, 20000]

    def test_ions_chain_parallel(self):
        a, *_ = _link(
            _cue("A"),
            _cue("B", 5000, 10000),
            _cue("C", 2000),
            _cue("D", 3000, 0, "pause"),
        )
        got = chain_pass.layout(a, T0, "parallel")
        assert [t - T0 for _, t in got] == [0, 0, 0, 0]

    def test_the_default_mode_is_sequential(self):
        a, *_ = _link(_cue("A", 1000, 2000), _cue("B", 0, 0, "pause"))
        assert [t for _, t in chain_pass.layout(a, T0)] == [T0, T0 + 3000]

    def test_it_ends_after_the_first_cue_that_is_not_go(self):
        a, b, c = _link(_cue("A"), _cue("B", 1000, 0, "go_at_end"), _cue("C"))
        assert [x.id for x, _ in chain_pass.layout(a, T0)] == ["A", "B"]

    def test_a_disabled_cue_keeps_its_place_and_its_waits(self):
        """S07: B disabled in the file; C and D do not move."""
        a, *_ = _link(
            _cue("A"),
            _cue("B", 5000, 10000, enabled=False),
            _cue("C", 2000),
            _cue("D", 3000, 0, "pause"),
        )
        assert [t - T0 for _, t in chain_pass.layout(a, T0)] == [0, 0, 15000, 17000]

    def test_a_disabled_pause_cue_still_ends_the_chain(self):
        """D28: S11's B (pause, disabled) ends A's chain."""
        a, *_ = _link(
            _cue("A"),
            _cue("B", 3000, 4000, "pause", enabled=False),
            _cue("C", 2000, 0, "pause"),
        )
        assert [x.id for x, _ in chain_pass.layout(a, T0)] == ["A", "B"]

    def test_it_reads_no_flag_and_no_locality(self):
        a, b, c = (
            _NoFlags("A", 0, 0, "go"),
            _NoFlags("B", 1000, 0, "go"),
            _NoFlags("C", 0, 0, "pause"),
        )
        a._target_object, b._target_object = b, c
        assert [x.id for x, _ in chain_pass.layout(a, T0)] == ["A", "B", "C"]

    def test_a_cycle_stops_before_the_second_visit(self):
        a, b = _cue("A", 0, 1000), _cue("B", 0, 2000)
        a._target_object, b._target_object = b, a
        got = chain_pass.layout(a, T0)
        assert [(x.id, t - T0) for x, t in got] == [("A", 0), ("B", 1000)]

    def test_a_long_chain_is_capped(self):
        cues = _link(*[_cue(f"c{i}") for i in range(2000)])
        assert len(chain_pass.layout(cues[0], T0)) == 1024

    def test_a_cuelist_adds_its_own_waits_only(self):
        """A CueList is a chain cue like any other: its children add nothing,
        nested or not (Design §2; `_effective_duration_ms` body 0)."""
        inner = _cue("inner", 7000, 7000)
        lst = _cue("L", 1000, 2000)
        lst.contents = [_cue("k1", 9000, 9000), inner]
        inner.contents = [_cue("k2", 9000, 9000)]
        a, *_ = _link(_cue("A"), lst, _cue("Z", 0, 0, "pause"))
        got = chain_pass.layout(a, T0)
        assert [(x.id, t - T0) for x, t in got] == [("A", 0), ("L", 0), ("Z", 3000)]

    @pytest.mark.parametrize("mode", ["sequential", "parallel"])
    def test_equals_the_models_time_chain_for_every_fixture_script(self, mode):
        """AC3: `layout` equals the model's `time_chain`, for every script of the
        exported fixture and every entry, whatever the flags."""
        rnd = random.Random(20261123)
        checked = 0
        for sid, script in _scripts():
            variants = [
                _engine_script(script),
                _engine_script(script, flags=[False] * len(script)),
                _engine_script(script, flags=[True] * len(script)),
                _engine_script(
                    script, flags=[rnd.random() < 0.5 for _ in range(len(script))]
                ),
                _engine_script(script, cls=_NoFlags),
            ]
            for i0 in range(len(script)):
                want = _model_time_chain(script, i0, T0, mode)
                for cues in variants:
                    got = chain_pass.layout(cues[i0], T0, mode)
                    assert [(x.id, t) for x, t in got] == want, (sid, i0)
                    checked += 1
        assert checked > 0

    def test_an_unknown_mode_raises(self):
        a, *_ = _link(_cue("A", 1000, 0), _cue("B", 0, 0, "pause"))
        with pytest.raises(ValueError):
            chain_pass.layout(a, T0, "timecode")


class TestPass:
    def test_fields_and_arrival_of(self):
        a, b, c = _link(_cue("A"), _cue("B", 1000, 1000), _cue("C", 0, 0, "pause"))
        lay = chain_pass.layout(a, T0)
        p = chain_pass.Pass(epoch=3, anchor_ms=T0, layout=lay, root_seq=7)
        assert (p.epoch, p.anchor_ms, p.root_seq, p.mode) == (3, T0, 7, "sequential")
        assert p.entry is a
        assert p.arrival_of(c) == T0 + 2000
        assert p.arrival_of(_cue("C")) is None  # by identity, not by id

    def test_root_seq_defaults_to_zero(self):
        a = _cue("A", 0, 0, "pause")
        p = chain_pass.Pass(epoch=1, anchor_ms=T0, layout=[(a, T0)])
        assert p.root_seq == 0


# ---------------------------------------------------------------------------
# the flag as every node sees it (D31 d)
# ---------------------------------------------------------------------------


def _toggled(value=True, sent=10_000.0, now=None, seq=1, cue=None):
    cue = cue if cue is not None else _cue("X", enabled=not value)
    placed = chain_pass.ui_toggle(
        cue, value, sent, sent + 3.0 if now is None else now, seq
    )
    return cue, placed


class TestUiToggle:
    def test_the_flag_is_set_at_once(self):
        cue, placed = _toggled(value=False)
        assert cue.enabled is False
        assert placed is True

    def test_a_toggle_that_changes_nothing_is_still_recorded(self):
        """`ui_toggle` sets the flag whether or not it changes: the record keeps
        its place in bus order (Design §3)."""
        cue = _cue("X", enabled=True)
        assert chain_pass.ui_toggle(cue, True, 10_000.0, 10_003.0, 1) is True
        assert cue.enabled is True
        assert chain_pass.common_enabled(cue, 10_501.0, 0) is True

    @pytest.mark.parametrize(
        "offset, counts", [(W - 1, False), (W, False), (W + 1, True)]
    )
    def test_counts_only_more_than_w_after_its_send(self, offset, counts):
        """AC3: checked at W - 1, W and W + 1 ms after `sent_ms`."""
        cue, _ = _toggled(value=False, sent=10_000.0)
        assert chain_pass.common_enabled(cue, 10_000.0 + offset, 0) is (not counts)

    def test_a_toggle_that_came_before_the_go_counts_at_once(self):
        """D31 (d) addition 3: `seq <= root_seq` counts whatever the instant."""
        cue, _ = _toggled(value=False, sent=10_000.0, seq=4)
        assert chain_pass.common_enabled(cue, 10_001.0, 4) is False
        assert chain_pass.common_enabled(cue, 10_001.0, 3) is True

    def test_two_toggles_with_one_send_time_count_in_bus_order(self):
        cue = _cue("X", enabled=True)
        chain_pass.ui_toggle(cue, False, 10_000.0, 10_003.0, 1)
        chain_pass.ui_toggle(cue, True, 10_000.0, 10_004.0, 2)
        assert cue.enabled is True
        assert chain_pass.common_enabled(cue, 10_501.0, 0) is True
        assert chain_pass.common_enabled(cue, 10_400.0, 0) is True  # neither counts

    def test_the_last_one_that_counts_wins(self):
        cue = _cue("X", enabled=True)
        chain_pass.ui_toggle(cue, False, 10_000.0, 10_003.0, 1)
        chain_pass.ui_toggle(cue, True, 10_300.0, 10_303.0, 2)
        assert chain_pass.common_enabled(cue, 10_600.0, 0) is False
        assert chain_pass.common_enabled(cue, 10_801.0, 0) is True

    def test_no_send_time_counts_from_its_arrival(self):
        """A toggle with no `sent_ms` (an older controller, or one whose MTC
        listener is not receiving) counts from its arrival; the caller logs the
        WARNING (`ui_toggle` returns False)."""
        cue = _cue("X", enabled=True)
        placed = chain_pass.ui_toggle(cue, False, None, 20_000.0, 1)
        assert placed is False
        assert cue.enabled is False
        assert chain_pass.common_enabled(cue, 19_999.0, 0) is True
        assert chain_pass.common_enabled(cue, 20_001.0, 0) is False

    @pytest.mark.parametrize("late", [W + 1, -(W + 1), 30_000.0])
    def test_a_send_time_more_than_w_away_counts_from_its_arrival(self, late):
        cue = _cue("X", enabled=True)
        placed = chain_pass.ui_toggle(cue, False, 20_000.0 - late, 20_000.0, 1)
        assert placed is False
        assert chain_pass.common_enabled(cue, 19_999.0, 0) is True
        assert chain_pass.common_enabled(cue, 20_001.0, 0) is False

    def test_a_send_time_w_away_is_still_placed(self):
        cue = _cue("X", enabled=True)
        assert chain_pass.ui_toggle(cue, False, 20_000.0 - W, 20_000.0, 1) is True

    def test_a_cue_with_two_owners_reads_at_start_minus_w(self):
        """AC3 "Decision": a cue with two owners is decided from `common_enabled`
        at `start - W`: toggles sent 2W + 1 ms before its start count in the
        pass, 2W and 2W - 1 ms before do not (S81, S79, S82)."""
        start = 50_000.0
        for before, counts in ((2 * W + 1, True), (2 * W, False), (2 * W - 1, False)):
            cue = _cue("V", enabled=True)
            chain_pass.ui_toggle(cue, False, start - before, start - before + 3, 1)
            assert chain_pass.common_enabled(cue, start - W, 0) is (not counts), before


class TestActionToggle:
    def test_alone_it_sets_the_value(self):
        cue = _cue("P", enabled=False)
        assert chain_pass.action_toggle(cue, True, 30_000.0, 0) is True
        assert cue.enabled is True
        assert chain_pass.common_enabled(cue, 30_001.0, 0) is True

    def test_a_ui_toggle_sent_less_than_w_before_keeps_the_last_word(self):
        """S72: En (enable P) at +5; a UI 'disable P' sent 2.5 ms before it: the
        action comes first, the click keeps the last word, on every node."""
        cue = _cue("P", enabled=False)
        chain_pass.ui_toggle(cue, False, 29_997.5, 30_000.5, 1)
        assert chain_pass.action_toggle(cue, True, 30_000.0, 0) is False
        assert cue.enabled is False
        # The click counts from its send + W (30 497.5): up to there every node
        # reads the action's value, from there the click's.
        assert chain_pass.common_enabled(cue, 30_497.0, 0) is True
        assert chain_pass.common_enabled(cue, 30_497.0, 1) is False  # a later GO
        assert chain_pass.common_enabled(cue, 30_498.0, 0) is False

    def test_a_ui_toggle_sent_more_than_w_before_is_overwritten(self):
        cue = _cue("P", enabled=True)
        chain_pass.ui_toggle(cue, False, 29_400.0, 29_403.0, 1)
        assert chain_pass.action_toggle(cue, True, 30_000.0, 0) is True
        assert cue.enabled is True
        assert chain_pass.common_enabled(cue, 31_000.0, 0) is True

    def test_a_toggle_before_the_go_counts_at_the_action(self):
        cue = _cue("P", enabled=True)
        chain_pass.ui_toggle(cue, False, 29_900.0, 29_903.0, 2)
        # The GO came after toggle 2: it counts at the action's start, which
        # overwrites it.
        assert chain_pass.action_toggle(cue, True, 30_000.0, 2) is True
        assert chain_pass.common_enabled(cue, 31_000.0, 2) is True


class TestRecords:
    def test_retire_folds_the_old_records_in_bus_order(self):
        cue = _cue("B", enabled=True)
        chain_pass.ui_toggle(cue, False, 10_000.0, 10_003.0, 1)  # since 10 500
        chain_pass.ui_toggle(cue, True, 12_000.0, 12_003.0, 2)  # since 12 500
        assert chain_pass.retire(11_000.0, [cue]) == 1
        assert chain_pass.common_enabled(cue, 11_000.0, 0) is False
        assert chain_pass.common_enabled(cue, 12_501.0, 0) is True
        assert chain_pass.retire(13_000.0, [cue]) == 1
        assert chain_pass.retire(13_000.0, [cue]) == 0
        assert cue.enabled is True

    def test_a_record_that_cannot_go_keeps_the_ones_behind_it(self):
        """Folded in bus order: an arrival-placed record behind a pending one
        waits for it."""
        cue = _cue("B", enabled=True)
        chain_pass.ui_toggle(cue, False, 10_000.0, 10_003.0, 1)  # since 10 500
        chain_pass.ui_toggle(cue, True, None, 9_000.0, 2)  # arrival 9 000
        assert chain_pass.retire(10_000.0, [cue]) == 0
        assert chain_pass.common_enabled(cue, 10_501.0, 0) is True

    def test_kept_for_an_action_that_acts_3_s_late(self):
        """S90: Dz (disable B) due at +5 acts 3 s late on one node; the record of
        a UI 'enable B' sent at +4.9 must still be there: the node's floor is
        the anchor of the pass that still has Dz to do, not its MTC - W."""
        cue = _cue("B", enabled=False)
        anchor = T0
        chain_pass.ui_toggle(cue, True, T0 + 4900.0, T0 + 4903.0, 1)
        floor = min(T0 + 8000.0 - W, anchor)  # Dz has not acted yet
        assert chain_pass.retire(floor, [cue]) == 0
        assert chain_pass.action_toggle(cue, False, T0 + 5000.0, 0) is True
        assert cue.enabled is True  # the click keeps the last word (S90)

    def test_a_late_read_logs_an_error(self):
        """A read that meets a retired record: ERROR (the model counts these: 0
        under the rule)."""
        cue = _cue("B", enabled=True)
        cue.id = "cue-B"
        chain_pass.ui_toggle(cue, False, 10_000.0, 10_003.0, 1)
        chain_pass.retire(20_000.0, [cue])
        with patch("cuemsengine.cues.chain_pass.Logger") as log:
            chain_pass.common_enabled(cue, 10_400.0, 0)
        text = " ".join(str(c.args[0]) for c in log.error.call_args_list)
        assert "late read of cue-B's flag" in text

    def test_a_read_after_the_retired_records_is_quiet(self):
        cue = _cue("B", enabled=True)
        chain_pass.ui_toggle(cue, False, 10_000.0, 10_003.0, 1)
        chain_pass.retire(20_000.0, [cue])
        with patch("cuemsengine.cues.chain_pass.Logger") as log:
            assert chain_pass.common_enabled(cue, 20_001.0, 0) is False
        log.error.assert_not_called()


# ---------------------------------------------------------------------------
# the node's order of steps (Design §5)
# ---------------------------------------------------------------------------


class _FakeClock:
    """A clock that the waiter's own sleeps move: a wait that nobody releases
    reaches 5 s at once."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def _key(instant, position=0, sub=0, anchor=T0, entry="A"):
    return (instant, anchor, entry, position, sub)


class TestStepOrder:
    def test_no_smaller_key_no_wait(self):
        order = chain_pass.StepOrder()
        order.add(_key(5000, 1), "Dz")
        order.add(_key(5000, 2), "P")
        t = time.monotonic()
        assert order.wait_turn(_key(5000, 1)) is True
        assert time.monotonic() - t < 0.05

    def test_a_step_waits_for_the_one_before_it_300_ms_late(self):
        """S38: Dz and P due together, Dz's thread 300 ms late: P waits."""
        order = chain_pass.StepOrder()
        dz, p = _key(5000, 2), _key(5000, 3)
        order.add(dz, "Dz")
        order.add(p, "P")
        threading.Timer(0.3, order.done, args=(dz,)).start()
        t = time.monotonic()
        assert order.wait_turn(p) is True
        assert time.monotonic() - t >= 0.28

    def test_an_earlier_start_waits_too(self):
        """S92: En at +5, P at +5.2; En's thread 300 ms late: P waits."""
        order = chain_pass.StepOrder()
        en, p = _key(5000, 1), _key(5200, 2)
        order.add(en, "En")
        order.add(p, "P")
        threading.Timer(0.3, order.done, args=(en,)).start()
        t = time.monotonic()
        assert order.wait_turn(p) is True
        assert time.monotonic() - t >= 0.28

    def test_a_step_already_done_is_not_waited_for(self):
        """Nothing waits for a step that is silent, cut, held, replaced or
        refused: those paths call `done` before the waiter comes."""
        order = chain_pass.StepOrder()
        a, b = _key(5000, 1), _key(5000, 2)
        order.add(a, "A")
        order.add(b, "B")
        order.done(a)
        assert order.pending() == [b]
        t = time.monotonic()
        assert order.wait_turn(b) is True
        assert time.monotonic() - t < 0.05

    def test_a_later_key_does_not_hold_an_earlier_one(self):
        order = chain_pass.StepOrder()
        order.add(_key(6000, 1), "late")
        order.add(_key(5000, 9), "early")
        assert order.wait_turn(_key(5000, 9)) is True

    def test_three_stops_due_together_act_within_50_ms(self):
        order = chain_pass.StepOrder()
        keys = [_key(5000, i) for i in (1, 2, 3)]
        for i, k in enumerate(keys):
            order.add(k, f"S{i}")
        acted = []

        def act(k):
            order.wait_turn(k)
            acted.append((k, time.monotonic()))
            order.done(k)

        threads = [threading.Thread(target=act, args=(k,)) for k in reversed(keys)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(2.0)
        assert [k for k, _ in acted] == keys
        assert acted[-1][1] - acted[0][1] < 0.05

    def test_a_wait_warns_once_and_gives_up_after_5_s(self):
        clock = _FakeClock()
        order = chain_pass.StepOrder(clock=clock, sleep=clock.sleep)
        order.add(_key(5000, 1), "Dz")
        order.add(_key(5000, 2), "P")
        with patch("cuemsengine.cues.chain_pass.Logger") as log:
            assert order.wait_turn(_key(5000, 2)) is False
        warnings = [str(c.args[0]) for c in log.warning.call_args_list]
        errors = [str(c.args[0]) for c in log.error.call_args_list]
        assert len(warnings) == 1 and "P still waiting for Dz" in warnings[0]
        assert len(errors) == 1 and "P gave up waiting for Dz after 5 s" in errors[0]
        assert 5.0 <= clock.t < 5.1

    def test_a_short_wait_does_not_warn(self):
        clock = _FakeClock()
        a, b = _key(5000, 1), _key(5000, 2)
        box = {}

        def sleep(s):
            clock.sleep(s)
            if clock.t >= 0.1:
                box["order"].done(a)

        order = box["order"] = chain_pass.StepOrder(clock=clock, sleep=sleep)
        order.add(a, "A")
        order.add(b, "B")
        with patch("cuemsengine.cues.chain_pass.Logger") as log:
            assert order.wait_turn(b) is True
        log.warning.assert_not_called()

    def test_clear_releases_every_waiter(self):
        """STOP and load clear the node's pending steps."""
        order = chain_pass.StepOrder()
        order.add(_key(5000, 1), "A")
        order.add(_key(5000, 2), "B")
        threading.Timer(0.05, order.clear).start()
        assert order.wait_turn(_key(5000, 2)) is True
        assert order.pending() == []

    def test_done_of_an_unknown_key_is_harmless(self):
        order = chain_pass.StepOrder()
        order.done(_key(1, 1))
        assert order.pending() == []
