<!--
***
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
***
-->

# cuems-engine

**Current release: v0.1.0rc2** — see [CHANGELOG.md](./CHANGELOG.md).

**Timecode-driven audio, video, and DMX cueing engine with OSCQuery control.**

[![PyPI - Version](https://img.shields.io/pypi/v/cuemsengine.svg)](https://pypi.org/project/cuemsengine)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/cuemsengine.svg)](https://pypi.org/project/cuemsengine)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Deploy MkDocs site](https://github.com/stagesoft/cuems-engine/actions/workflows/gh-pages.yml/badge.svg)](https://github.com/stagesoft/cuems-engine/actions/workflows/gh-pages.yml)
[![Upload Python Package](https://github.com/stagesoft/cuems-engine/actions/workflows/pypi-publish.yml/badge.svg)](https://github.com/stagesoft/cuems-engine/actions/workflows/pypi-publish.yml)

* **Source / issues:** [stagesoft/cuems-engine](https://github.com/stagesoft/cuems-engine) on GitHub
* **API reference (HTML):** [stagesoft.github.io/cuems-engine](https://stagesoft.github.io/cuems-engine/)

`cuems-engine` is the Python runtime at the heart of the **CueMS** (Cue Management System). It synchronises audio, video, and DMX playback across one or more nodes using MIDI Timecode (MTC), exposing a live control surface over OSC and WebSocket.

It is composed of:

* **`cuemsengine`** — a Python package providing the full engine runtime, core primitives, and player orchestration
* **`controller-engine`** — the systemd-managed master service that drives timecode, dispatches cues, and coordinates all nodes
* **`node-engine`** — the systemd-managed per-node service that arms and fires players (audio, video, DMX) on receiving cue commands

---

## Overview

The engine models show control as a deterministic, timecode-synchronised pipeline:

```text
MTC Timecode → Controller Engine → Cue Dispatch → Node Engine → Player Lifecycle → Output
                                                                                    ├── Audio (JACK)
                                                                                    ├── Video (Gradient)
                                                                                    └── DMX
```

* **MTC Timecode** drives the system clock — all scheduling and playback boundaries are derived from it
* **Controller Engine** owns the cue list, tracks playback state, and coordinates the node fleet
* **Cue Dispatch** selects the next cue, handles pre/post-waits, arming, and go-trigger logic
* **Node Engine** receives commands over NNG, manages subprocess lifecycles, and reports status back
* **Player Lifecycle** wraps audio (via JACK), video (via `gradient-motiond`), and DMX subprocesses
* **Output** delivers the final media signal to the physical hardware

---

## Architecture

### Controller Engine: `ControllerEngine`

`ControllerEngine` is the master process (`scripts/controller_engine.py`). Responsibilities:

* Manage the WebSocket interface for the show editor
* Host the Ossia/OSCQuery device tree for live parameter control
* Run as MTC master — generate and distribute the timecode reference
* Monitor the node fleet via NNG, detect failures, and trigger restarts
* Track cue status and broadcast updates to connected clients

Typical deployment:

```bash
systemctl enable controller-engine
systemctl start controller-engine
```

---

### Node Engine: `NodeEngine`

`NodeEngine` is the per-node process (`scripts/node_engine.py`). Responsibilities:

* Accept cue commands from the controller over NNG
* Manage the deploy workflow — rsync project assets to the node before playback
* Arm and launch audio, video, and DMX players as subprocesses
* Register OSC/OSCQuery endpoints for each active player
* Synchronise playback start to the MTC timecode from the controller

Typical deployment (on each playback node):

```bash
systemctl enable node-engine
systemctl start node-engine
```

---

### Core: `core/`

Shared base layer used by both engines:

* **`BaseEngine`** — abstract engine base; owns the asyncio event loop, `ConfigManager`, OSCQuery client/server lifecycle, MTC listener integration, and the ongoing/next cue pointers
* **`EngineStatus`** — structured data model for engine state
* **`libmtc`** — MIDI Timecode master helper

---

### Communications: `comms/`

NNG-based message transport between controller and nodes:

* **`ControllerCommunications`** — controller-side NNG publisher and WebSocket bridge
* **`NodeCommunications`** — node-side NNG receiver and command dispatcher
* **`AsyncCommsThread`** — asyncio/thread bridge for non-blocking NNG I/O
* **`NodesHub`** — node operation enum and shared data models

---

### Cues: `cues/`

Cue execution layer — the unit of show control:

* **`CueHandler`** — singleton managing the armed-cue registry and video player index
* **`ActionHandler`** — action cue dispatch with a three-phase hook system (`before_dispatch`, `after_dispatch`, `wrap_dispatch`) and NNG status sink
* **`arm_cue`** — cue arming workflow (pre-load, readiness check)
* **`run_cue`** — single-shot cue playback (audio, video, DMX)
* **`loop_cue`** — loop/multiplay cue execution with MTC-boundary polling
* **`helpers`** — timing utilities (`find_timing`, pre/post-wait calculation)

---

### Players: `players/`

Player subprocess management and hardware I/O:

* **`PlayerHandler`** — singleton owning all active player instances; handles layer routing, canvas setup, and OSC communication with subprocesses
* **`AudioMixer`** — JACK-based audio mixing and routing
* **`JackConnectionManager`** — JACK port connection management
* **`AudioPlayer`** — audio client subprocess wrapper
* **`VideoPlayer`** — video client subprocess wrapper (delegates to `gradient-motiond`)
* **`DmxPlayer`** — DMX output subprocess wrapper
* **`GradientClient`** — OSC client for communicating with `gradient-motiond`
* **`Player`** — abstract base player interface

---

### OSC / OSCQuery: `osc/`

Protocol layer for live parameter control and editor communication:

* **`OssiaNodes`** — Ossia device tree node management (parameter registration, type mapping)
* **`OssiaClient`** / **`OssiaServer`** — OSCQuery client/server lifecycle wrappers
* **`WebSocketOscHandler`** — bidirectional WebSocket-to-OSC bridge between the show editor and the engine
* **`helpers`** — OSC value routing and callback injection utilities
* **`endpoints`** — OSCQuery endpoint registration helpers
* **`PyOsc`** — pure-Python OSC fallback for environments without Ossia

---

### Tools: `tools/`

Operational utilities used by both engines:

* **`CuemsDeploy`** — rsync-based project asset deployment to nodes; mandatory-file precheck, progress streaming, startup and inactivity watchdog timeouts
* **`MtcListener`** — MIDI Timecode decoder with 24h rollover detection and quarter-frame interpolation
* **`PortHandler`** — dynamic OSC port allocation
* **`display_conf`** — display and canvas configuration parser
* **`system_ports`** — system MIDI port enumeration

---

## Core Concepts

* **MTC Timecode** — the authoritative temporal reference for all playback scheduling and boundary evaluation
* **Cue** — a discrete show event (audio, video, DMX, or action) with pre/post-wait offsets and arming state
* **Player** — a managed subprocess that owns a single media channel and communicates back via OSC
* **Deploy** — the rsync-based transfer of project assets to a node before playback begins
* **OSCQuery** — the bidirectional device-tree protocol used for live parameter exposure and editor control
* **NNG** — the low-latency message transport between the controller and node engines

---

## Design Goals

* **Deterministic** — identical timecode inputs produce identical playback; all scheduling derives from MTC
* **Modular** — clean separation between timecode, cue logic, player management, and transport layers
* **Real-time capable** — asyncio-based event loop suitable for continuous execution under systemd
* **Observable** — structured logging for all engine events; silent failures are a constitution violation
* **TDD-disciplined** — every production code path is preceded by a failing test; see `tests/`
* **Embeddable** — `cuemsengine` can be imported and driven programmatically outside the CLI entry points

---

## Installation

### PyPI

```bash
pip install cuemsengine
```

### Debian package

The `debian/bookworm` branch carries the packaging metadata. Two packages are produced:

| Package | Description |
|---|---|
| `cuems-engine` | Core engine runtime — controller and node engines |
| `cuems-engine-mock` | Mock player binaries for headless/CI environments without audio or video hardware |

Build from source:

```bash
git clone --branch debian/bookworm https://github.com/stagesoft/cuems-engine.git
cd cuems-engine
dpkg-buildpackage -us -uc
sudo dpkg -i ../cuems-engine_*.deb
```

System-package dependencies installed automatically: `python3-pyossia (>= 2.0.0)`, `python3-systemd (>= 235)`, `cuems-utils`, `cuems-common`.

Binaries are installed to `/usr/lib/cuems/bin/`; systemd service files are provided by the `cuems-common` package.

---

## Development

### Prerequisites

* Python 3.11 (managed via pyenv)
* Poetry
* System packages: `python3-pyossia`, `python3-systemd`, `libjack-jackd2-dev`

### Editable install

```bash
# From the repo root
poetry install

# Or, when the package is already installed system-wide under /usr/lib/cuems,
# replace it with a symlink to this source tree:
./scripts/link-dev.sh
```

Restart the `controller-engine` and `node-engine` services after symlinking to pick up source changes. To restore the installed package, reinstall the Debian package.

### Run tests

```bash
cd src
pytest
```

Useful markers:

```bash
pytest -m unit                  # fast unit tests only
pytest -m "not slow"            # skip long-running tests
pytest -m integration           # integration tests (requires hardware or mocks)
pytest --cov=cuemsengine        # with coverage report
```

### Code style

```bash
black src/
isort src/
flake8 src/
```

---

## Copyright notice

Copyright © 2026 Stagelab Coop SCCL. Authors: Alexander Ramos, Ion Reguera (`ion@stagelab.coop`) and Adrià Masip (`adria@stagelab.coop`).

This work is part of **cuems-engine**. It is free software: you can redistribute it and/or modify it under the terms of the **GNU General Public License** as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but **without any warranty**; without even the implied warranty of **merchantability** or **fitness for a particular purpose**. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program. If not, see [https://www.gnu.org/licenses/](https://www.gnu.org/licenses/).

The SPDX short form of this notice is: `SPDX-License-Identifier: GPL-3.0-or-later`.

---

## License

This project is licensed under the terms of the **GNU General Public License v3.0 or later (GPL-3.0-or-later)**.

You are free to use, modify, and redistribute this software under the conditions set by the license. Any derivative work must also be distributed under the same license terms.

See the [LICENSE](./LICENSE) file for the full license text.

---

### Summary of Terms

* **Permissions**:

  * Use for any purpose
  * Study and modify the source code
  * Redistribute original or modified versions

* **Conditions**:

  * Source code must be made available when distributing
  * Modifications must be licensed under GPL v3 or later
  * Include a copy of the license and preserve notices

* **Limitations**:

  * Provided *without warranty*
  * No liability for damages or misuse

---
