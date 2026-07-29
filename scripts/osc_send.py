#!/usr/bin/env python3
"""Send a single OSC message to a server.

Usage:
    osc_send.py <path> <value> [--ip IP] [--port PORT]
"""

import argparse

from pythonosc.udp_client import SimpleUDPClient


def parse_value(raw: str):
    for cast in (int, float):
        try:
            return cast(raw)
        except ValueError:
            continue
    return raw


def main():
    parser = argparse.ArgumentParser(description="Send an OSC message")
    parser.add_argument("path", help="OSC address, e.g. /cue/go")
    parser.add_argument("value", help="Value to send (int, float, or string)")
    parser.add_argument("--ip", default="127.0.0.1", help="Target OSC server IP")
    parser.add_argument("--port", type=int, default=9000, help="Target OSC server port")
    args = parser.parse_args()

    client = SimpleUDPClient(args.ip, args.port)
    client.send_message(args.path, parse_value(args.value))


if __name__ == "__main__":
    main()
