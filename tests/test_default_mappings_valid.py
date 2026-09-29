# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""The XML fixtures the engine loads stay loadable by the library.

Each document is read through the public loader the engine itself uses, which
validates it: ``ConfigManager`` for configuration (settings, node map,
mappings, project documents) and ``CuemsScript.load`` for show scripts. A
fixture that stops validating would make ``BaseEngine.load_config()`` exit -1
and break every test that starts an engine.
"""

import shutil
from os import environ
from pathlib import Path

import pytest
from cuemsutils.cues import CuemsScript
from cuemsutils.tools.ConfigManager import ConfigManager

FIXTURE_DIR = Path(__file__).parent.parent / "dev" / "test_xml_files"
PROJECT = "fixture_project"


@pytest.fixture
def config_manager(tmp_path, monkeypatch):
    """A ConfigManager over copies of the fixtures, in the deployed layout.

    ``settings.xml``'s ``library_path`` points at ``tmp_path/library``, where
    ``project_settings.xml``/``project_mappings.xml`` sit as a project's
    ``settings.xml``/``mappings.xml`` (the layout CuemsDeploy ships).
    """
    conf = tmp_path / "conf"
    library = tmp_path / "library"
    project = library / "projects" / PROJECT
    conf.mkdir()
    project.mkdir(parents=True)
    settings = (FIXTURE_DIR / "settings.xml").read_text()
    (conf / "settings.xml").write_text(
        settings.replace("/opt/cuems_library", str(library))
    )
    for name in ("network_map.xml", "default_mappings.xml"):
        shutil.copy(FIXTURE_DIR / name, conf / name)
    shutil.copy(FIXTURE_DIR / "project_settings.xml", project / "settings.xml")
    shutil.copy(FIXTURE_DIR / "project_mappings.xml", project / "mappings.xml")
    monkeypatch.setitem(environ, "CUEMS_CONF_PATH", str(conf))
    return ConfigManager(config_dir=str(conf), load_all=False)


def test_settings_xml_loads(config_manager):
    """Constructing the manager reads and validates settings.xml."""
    assert config_manager.settings["library_path"].endswith("library")


def test_network_map_xml_loads(config_manager):
    config_manager.load_network_map()
    assert config_manager.network_map["node_list"]


def test_default_mappings_xml_loads(config_manager):
    config_manager.load_net_and_node_mappings()
    assert config_manager.mappings


def test_project_settings_xml_loads(config_manager, caplog):
    config_manager.load_project_settings(PROJECT)
    # A missing file is tolerated ("Keeping default settings"); this one exists.
    assert f"Project {PROJECT} settings loaded" in caplog.text


def test_project_mappings_xml_loads(config_manager):
    config_manager.load_net_and_node_mappings()
    config_manager.load_project_mappings(PROJECT)
    assert config_manager.project_mappings is not config_manager.mappings


@pytest.mark.parametrize("project", ["complex_test", "complex_test_v2"])
def test_script_fixture_loads_and_validates(project):
    script = CuemsScript.load(str(FIXTURE_DIR / "projects" / project / "script.xml"))
    assert not script.validate()
