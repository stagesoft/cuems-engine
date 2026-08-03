# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

from threading import Thread

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_message import OscMessage
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient

PYOSC_HOST = "127.0.0.1"
PYOSC_PORT = 10001
# How long to wait for a reply to arrive. UDPClient.receive() blocks in recv()
# until data lands, so this only ever bounds the FAILURE path — a reply that
# comes back promptly still returns immediately, and raising this costs nothing
# on the happy path. It used to be 0.001, which is a poll interval, not a
# round-trip budget: any reply slower than 1 ms was treated as no reply at all.
# (python-osc's own default is 30 s; 2 s is generous for localhost while still
# failing fast when something is genuinely wrong.)
PYOSC_MSG_TIMEOUT = 2.0


def new_osc_client(cls) -> SimpleUDPClient:
    return SimpleUDPClient(cls.host, cls.port)


class PyOscClient(object):
    def __init__(self, host=PYOSC_HOST, port=PYOSC_PORT):
        self.host = host
        self.port = port
        self.client = new_osc_client(self)

    def send_message(self, address: str, *args) -> None:
        self.client.send_message(address, args)

    def get_first_message(self, timeout=PYOSC_MSG_TIMEOUT) -> OscMessage:
        res = self.client.get_messages(timeout)
        try:
            return next(res)
        except StopIteration:
            # get_messages() is a generator that yields nothing when the wait
            # elapses, so next() raises StopIteration. Letting that escape a
            # regular function is a trap: Python re-labels it inside any
            # enclosing generator, which is how a plain timeout surfaced as
            # "RuntimeError: generator raised StopIteration" with no mention of
            # OSC at all. Report what actually happened.
            raise TimeoutError(
                f"No OSC reply from {self.host}:{self.port} within {timeout}s"
            ) from None

    def send_with_response(self, address: str, *args) -> OscMessage:
        self.send_message(address, *args)
        return self.get_first_message()


class PyOscServer(object):
    def __init__(self, host=PYOSC_HOST, port=PYOSC_PORT, endpoints=[]):
        self.host = host
        self.port = port
        self.endpoints = endpoints
        self.dispatcher = Dispatcher()
        self.handlers = {}
        self.server = self.new_server()

    def start(self) -> None:
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def new_server(self) -> ThreadingOSCUDPServer:
        self.add_handlers()
        return ThreadingOSCUDPServer((self.host, self.port), self.dispatcher)

    def add_handlers(self) -> None:
        """
        Add handlers to the dispatcher and store them in the handlers dict
        """
        if len(self.endpoints) == 0:
            return
        for endpoint_, function_ in self.endpoints.items():
            self.handlers[endpoint_] = self.dispatcher.map(endpoint_, function_)
