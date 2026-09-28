<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# `cuems-engine` — the migration inventory, re-measured

**Measured 2026-09-25** against `feat/nodelist-modify-dispatch` @ `dbc9e6d`, working tree clean.
Upstream's own figures (2026-09-03, `rc_1` @ `fc8d2bb`) are kept **in brackets** so the drift is
visible rather than silent. Where a bracket is absent the site is new to this pass.

Paths are relative to this repository's root.

---

## 1. Callers that keep resolving and become wrong (007 FR-030a-ii)

This is the class the feature searches for. **Each one gets a test that fails against the
pre-migration value before the fix lands** — constitution II, and upstream T023's requirement.

| # | Site | Reads | After 007 | Failure mode |
|---|---|---|---|---|
| 1 | `src/cuemsengine/core/BaseEngine.py:33` | `CONTROLLER_NETWORK_FLAG = "NodeType.master"` | the vocabulary is `NodeRole.controller` | the constant itself is the defect; both comparisons below derive from it |
| 2 | `src/cuemsengine/core/BaseEngine.py:410` | `node.get("node_type") == CONTROLLER_NETWORK_FLAG` in `_controller_ip_from_map` | `node_type` is absent; `.get` returns `None` | loop falls through → `ValueError("No controller node found in network map")` **on a map that contains one**. Loud, but says the wrong thing |
| 3 | `src/cuemsengine/core/BaseEngine.py:440` | same comparison, in `find_hosts` | as above | `controller` is `False` for every host — **and see F1, this site has a second, independent defect** |
| 4 | `src/cuemsengine/core/BaseEngine.py:443` | `node.get("online") == "True"` | `online` decodes to a real `bool` for `network_map` (007 R1's adapter table) | `True == "True"` is `False` → every host filtered out. **The purest silent case in this repository** |

**`_controller_ip_from_map` unwraps correctly** (`:409`, `node_item.get("node", {})`), so only its
vocabulary is wrong. `find_hosts` does not — F1.

## 2. Deprecated import paths (006's retired surface, removed in the release after `0.1.0rc16`)

| Site | Import | Status |
|---|---|---|
| `src/cuemsengine/core/BaseEngine.py:17` | `from cuemsutils.xml import XmlReaderWriter` | resolves and warns today; **gone** when upstream US10 lands |
| `src/cuemsengine/ControllerEngine.py:15` [`:12`] | `from cuemsutils.xml.Settings import NetworkMap` | same |

Both are also **Q14 violations** in their own right: `cuemsutils.xml` declares `__all__ == []` and is
internal machinery. The replacement surface is `CuemsScript` (show) and
`ConfigManager`/`ConfigBase` (config) — `01-settled-decisions.md` D12/D15.

## 3. The mutating adoption API

`NetworkMap.get_nodes_by_adoption` is deprecated upstream (its docstring says so) because it mutates
its argument in place: it rewrites `online`/`adopted` from `str` to `bool` and therefore survives
exactly one pass over a given dict. The non-mutating replacement is
`NetworkMap.partition_by_adoption`.

**The replacement changes the shape, and that is the migration's one real edit.** Measured against
`cuems-utils@b7db53e`, `src/cuemsutils/xml/settings.py:227-268`:

| | `get_nodes_by_adoption` | `partition_by_adoption` |
|---|---|---|
| Returns | `(list, list)` | `(tuple, tuple)` |
| Element shape | `{"node": {...}}` **wrappers** | **bare node objects** — the wrapper is not carried across |
| Mutates the argument | yes, `online` **and** `adopted` → `bool` | no; reads `adopted` only, never writes back |
| Raises | `ValueError` on no map / no node list | identical |

So every unwrap on the call path inverts: `ControllerEngine.py:289`'s
`(entry.get("node") or {}).get("uuid")` becomes `entry.get("uuid")`. Getting this backwards yields
`None` for every uuid and registers no OSC handlers — silently, which is this feature's whole
subject. Note also that `partition_by_adoption` does **not** normalise `online`; code that relied on
the mutating method's side effect to get a `bool` there must read it itself.

| Site | What it does | Note |
|---|---|---|
| `src/cuemsengine/core/BaseEngine.py:433` | `self.cm.network_map.get_nodes_by_adoption(network_dict)` | inside `find_hosts` — unreachable (F1) |
| `src/cuemsengine/ControllerEngine.py:287` [`:249`] | `NetworkMap.get_nodes_by_adoption(self.cm.network_map)` in `_register_node_osc_handlers` | **new to the six commits.** Unwraps correctly at `:289`. Its docstring (`:272-277`) documents the mutation hazard and works around it by controlling *when* it is called |
| `src/cuemsengine/ControllerEngine.py:938-943` | `_reload_network_map`'s docstring: *"ORDER MATTERS"* | **new.** Encodes the hazard as a calling convention. Migrating to `partition_by_adoption` **retires this constraint entirely** — say so in the spec, because it is a simplification the migration buys rather than a risk it takes |
| `src/cuemsengine/ControllerEngine.py:1418` [`:1152-1168`] | `_adopted_uuids_from_network_map` | an **inline workaround** whose own comment says it exists to avoid the mutating method. It is what `partition_by_adoption` now does properly — **delete it, do not port it** |

`_adopted_uuids_from_network_map` has three callers: `:1489`, `:1553`, `:1738`. It also does its own
string/bool dual read on `adopted` (`:1433-1434`), which degrades **safely** after 007 — the
`isinstance(adopted, str)` branch goes dead and the value is already a `bool`. Contrast site 4
above, which does not. Both shapes in one repository is why this class has to be searched for
rather than inferred.

## 4. Test fixtures written in the retired vocabulary

A green suite is not evidence here. These three lines make it green:

```
tests/test_core_baseengine_controller_ip.py:34   {"node": {"node_type": "NodeType.master", "ip": ip}}
tests/test_core_baseengine_controller_ip.py:38   {"node": {"node_type": "NodeType.slave",  "ip": ip}}
tests/test_core_baseengine_controller_ip.py:101  [{"node": {"node_type": "NodeType.master"}}]
```

Two fixtures must exist after the migration — pre-007 (`node_type`) and post-007 (`node_role`) — and
**the post-007 one must fail against the pre-migration code**. This is upstream T073's discipline,
applied here; `cuems-power-bridge` did exactly this and its
`specs/001-node-role-parser/evidence/pre-migration-parser-failure.txt` is the worked precedent.

## 5. The dependency pin — this repository is now one of the last two that cannot express the gate

| Repository | `pyproject.toml` | `debian/control` | Expresses "refuse a library that moved past me"? |
|---|---|---|---|
| `cuems-common` | — | `>= 0.1.0rc16`, `<< 0.1.1~` | yes |
| `cuems-nodeconf` | `>=0.1.0rc16,<0.1.1` | `>= 0.1.0rc16`, `<< 0.1.1~` | yes |
| `cuems-power-bridge` | `>=0.1.0rc16,<0.1.1` | `>= 0.1.0rc16` | floor bounded in `pyproject`; **control still unbounded** |
| **`cuems-engine`** | **`>=0.1.0rc10`** (`:41`) | **`>= 0.1.0rc4`** (`:18`) | **no — and the two disagree with each other** |
| **`cuems-editor`** | **`>=0.1.0rc10`** (`:27`) | **no `debian/` at all** | **no** |

A `>=` floor says only *"I need at least this"*. The gate's claim is the opposite direction, and only
an upper bound or a `Breaks:` states it. Reconcile the two files **and** bound them (upstream
FR-092, FR-091).

## 6. The duration change (008 D17/D18b)

`Media.duration` is now `cms:CTimecodeType` and its getter returns a `CTimecode` already. Five sites
wrap it again:

```
src/cuemsengine/cues/run_cue.py:176     CTimecode(cue.media.duration).return_in_other_framerate(...)
src/cuemsengine/cues/run_cue.py:430     CTimecode(cue.media.duration).return_in_other_framerate(...)
src/cuemsengine/cues/loop_cue.py:112    CTimecode(cue.media.duration).return_in_other_framerate(...)
src/cuemsengine/cues/loop_cue.py:276    CTimecode(cue.media.duration).return_in_other_framerate(...)
src/cuemsengine/cues/CueHandler.py:166  CTimecode(cue.media.duration).milliseconds_exact if cue.media else 0
```

All five line numbers are **unchanged** from upstream.

**Measured 2026-09-25 rather than assumed**: `CTimecode(CTimecode('00:00:12.500'))` returns an equal
`CTimecode` and does not raise — the wrap is **idempotent**. So these five sites are redundant, not
broken, and none of them is a release blocker. Cleaning them up is a readability change this feature
may take or leave; record which, and do not let "harmless" be inferred from a green suite, because
the suite would be green either way.

## 7. The dead fade handlers (008 dropped `fade_in`/`fade_out` in the `script` 1→2 conversion)

The conversion rewrites `action_type` `fade_in`/`fade_out` → `play`/`stop`, and it is
behaviour-preserving **precisely because** this repository already dispatches both as stubs treated
exactly that way (`ActionHandler.py:524`, `:553` — *"treated as play"*, *"treated as stop"*). After
the conversion nothing emits the old values, so these become unreachable:

```
src/cuemsengine/cues/ActionHandler.py:38-39   [:30]  "fade_in", "fade_out" in SUPPORTED_CUE_ACTIONS
src/cuemsengine/cues/ActionHandler.py:516            _handle_fade_in
src/cuemsengine/cues/ActionHandler.py:542            _handle_fade_out
src/cuemsengine/cues/ActionHandler.py:784-785        their _ACTION_HANDLERS entries
```

**Deleting them is a decision, not housekeeping**: an unconverted document still carries the old
`action_type`, and the library's convert-on-read path is what makes that safe. The spec must state
the ordering it depends on. Note the upstream original recorded the `SUPPORTED_CUE_ACTIONS` members
as one site (`:30`); they are two lines, `:38` and `:39`.

## 8. Script deployment — untouched by this feature, but adjacent to a later one

```
src/cuemsengine/tools/CuemsDeploy.py:329, :649
src/cuemsengine/NodeEngine.py:730, :805
src/cuemsengine/core/BaseEngine.py:505  os.path.join(..., "projects", project_name, "script.xml")
```

`script.xml` is rsynced controller → node. **`BaseEngine.py:505` hardcodes the filename**, while
`cuems-editor` reads it from configuration (`script_file_name`, whose own docstring example is
`cue_script.xml`). That divergence is not this feature's to fix, but it is a trap for
`cuems-utils` feature 012's uuid re-mint, which walks project libraries — a procedure that hardcodes
the name skips a library silently and completely. Record it; do not act on it here.

## 9. Non-shipped fixtures — exempt, and exempt for a stated reason

```
dev/network_map.xml
dev/test_xml_files/network_map.xml
dev/CuemsEngine_old.py
```

All three carry `<node_type>NodeType.master</node_type>`. Upstream's clarification Q1 answered the
counting question: **shipped sources only**, and these three join the enumerated exempt set by name.
The exempt set must say *why* each entry is exempt — "not shipped" is a different reason from "this
code exists to detect the retired spelling", and conflating them is how the next sweep loses the
distinction.
