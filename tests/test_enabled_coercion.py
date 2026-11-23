# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""A cue's ``enabled`` read from the XML as a string is a bool (1amfwm7jnqf).

The script reader (cuems-utils ``DmxCueParser``) hands a DmxCue its raw dict,
so a DmxCue saved disabled has ``enabled == 'False'``, and ``bool('False')`` is
True: the setup gate sent the scene of a saved-disabled DmxCue. The engine
must not depend on the reader for this:

- ``chain_pass.as_enabled`` / ``cue_enabled``: a bool passes, a string is read
  strictly (``true/false/1/0/yes/no/on/off``, any case), None is True, anything
  else is True with one WARNING per cue;
- the flag as every node sees it (``common_enabled``, the setup gate's
  ``CueHandler._common``) is False for a DmxCue built from ``'False'``;
- at load (``BaseEngine.read_script``) every cue of the parsed script, of every
  type and in a nested CueList, gets its ``enabled`` as a bool;
- the controller reports bools for the UI (``_collect_cue_enabled``).
"""

import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

sys.modules.setdefault("cuemsutils.tools.Osc_nodes_hub", Mock())

from cuemsutils.cues import (  # noqa: E402
    ActionCue,
    AudioCue,
    CueList,
    DmxCue,
    VideoCue,
)
from cuemsutils.xml.Parsers import CuemsParser  # noqa: E402

from cuemsengine.cues import chain_pass  # noqa: E402
from cuemsengine.cues.CueHandler import CueHandler  # noqa: E402

T = 100_000.0


def _id():
    return str(uuid4())


@pytest.fixture(autouse=True)
def _fresh_warnings():
    chain_pass._ENABLED_WARNED.clear()
    yield
    chain_pass._ENABLED_WARNED.clear()


# ---------------------------------------------------------------------------
# the helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (True, True),
        (False, False),
        (None, True),
        ("True", True),
        ("False", False),
        ("true", True),
        ("false", False),
        (" FALSE ", False),
        ("1", True),
        ("0", False),
        ("yes", True),
        ("no", False),
        ("On", True),
        ("off", False),
        (1, True),
        (0, False),
    ],
)
def test_as_enabled_reads_a_yes_or_a_no(value, expected):
    with patch.object(chain_pass.Logger, "warning") as warn:
        assert chain_pass.as_enabled(value, "c1") is expected
    warn.assert_not_called()


@pytest.mark.parametrize("value", ["maybe", "", 2, 0.5, object()])
def test_as_enabled_anything_else_is_enabled_with_one_warning_per_cue(value):
    with patch.object(chain_pass.Logger, "warning") as warn:
        assert chain_pass.as_enabled(value, "c1") is True
        assert chain_pass.as_enabled(value, "c1") is True
        assert warn.call_count == 1
        assert chain_pass.as_enabled(value, "c2") is True
        assert warn.call_count == 2


def test_cue_enabled_default_when_the_cue_has_none():
    assert chain_pass.cue_enabled(SimpleNamespace()) is True
    assert chain_pass.cue_enabled(SimpleNamespace(), False) is False
    assert chain_pass.cue_enabled(SimpleNamespace(enabled="False")) is False


# ---------------------------------------------------------------------------
# the setup gate / the flag as every node sees it
# ---------------------------------------------------------------------------


def test_dmx_cue_saved_disabled_is_disabled_at_the_setup_gate():
    # what DmxCueParser builds: the raw dict, enabled the XML's text
    cue = DmxCue({"enabled": "False", "id": _id()})
    assert chain_pass.cue_enabled(cue) is False
    assert chain_pass.common_enabled(cue, T) is False
    assert CueHandler._common(cue, T) is False


def test_dmx_cue_saved_enabled_is_enabled_at_the_setup_gate():
    cue = DmxCue({"enabled": "True", "id": _id()})
    assert chain_pass.common_enabled(cue, T) is True
    assert CueHandler._common(cue, T) is True


@pytest.mark.parametrize("flag", [True, False])
def test_a_bool_is_untouched(flag):
    cue = DmxCue({"enabled": flag, "id": _id()})
    assert chain_pass.common_enabled(cue, T) is flag
    assert chain_pass.normalise_enabled(cue) == 0
    assert cue.enabled is flag


def test_dmx_cue_from_the_reader_is_disabled_at_the_setup_gate():
    """The real reader path: CuemsParser dispatches a DmxCue to DmxCueParser."""
    cue = CuemsParser({"DmxCue": {"id": _id(), "enabled": "False"}}).parse()
    assert isinstance(cue, DmxCue)
    assert CueHandler._common(cue, T) is False


def test_a_toggle_record_keeps_the_saved_value_as_a_bool():
    """A UI toggle on a saved-disabled DmxCue keeps ``False`` as its base, not
    the string: a read for an instant before the toggle counts sees it off."""
    cue = DmxCue({"enabled": "False", "id": _id()})
    try:
        chain_pass.ui_toggle(cue, True, T, T, seq=1)
        assert cue._toggle_base is False
        assert chain_pass.common_enabled(cue, T) is False
        assert chain_pass.common_enabled(cue, T + chain_pass.W_MS + 1) is True
    finally:
        chain_pass.forget([cue])


# ---------------------------------------------------------------------------
# at load
# ---------------------------------------------------------------------------


def _parsed_script():
    """A script as the cuems-utils reader builds it from the XML's dict."""
    return CuemsParser(
        {
            "CuemsScript": {
                "id": _id(),
                "name": "enabled",
                "CueList": {
                    "id": _id(),
                    "enabled": "true",
                    "contents": [
                        {"DmxCue": {"id": _id(), "enabled": "False"}},
                        {"DmxCue": {"id": _id(), "enabled": "True"}},
                        {"AudioCue": {"id": _id(), "enabled": "false"}},
                        {"VideoCue": {"id": _id(), "enabled": "true"}},
                        {"ActionCue": {"id": _id(), "enabled": "false"}},
                        {
                            "CueList": {
                                "id": _id(),
                                "enabled": "false",
                                "contents": [
                                    {"DmxCue": {"id": _id(), "enabled": "False"}}
                                ],
                            }
                        },
                    ],
                },
            }
        }
    ).parse()


EXPECTED = [
    (DmxCue, False),
    (DmxCue, True),
    (AudioCue, False),
    (VideoCue, True),
    (ActionCue, False),
    (CueList, False),
]


def _check_bools(cuelist):
    assert cuelist.enabled is True
    got = [(type(c), c.enabled) for c in cuelist.contents]
    assert got == EXPECTED
    for c in cuelist.contents:
        assert isinstance(c.enabled, bool)
    (inner,) = cuelist.contents[-1].contents
    assert isinstance(inner, DmxCue) and inner.enabled is False


def test_normalise_enabled_turns_every_cue_into_a_bool():
    script = _parsed_script()
    chain_pass.normalise_enabled(script.cuelist)
    _check_bools(script.cuelist)
    assert chain_pass.normalise_enabled(script.cuelist) == 0


def test_read_script_normalises_every_cue(tmp_path):
    from cuemsengine.core import BaseEngine as base_module

    project = tmp_path / "projects" / "p"
    project.mkdir(parents=True)
    (project / "script.xml").write_text("<unused/>")
    script = _parsed_script()
    reader = Mock()
    reader.read_to_objects.return_value = script
    fake = SimpleNamespace(cm=SimpleNamespace(library_path=str(tmp_path)))
    with patch.object(base_module, "XmlReaderWriter", return_value=reader):
        base_module.BaseEngine.read_script(fake, "p")
    assert fake.script is script
    _check_bools(script.cuelist)


def test_controller_reports_bools():
    from cuemsengine.ControllerEngine import ControllerEngine

    script = _parsed_script()
    fake = SimpleNamespace()
    fake._collect_cue_enabled = lambda cl: ControllerEngine._collect_cue_enabled(
        fake, cl
    )
    result = fake._collect_cue_enabled(script.cuelist)
    assert len(result) == 7
    assert all(isinstance(v, bool) for v in result.values())
    assert result[script.cuelist.contents[0].id] is False
    assert result[script.cuelist.contents[1].id] is True
