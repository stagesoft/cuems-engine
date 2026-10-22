# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""The shape of ``tests/`` (contract C2).

Tests live in ``tests/unit``, ``tests/integration`` and ``tests/contract``, and
the directory decides the marker. This module guards the three invariants so a
test dropped at the root, or a path to the fixtures spelled by hand, fails
loudly instead of drifting:

1. No ``test_*.py`` or ``testdev_*.py`` file sits directly in ``tests/``.
2. Every collected item carries exactly one of ``unit`` / ``integration`` /
   ``contract``, matching its directory.
3. The fixtures' directory is spelled once, in ``tests/support/paths.py``.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parents[1]
KINDS = ("unit", "integration", "contract")
# Assembled, so that this file does not spell what invariant 3 forbids.
DATA_SPELLINGS = ("test_xml" + "_files", "tests" + "/data")


def _collected(*extra):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-o",
            "addopts=",
            "-p",
            "no:cacheprovider",
            *extra,
            str(TESTS),
        ],
        capture_output=True,
        text=True,
        cwd=TESTS.parent,
    )
    assert result.returncode in (0, 5), result.stdout[-2000:] + result.stderr[-2000:]
    return [line for line in result.stdout.splitlines() if "::" in line]


def test_no_test_file_sits_at_the_root_of_tests():
    strays = sorted(
        path.name
        for pattern in ("test_*.py", "testdev_*.py")
        for path in TESTS.glob(pattern)
    )
    assert not strays, f"test files at the root of tests/: {strays}"


@pytest.mark.parametrize("kind", KINDS)
def test_each_directory_holds_only_items_of_its_own_marker(kind):
    in_kind = _collected("-m", kind)
    elsewhere = [item for item in in_kind if not item.startswith(f"tests/{kind}/")]
    assert not elsewhere, f"{kind}-marked items outside tests/{kind}/: {elsewhere[:5]}"


def test_every_item_has_exactly_one_kind():
    everything = _collected()
    by_kind = {kind: set(_collected("-m", kind)) for kind in KINDS}
    unmarked = [
        item for item in everything if not any(item in s for s in by_kind.values())
    ]
    doubled = [
        item for item in everything if sum(item in s for s in by_kind.values()) > 1
    ]
    assert everything, "nothing collected"
    assert not unmarked, f"items with none of {KINDS}: {unmarked[:5]}"
    assert not doubled, f"items with more than one of {KINDS}: {doubled[:5]}"


def test_the_fixture_directory_is_spelled_only_in_support_paths():
    allowed = TESTS / "support" / "paths.py"
    offenders = [
        f"{path.relative_to(TESTS)}: {spelling}"
        for path in sorted(TESTS.rglob("*.py"))
        if path != allowed
        for spelling in DATA_SPELLINGS
        if re.search(re.escape(spelling), path.read_text())
    ]
    assert not offenders, f"hand-built fixture paths: {offenders[:8]}"
