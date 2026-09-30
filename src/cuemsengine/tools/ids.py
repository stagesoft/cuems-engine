# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""One home for node and cue ids.

``Uuid`` is canonical **as cuemsutils delivers it**: a converged id (uuid4) is a
``Uuid``, anything else (a uuid1, the NOT PROVISIONED sentinel, a name) stays
the raw ``str``. :func:`as_id` is the library's published rule,
``cuemsutils.tools.coerce_identity``; the engine no longer keeps its own copy.

Every id entering engine code goes through :func:`as_id` and every id leaving
it (sort key, slice, JSON, OSC, concatenation) through :func:`id_str`.
"""

from cuemsutils.tools import coerce_identity as as_id

__all__ = ["as_id", "id_str"]


def id_str(value) -> str:
    """Egress: the id as text; ``None`` renders as ``""``."""
    return "" if value is None else str(value)
