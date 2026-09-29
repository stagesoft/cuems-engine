# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""The engine's identity helpers (Group 7, contracts/ids.md).

Pins ``as_id``/``id_str`` only. The library's ``Uuid`` is exercised as an
input, never re-tested (FR-030a-i spirit).
"""

import pytest
from cuemsutils.tools.Uuid import Uuid

from cuemsengine.tools.ids import as_id, id_str

UUID4 = "3f2b8c1e-5d4a-4b6e-9c7f-1a2b3c4d5e6f"
UUID1 = "268a0b70-1dfb-11eb-bc5f-2b59ad58b106"
NIL = "00000000-0000-0000-0000-000000000000"


def test_a_uuid_passes_through_unchanged():
    u = Uuid(UUID4)
    assert as_id(u) is u


def test_a_uuid4_string_becomes_a_uuid():
    result = as_id(UUID4)
    assert isinstance(result, Uuid)
    assert str(result) == UUID4


@pytest.mark.parametrize(
    "raw", [UUID1, NIL, "controller"], ids=["uuid1", "nil", "text"]
)
def test_anything_else_non_empty_stays_the_raw_string(raw):
    result = as_id(raw)
    assert type(result) is str
    assert result == raw


@pytest.mark.parametrize("raw", ["", None])
def test_empty_and_none_become_none(raw):
    assert as_id(raw) is None


def test_other_types_go_through_str_first():
    class Stringy:
        def __str__(self):
            return UUID4

    assert isinstance(as_id(Stringy()), Uuid)
    assert as_id(42) == "42"


@pytest.mark.parametrize("raw", [UUID4, UUID1, NIL, "", None, "controller"])
def test_as_id_is_idempotent(raw):
    once = as_id(raw)
    assert as_id(once) == once
    assert type(as_id(once)) is type(once)


def test_a_uuid_and_its_string_are_one_set_member():
    u = Uuid(UUID4)
    ids = {as_id(u), as_id(str(u))}
    assert len(ids) == 1
    assert hash(as_id(u)) == hash(as_id(str(u)))


def test_sorting_mixed_ids_by_id_str_never_raises():
    mixed = [as_id(UUID4), UUID1, as_id("9a8b7c6d-1e2f-4a3b-8c4d-5e6f7a8b9c0d"), NIL]
    ordered = sorted(mixed, key=id_str)
    assert [id_str(x) for x in ordered] == sorted(id_str(x) for x in mixed)


def test_id_str_renders_ids_and_none():
    assert id_str(as_id(UUID4)) == UUID4
    assert type(id_str(as_id(UUID4))) is str
    assert id_str(UUID1) == UUID1
    assert id_str(None) == ""
