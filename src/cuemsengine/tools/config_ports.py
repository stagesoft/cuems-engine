# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

"""Extract the port numbers a node declares in settings.xml.

Lives in tools/ rather than NodeEngine so BaseEngine can use it without an
import cycle — both the controller and the node engine need to exclude their
declared ports from the allocator (869ed9wf7).
"""


def is_int(value: any) -> bool:
    """Check if a value can be read as an integer.

    Catches TypeError as well as ValueError: an empty element such as
    `<oscquery_ws_port/>` decodes to None in xmlschema, and `int(None)` raises
    TypeError, not ValueError.
    """
    try:
        int(value)
        return True
    except (TypeError, ValueError):
        return False


def get_config_ports(node_conf: dict) -> dict:
    """Create a dict of ports from the config.

    Only scans top-level keys. Nested ports — `videoplayer/osc_port` is the
    one that exists today — are invisible here and must be registered by
    whoever reads them (NodeEngine.set_video_players does).
    """
    k = [i for i in node_conf.keys() if "port" in i and is_int(node_conf[i])]
    v = [int(node_conf[i]) for i in k]
    return dict(zip(k, v))
