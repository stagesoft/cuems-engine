# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""The engine reaches cuemsutils through public paths only (FR-008, SC-003).

``cuemsutils.xml`` and ``cuemsutils.config`` are internal machinery
(``__all__ == []``); the node vocabulary and the mutating adoption API are
gone upstream. This scans the shipped package's source text, so it needs no
library import to run. Contract: specs/008-cuems-utils-migration/contracts/
public-surface.md.
"""

import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "src" / "cuemsengine"
IDS_MODULE = PACKAGE / "tools" / "ids.py"

# Import statements only (line start + indentation), so prose naming a path in
# a docstring does not trip the rule. Covers ``from cuemsutils.xml import``,
# ``from cuemsutils.xml.X import``, ``import cuemsutils.xml…`` and
# ``from cuemsutils import xml``.
INTERNAL_IMPORT = re.compile(
    r"^\s*(?:from\s+cuemsutils\.(?:xml|config)\b"
    r"|import\s+cuemsutils\.(?:xml|config)\b"
    r"|from\s+cuemsutils\s+import\s+.*\b(?:xml|config)\b)",
    re.MULTILINE,
)
UUID_IMPORT = re.compile(
    r"^\s*(?:from\s+cuemsutils\.tools\.Uuid\b"
    r"|import\s+cuemsutils\.tools\.Uuid\b"
    r"|from\s+cuemsutils\.tools\s+import\s+.*\bUuid\b)",
    re.MULTILINE,
)
ANY_CUEMSUTILS_IMPORT = re.compile(r"^\s*(?:from|import)\s+cuemsutils\b", re.MULTILINE)

# Referenced anywhere in the source text, docstrings included: these name
# machinery that no longer exists upstream (or never should be reached for).
BANNED_SYMBOLS = (
    "get_nodes_by_adoption",
    "partition_by_adoption",
    "_adopted_uuids_from_network_map",
    "find_hosts",
    "CONTROLLER_NETWORK_FLAG",
    "NodeType.",
)


def _modules():
    return sorted(PACKAGE.rglob("*.py"))


def _offenders(pattern, modules):
    found = []
    for module in modules:
        text = module.read_text()
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            found.append(f"{module.relative_to(PACKAGE.parent)}:{line}")
    return found


def test_the_scan_is_not_vacuous():
    """A rename or a wrong root must not turn every rule silently green."""
    modules = _modules()
    assert modules, f"no modules found under {PACKAGE}"
    assert _offenders(ANY_CUEMSUTILS_IMPORT, modules), (
        f"no cuemsutils import found under {PACKAGE} — the scan is looking in "
        "the wrong place"
    )


def test_no_internal_cuemsutils_import():
    offenders = _offenders(INTERNAL_IMPORT, _modules())
    assert not offenders, (
        "imports from cuemsutils.xml / cuemsutils.config (internal): "
        f"{offenders}. Use CuemsScript.load and ConfigManager instead."
    )


def test_uuid_class_is_imported_only_by_the_ids_module():
    modules = [m for m in _modules() if m != IDS_MODULE]
    offenders = _offenders(UUID_IMPORT, modules)
    assert not offenders, (
        f"cuemsutils.tools.Uuid imported outside tools/ids.py: {offenders}. "
        "Convert ids with cuemsengine.tools.ids.as_id / id_str."
    )


def test_no_reference_to_removed_node_machinery():
    offenders = []
    for symbol in BANNED_SYMBOLS:
        pattern = re.compile(re.escape(symbol))
        offenders += [f"{where} {symbol}" for where in _offenders(pattern, _modules())]
    assert not offenders, f"references to removed node machinery: {offenders}"
