# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CueMS Engine is a distributed master-node system for multimedia cue playback (audio/video/DMX lighting) in live performance environments. Written in Python 3.11+, built with Poetry, licensed GPL-3.0.

- **ControllerEngine** — master orchestrator: loads projects, broadcasts MTC timecode, tracks cue status, communicates with UI via WebSocket OSC (port 9190) and with nodes via NNG bus (port 9093)
- **NodeEngine** — local executor: runs cues, manages players (Audio/Video/DMX), connects to controller via NNG

## Build & Install

```bash
poetry install                  # install all dependencies
./scripts/link-dev.sh           # dev mode: symlink installed package → source
```

Some dependencies are Debian system packages (not in pyproject.toml): `python3-systemd`, `python3-pyossia`.

## Running Tests

The project uses a custom Python environment at `/usr/lib/cuems`. Always use:

```bash
/usr/lib/cuems/bin/python3 -m pytest tests/ -v              # all tests
/usr/lib/cuems/bin/python3 -m pytest tests/test_foo.py -v    # single file
/usr/lib/cuems/bin/python3 -m pytest tests/test_foo.py::TestClass::test_method -v  # single test
/usr/lib/cuems/bin/python3 -m pytest tests/ -m "not slow"    # skip slow tests
/usr/lib/cuems/bin/python3 -m pytest tests/ -n 4             # parallel (pytest-xdist)
/usr/lib/cuems/bin/python3 -m pytest tests/ --cov=src/cuemsengine --cov-report=html  # coverage
```

Test markers: `slow`, `integration`, `unit`, `cuems`. Tests have a 40-second watchdog timeout with automatic cleanup.

## Linting & Formatting

```bash
black src/ tests/               # formatter (line-length 88)
isort src/ tests/               # import sorter (black profile)
flake8 src/ tests/              # linter
```

## Architecture

```
UI (browser)
  │ WebSocket OSC (:9190)
  ▼
ControllerEngine (master)
  │ NNG Bus (:9093)          MTC via MIDI
  ▼                          ▼
NodeEngine(s) ──────► Players (subprocess/OSC)
  ├── AudioPlayer (JACK)
  ├── VideoPlayer (Jadeo/OSC)
  └── DmxPlayer (DMX/USB)
```

### Key modules under `src/cuemsengine/`

- **core/** — `BaseEngine` (shared base class with config, MTC, status, OSCQuery), `EngineStatus` (status model)
- **comms/** — `ControllerCommunications` / `NodeCommunications` (async NNG + WebSocket threads), `NodesHub` (NNG bus for inter-node ops)
- **cues/** — `CueHandler` (singleton cue lifecycle), `arm_cue`, `run_cue`, `loop_cue`
- **players/** — `Player` base (subprocess wrapper), `AudioPlayer`, `VideoPlayer`, `DmxPlayer`, `AudioMixer`, `PlayerHandler` (singleton manager)
- **osc/** — `OssiaServer`/`OssiaClient` (OSCQuery), `WebSocketOscHandler`, endpoint definitions
- **scripts/** — CLI entry points: `controller_engine.py`, `node_engine.py`, plus mock players for testing

### Communication protocols

1. **UI → Controller:** WebSocket OSC commands (e.g. `/engine/command/go`)
2. **Controller ↔ Nodes:** NNG bus with serialized `NodeOperation` objects (ADD/REMOVE/UPDATE)
3. **Timecode sync:** MTC Master (Controller) → MIDI → MTC Listener (Nodes)
4. **Player control:** OSC messages routed through the engine stack

### Singletons

`CueHandler` and `PlayerHandler` are singletons — instantiated once per engine process.

## Entry Points

```
controller-engine   → cuemsengine.scripts.controller_engine:main
node-engine         → cuemsengine.scripts.node_engine:main
mock-audioplayer    → cuemsengine.scripts.mock_audioplayer:main
mock-videocomposer  → cuemsengine.scripts.mock_videocomposer:main
mock-dmxplayer      → cuemsengine.scripts.mock_dmxplayer:main
mock-jack-volume    → cuemsengine.scripts.mock_jack_volume:main
```

## Critical Rules

- **Never auto-stop a running project.** No command (unload, load, reset, etc.) should implicitly stop playback as a side effect. If an operation requires the project to not be running, it must reject with an error. The user must explicitly stop playback first. This is safety-critical in live performance.

## Configuration

- Node config and network map: `~/.cuems/` or `/etc/cuems/` (loaded by `ConfigManager` from `cuemsutils`)
- Schemas: `/etc/cuems/`
- Systemd services: `cuems-node-engine.service`, `cuems-engine.service` (Type=simple, Restart=always)
