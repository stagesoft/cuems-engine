# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>
"""Fire-and-forget UDP OSC client for gradient-motiond v0.3.0."""

from cuemsutils.log import Logger
from pythonosc.osc_message_builder import OscMessageBuilder

from ..osc.PyOsc import PyOscClient


class GradientClient:
    """Fire-and-forget UDP OSC client for gradient-motiond v0.3.0.

    Holds node_name at construction and injects it as node_name on every
    send_fade — callers do not pass it. Safe to construct multiple times;
    each new instance replaces the prior one in PlayerHandler.

    node_name MUST match the value gradient-motiond filters on (its
    --node-name CLI flag, defaulting to the OS hostname — see
    node-identity-contract.md in cuems-common). It is NOT the node's UUID:
    the daemon's OscServer drops any message whose node_name field doesn't
    match byte-for-byte, silently (DEBUG-only log), so a UUID never
    matches and every send is a no-op.
    """

    def __init__(
        self, host: str = "127.0.0.1", port: int = 7100, node_name: str = ""
    ) -> None:
        self._host = host
        self._port = port
        self._node_name = node_name
        self._osc = PyOscClient(host=host, port=port)

    def send_fade(
        self,
        motion_id: str,
        osc_host: str,
        osc_port: int,
        osc_path: str,
        start_value: float,
        end_value: float,
        start_mtc_ms: int,
        duration_ms: int,
        curve_type: str,
        curve_params_json: str = "{}",
    ) -> None:
        builder = OscMessageBuilder(address="/gradient/start_fade")
        builder.add_arg(motion_id, arg_type="s")
        # node_name — self-injected
        builder.add_arg(self._node_name, arg_type="s")
        builder.add_arg(osc_host, arg_type="s")
        builder.add_arg(int(osc_port), arg_type="i")
        builder.add_arg(osc_path, arg_type="s")
        builder.add_arg(float(start_value), arg_type="f")
        builder.add_arg(float(end_value), arg_type="f")
        builder.add_arg(int(start_mtc_ms), arg_type="h")  # int64 — REQUIRED
        builder.add_arg(int(duration_ms), arg_type="i")
        builder.add_arg(curve_type, arg_type="s")
        builder.add_arg(curve_params_json, arg_type="s")
        try:
            self._osc.client.send(builder.build())
        except Exception as exc:
            Logger.error(f"GradientClient.send_fade failed: {exc}")
            raise

    def send_cancel_motion(self, motion_id: str) -> None:
        try:
            self._osc.client.send_message(
                "/gradient/cancel_motion", (motion_id, self._node_name)
            )
        except Exception as exc:
            Logger.error(f"GradientClient.send_cancel_motion failed: {exc}")
            raise

    def send_cancel_all(self) -> None:
        try:
            self._osc.client.send_message("/gradient/cancel_all", self._node_name)
        except Exception as exc:
            Logger.error(f"GradientClient.send_cancel_all failed: {exc}")
            raise
