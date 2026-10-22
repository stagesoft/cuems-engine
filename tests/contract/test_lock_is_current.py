# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""``poetry.lock`` describes ``pyproject.toml`` (cuems-utils feature 016, FR-022).

The coordinated minor bump moved the ``cuemsutils`` bound to ``>=0.1.1,<0.1.2``.
No index serves ``cuemsutils 0.1.1`` until it is published, so the lock cannot be
regenerated yet, and a lock that names a local file source must never be committed.
This test is therefore a strict expected failure. On the day the lock is regenerated
at publication it passes, ``strict`` turns that into a failure, and the marker has
to go. That way the obligation cannot be forgotten, and the stale lock cannot stay
hidden behind a CI cache keyed on ``poetry.lock`` (planning document §4.2 of
``coordinated-release-inputs-pyossia-and-engine-ci.md``).
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.xfail(
    strict=True,
    reason="poetry.lock relocks at publication, once cuemsutils 0.1.1 is resolvable "
    "(cuems-utils 016, FR-022)",
    # Only the lock assertion is expected to fail; anything else (no poetry) is real.
    raises=AssertionError,
)
def test_poetry_lock_is_current():
    beside = Path(sys.executable).with_name("poetry")
    poetry = shutil.which("poetry") or (str(beside) if beside.exists() else None)
    if poetry is None:
        # Not a skip: a skipped strict xfail would hide the obligation.
        pytest.fail("poetry is not on PATH; this check needs it (CI pins poetry 2.4.1)")
    result = subprocess.run(
        [poetry, "check", "--lock"], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
