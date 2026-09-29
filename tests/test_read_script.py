# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""BaseEngine.read_script across script.xml versions (FR-007).

A version-1 show is converted in memory and its file left alone; a document
newer than the library is refused with the library's own error; a missing
script keeps raising ``FileNotFoundError``.
"""

import hashlib
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from cuemsengine.core.BaseEngine import BaseEngine

PROJECTS = Path(__file__).parent / ".." / "dev" / "test_xml_files" / "projects"


def _engine(library):
    engine = BaseEngine(with_cm=False, with_mtc=False, with_signals=False)
    engine.cm = SimpleNamespace(library_path=str(library))
    return engine


def _library_with(tmp_path, project, source):
    target = tmp_path / "projects" / project
    shutil.copytree(PROJECTS / source, target)
    return tmp_path, target / "script.xml"


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_version_1_script_loads_and_its_file_is_untouched(tmp_path):
    library, script = _library_with(tmp_path, "show", "complex_test")
    before = _digest(script)

    engine = _engine(library)
    engine.read_script("show")

    assert engine.script is not None
    assert _digest(script) == before


def test_a_script_newer_than_the_library_is_refused(tmp_path):
    library, script = _library_with(tmp_path, "show", "complex_test_v2")
    text = script.read_text()
    assert 'doc_version="2"' in text
    script.write_text(text.replace('doc_version="2"', 'doc_version="3"', 1))

    with pytest.raises(Exception, match="newer than this library's current version"):
        _engine(library).read_script("show")


def test_a_missing_script_raises_file_not_found(tmp_path):
    (tmp_path / "projects" / "show").mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        _engine(tmp_path).read_script("show")
