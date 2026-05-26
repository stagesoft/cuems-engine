# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>
"""Unit tests for GradientClient — Phase 2 / T001.

Covers (SC-004 required 8 tests, plus extras):
1. /gradient/start_fade address
2. ,sssisffhiss type-tag string
3. motion_id at position 0
4. constructor-supplied node_uuid injected at position 1 (node_name)
5. start_mtc_ms 'h' (int64) tag round-trips values exceeding int32 range
6. /gradient/cancel_all emission with no args
7. /gradient/cancel_motion emission with motion_id
8. OSC send error logged at ERROR and re-raised
"""

from __future__ import annotations

import logging
import socket
from unittest.mock import MagicMock

import pytest
from pythonosc.osc_message import OscMessage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _type_tag_str(data: bytes) -> str:
    """Extract the OSC type-tag string (e.g. ',sssisffhiss') from raw dgram bytes."""
    idx = data.index(b",")
    end = data.index(b"\x00", idx)
    return data[idx:end].decode("ascii")


def _recv(sock: socket.socket) -> tuple[bytes, OscMessage]:
    data, _ = sock.recvfrom(4096)
    return data, OscMessage(data)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def udp_listener():
    """Ephemeral UDP socket that acts as the gradient-motiond listener."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(2.0)
    port = sock.getsockname()[1]
    yield sock, port
    sock.close()


@pytest.fixture
def gradient_client(udp_listener):
    from cuemsengine.players.GradientClient import GradientClient

    _, port = udp_listener
    return GradientClient(host="127.0.0.1", port=port, node_uuid="node-test")


_FADE_KWARGS = dict(
    motion_id="test-motion-id",
    osc_host="127.0.0.1",
    osc_port=12300,
    osc_path="/volmaster",
    start_value=0.85,
    end_value=0.0,
    start_mtc_ms=5000,
    duration_ms=5000,
    curve_type="linear",
    curve_params_json="{}",
)


# ---------------------------------------------------------------------------
# SC-004 required tests — send_fade
# ---------------------------------------------------------------------------


class TestSendFade:
    def test_send_fade_emits_correct_osc_address(self, udp_listener, gradient_client):
        """(SC-004 #1) /gradient/start_fade address."""
        sock, _ = udp_listener
        gradient_client.send_fade(**_FADE_KWARGS)
        _, msg = _recv(sock)
        assert msg.address == "/gradient/start_fade"

    def test_send_fade_type_tags(self, udp_listener, gradient_client):
        """(SC-004 #2) Type-tag string is ,sssisffhiss."""
        sock, _ = udp_listener
        gradient_client.send_fade(**_FADE_KWARGS)
        data, _ = _recv(sock)
        assert _type_tag_str(data) == ",sssisffhiss"

    def test_send_fade_motion_id_at_position_0(self, udp_listener, gradient_client):
        """(SC-004 #3) motion_id at params[0]."""
        sock, _ = udp_listener
        gradient_client.send_fade(**_FADE_KWARGS)
        _, msg = _recv(sock)
        assert msg.params[0] == "test-motion-id"

    def test_send_fade_node_uuid_injected_as_node_name(
        self, udp_listener, gradient_client
    ):
        """(SC-004 #4) Constructor-supplied node_uuid injected at params[1] (node_name)."""
        sock, _ = udp_listener
        gradient_client.send_fade(**_FADE_KWARGS)
        _, msg = _recv(sock)
        assert msg.params[1] == "node-test"

    def test_send_fade_start_mtc_ms_is_int64(self, udp_listener):
        """(SC-004 #5) start_mtc_ms type tag is 'h' (int64); round-trips values > int32."""
        from cuemsengine.players.GradientClient import GradientClient

        sock, port = udp_listener
        gc = GradientClient(host="127.0.0.1", port=port, node_uuid="n")
        large_val = 2**33  # 8_589_934_592 — exceeds int32 max (2_147_483_647)
        gc.send_fade(**{**_FADE_KWARGS, "start_mtc_ms": large_val})
        data, msg = _recv(sock)
        # type-tag string: ',sssisffhiss' — ',' at [0], so start_mtc_ms tag is at [8]
        assert (
            _type_tag_str(data)[8] == "h"
        ), "start_mtc_ms type tag must be 'h' (int64)"
        assert msg.params[7] == large_val

    def test_send_fade_osc_error_is_raised(self, udp_listener, gradient_client, caplog):
        """(SC-004 #8) OSC send error is logged at ERROR and re-raised."""
        gradient_client._osc.client.send = MagicMock(side_effect=OSError("send failed"))
        with caplog.at_level(logging.ERROR):
            with pytest.raises(OSError):
                gradient_client.send_fade(**_FADE_KWARGS)
        assert any(
            "GradientClient.send_fade failed" in r.message for r in caplog.records
        )

    def test_send_fade_all_11_params_present(self, udp_listener, gradient_client):
        """All 11 fields of the wire contract are present in the sent message."""
        sock, _ = udp_listener
        gradient_client.send_fade(**_FADE_KWARGS)
        _, msg = _recv(sock)
        assert len(msg.params) == 11

    def test_send_fade_osc_host_at_position_2(self, udp_listener, gradient_client):
        sock, _ = udp_listener
        gradient_client.send_fade(**_FADE_KWARGS)
        _, msg = _recv(sock)
        assert msg.params[2] == "127.0.0.1"

    def test_send_fade_osc_port_at_position_3(self, udp_listener, gradient_client):
        sock, _ = udp_listener
        gradient_client.send_fade(**_FADE_KWARGS)
        _, msg = _recv(sock)
        assert msg.params[3] == 12300

    def test_send_fade_curve_type_at_position_9(self, udp_listener, gradient_client):
        sock, _ = udp_listener
        gradient_client.send_fade(**_FADE_KWARGS)
        _, msg = _recv(sock)
        assert msg.params[9] == "linear"

    def test_send_fade_curve_params_json_default(self, udp_listener):
        """curve_params_json defaults to '{}'."""
        from cuemsengine.players.GradientClient import GradientClient

        sock, port = udp_listener
        gc = GradientClient(host="127.0.0.1", port=port, node_uuid="n")
        kwargs = {k: v for k, v in _FADE_KWARGS.items() if k != "curve_params_json"}
        gc.send_fade(**kwargs)
        _, msg = _recv(sock)
        assert msg.params[10] == "{}"


# ---------------------------------------------------------------------------
# SC-004 required tests — send_cancel_all
# ---------------------------------------------------------------------------


class TestSendCancelAll:
    def test_send_cancel_all_emits_correct_address(self, udp_listener, gradient_client):
        """(SC-004 #6) /gradient/cancel_all address."""
        sock, _ = udp_listener
        gradient_client.send_cancel_all()
        _, msg = _recv(sock)
        assert msg.address == "/gradient/cancel_all"

    def test_send_cancel_all_no_params(self, udp_listener, gradient_client):
        """cancel_all carries no arguments."""
        sock, _ = udp_listener
        gradient_client.send_cancel_all()
        _, msg = _recv(sock)
        assert msg.params == []


# ---------------------------------------------------------------------------
# SC-004 required tests — send_cancel_motion
# ---------------------------------------------------------------------------


class TestSendCancelMotion:
    def test_send_cancel_motion_emits_correct_address(
        self, udp_listener, gradient_client
    ):
        """(SC-004 #7) /gradient/cancel_motion address."""
        sock, _ = udp_listener
        gradient_client.send_cancel_motion("test-motion-id-42")
        _, msg = _recv(sock)
        assert msg.address == "/gradient/cancel_motion"

    def test_send_cancel_motion_motion_id(self, udp_listener, gradient_client):
        sock, _ = udp_listener
        gradient_client.send_cancel_motion("test-motion-id-42")
        _, msg = _recv(sock)
        assert msg.params[0] == "test-motion-id-42"
