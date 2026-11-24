# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""A DMX cue saved disabled and enabled inside its pass sends its scene, on every
node (1amfwm7jnqf, AC12 d1).

Found on the `test` rig on 2026-11-23: such a cue was never armed (arm() arms an
enabled cue only), and an enable inside its pass leaves the cue to its own thread
(Design §3), which sent nothing, having no frame data, while it logged a send.
The thread now arms it before the send, and a send is logged only when it
happened.

Three toggles of the same script (A on n1 at +0, M on every node at +8, C after):
the enable before M's scene instant (start - run-ahead), the enable after it
(the late send at the start, AC12 d1), and the enable too close to the start to
count in this pass (AC12 d2: no scene). Runs on the chain simulator, one
subprocess per node; never on casas (house rule A12).
"""

from __future__ import annotations

import copy

import pytest

T0 = 100_000.0
START_M = T0 + 8_000.0
RUN_AHEAD = 5_000.0
TOL_MS = 41.0  # one 25 fps frame

BASE = {
    "id": "AC12-d",
    "family": "dmx",
    "name": "M saved disabled, enabled inside its pass",
    "events": [],
    "expect": None,
    "anchors": None,
    "perturb": None,
    "until_s": 30.0,
    "kind": "rule",
    "notes": [],
    "own": None,
    "stops": None,
    "standby": None,
    "agree": True,
    "nodes": ["n1", "n2"],
    "flags": None,
    "script": [
        {
            "name": "A",
            "pre": 0.0,
            "post": 0.0,
            "post_go": "go",
            "kind": "audio",
            "node": "n1",
            "body": 4000.0,
            "enabled": True,
            "action": None,
            "target": None,
            "link": None,
            "children": [],
        },
        {
            "name": "M",
            "pre": 8000.0,
            "post": 0.0,
            "post_go": "go",
            "kind": "dmx",
            "node": "*",
            "body": 0.0,
            "enabled": False,
            "action": None,
            "target": None,
            "link": None,
            "children": [],
        },
        {
            "name": "C",
            "pre": 2000.0,
            "post": 0.0,
            "post_go": "pause",
            "kind": "audio",
            "node": "n2",
            "body": 4000.0,
            "enabled": True,
            "action": None,
            "target": None,
            "link": None,
            "children": [],
        },
    ],
    "rules": {
        "mode": "sequential",
        "toggle": "sent",
        "commit_decides": True,
        "order": "instants",
        "pointer": "rule",
        "until": True,
        "ownership": "pass",
        "dmx_cancel": False,
        "owners": "common",
        "child": "carried",
        "retire": "open",
        "guard": "auto",
        "late_arm": "late",
        "arm_fail": "silent",
    },
    "t0_ms": T0,
    "constants": {
        "bus_ms": {"n1": 3.0, "n2": 5.0, "n3": 7.0},
        "relay_ms": 8.0,
        "go_lead_ms": 80.0,
        "w_ms": 500.0,
        "commit_ms": 120.0,
        "run_ahead_ms": RUN_AHEAD,
    },
}


def _scenario(enable_at_ms: float) -> dict:
    sc = copy.deepcopy(BASE)
    sc["events"] = [["go", "A", T0], ["toggle", "M", True, enable_at_ms]]
    return sc


def _run(enable_at_ms: float) -> dict:
    from tests.chain_sim.driver import SimError, run_scenario
    from tests.chain_sim.node import cue_id

    try:
        runs = run_scenario(_scenario(enable_at_ms))
    except SimError as e:
        pytest.fail(f"the harness could not run it: {e}", pytrace=False)
    return {"runs": runs, "m": cue_id("M")}


def _lines(run: dict, needle: str) -> list:
    return [(mtc, msg) for mtc, _, msg in run["journal"] if needle in msg]


def _unsent(run: dict, m: str) -> list:
    """The engine's "scene not sent (see above)" lines: a send that failed.
    "not sent, the cue is disabled" is a withheld scene, not a failure."""
    return [x for x in _lines(run, f"{m}: DMX scene not sent") if "(see above)" in x[1]]


@pytest.mark.parametrize(
    "case, enable_at, sent_at, late",
    [
        # before the scene instant: the scene goes at its instant
        ("early", T0 + 1_000.0, START_M - RUN_AHEAD, False),
        # AC12 d1: after the scene instant, before start - W: late, at the start
        ("d1", T0 + 5_000.0, START_M, True),
    ],
)
def test_an_enabled_dmx_cue_sends_its_scene_on_every_node(
    case, enable_at, sent_at, late
):
    got = _run(enable_at)
    m = got["m"]
    for node, run in got["runs"].items():
        where = f"{case} on {node}"
        sent = _lines(run, f"SIM: DMX scene sent to the player for cue {m}")
        assert len(sent) == 1, f"{where}: {len(sent)} scene sends, expected 1"
        assert (
            abs(float(sent[0][0]) - sent_at) <= TOL_MS
        ), f"{where}: scene sent at {sent[0][0]}, expected {sent_at}"
        assert not _lines(
            run, f"SIM: DMX cue {m} has no frame data"
        ), f"{where}: the cue was not armed when its scene was due"
        assert not _unsent(run, m), where
        engine_line = f"DMX scene sent to local player for cue {m}"
        logged = _lines(run, engine_line)
        assert len(logged) == 1, f"{where}: {len(logged)} engine send lines"
        assert (
            "(late, at its start)" in logged[0][1]
        ) == late, f"{where}: {logged[0][1]!r}"


def test_an_enable_too_close_to_the_start_sends_nothing_in_this_pass():
    # AC12 d2: 300 ms before the start, inside W: from the next pass.
    got = _run(START_M - 300.0)
    m = got["m"]
    for node, run in got["runs"].items():
        assert not _lines(run, f"SIM: DMX scene sent to the player for cue {m}"), node
        assert not _lines(run, f"DMX scene sent to local player for cue {m}"), node
        assert not _unsent(run, m), node
