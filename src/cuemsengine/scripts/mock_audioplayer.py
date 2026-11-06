#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

"""
Mock cuems-audioplayer replacement for headless/cloud deployments.

Accepts the same CLI as cuems-audioplayer, starts an OSC UDP server on the
assigned port, logs all received commands, and stays alive until /quit or
SIGTERM.

869feynrj (cuems-RELATIONS Plans/2026-11-03-audio-first-pass-head-869feynrj.md
§4.1, §5): it speaks the engine's side of a self-gated start, so the engine's
follow commit, its cancels and its cancel records can be exercised without
audio. On stdout, like the real player:

    [<slug>] [OK] CAPS: dayalign selfgate
    [<slug>] [OK] LATENCY <frames> <rate> <period>[ override]
    [<slug>] [OK] RUNNING!
    [<slug>] [OK] START <start_ms_mod_day> <target_samples> <rate>
    [<slug>] [OK] CANCEL <seq> <hold|play> <ms_of_output>

It claims ``dayalign selfgate`` but not ``loop varispeed``: it does not wrap
loops and prints no LOOP acks, so the engine drives it in legacy loop mode.
It "starts" (nothing sounds) when it follows and its MTC head + latency
reaches the start, at the first period that holds sample 0, and prints START
at the first start since each /mtcfollow 1 received in HOLD. The MTC comes
from an ALSA MIDI input (``--mtc-port``, default "Midi Through Port-0"); without
one it never starts and says so.
"""

import argparse
import signal
import sys
import threading
import time

from cuemsutils.log import Logger
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import BlockingOSCUDPServer

RATE = 48000
PERIOD_FRAMES = 512
LATENCY_FRAMES = 1536
DAY_MS = 86_400_000
FRAME_MS = 40.0  # CUEMS MTC is always 25 fps


def _make_handler(name: str):
    def handler(address, *args):
        Logger.info(f"[mock-audioplayer] OSC {address} {list(args)}")

    handler.__name__ = name
    return handler


def _quit_handler(server_ref: list, address, *args):
    Logger.info(f"[mock-audioplayer] OSC {address} -- shutting down")
    if server_ref:
        threading.Thread(target=server_ref[0].shutdown, daemon=True).start()


class MtcHead:
    """Whole-frame MTC head from quarter frames and full frames (the engine's
    MtcListener rule: +1 frame at quarter frames 3 and 7, decode at 7)."""

    def __init__(self):
        self.ms = None
        self.rx = None
        self._qf = [0] * 8

    def live(self) -> bool:
        return self.rx is not None and time.monotonic() - self.rx < 0.5

    def on_message(self, msg) -> None:
        if msg.type == "quarter_frame":
            self.rx = time.monotonic()
            self._qf[msg.frame_type] = msg.frame_value
            if msg.frame_type in (3, 7) and self.ms is not None:
                self.ms += FRAME_MS
            if msg.frame_type == 7:
                q = self._qf
                frames = q[0] | (q[1] << 4)
                secs = q[2] | (q[3] << 4)
                mins = q[4] | (q[5] << 4)
                hrs = (q[6] | (q[7] << 4)) & 0x1F
                self.ms = ((hrs * 60 + mins) * 60 + secs) * 1000.0 + frames * FRAME_MS
        elif (
            msg.type == "sysex"
            and len(msg.data) == 8
            and msg.data[:4]
            == (
                127,
                127,
                1,
                1,
            )
        ):
            self.rx = time.monotonic()
            hh, mm, ss, ff = msg.data[4:]
            self.ms = (((hh & 0x1F) * 60 + mm) * 60 + ss) * 1000.0 + ff * FRAME_MS


class SelfGate:
    """The player's self-gated start, reduced to what the engine sees."""

    def __init__(self, slug: str, latency_frames: int):
        self.slug = slug
        self.latency_ms = latency_frames * 1000.0 / RATE
        self.period_ms = PERIOD_FRAMES * 1000.0 / RATE
        self.lock = threading.Lock()
        self.following = False
        self.playing = False
        self.start_ms = None  # mod day
        self.first_start_pending = False
        self.t_play = None
        self.head = MtcHead()

    def line(self, text: str) -> None:
        print(f"[{self.slug}] [OK] {text}", flush=True)

    def on_start_tod(self, address, *args):
        with self.lock:
            if args:
                self.start_ms = int(args[0]) % DAY_MS

    def on_offset(self, address, *args):
        with self.lock:
            if args:
                self.start_ms = int(round(-float(args[0]))) % DAY_MS

    def on_mtcfollow(self, address, *args):
        with self.lock:
            on = bool(args and int(args[0]) != 0)
            if on:
                self.first_start_pending = not self.playing
                self.following = True
            else:
                self.following = False
                self.playing = False

    def on_cancelstart(self, address, *args):
        if not args:
            Logger.error("[mock-audioplayer] /cancelstart without a seq: ignored")
            return
        seq = int(args[0])
        with self.lock:
            self.following = False
            self.first_start_pending = False
            if self.playing:
                ms = int((time.monotonic() - self.t_play) * 1000)
                state = "play"
            else:
                ms, state = 0, "hold"
            self.playing = False
        self.line(f"CANCEL {seq} {state} {ms}")

    def tick(self) -> None:
        """Every few ms: start when sample 0 falls in the coming period."""
        with self.lock:
            if not self.following or self.playing or self.start_ms is None:
                return
            if not self.head.live() or self.head.ms is None:
                return
            head = self.head.ms % DAY_MS
            target = head + self.latency_ms - self.start_ms
            target = (target + DAY_MS / 2) % DAY_MS - DAY_MS / 2  # nearest day
            if target < -self.period_ms:
                return
            self.playing = True
            self.t_play = time.monotonic()
            report = self.first_start_pending
            self.first_start_pending = False
            start = self.start_ms
        if report:
            self.line(f"START {start} {int(round(target * RATE / 1000))} {RATE}")


def _open_mtc(port_name: str, head: MtcHead):
    try:
        import mido

        names = mido.get_input_names()
        match = [n for n in names if port_name in n]
        if not match:
            Logger.warning(
                f"[mock-audioplayer] MTC port '{port_name}' not found: it will "
                "never self-start"
            )
            return None
        return mido.open_input(match[0], callback=head.on_message)
    except Exception as e:
        Logger.warning(f"[mock-audioplayer] no MTC input ({e}): never self-starts")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Mock cuems-audioplayer for headless deployments"
    )
    parser.add_argument("--port", type=int, required=True, help="OSC UDP port")
    parser.add_argument("--uuid", type=str, default=None, help="Player UUID")
    parser.add_argument("--output-latency-ms", type=int, default=None)
    parser.add_argument("--mtc-port", type=str, default="Midi Through Port-0")
    parser.add_argument("media", nargs="?", default=None, help="Media file path")
    args, _ = parser.parse_known_args()

    Logger.info(
        f"[mock-audioplayer] starting -- port={args.port} uuid={args.uuid}"
        f"media={args.media}"
    )

    slug = f"mock:{args.uuid or args.port}"
    override = args.output_latency_ms is not None
    latency_frames = (
        args.output_latency_ms * RATE // 1000 if override else LATENCY_FRAMES
    )
    gate = SelfGate(slug, latency_frames)

    dispatcher = Dispatcher()
    server_ref = []

    dispatcher.map("/quit", lambda address, *a: _quit_handler(server_ref, address, *a))
    dispatcher.map("/start_tod", gate.on_start_tod)
    dispatcher.map("/offset", gate.on_offset)
    dispatcher.map("/mtcfollow", gate.on_mtcfollow)
    dispatcher.map("/cancelstart", gate.on_cancelstart)
    for endpoint in (
        "/load",
        "/play",
        "/stop",
        "/vol0",
        "/vol1",
        "/volmaster",
        "/check",
        "/stoponlost",
        "/loop",
    ):
        dispatcher.map(endpoint, _make_handler(endpoint))
    dispatcher.set_default_handler(
        lambda address, *a: Logger.info(f"[mock-audioplayer] OSC {address} {list(a)}")
    )

    server = BlockingOSCUDPServer(("0.0.0.0", args.port), dispatcher)
    server_ref.append(server)

    def handle_signal(signum, frame):
        Logger.info(f"[mock-audioplayer] signal {signum}, shutting down")
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    mtc_port = _open_mtc(args.mtc_port, gate.head)

    def ticker():
        while True:
            time.sleep(0.002)
            gate.tick()

    threading.Thread(target=ticker, daemon=True, name="selfgate").start()

    gate.line("CAPS: dayalign selfgate")
    gate.line(
        f"LATENCY {latency_frames} {RATE} {PERIOD_FRAMES}"
        + (" override" if override else "")
    )
    gate.line("RUNNING!")
    Logger.info(f"[mock-audioplayer] listening on port {args.port}")
    server.serve_forever()
    if mtc_port is not None:
        mtc_port.close()
    Logger.info("[mock-audioplayer] stopped")
    sys.exit(0)


if __name__ == "__main__":
    main()
