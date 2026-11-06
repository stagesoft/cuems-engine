# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""The follow lead F and the GO lead L (869feynrj §4.2 step 2, §4.5b-d, D8, D11).

Pure functions and constants, importable by both engines (the controller
process has no CueHandler). cuems-RELATIONS
Plans/2026-11-03-audio-first-pass-head-869feynrj.md; the executable spec is
baselines/869feynrj-model/timeline_model.py (Plan.lead, Plan.F_for, ceil_frame).

- F, the follow-commit lead, per node: max(FOLLOW_LEAD_MS, the node's
  out_latency_ms + 2 polls + 5 + margin), due from the ROUNDED start label the
  player gets (review 4 M2).
- L, the GO lead, per operator GO, from the cluster: max(GO_LEAD_FLOOR_MS,
  max over the required nodes of out_latency_ms + delta + margin), capped at
  GO_LEAD_MAX_MS. A node with no out_latency_ms does not raise L.
- The led anchor is ceiled to the next MTC frame (D11), so every start stays
  on the 40 ms grid and the lead is >= L.
"""

import math

# CUEMS MTC is always 25 fps (the engine never sets another rate).
FRAME_MS = 40.0

FOLLOW_LEAD_MS = 120.0
FOLLOW_POLL_MS = 20.0  # CueHandler._wait_mtc's poll

GO_LEAD_FLOOR_MS = 50.0
GO_LEAD_MAX_MS = 250.0
# PROVISIONAL: step 3 measures delta (GO press -> follow commit, preloaded
# cues, with the post-GO lookahead running) and the floor; Ion fixes the
# numbers. No settings key, no XSD (plan §4.5c).
GO_LEAD_DELTA_MS = 15.0
GO_LEAD_MARGIN_MS = 5.0

# An rc6-7 node engine (no lead_ms) accepts the controller's anchor only while
# local - anchor >= -200 ms: from L ~ 160 ms, when its MTC reads a frame
# behind, it rejects a led anchor and starts on its own MTC, L early (S0-14).
OLD_NODE_ACCEPT_MS = 160.0


def ceil_frame(ms: float, frame_ms: float = FRAME_MS) -> float:
    """The first MTC frame at or after ``ms`` (D11)."""
    return math.ceil(ms / frame_ms - 1e-9) * frame_ms


def follow_lead_ms(out_latency_ms: float | None) -> float:
    """F for this node (§4.2 step 2, review 4 M2): 120 ms on usual rigs
    (32 ms latency + 10.7 ms period -> 42.7 + 40 + 5 + 5 = 92.7 < 120)."""
    if not isinstance(out_latency_ms, (int, float)) or isinstance(out_latency_ms, bool):
        return FOLLOW_LEAD_MS
    return max(
        FOLLOW_LEAD_MS,
        float(out_latency_ms) + 2 * FOLLOW_POLL_MS + 5.0 + GO_LEAD_MARGIN_MS,
    )


def go_lead_ms(latencies: dict) -> tuple[float, str | None, float]:
    """L for one operator GO (§4.5d).

    ``latencies``: {node: out_latency_ms or None} over the required nodes.
    Returns (L, the node that asked for more than the cap or None, the
    uncapped value). A node with None does not raise L.
    """
    need = GO_LEAD_FLOOR_MS
    who = None
    for node, lat in latencies.items():
        if not isinstance(lat, (int, float)) or isinstance(lat, bool):
            continue
        want = float(lat) + GO_LEAD_DELTA_MS + GO_LEAD_MARGIN_MS
        if want > need:
            need, who = want, node
    if need > GO_LEAD_MAX_MS:
        return GO_LEAD_MAX_MS, who, need
    return need, None, need


def lead_source(latencies: dict) -> tuple | None:
    """(node, out_latency_ms) of the node whose latency sets L, or None when
    L is the floor (step 3's GO lead line)."""
    best = None
    for node, lat in latencies.items():
        if not isinstance(lat, (int, float)) or isinstance(lat, bool):
            continue
        if float(lat) + GO_LEAD_DELTA_MS + GO_LEAD_MARGIN_MS <= GO_LEAD_FLOOR_MS:
            continue
        if best is None or lat > best[1]:
            best = (node, float(lat))
    return best
