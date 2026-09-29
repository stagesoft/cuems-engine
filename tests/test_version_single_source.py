# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""``cuemsengine.__version__`` is the one version source (FR-019b).

``pyproject.toml`` keeps a literal copy only because Poetry refuses a dynamic
version in package mode, and ``CHANGELOG.md``'s newest entry names the version
it describes. Both must equal the source. ``debian/changelog`` is deliberately
not read: packaging versions are cut on the packaging branch (FR-019a).
"""

import re
import tomllib
from pathlib import Path

from cuemsengine import __version__

ROOT = Path(__file__).resolve().parent.parent
HEADER = re.compile(r"^## v(\S+)", re.MULTILINE)


def test_pyproject_version_is_the_source_version():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    copy = pyproject["tool"]["poetry"]["version"]
    assert copy == __version__, (
        f"pyproject.toml [tool.poetry] version is {copy!r} but "
        f"cuemsengine.__version__ is {__version__!r}: set pyproject.toml to "
        f"{__version__!r}"
    )


def test_changelog_top_entry_is_the_source_version():
    match = HEADER.search((ROOT / "CHANGELOG.md").read_text())
    assert match, "no '## v<version>' header found in CHANGELOG.md"
    top = match.group(1)
    assert top == __version__, (
        f"CHANGELOG.md's newest entry is v{top} but cuemsengine.__version__ is "
        f"{__version__!r}: add a '## v{__version__}' entry on top"
    )
