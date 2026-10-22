<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# tests/

```
tests/
  conftest.py      shared fixtures + the hook that derives the marker from the directory
  support/         helpers, fixtures, network_map_helpers, reader, ports, paths (DATA_DIR)
  data/            XML fixtures: settings, network_map, mappings, projects/ (media/ is git-ignored)
  unit/            tests with no real socket, subprocess, JACK/ALSA or long sleep
  integration/     tests that use one of those
  contract/        repository and packaging invariants
```

**The directory decides the marker.** `conftest.py` adds `unit`, `integration` or `contract` from the first path segment
under `tests/`; a test file anywhere else (including the root of `tests/`) is a collection error that names the file.
Do not write `@pytest.mark.unit` or `@pytest.mark.integration`. `slow` stays an explicit, additional mark.

## Classification rule

A test is **integration** if it does any of these:

- binds or connects a real socket (NNG, UDP, TCP, an OSCQuery or pyossia device)
- starts a real subprocess or player
- touches JACK or ALSA
- relies on a `sleep` ≥ 0.5 s for correctness

A test is **contract** if it asserts a repository or packaging invariant: the public surface, versions, the lock, the
default mappings, the changelog completeness, or this layout.

Everything else is **unit**, and a unit test that needs one of the integration resources mocks it. Name a test file after
the source module it covers (`test_<module>.py`). Fixtures are read through `tests.support.paths.DATA_DIR`; no other file
spells the path.

## Selection

| What | Command |
|---|---|
| fast loop, no network needed | `pytest tests/unit tests/contract -n auto --dist loadfile` |
| integration (what CI runs) | `pytest tests/integration -m "not slow" --dist loadfile` |
| on a rig | `pytest tests/integration -m slow` |

`--dist loadfile` keeps all tests of a file on one xdist worker: `unit/test_port_handler.py` picks real ports and two of its
tests on different workers collide.

On a host without `libmtcmaster.so.0` the engine does not import. CI installs it; locally, see the libmtc stub used by
feature 009 (`specs/009-release-line-reconciliation/evidence/libmtc-stub.patch`), which is never committed.
