<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# `cuems-engine` — findings new to the 2026-09-25 pass

Four findings the upstream flow could not have carried: two are live defects independent of this
migration, one is a simplification the migration buys, and one is a scoping change. Each was
**measured**, and the measurement is stated so it can be re-run.

---

## F1 — `find_hosts` is unreachable, and broken for a reason the vocabulary fix does not touch

Upstream lists `BaseEngine.py:440` and `:443` as two FR-030a-ii sites. Both are inside `find_hosts`.
Two things are true of it that upstream does not record.

**It has no caller.** Swept across all seven ecosystem repositories 2026-09-25:

```bash
cd /disk/Projects/StageLab
for r in cuems-engine cuems-editor cuems-frontend cuems-nodeconf \
         cuems-common cuems-power-bridge cuems-utils; do
  grep -rn 'find_hosts' $r --include='*.py' --include='*.ts' --include='*.sh' 2>/dev/null \
    | grep -v '/.git/'
done
```

One hit: `cuems-engine/src/cuemsengine/core/BaseEngine.py:417`, the definition. **A grep inside this
repository alone would not have licensed that claim** — this is a library-consumer ecosystem and
"unused" is only provable across the siblings.

**It reads the wrapper, not the node.** `get_nodes_by_adoption` returns `{"node": {...}}` wrappers
(`cuems-utils/src/cuemsutils/xml/settings.py:221`). `find_hosts` iterates them and calls
`node.get("ip")`, `node.get("uuid")`, `node.get("node_type")`, `node.get("online")` — all four read
the wrapper, which holds one key, `"node"`. So all four are `None`, `hosts` is `[]`,
`any(... for host in [])` is `False`, and the method raises
`AttributeError("No controller found in network map")` **unconditionally, today, before any 007 or
008 consideration**.

`_controller_ip_from_map` twelve lines above gets this right (`:409`,
`node_item.get("node", {})`), which is why the bug is easy to miss on a reading.

**Consequence for the spec**: fixing the two vocabulary comparisons at `:440`/`:443` produces a
method that is still broken and still has no caller. The decision is **fix-and-wire, or delete** —
and it should be taken deliberately, since `_controller_ip_from_map` already serves the one need
`find_hosts` looks like it was written for. Either way the wrapper bug must be named, or the next
reader will treat `:440`/`:443` as closed because the vocabulary is right.

---

## F2 — the six new commits built *around* the deprecated mutating API, not off it

`feat/nodelist-modify-dispatch` (six commits, 2026-09) landed the adopt/un-adopt hop and runtime
cluster liveness. In doing so it added:

- a **second** `get_nodes_by_adoption` call site — `ControllerEngine.py:287`, in
  `_register_node_osc_handlers`;
- a docstring (`:272-277`) warning that the method *"mutates online/adopted from str to bool IN
  PLACE, so it only survives one pass over a given dict"*, with a rule about when it is safe to call;
- a second docstring (`:938-943`) in `_reload_network_map` — *"ORDER MATTERS"* — making that rule a
  calling convention between two methods.

This is careful, correct work against an API upstream had already deprecated. It is also the
strongest argument for basing this feature's branch on `feat/nodelist-modify-dispatch` rather than
`rc_1`: the migration's target is precisely the code these six commits added constraints around.

**What the migration buys, and the spec should claim it**: `partition_by_adoption` does not mutate,
so the one-pass hazard, the calling convention at `:938-943`, and the inline workaround at `:1418`
all **cease to exist**. Three pieces of defensive machinery are deleted rather than ported. That is a
simplification the feature earns, not a risk it takes — state it that way, and delete
`_adopted_uuids_from_network_map` instead of migrating it.

---

## F2a — the base branch is one third of an unmerged three-repository feature

F2 treats `feat/nodelist-modify-dispatch` as this repository's own work. It is not: on **2026-09-04**,
fourteen commits landed across **three** repositories as one coordinated feature, under three different
branch names, and **none of the three is merged anywhere**. Found 2026-09-25.

| Tier | Repository | Branch | Commits | State |
|---|---|---|---|---|
| UI | `cuems-frontend` | — | **none** | **the tier does not exist** |
| middleware | `cuems-editor` | `feat/nodelist-adoption-api` | 5 ahead of `rc1`, 0 behind | that repository's migration base, by the same decision |
| engine | **`cuems-engine`** | **`feat/nodelist-modify-dispatch`** | 6 ahead of `rc_1` | **this feature's base** |
| node daemon | `cuems-nodeconf` | `feat/nodelist-modify-hardening` | 3 ahead, **47 behind**, **not merged** | see below |

The pairings are one-to-one. This repository's `52962d9 expose runtime cluster liveness to the UI` is
answered by the editor's `c2eeb80 relay the engine's liveness view as node_status`; `cf5c4ad refuse
instantly when nodeconf is not running` by its `829c56c nodeconf_available was cached and could tell the
UI a comfortable lie`. And `8e36d13`'s own message — *"land the adopt/un-adopt hop **the editor was
already calling**"* — names the dependency direction.

**The chain is Frontend → (WS :9092) → Editor → (NNG, /tmp/editor.ipc) → Engine → (NNG) → nodeconf.**
Three tiers are built. Measured 2026-09-25,
`grep -rn "nodelist_get\|node_status\|cluster_status\|cluster_warning\|nodeconf_available"
../cuems-frontend/src/` returns **nothing** — this feature has **no UI**, and `cuems-frontend`'s own flow
does not know it exists.

**Two consequences for this feature's scope:**

- **`cluster_status` is a contract, not an internal name.** `ControllerEngine`'s dispatch entry
  (`"cluster_status": self.get_cluster_status`) is called by `../cuems-editor`'s `CuemsWsUser.py:496,
  :501`, which relays it to the UI as `node_status`. Renaming or reshaping it during this migration is a
  cross-repository change. Same for `cluster_warning`'s broadcast payload.
- **The editor's `node_status` distinguishes two liveness facts, and this repository owns the
  distinction.** Its docstring (`../cuems-editor/src/cuemseditor/CuemsWsUser.py:469-472`) says `online`
  is `cuems-nodeconf`'s ~30 s discovery view while `alive` is **this engine's** sub-second ping/pong —
  *"the only signal the GO gate trusts"*. `03-migration-inventory.md` §1's retyping of `online` to `bool`
  touches only the first. Keep them apart.

### ⚠ This repository's `cf5c4ad` interacts badly with an open `cuems-nodeconf` bug

`cuems-nodeconf`'s third of the cluster is not in its published candidate `6c0cca7`. Measured against the
current tree (`../cuems-utils/specs/010-consumer-migration/nodeconf-map-write-divergence.md`), most of it
is superseded: the IPC-reply fix was ported verbatim, the truncated-map hazard is gone **by construction**
(the daemon renders no temp file now; the library's `write_tree` uses `tempfile.mkstemp`), and the
lost-adopt race does not reproduce in 60 concurrent trials.

**One open bug reaches this repository**, and `cf5c4ad` is why it is worse than it was:

`cuems-nodeconf`'s `start()` calls `set_comms()` **before** `run()`, so its NNG responder accepts
adopt/unadopt while `run()` is still installing the map — a window bounded by `get_ips()`'s 10 s
`TimeoutLoop`. An adopt landing in it hits an **empty** `NodeIndex` and gets back a confident, specific,
wrong `{'OK': False, 'error': 'Node <uuid> not found'}`.

`cf5c4ad` replaced a 15 s stall with an instant refusal by checking that **`/tmp/nodeconf.ipc` exists**.
That socket is created by `set_comms()` — *before* the window opens. So during start-up the probe reports
nodeconf **available**, this repository forwards the adopt, and the operator reads "Node not found" for a
node that is present. Before `cf5c4ad` they got a stall.

`cf5c4ad` is correct and should not be reverted — the 15 s stall on a fleet where nodeconf ships disabled
was the worse failure, and it was measured on the rig. But **the readiness signal it trusts is the wrong
one**, and the fix belongs on nodeconf's side (a readiness flag set at the end of `read_network_map`, not
a mutex). Two things for this feature to do and not more: do not deepen the dependency on
socket-existence-as-readiness, and record the interaction so whoever fixes nodeconf knows this caller
exists.

## F3 — two string/bool dual reads, one safe and one not, in the same repository

After 007, `network_map`'s adapter table decodes `adopted` and `online` to real `bool`s. Two sites
read them and they behave differently:

| Site | Code | After 007 |
|---|---|---|
| `ControllerEngine.py:1433-1434` | `if isinstance(adopted, str): adopted = adopted.strip().lower() in (...)` | **safe.** The branch goes dead; the value is already a `bool` and is used as one |
| `BaseEngine.py:443` | `node.get("online") == "True"` | **broken.** `True == "True"` is `False`. Filters out every host |

Both are "the same kind of code" on a skim. One degrades to correct and one degrades to silently
empty. This is the concrete reason FR-030a-ii sites are **searched for** rather than reasoned about
from a pattern — and it belongs in the spec as the justification for the search, not as a footnote.

---

## F4 — the pin gap has narrowed to two repositories, which changes the release-gate argument

When upstream wrote the release-gate contract, `cuems-common` was the only edge expressing the gate.
Measured 2026-09-25, three of the five Python consumers now do:

| Repository | `pyproject.toml` | `debian/control` |
|---|---|---|
| `cuems-common` | — | `>= 0.1.0rc16`, `<< 0.1.1~` |
| `cuems-nodeconf` | `>=0.1.0rc16,<0.1.1` | `>= 0.1.0rc16`, `<< 0.1.1~` |
| `cuems-power-bridge` | `>=0.1.0rc16,<0.1.1` | `>= 0.1.0rc16` — **upper bound missing in control** |
| **`cuems-engine`** | `>=0.1.0rc10` | `>= 0.1.0rc4` |
| **`cuems-editor`** | `>=0.1.0rc10` | no `debian/` |

So the gate is no longer a thing to be argued for — it is a convention three sibling repositories
already follow, and this one is one of the two holdouts. Cite `cuems-nodeconf`'s `debian/control:18-19`
as the model rather than re-deriving the reasoning.

Also worth recording because it will otherwise be mistaken for this repository's problem:
`cuems-power-bridge`'s `debian/control` floor is bounded in `pyproject.toml` but **not** in
`control`. That is the bridge's gap, not this one's; report it, do not fix it from here.
