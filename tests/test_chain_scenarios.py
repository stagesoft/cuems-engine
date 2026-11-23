# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""AC2 of plan 2026-11-18-autocontinue-cumulative-waits (1amfwm7jnqf): one test
per scenario of the executable model, on one subprocess per simulated node.

The fixture `tests/fixtures/chain_scenarios.json` is the model's own data,
exported from cuems-RELATIONS `baselines/autocontinue-cumulative/model/` at
commit 41d257f (rev 9.1; run_all.py since exports the model's constants too,
which the harness reads) with `python3 -I run_all.py --json`; it is never edited
by hand. When the model changes, export it again (Constraints, "The model
leads").

Each scenario runs through `tests/chain_sim/` (driver: the virtual MTC, the bus,
the relay; node: one engine per process). What is compared comes from the
node journals, in the lines of the plan's Design §6:

- `Chain pass <n> (<mode>, engine <v>) from <id>, anchor <ms> ms: <id> +<off>…`
  gives the anchors and, with each cue's prewait, every cue's start;
- `Cue <id> revealed at mtc <ms> ms (start <ms> ms)` a start with output;
- `Cue <id> passed silent at mtc <ms> ms` a start without (snapped to the start
  the Chain pass lines give; a late thread logs later than its start);
- `<id>: DMX scene already sent; it fires at <ms> ms` a DMX output anyway;
- `Action <stop|pause|fade_out> on <id>: applied` a stop (counted when the target
  was on stage, as the model counts it).

A cue is read on the first node that runs it (its owner; `n1` for a cue every
node runs), as the model's `evaluate` does. `rule` and `info` rows are compared
with their own expectations; `defect` rows (today's behaviour switched on in the
model) must give the RULE's outcome: the twin scenario's (AC2's map), cut at the
first event the defect row does not have. The readings the plan does not take
are skipped by name.

Step 2 may have to adapt the fake-player patch points of `chain_sim/node.py` as
the engine changes. Never run on casas (house rule A12).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "chain_scenarios.json"
SCENARIOS = json.loads(FIXTURE.read_text(encoding="utf-8"))
BY_ID = {sc["id"]: sc for sc in SCENARIOS}

#: AC2: a defect row must give its twin's (the rule's) outcome.
TWINS = {
    "S12": "S11",
    "S39": "S38",
    "S43": "S42",
    "S46": "S45",
    "S69": "S68",
    "S80": "S79",
    "S88": "S87",
    "S97": "S96",
    "S101": "S100",
}
#: AC2: readings the plan does not take.
NOT_TAKEN = ("S27", "S67", "S74", "S76", "S86", "S91", "S93")
TOL_S = 0.041  # one 25 fps frame, and the ms of a rounded label


# ---------------------------------------------------------------------------
# expectations
# ---------------------------------------------------------------------------
def _event_s(sc: dict, ev) -> float:
    kind = ev[0]
    ms = {"go": 2, "go_next": 1, "stop_all": 1, "toggle": 3}[kind]
    return (float(ev[ms]) - float(sc["t0_ms"])) / 1000.0


def _entry_s(x) -> float:
    return float(x[1:]) if isinstance(x, str) else float(x)


def expectations(sc: dict) -> dict:
    """What the engine must give for a scenario: the fixture's own values, or for
    a defect row the twin's, cut at the first event the row lacks."""
    keys = ("expect", "anchors", "standby", "stops", "own", "flags", "notes", "agree")
    if sc["kind"] != "defect":
        return {k: sc[k] for k in keys}
    twin = BY_ID[TWINS[sc["id"]]]
    mine, theirs = sc["events"], twin["events"]
    if mine == theirs:
        return {k: twin[k] for k in keys}
    if len(mine) >= len(theirs) or theirs[: len(mine)] != mine:
        raise ValueError(f"{sc['id']}: events are not a prefix of {twin['id']}'s")
    return cut(twin, _event_s(twin, theirs[len(mine)]))


def cut(twin: dict, cut_s: float) -> dict:
    """A scenario's expectations up to (not including) the instant `cut_s`."""

    def table(t):
        if t is None:
            return None
        out = {}
        for name, entries in t.items():
            kept = [x for x in entries if _entry_s(x) < cut_s]
            if kept:
                out[name] = kept
        return out

    anchors = twin["anchors"]
    stops = twin["stops"]
    gos_before = sum(
        1
        for e in twin["events"]
        if e[0] in ("go", "go_next") and _event_s(twin, e) < cut_s
    )
    return {
        "expect": table(twin["expect"]),
        "anchors": None if anchors is None else [a for a in anchors if a < cut_s],
        "standby": None if twin["standby"] is None else twin["standby"][:gos_before],
        "stops": None if stops is None else [s for s in stops if s[1] < cut_s],
        "own": (
            None
            if twin["own"] is None
            else {n: table(t) for n, t in twin["own"].items()}
        ),
        "flags": None,  # the flags at the end belong to the whole run
        "notes": twin["notes"],
        "agree": twin["agree"],
    }


# ---------------------------------------------------------------------------
# journal lines (Design §6)
# ---------------------------------------------------------------------------
NUM = r"(-?\d+(?:\.\d+)?)"
RE_PASS = re.compile(
    rf"Chain pass (\d+) \((\w+), engine ([^)]*)\) from (\S+), anchor {NUM} ms: (.*)$"
)
RE_ENTRY = re.compile(rf"^(\S+) \+{NUM}((?: off| held| remote)*)$")
RE_REVEALED = re.compile(rf"Cue (\S+) revealed at mtc {NUM} ms \(start {NUM} ms\)")
RE_SILENT = re.compile(rf"Cue (\S+) passed silent at mtc {NUM} ms")
RE_DMX_FIRES = re.compile(rf"(\S+): DMX scene already sent; it fires at {NUM} ms")
RE_STOP = re.compile(r"Action (stop|pause|fade_out) on (\S+): applied")

#: model note -> (the node it names, or None for any) and the journal line
NOTE_LINES = (
    (r"DMX scene already sent on (n\d)", r": DMX scene already sent; it fires at"),
    (r"a stop does not recall it", r": DMX scene already sent; it fires at"),
    (r"a newer pass replaces it", r": DMX scene already sent; it fires at"),
    (r"^zero-length loop: (\w+) into (\S+)$", "zero-length loop: {0} into {id1} at"),
    (r"^zero-length loop$", r"zero-length loop: "),
    (
        r"announced \d+ ms after its instant on (n\d)",
        r"Follow: announce .* arrived \d+ ?ms after its instant",
    ),
    (
        r"arrived \d+ ms after it was sent on (n\d)",
        r"cue_enabled for .* arrived \d+ ms after it was sent \(limit 500 ms\): "
        r"applied at once",
    ),
    (
        r"^(\S+) could not be armed on (n\d)",
        "{id0} could not be armed; it does not play in pass",
    ),
    (r"^(\S+) joins \d+ ms late on (n\d)", "Cue {id0} .*firing LATE"),
)
#: ERROR lines a rule row must not have unless one of its notes names them
ERROR_LINES = (
    r"zero-length loop: ",
    r"could not be armed; it does not play in pass",
    r"late read of .*'s flag",
    r"gave up waiting for .* after 5 s",
)


def note_line(note: str, ids: dict):
    """(node or None, compiled journal regex) for a model note."""
    for pat, line in NOTE_LINES:
        m = re.search(pat, note)
        if not m:
            continue
        groups = m.groups()
        node = next((g for g in groups if re.fullmatch(r"n\d", g or "")), None)
        fmt = {f"id{i}": re.escape(ids.get(g, g)) for i, g in enumerate(groups)}
        text = line.format(*groups, **fmt) if "{" in line else line
        return node, re.compile(text)
    raise AssertionError(f"no journal line is mapped for the model note {note!r}")


def _specs(sc: dict) -> dict:
    out = {}
    for spec in sc["script"]:
        out[spec["name"]] = (spec, None)
        for k in spec.get("children") or []:
            out[k["name"]] = (k, spec["name"])
    return out


def observer(sc: dict, name: str) -> str:
    """The node whose view of a cue the model reports (evaluate)."""
    spec, _ = _specs(sc)[name]
    if spec["node"] == "*":
        return sc["nodes"][0]
    owners = spec["node"].split("+")
    return next(n for n in sc["nodes"] if n in owners)


def analyse(sc: dict, runs: dict) -> dict:
    """The model's views (table, anchors, standby, stops, own, flags) from the
    node journals."""
    T0 = float(sc["t0_ms"])
    specs = _specs(sc)
    ids = runs[sc["nodes"][0]]["ids"]
    name_of = {v: k for k, v in ids.items()}

    def secs(ms):
        return round((float(ms) - T0) / 1000.0, 3)

    per_node = {}
    for n, run in runs.items():
        anchors, starts, events = [], {}, []
        for mtc, level, msg in run["journal"]:
            m = RE_PASS.search(msg)
            if m:
                anchor = float(m.group(5))
                anchors.append(anchor)
                for part in m.group(6).split(", "):
                    e = RE_ENTRY.match(part.strip())
                    if not e or e.group(1) not in name_of:
                        continue
                    nm = name_of[e.group(1)]
                    spec, _ = specs[nm]
                    st = anchor + float(e.group(2)) + spec["pre"]
                    starts.setdefault(nm, []).append(st)
                    for kid in spec.get("children") or []:
                        starts.setdefault(kid["name"], []).append(st)
                continue
            m = RE_REVEALED.search(msg)
            if m and m.group(1) in name_of:
                events.append((name_of[m.group(1)], float(m.group(3)), True, mtc))
                continue
            m = RE_SILENT.search(msg)
            if m and m.group(1) in name_of:
                nm, at = name_of[m.group(1)], float(m.group(2))
                cands = [s for s in starts.get(nm, []) if s <= at + 1.0]
                st = max(cands) if cands else round(at / 40.0) * 40.0
                events.append((nm, st, False, mtc))
                continue
            m = RE_DMX_FIRES.search(msg)
            if m and m.group(1) in name_of:
                events.append((name_of[m.group(1)], float(m.group(2)), True, mtc))
        # a DMX scene that fires anyway replaces the silent pass at that start
        fired = {(nm, st) for nm, st, out, _ in events if out}
        events = [
            e
            for e in events
            if e[2] or not any(e[0] == f[0] and abs(e[1] - f[1]) < 1.0 for f in fired)
        ]
        seen, uniq = set(), []
        for e in events:
            key = (e[0], round(e[1]), e[2])
            if key not in seen:
                seen.add(key)
                uniq.append(e)
        per_node[n] = {"anchors": anchors, "events": uniq}

    order = [nm for nm in specs]
    table = {}
    for nm in order:
        obs = per_node[observer(sc, nm)]["events"]
        mine = sorted((st, out) for x, st, out, _ in obs if x == nm)
        if mine:
            table[nm] = [secs(st) if out else f"~{secs(st):g}" for st, out in mine]

    own = {}
    for n in runs:
        o = {}
        for nm, st, out, _ in sorted(per_node[n]["events"], key=lambda e: e[1]):
            if out:
                o.setdefault(nm, []).append(secs(st))
        own[n] = o

    stops = set()
    for n, run in runs.items():
        evs = per_node[n]["events"]
        for mtc, level, msg in run["journal"]:
            m = RE_STOP.search(msg)
            if not m or m.group(2) not in name_of:
                continue
            target = name_of[m.group(2)]
            acts = [
                st
                for nm, st, out, _ in evs
                if out
                and specs[nm][0]["kind"] == "action"
                and specs[nm][0].get("target") == target
                and st <= mtc + 1.0
            ]
            if not acts:
                continue
            instant = max(acts)
            body = specs[target][0]["body"]
            owner_evs = per_node[observer(sc, target)]["events"]
            on_stage = any(
                nm == target and out and st <= instant < st + body
                for nm, st, out, _ in owner_evs
            )
            if on_stage:
                stops.add((target, secs(instant)))

    return {
        "table": table,
        "anchors": {n: [secs(a) for a in per_node[n]["anchors"]] for n in runs},
        "standby": {n: run["standby"] for n, run in runs.items()},
        "stops": sorted(stops, key=lambda r: (r[1], r[0])),
        "own": own,
        "flags": {n: run["flags"] for n, run in runs.items()},
        "ids": ids,
    }


# ---------------------------------------------------------------------------
# comparison
# ---------------------------------------------------------------------------
def same_entries(got: list, want: list) -> bool:
    if len(got) != len(want):
        return False
    for g, w in zip(got, want):
        if isinstance(g, str) != isinstance(w, str):
            return False
        if abs(_entry_s(g) - _entry_s(w)) > TOL_S:
            return False
    return True


def same_table(got: dict, want: dict) -> bool:
    return set(got) == set(want) and all(same_entries(got[k], want[k]) for k in want)


def same_times(got: list, want: list) -> bool:
    return len(got) == len(want) and all(
        abs(float(g) - float(w)) <= TOL_S for g, w in zip(got, want)
    )


def problems(sc: dict, want: dict, seen: dict, runs: dict) -> list:
    out = []
    first = sc["nodes"][0]
    if not same_table(seen["table"], want["expect"]):
        out.append(f"starts {seen['table']}, expected {want['expect']}")
    if want["anchors"] is not None and not same_times(
        seen["anchors"][first], want["anchors"]
    ):
        out.append(f"anchors {seen['anchors'][first]}, expected {want['anchors']}")
    if want["standby"] is not None and seen["standby"][first] != want["standby"]:
        out.append(f"standby {seen['standby'][first]}, expected {want['standby']}")
    if want["stops"] is not None:
        exp = sorted((c, float(t)) for c, t in want["stops"])
        got = sorted(seen["stops"])
        if len(exp) != len(got) or any(
            a[0] != b[0] or abs(a[1] - b[1]) > TOL_S for a, b in zip(got, exp)
        ):
            out.append(f"stops {got}, expected {exp}")
    for n, t in (want["own"] or {}).items():
        if t is not None and not same_table(seen["own"].get(n, {}), t):
            out.append(f"{n} outputs {seen['own'].get(n)}, expected {t}")
    for n, flags in (want["flags"] or {}).items():
        for k, v in flags.items():
            if seen["flags"][n].get(k) != v:
                out.append(f"{k} ends {seen['flags'][n].get(k)} on {n}, expected {v}")
    if want["agree"]:
        for n in sc["nodes"][1:]:
            if not same_times(
                sorted(seen["anchors"][n]), sorted(seen["anchors"][first])
            ):
                out.append(f"pass anchors differ: {n} {seen['anchors'][n]}")
            if want["agree"] is True and seen["flags"][n] != seen["flags"][first]:
                out.append(f"flags differ at the end on {n}")
            if want["agree"] is True and seen["standby"][n] != seen["standby"][first]:
                out.append(f"standby differs on {n}: {seen['standby'][n]}")
    named = []
    for note in want["notes"]:
        node, rx = note_line(note, seen["ids"])
        named.append(rx)
        nodes = [node] if node else list(runs)
        if not any(rx.search(msg) for n in nodes for _, _, msg in runs[n]["journal"]):
            out.append(f"no journal line for the note {note!r} ({rx.pattern})")
    if sc["kind"] == "rule":
        for n, run in runs.items():
            for _, level, msg in run["journal"]:
                if level != "ERROR":
                    continue
                if any(re.search(p, msg) for p in ERROR_LINES) and not any(
                    rx.search(msg) for rx in named
                ):
                    out.append(f"unexpected ERROR on {n}: {msg}")
    for n, run in runs.items():
        for _, level, msg in run["journal"]:
            if msg.startswith("SIM: Traceback") or msg.startswith("SIM: hook raised"):
                out.append(f"{n}: {msg}")
    return out


# ---------------------------------------------------------------------------
# tests without subprocesses
# ---------------------------------------------------------------------------
def test_the_fixture_is_the_models_101_scenarios():
    assert [sc["id"] for sc in SCENARIOS] == [
        f"S{i:02d}" if i < 100 else f"S{i}" for i in range(1, 102)
    ]
    kinds = {}
    for sc in SCENARIOS:
        kinds[sc["kind"]] = kinds.get(sc["kind"], 0) + 1
    assert kinds == {"rule": 78, "info": 14, "defect": 9}
    assert {sc["model_verdict"] for sc in SCENARIOS if sc["kind"] == "rule"} == {"PASS"}
    assert all(sc["t0_ms"] == 100_000.0 for sc in SCENARIOS)


def test_every_defect_row_has_its_twin_and_a_readable_rule_outcome():
    defects = sorted(sc["id"] for sc in SCENARIOS if sc["kind"] == "defect")
    assert defects == sorted(TWINS)
    for d, twin in TWINS.items():
        assert BY_ID[twin]["kind"] != "defect"
        assert BY_ID[d]["script"] == BY_ID[twin]["script"], d
        expectations(BY_ID[d])  # raises when the events are not a prefix


def test_the_readings_not_taken_are_info_rows():
    for sid in NOT_TAKEN:
        assert BY_ID[sid]["kind"] == "info", sid


def test_a_defect_row_with_fewer_events_takes_the_twins_outcome_up_to_the_cut():
    # S88 is S87 without its GO at +20 s
    want = expectations(BY_ID["S88"])
    assert want["expect"] == {"A": [0], "L": [8], "Kb": [8]}
    assert want["anchors"] == [0]
    assert want["flags"] is None


def test_a_defect_row_with_the_same_events_takes_the_twins_outcome():
    assert expectations(BY_ID["S12"])["expect"] == BY_ID["S11"]["expect"]
    assert expectations(BY_ID["S12"])["standby"] == ["C", "D"]
    assert expectations(BY_ID["S101"])["notes"] == BY_ID["S100"]["notes"]


def test_cut_keeps_silent_entries_by_their_instant():
    twin = {
        "expect": {"A": [0, 20], "B": ["~5", "~25"]},
        "anchors": [0, 20],
        "standby": ["B", "C"],
        "stops": [["A", 5], ["A", 25]],
        "own": {"n1": {"A": [0, 20]}},
        "flags": {"n1": {"A": True}},
        "notes": [],
        "agree": True,
        "events": [["go", "A", 100000.0], ["go", "A", 120000.0]],
        "t0_ms": 100000.0,
    }
    got = cut(twin, 20.0)
    assert got["expect"] == {"A": [0], "B": ["~5"]}
    assert got["anchors"] == [0] and got["standby"] == ["B"]
    assert got["stops"] == [["A", 5]] and got["own"] == {"n1": {"A": [0]}}


def test_every_note_the_harness_must_find_is_mapped_to_a_journal_line():
    ids = {"A": "id-a", "V": "id-v", "B": "id-b"}
    for sc in SCENARIOS:
        if sc["id"] in NOT_TAKEN:
            continue
        for note in expectations(sc)["notes"]:
            note_line(note, ids)  # raises when unmapped


def test_the_journal_parser_reads_the_design_lines():
    sc = {
        "t0_ms": 100000.0,
        "nodes": ["n1"],
        "script": [
            {"name": "A", "pre": 0.0, "node": "n1", "kind": "audio", "body": 4000.0},
            {"name": "B", "pre": 5000.0, "node": "n1", "kind": "audio", "body": 4000.0},
        ],
    }
    runs = {
        "n1": {
            "ids": {"A": "ida", "B": "idb"},
            "standby": [None],
            "flags": {"A": True, "B": False},
            "journal": [
                (
                    100000.0,
                    "INFO",
                    "Chain pass 1 (sequential, engine 0.1.0rc6-9) from ida, "
                    "anchor 100000 ms: ida +0, idb +0 off",
                ),
                (
                    100000.0,
                    "INFO",
                    "Cue ida revealed at mtc 100040 ms (start 100000 ms)",
                ),
                (105020.0, "INFO", "Cue idb passed silent at mtc 105020 ms"),
            ],
        }
    }
    seen = analyse(sc, runs)
    assert seen["table"] == {"A": [0.0], "B": ["~5"]}
    assert seen["anchors"] == {"n1": [0.0]}
    assert seen["own"] == {"n1": {"A": [0.0]}}


# ---------------------------------------------------------------------------
# one test per scenario, on one subprocess per node
# ---------------------------------------------------------------------------
_API_MISSING: list = []  # the first "engine lacks the API" error, for the rest


@pytest.mark.parametrize("sid", [sc["id"] for sc in SCENARIOS])
def test_scenario(sid):
    if sid in NOT_TAKEN:
        pytest.skip("reading not taken (plan AC2)")
    sc = BY_ID[sid]
    if _API_MISSING:
        pytest.fail(_API_MISSING[0], pytrace=False)
    from tests.chain_sim.driver import SimError, run_scenario

    want = expectations(sc)
    try:
        runs = run_scenario(sc)
    except SimError as e:
        if "lacks the API" in str(e):
            _API_MISSING.append(f"{sid}: {e}")
        pytest.fail(f"{sid}: the harness could not run it: {e}", pytrace=False)
    seen = analyse(sc, runs)
    found = problems(sc, want, seen, runs)
    stuck = {n: r["stuck"] for n, r in runs.items() if r["stuck"]}
    assert not found, (
        f"{sid} ({sc['kind']}, {sc['name']}):\n  "
        + "\n  ".join(found)
        + (f"\n  threads quiet but not on the clock: {stuck}" if stuck else "")
    )
