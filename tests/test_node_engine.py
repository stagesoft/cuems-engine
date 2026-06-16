# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>
"""Tests for NodeEngine.start() late-bind protocol (T023a)."""

import sys
from unittest.mock import MagicMock, patch

sys.modules.setdefault('cuemsutils.tools.Osc_nodes_hub', MagicMock())


def test_node_engine_start_late_binds_deploy_manager_loop():
    """T023a: NodeEngine.start() must bind CUE_HANDLER.communications_thread.event_loop
    to self.deploy_manager.loop after set_nng_comms() starts the comms thread."""
    sentinel_loop = object()

    from cuemsengine.NodeEngine import NodeEngine

    node = object.__new__(NodeEngine)
    node.nng_hub_address = 'tcp://10.0.0.1:9999'
    node.deploy_manager = MagicMock()
    node.deploy_manager.loop = None
    node.mtc_listener = MagicMock()
    node.stop_requested = False
    node.cm = MagicMock()
    node.cm.node_uuid = 'test-node-uuid'

    with patch('cuemsengine.NodeEngine.CUE_HANDLER') as mock_cue_handler, \
         patch.object(node, 'set_oscquery_comms'), \
         patch.object(node, 'set_players'), \
         patch.object(node, '_setup_nng_command_callback'), \
         patch('cuemsengine.core.BaseEngine.BaseEngine.start'):

        mock_cue_handler.communications_thread.event_loop = sentinel_loop
        node.start()

    assert node.deploy_manager.loop is sentinel_loop, (
        'NodeEngine.start() must late-bind CUE_HANDLER.communications_thread.event_loop '
        'to deploy_manager.loop'
    )
