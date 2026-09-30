# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""The engine's identity helpers (Group 7, contracts/ids.md).

``as_id`` is cuemsutils' published ``coerce_identity``; its rule is pinned by
the library's own ``tests/contract/test_published_coercion.py`` and is not
re-tested here (FR-030a-i). What this file pins is the engine's side: that it
delegates rather than keeps a copy, and that ``id_str`` renders every id the
library can hand it as sortable text.
"""

from cuemsutils.tools import coerce_identity

from cuemsengine.tools.ids import as_id, id_str

UUID4 = "3f2b8c1e-5d4a-4b6e-9c7f-1a2b3c4d5e6f"
UUID1 = "268a0b70-1dfb-11eb-bc5f-2b59ad58b106"
NIL = "00000000-0000-0000-0000-000000000000"


def test_as_id_is_the_librarys_published_rule_not_a_copy():
    assert as_id is coerce_identity


def test_sorting_mixed_ids_by_id_str_never_raises():
    mixed = [as_id(UUID4), UUID1, as_id("9a8b7c6d-1e2f-4a3b-8c4d-5e6f7a8b9c0d"), NIL]
    ordered = sorted(mixed, key=id_str)
    assert [id_str(x) for x in ordered] == sorted(id_str(x) for x in mixed)


def test_id_str_renders_ids_and_none():
    assert id_str(as_id(UUID4)) == UUID4
    assert type(id_str(as_id(UUID4))) is str
    assert id_str(UUID1) == UUID1
    assert id_str(None) == ""
