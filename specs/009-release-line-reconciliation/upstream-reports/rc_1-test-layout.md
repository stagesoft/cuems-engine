<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# For the rc_1 maintainer: the test layout 0.1.1 introduces, and how your tests land in it

From cuems-engine feature 009, 2026-10-22. After 009 is merged into `feat/xml-refactor`, `tests/` is no longer flat. Nothing on
`rc_1` changes by this feature; this tells you what to do when `rc_1` merges with it.

## The layout

```
tests/
  conftest.py      fixtures + the marker hook
  support/         helpers.py, fixtures.py, network_map_helpers.py, reader.py, ports.py, paths.py (DATA_DIR)
  data/            XML fixtures (what was dev/test_xml_files/)
  unit/  integration/  contract/
```

## The classification rule

Integration if the test binds or connects a real socket (NNG, UDP, TCP, an OSCQuery or pyossia device), starts a real subprocess
or player, touches JACK or ALSA, or relies on a `sleep` ≥ 0.5 s. Contract if it asserts a repository or packaging invariant.
Everything else is unit and mocks what it would otherwise touch. `slow` stays an additional mark.

## The marker hook

`tests/conftest.py` adds `unit`, `integration` or `contract` from the first path segment under `tests/`. A test file anywhere else is
a **collection error that names the file** (`pytest.UsageError`); it never falls back to `unit`. Delete hand-written
`@pytest.mark.unit` / `@pytest.mark.integration` decorators when you move a file; `pyproject.toml` registers `contract` and no longer
registers `cuems` (the pytest plugin `tests/pytest_cuems_plugin.py` is gone; `engine_cleanup` and `process_cleanup` stay in `conftest.py`).

## How a test written on `rc_1` at the root is placed when it merges

1. `git merge` the line into the branch. A new `tests/test_foo.py` arrives at the root (it is a new file, so no conflict), and
   `tests/test_layout.py::test_no_test_file_sits_at_the_root_of_tests` fails and names it.
2. `git mv tests/test_foo.py tests/<unit|integration|contract>/test_foo.py` by the rule above.
3. Rewrite the imports `from .fixtures import …` / `from .helpers import …` / `from .network_map_helpers import …` to
   `from tests.support.<module> import …`; replace a hand-built path to the fixtures with `from tests.support.paths import DATA_DIR`
   (a test that spells `test_xml_files` or `tests/data` by hand fails `test_layout.py`).
4. A test that edits an existing file that the layout moved merges as a rename: git follows `git mv` when the file is unchanged enough.
   If the test file was edited on `rc_1` after the move, merge with `--no-ff` and resolve against the moved path.

To avoid the work, put new tests in `tests/unit/`, `tests/integration/` or `tests/contract/` on `rc_1` from now on.

Also run the parallel suite with `-n auto --dist loadfile`: `unit/test_port_handler.py` has a latent race between its own tests
on different workers (reproducible at `e994a5e`).
