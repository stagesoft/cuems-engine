# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""The ``stop_project`` ActionCue goes through the library's schema (X-1).

``stop_project`` (869fhjdq5) is the authored end of an unattended show. Its
``action_type`` value lives in the version-2 ``script.xsd`` of cuems-utils, and
the engine cannot load or save a project that holds one unless the installed
library carries it. cuems-utils 0.1.1 must therefore contain the value that
rc17 introduced; until it does, both tests below are STRICT expected failures,
so the day it lands they cannot go unnoticed: they turn into plain passing
tests the same moment, with nothing to remember.

The cue is **targetless**: rc17's authors write ``<action_target />``, and the
library has to accept that shape on load and on save.

Tests that build the ActionCue in code stay ordinary tests
(``test_controller_stop_project.py``).

Upstream report: specs/009-release-line-reconciliation/upstream-reports/cuems-utils-x1-x4.md
"""

from pathlib import Path

import pytest
from cuemsutils.cues import ActionCue, CuemsScript

from tests.support.paths import DATA_DIR

FIXTURE = DATA_DIR / "projects" / "stop_project_v2" / "script.xml"
REPORT = "specs/009-release-line-reconciliation/upstream-reports/cuems-utils-x1-x4.md"


def _library_lacks_stop_project() -> bool:
    """True while the installed cuemsutils refuses the fixture.

    The condition of the xfail below, not a skip: with a library that carries
    the value the tests run for real and have to pass.
    """
    try:
        CuemsScript.load(str(FIXTURE))
    except Exception:
        return True
    return False


needs_cuemsutils_stop_project = pytest.mark.xfail(
    _library_lacks_stop_project(),
    strict=True,
    reason=f"cuems-utils 0.1.1 lacks rc17 stop_project — {REPORT}",
)


@needs_cuemsutils_stop_project
def test_a_targetless_stop_project_script_loads():
    script = CuemsScript.load(str(FIXTURE))

    (cue,) = script.cuelist.contents
    assert isinstance(cue, ActionCue)
    assert cue.action_type == "stop_project"
    assert not cue.action_target


@needs_cuemsutils_stop_project
def test_a_loaded_stop_project_script_saves_through_the_published_write_path(tmp_path):
    script = CuemsScript.load(str(FIXTURE))
    saved = tmp_path / "script.xml"

    script.save(str(saved))

    again = CuemsScript.load(str(saved))
    (cue,) = again.cuelist.contents
    assert cue.action_type == "stop_project"
