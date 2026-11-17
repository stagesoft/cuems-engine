# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

"""
JACK Connection Manager

This module provides a simple interface for managing JACK audio connections
using the python-jack (JACK-Client) library.
"""

import re
import shutil
import subprocess

try:
    import jack
except (ImportError, OSError):
    jack = None

from cuemsutils.log import Logger, logged

# 869feynrj §4.5d: the playback latency comes from `jack_lsp -l -p`, not from
# the Python client. The venv's JACK-Client (0.5.7 on the deployed stack) has
# no Port.get_latency_range and its cffi does not declare jack_latency_range_t
# (step 3 on test2: every node start failed the query).
JACK_LSP = "jack_lsp"
JACK_LSP_TIMEOUT_S = 2.0
_PLAYBACK_LATENCY = re.compile(r"port playback latency = \[\s*(\d+)\s+(\d+)\s*\]")
_PROPERTIES = re.compile(r"properties:\s*(.*)")


def parse_jack_lsp_playback_latency(text: str) -> int | None:
    """The largest playback latency (frames, the range's max) over the
    physical playback ports (properties ``input`` and ``physical``) in the
    output of ``jack_lsp -l -p``, or None when there is none.

    Port names start a line; their attributes are indented below them. Other
    unindented lines (a comment, a stray path) are ports with no properties
    and never count."""
    ports = []
    current = None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            current = {"latency": None, "properties": set()}
            ports.append(current)
            continue
        if current is None:
            continue
        m = _PLAYBACK_LATENCY.search(line)
        if m:
            current["latency"] = int(m.group(2))
            continue
        m = _PROPERTIES.search(line)
        if m:
            current["properties"] = {p.strip() for p in m.group(1).split(",") if p}
    latencies = [
        p["latency"]
        for p in ports
        if p["latency"] is not None and {"input", "physical"} <= p["properties"]
    ]
    return max(latencies) if latencies else None


class JackConnectionManager:
    """Manager for JACK audio connections.

    Uses the python-jack (JACK-Client) library to manage JACK port connections.
    Creates a lightweight client just for querying and connection management.
    """

    def __init__(self, client_name: str = "cuems_connection_manager"):
        """Initialize the JACK connection manager.

        Args:
            client_name: Name for the JACK client (default:
            'cuems_connection_manager')
        """
        self.client_name = client_name
        self._client = None
        self._initialize_client()

    def _initialize_client(self):
        """Initialize the JACK client."""
        if jack is None:
            Logger.warning(
                "JACK library not available -- JackConnectionManager running"
                "in no-op mode"
            )
            self._client = None
            return
        try:
            # Create a client without ports, just for connection management
            self._client = jack.Client(self.client_name, no_start_server=True)
            Logger.debug(
                f"JACK connection manager client '{self.client_name}' initialized"
            )
        except jack.JackError as e:
            Logger.error(f"Failed to initialize JACK client: {e}")
            self._client = None

    @property
    def client(self):
        """Get the JACK client, reinitializing if necessary."""
        if self._client is None:
            self._initialize_client()
        return self._client

    def _reset_client(self):
        """Discard the current client so the next access reinitializes.

        Needed because jackd can deregister our client after a process-graph
        error (e.g. an audioplayer XRun that trips ProcessGraphAsyncMaster).
        Python still holds a reference to a dead handle; every subsequent
        connect/disconnect silently returns -1. Calling this on a JackError
        lets the retry path get a fresh, registered client.
        """
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    @logged
    def get_ports(
        self,
        pattern: str = None,
        is_audio: bool = True,
        is_output: bool = None,
        is_input: bool = None,
    ) -> list[str]:
        """Get list of JACK ports.

        Args:
            pattern: Optional regex pattern to filter port names
            is_audio: Filter for audio ports (default: True)
            is_output: Filter for output ports (default: None = all)
            is_input: Filter for input ports (default: None = all)

        Returns:
            List of port names
        """
        if self.client is None:
            Logger.error("JACK client not initialized")
            return []

        try:
            ports = self.client.get_ports(
                name_pattern=pattern if pattern else "",
                is_audio=is_audio,
                is_output=is_output,
                is_input=is_input,
            )
            port_names = [p.name for p in ports]
            Logger.debug(f"Found {len(port_names)} JACK ports")
            return port_names

        except jack.JackError as e:
            Logger.error(f"Error getting JACK ports: {e}")
            return []
        except Exception as e:
            Logger.error(f"Unexpected error getting JACK ports: {e}")
            return []

    def port_exists(self, port_name: str) -> bool:
        """Check if a JACK port exists.

        Args:
            port_name: Full name of the port (e.g., 'client_name:port_name')

        Returns:
            True if the port exists, False otherwise
        """
        if self.client is None:
            return False

        try:
            ports = self.client.get_ports(name_pattern=f"^{port_name}$")
            return len(ports) > 0
        except Exception:
            return False

    @logged
    def connect_by_name(self, source_port: str, destination_port: str) -> bool:
        """Connect two JACK ports by name.

        Args:
            source_port: Name of the source port (output)
            destination_port: Name of the destination port (input)

        Returns:
            True if connection successful, False otherwise
        """
        for attempt in (0, 1):
            if self.client is None:
                Logger.error("JACK client not initialized")
                return False
            try:
                if self.is_connected(source_port, destination_port):
                    Logger.debug(
                        f"Ports already connected: {source_port} ->"
                        f"{destination_port}"
                    )
                    return True
                self.client.connect(source_port, destination_port)
                Logger.info(f"Connected {source_port} -> {destination_port}")
                return True
            except jack.JackError as e:
                if attempt == 0:
                    Logger.warning(
                        f"connect failed, retrying with fresh client:"
                        f"{source_port} -> {destination_port}: {e}"
                    )
                    self._reset_client()
                    continue
                Logger.warning(
                    f"Failed to connect {source_port} -> {destination_port}: {e}"
                )
                return False
            except Exception as e:
                Logger.error(f"Unexpected error connecting JACK ports: {e}")
                return False
        return False

    @logged
    def disconnect_by_name(self, source_port: str, destination_port: str) -> bool:
        """Disconnect two JACK ports by name.

        Args:
            source_port: Name of the source port (output)
            destination_port: Name of the destination port (input)

        Returns:
            True if disconnection successful, False otherwise
        """
        for attempt in (0, 1):
            if self.client is None:
                Logger.error("JACK client not initialized")
                return False
            try:
                self.client.disconnect(source_port, destination_port)
                Logger.info(f"Disconnected {source_port} -> {destination_port}")
                return True
            except jack.JackError as e:
                if attempt == 0:
                    Logger.warning(
                        f"disconnect failed, retrying with fresh client:"
                        f"{source_port} -> {destination_port}: {e}"
                    )
                    self._reset_client()
                    continue
                Logger.warning(
                    f"Failed to disconnect {source_port} -> {destination_port}: {e}"
                )
                return False
            except Exception as e:
                Logger.error(f"Unexpected error disconnecting JACK ports: {e}")
                return False
        return False

    @logged
    def get_connections(self, port_name: str) -> list[str]:
        """Get all connections for a given port.

        Args:
            port_name: Name of the port to query

        Returns:
            List of connected port names
        """
        if self.client is None:
            Logger.error("JACK client not initialized")
            return []

        try:
            # Get the port object
            ports = self.client.get_ports(name_pattern=f"^{port_name}$")
            if not ports:
                Logger.warning(f"Port not found: {port_name}")
                return []

            port = ports[0]

            # Get connections
            connections = self.client.get_all_connections(port)
            connection_names = [conn.name for conn in connections]

            return connection_names

        except jack.JackError as e:
            Logger.error(f"Error getting connections for port {port_name}: {e}")
            return []
        except Exception as e:
            Logger.error(f"Unexpected error getting connections: {e}")
            return []

    @logged
    def is_connected(self, source_port: str, destination_port: str) -> bool:
        """Check if two ports are connected.

        Args:
            source_port: Name of the source port
            destination_port: Name of the destination port

        Returns:
            True if connected, False otherwise
        """
        connections = self.get_connections(source_port)
        return destination_port in connections

    def playback_latency(self) -> tuple[int, int, int] | None:
        """(latency frames, sample rate, period frames) of the system
        playback ports, or None when JACK does not answer (one WARNING).

        The latency is the largest playback latency of the physical sinks,
        read with ``jack_lsp -l -p`` (1536 frames at -p512 -n3; run as the
        engine's user, jackd's, with a 2 s timeout); the rate and the period
        are the JACK client's. Called once at node start, on the starting
        thread (869feynrj §4.5d: a node's output latency is known before
        any audio player exists)."""
        client = self.client
        if client is None:
            Logger.warning("JACK playback latency: no JACK client")
            return None
        try:
            done = subprocess.run(
                [shutil.which(JACK_LSP) or JACK_LSP, "-l", "-p"],
                capture_output=True,
                text=True,
                timeout=JACK_LSP_TIMEOUT_S,
            )
            if done.returncode != 0:
                raise RuntimeError(
                    f"jack_lsp exited {done.returncode}: {(done.stderr or '').strip()}"
                )
            frames = parse_jack_lsp_playback_latency(done.stdout or "")
            if frames is None:
                raise RuntimeError("no physical playback port in jack_lsp -l -p")
            return frames, int(client.samplerate), int(client.blocksize)
        except Exception as e:
            Logger.warning(f"JACK playback latency query failed: {e!r}")
            return None

    def __del__(self):
        """Cleanup JACK client on deletion."""
        if self._client is not None:
            try:
                self._client.close()
                Logger.debug(
                    f"JACK connection manager client '{self.client_name}' closed"
                )
            except Exception as e:
                Logger.debug(f"Error closing JACK client: {e}")
