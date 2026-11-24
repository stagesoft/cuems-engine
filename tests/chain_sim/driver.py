# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""The test's side of the AC2 harness: the virtual MTC, the bus, the relay.

`run_scenario(scenario)` starts one `node.py` subprocess per simulated node,
loads the scenario's script on each, then walks the virtual MTC from event to
event and from wake to wake: at each instant it first moves every node's MTC
there, then delivers what is due, in the order the model's `World` takes it.

Delays. The fixture (`run_all.py --json`) carries each scenario's perturbations
and the model's constants (`constants`: `bus_ms`, `relay_ms`, `go_lead_ms`, from
cuems-RELATIONS `baselines/autocontinue-cumulative/model/chain_model.py`); the
values below are only the fallback for a row without them. A GO for anchor
`T` is sent at `T - GO_LEAD_MS` and reaches a node `bus` ms later; a UI toggle
sent at `t` reaches it at `t + bus`, carrying `sent_ms = t`; an operator STOP
reaches every node at `t`; what a node sends (a follow announcement or cancel,
a `stop_project`) reaches the other nodes `RELAY_MS` later (a `stop_project`
becomes a STOP on every node).
"""

from __future__ import annotations

import heapq
import multiprocessing
import os
import time

# chain_model.py (rev 9.1): the fallback when a row has no "constants".
BUS_MS = {"n1": 3.0, "n2": 5.0, "n3": 7.0}
RELAY_MS = 8.0
GO_LEAD_MS = 80.0


def constants(scenario: dict) -> tuple:
    """(bus_ms per node, relay_ms, go_lead_ms) from the fixture row."""
    c = scenario.get("constants") or {}
    return (
        dict(c.get("bus_ms") or BUS_MS),
        float(c.get("relay_ms", RELAY_MS)),
        float(c.get("go_lead_ms", GO_LEAD_MS)),
    )


WALL_TIMEOUT_S = float(os.environ.get("CUEMS_CHAIN_SIM_TIMEOUT", "300"))
REPLY_TIMEOUT_S = 60.0


class SimError(AssertionError):
    """The harness could not run the scenario (a node failed or hung)."""


class _Node:
    def __init__(self, ctx, name: str):
        from .node import node_main

        self.name = name
        self.conn, child = ctx.Pipe()
        self.proc = ctx.Process(
            target=node_main, args=(child,), name=f"chain-sim-{name}", daemon=True
        )
        self.proc.start()
        child.close()
        self.next_wake = None
        self.stuck: list = []

    def ask(self, *msg) -> dict:
        try:
            self.conn.send(msg)
        except (BrokenPipeError, OSError) as e:
            raise SimError(f"node {self.name} is gone ({e})")
        if not self.conn.poll(REPLY_TIMEOUT_S):
            raise SimError(f"node {self.name} did not answer {msg[0]!r}")
        try:
            reply = self.conn.recv()
        except EOFError:
            raise SimError(f"node {self.name} died on {msg[0]!r}")
        if not reply.get("ok"):
            raise SimError(f"node {self.name}, {msg[0]!r}:\n{reply.get('error')}")
        if "next_wake" in reply:
            self.next_wake = reply["next_wake"]
            if reply.get("stuck"):
                self.stuck.append((reply.get("now"), reply["stuck"]))
        return reply

    def close(self):
        try:
            if self.proc.is_alive():
                self.conn.send(("quit",))
                if self.conn.poll(2.0):
                    self.conn.recv()
        except Exception:
            pass
        self.proc.join(timeout=2.0)
        if self.proc.is_alive():
            self.proc.kill()
            self.proc.join(timeout=2.0)


def event_time_ms(ev) -> float:
    """The instant of a fixture event (the controller's send / the press)."""
    kind = ev[0]
    if kind == "go":
        return float(ev[2])
    if kind in ("go_next", "stop_all"):
        return float(ev[1])
    if kind == "toggle":
        return float(ev[3])
    raise ValueError(kind)


def bus_ms(scenario: dict, node: str) -> float:
    p = ((scenario.get("perturb") or {}).get(node) or {}).get("bus_ms")
    return float(p) if p is not None else float(constants(scenario)[0][node])


def run_scenario(scenario: dict) -> dict:
    """Run one fixture scenario; {node: {"journal", "standby", "flags", "ids",
    "stuck"}}."""
    names = list(scenario["nodes"])
    _, relay_ms, go_lead_ms = constants(scenario)
    T0 = float(scenario["t0_ms"])
    until = T0 + float(scenario["until_s"]) * 1000.0
    times = [event_time_ms(e) for e in scenario["events"]]
    start = min([T0 - go_lead_ms] + times) - 50.0

    queue: list = []  # (t, order key, seq, node, kind, payload)
    seq = [0]

    def put(t, key, node, kind, payload):
        heapq.heappush(queue, (t, key, seq[0], node, kind, payload))
        seq[0] += 1

    cue_ids = {}
    from .node import cue_id

    for spec in scenario["script"]:
        cue_ids[spec["name"]] = cue_id(spec["name"])
        for k in spec.get("children") or []:
            cue_ids[k["name"]] = cue_id(k["name"])

    run_seq = 0
    for ev in scenario["events"]:
        kind = ev[0]
        if kind in ("go", "go_next"):
            run_seq += 1
            T = float(ev[2] if kind == "go" else ev[1])
            sent = T - go_lead_ms
            go = {"go_mtc_ms": T, "lead_ms": go_lead_ms, "run_seq": run_seq}
            for n in names:
                if kind == "go":
                    put(
                        sent + bus_ms(scenario, n),
                        (sent, 0),
                        n,
                        "go_entry",
                        {"entry": ev[1], "go": go},
                    )
                else:
                    put(sent + bus_ms(scenario, n), (sent, 0), n, "go", go)
        elif kind == "toggle":
            _, name, value, t = ev
            text = f"{cue_ids[name]} {1 if value else 0}"
            for n in names:
                put(
                    float(t) + bus_ms(scenario, n),
                    (float(t), 0),
                    n,
                    "cue_enabled",
                    (text, float(t)),
                )
        elif kind == "stop_all":
            for n in names:
                put(float(ev[1]), (float(ev[1]), -3), n, "stop", None)

    ctx = multiprocessing.get_context("spawn")
    nodes = {}
    wall0 = time.monotonic()
    stopped_by_project = [False]
    try:
        for n in names:
            nodes[n] = _Node(ctx, n)
        for n in names:
            nodes[n].ask("init", {"node": n, "scenario": scenario, "start_ms": start})

        def handle(origin: str, reply: dict, now: float):
            for kind, payload in reply.get("outbox") or []:
                if kind == "follow":
                    for n in names:
                        if n != origin:
                            put(now + relay_ms, (now, 1), n, "follow", payload)
                elif kind == "stop_project" and not stopped_by_project[0]:
                    stopped_by_project[0] = True  # first valid message wins
                    for n in names:
                        put(now + relay_ms, (now, 1), n, "stop", None)

        now = start
        while True:
            if time.monotonic() - wall0 > WALL_TIMEOUT_S:
                raise SimError(
                    f"{scenario['id']}: wall timeout {WALL_TIMEOUT_S:.0f} s at "
                    f"virtual {now - T0:+.0f} ms"
                )
            t_ev = queue[0][0] if queue else float("inf")
            wakes = [x.next_wake for x in nodes.values() if x.next_wake is not None]
            t_wake = min(wakes) if wakes else float("inf")
            t = min(t_ev, t_wake)
            if t > until or t == float("inf"):
                break
            if t > now:
                now = t
                for n in names:
                    handle(n, nodes[n].ask("advance", now), now)
            elif t_ev > now:
                # a wake at or before now that the node did not take: move on
                now = now + 1.0
                for n in names:
                    handle(n, nodes[n].ask("advance", now), now)
                continue
            while queue and queue[0][0] <= now:
                _, _, _, n, kind, payload = heapq.heappop(queue)
                if kind == "go_entry":
                    msg = ("bus", "go_entry", payload, None)
                elif kind == "go":
                    msg = ("bus", "go", payload, None)
                elif kind == "cue_enabled":
                    msg = ("bus", "cue_enabled", payload[0], payload[1])
                elif kind == "follow":
                    msg = ("bus", "follow", payload, None)
                else:
                    msg = ("bus", kind, payload, None)
                handle(n, nodes[n].ask(*msg), now)

        out = {}
        for n in names:
            res = nodes[n].ask("finish")
            res["stuck"] = nodes[n].stuck
            out[n] = res
        return out
    finally:
        for x in nodes.values():
            x.close()
