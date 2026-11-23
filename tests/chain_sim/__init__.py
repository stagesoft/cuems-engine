# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""The AC2 harness of plan 2026-11-18-autocontinue-cumulative-waits (1amfwm7jnqf).

A scenario of the executable model (cuems-RELATIONS
`baselines/autocontinue-cumulative/model/`) runs on one subprocess per simulated
node (`node.py`), each with its own CUE_HANDLER, ACTION_HANDLER and script tree,
fed by the test's process (`driver.py`), which owns the virtual MTC, the bus and
the follow relay. Test helper only: nothing in `src/` changes for it.
"""
