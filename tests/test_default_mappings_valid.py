# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

from pathlib import Path

import pytest

from cuemsutils.xml import XmlReaderWriter

# XML fixtures under dev/test_xml_files/ that BaseEngine and related
# code paths load when engine tests set CUEMS_CONF_PATH to this dir.
# Each must stay schema-valid or BaseEngine.load_config() exits -1 and
# every test that touches engine startup breaks.
FIXTURE_DIR = Path(__file__).parent.parent / "dev" / "test_xml_files"

FIXTURES = [
    ("settings.xml", "settings"),
    ("network_map.xml", "network_map"),
    ("project_settings.xml", "project_settings"),
    ("project_mappings.xml", "project_mappings"),
    ("default_mappings.xml", "project_mappings"),
]


@pytest.mark.parametrize("xml_name,schema_name", FIXTURES)
def test_engine_xml_fixture_validates_against_schema(xml_name, schema_name):
    reader = XmlReaderWriter(
        schema_name=schema_name,
        xmlfile=str(FIXTURE_DIR / xml_name),
    )
    reader.validate()
