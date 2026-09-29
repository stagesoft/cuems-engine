# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""One home for node and cue ids.

``Uuid`` is canonical **as cuemsutils delivers it**: a uuid4 is a ``Uuid``,
anything else (a uuid1, the nil uuid, a name) stays the raw ``str``. That
mirrors the library's uuid decoder, which is internal; replace ``as_id`` with a
public helper once the library offers one (upstream report UR-6).

``Uuid`` compares and hashes equal to its string but cannot be ordered, sliced
or split, so every id entering engine code goes through :func:`as_id` and every
id leaving it (sort key, slice, JSON, OSC, concatenation) through
:func:`id_str`. This is the only engine module that imports ``Uuid``.
"""

from cuemsutils.tools.Uuid import Uuid


def as_id(value):
    """Ingress: a ``Uuid`` for a uuid4, the raw ``str`` otherwise, ``None`` if empty.

    Never raises; idempotent.
    """
    if value is None or isinstance(value, Uuid):
        return value
    raw = str(value)
    if not raw:
        return None
    try:
        return Uuid(raw)
    except ValueError:
        return raw


def id_str(value) -> str:
    """Egress: the id as text; ``None`` renders as ``""``."""
    return "" if value is None else str(value)
