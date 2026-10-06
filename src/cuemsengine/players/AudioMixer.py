# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

from time import sleep

from cuemsutils.log import Logger, logged
from pyossia import ValueType

from ..osc.helpers import add_callback_to_all
from ..osc.OssiaClient import PlayerClient
from .JackConnectionManager import JackConnectionManager
from .Player import Player

JACK_VOLUME_PATH = "/usr/local/bin/jack-volume"
# usage: jack-volume [-c <jack_client_name>] [-s <jack_server_name>] [-p
# <osc_port>] [-n <number_of_channels>]


class AudioMixer(Player):
    """JACK audio mixer using jack-volume controlled via OSC.

    This class manages a jack-volume process which provides volume control
    for multiple audio channels. It connects to JACK and exposes OSC control.

    OSC address format: /audiomixer/<instance>/<channel>
    where channel can be 'master' or '0', '1', '2', etc.
    """

    def __init__(
        self,
        audio_outputs,
        port,
        mixer_id: str,
        path=None,
        args: str | None = None,
    ):
        """Initialize the AudioMixer.

        Args:
            audio_outputs: List of audio output configurations
            port: OSC port for jack-volume communication
            mixer_id: Unique identifier for this mixer
            path: Optional path to jack-volume binary (defaults to
            JACK_VOLUME_PATH)
        """
        super().__init__()
        self.conn_man = JackConnectionManager()
        self.port = port
        self.ports = self.conn_man.get_ports()
        self.path = path if path else JACK_VOLUME_PATH
        self.channel_number = len(audio_outputs)
        self.audio_outputs = audio_outputs
        self.client_name = get_mixer_client_name(mixer_id)
        self.extra_args = args

        # Build command line arguments for jack-volume
        self.args = [
            "-c",
            self.client_name,
            "-p",
            str(port),
            "-n",
            str(self.channel_number),
        ]

        # Note: start() will be called by start_audio_mixer() with timeout
        # self.connect_to_jack() will be called after start() in
        # start_audio_mixer()

    @logged
    def run(self):
        """Start the jack-volume subprocess."""
        process_call_list = [self.path] + self.args
        if self.extra_args:
            for arg in self.extra_args.split():
                process_call_list.append(arg)
        Logger.info(f"Starting jack-volume with: {process_call_list}")
        self.call_subprocess(process_call_list)

    @logged
    def connect_to_jack(self, max_retries: int = 10, retry_delay: float = 0.5):
        """Connect mixer outputs to the configured playback ports.

        Retries if ports are not yet registered (race with jack-volume
        startup).
        """
        # Fail fast with no JACK server (see connect_player_to_outputs): the
        # retry loop is for the port-registration race, not for a host whose
        # jackd is absent/stubbed — there it just burned
        # len(audio_outputs) * max_retries * retry_delay seconds at startup.
        if self.conn_man.client is None:
            Logger.error(
                "No JACK server available - mixer outputs not wired; audio on"
                " this host will be SILENT. (jackd absent or stubbed -"
                " skipping the port wait.)"
            )
            return
        for i, playback_port in enumerate(self.audio_outputs):
            output_port = f"{self.client_name}:output_{i+1}"
            # Wait for both ports to be available
            for attempt in range(max_retries):
                if self.conn_man.port_exists(output_port) and self.conn_man.port_exists(
                    playback_port
                ):
                    break
                if attempt < max_retries - 1:
                    Logger.debug(
                        f"Waiting for JACK ports {output_port} /"
                        f" {playback_port}"
                        f" (attempt {attempt + 1}/{max_retries})"
                    )
                    sleep(retry_delay)
            else:
                Logger.warning(
                    f"JACK ports not available after {max_retries} attempts:"
                    f"{output_port} -> {playback_port}"
                )
                continue
            Logger.debug(f"Connecting {output_port} to {playback_port}")
            self.conn_man.connect_by_name(output_port, playback_port)

    @logged
    def connect_player_to_mixer(
        self,
        player_name: str,
        player_output_prefix: str = "output",
        mixer_channel: int = 0,
        max_retries: int = 30,
        retry_delay: float = 0.5,
    ):
        """Connect a player's output to a specific mixer input channel.

        First disconnects any existing connections from the player's outputs,
        then connects them to the mixer inputs. Will retry if ports are not
        immediately available (race condition with player startup).

        Handles both mono and stereo players:
        - Mono: output_0 → input_1 (single channel)
        - Stereo: output_0 → input_1, output_1 → input_2

        Args:
            player_name: Name of the player JACK client to connect
            player_output_prefix: Prefix for player's output ports (e.g.,
            'output')
            mixer_channel: Mixer input channel number (0-indexed)
            max_retries: Maximum number of connection attempts (default 10)
            retry_delay: Delay between retries in seconds (default 0.2)
        """
        from time import sleep

        if mixer_channel >= self.channel_number:
            Logger.error(
                f"Invalid mixer channel: {mixer_channel}. Max:"
                f"{self.channel_number - 1}"
            )
            return

        # Define player output ports
        # cuems-audioplayer uses space format: "outport 0", "outport 1"
        channel_0_output = f"{player_name}:{player_output_prefix} 0"
        channel_1_output = f"{player_name}:{player_output_prefix} 1"
        mixer_input_1 = f"{self.client_name}:input_{mixer_channel * 2 + 1}"
        mixer_input_2 = f"{self.client_name}:input_{mixer_channel * 2 + 2}"

        # Wait for player JACK ports to be available (retry mechanism).
        # Gate ONLY on port_exists(); get_connections() returns [] (not None)
        # for a missing port, so the old guard broke the loop immediately and
        # connected a not-yet-registered port -> jackd Unknown source port.
        for attempt in range(max_retries):
            if self.conn_man.port_exists(channel_0_output):
                break
            if attempt < max_retries - 1:
                Logger.debug(
                    f"Waiting for JACK port {channel_0_output} (attempt"
                    f"{attempt + 1}/{max_retries})"
                )
                sleep(retry_delay)
        else:
            Logger.warning(
                f"JACK port {channel_0_output} not available after"
                f"{max_retries} attempts"
            )
            return False

        # Check if player is stereo (has output_1) or mono (only output_0)
        is_stereo = self.conn_man.port_exists(channel_1_output)
        Logger.debug(f"Player {player_name} is {'stereo' if is_stereo else 'mono'}")

        # First, disconnect any existing connections from player outputs
        # Guard with port_exists to avoid sending disconnect requests for
        # ports that were destroyed by a concurrent /quit.
        if self.conn_man.port_exists(channel_0_output):
            Logger.debug(f"Disconnecting existing connections from {channel_0_output}")
            channel_0_connections = self.conn_man.get_connections(channel_0_output)
            for connection in channel_0_connections:
                Logger.debug(f"Disconnecting {channel_0_output} from {connection}")
                self.conn_man.disconnect_by_name(channel_0_output, connection)

        if is_stereo and self.conn_man.port_exists(channel_1_output):
            Logger.debug(f"Disconnecting existing connections from {channel_1_output}")
            channel_1_connections = self.conn_man.get_connections(channel_1_output)
            for connection in channel_1_connections:
                Logger.debug(f"Disconnecting {channel_1_output} from {connection}")
                self.conn_man.disconnect_by_name(channel_1_output, connection)

        # Connect to mixer inputs
        # For mono: connect output_0 to both input_1 and input_2 (if available)
        # For stereo: connect output_0 → input_1, output_1 → input_2

        # Connect first channel
        if self.conn_man.port_exists(mixer_input_1):
            Logger.debug(f"Connecting {channel_0_output} to {mixer_input_1}")
            self.conn_man.connect_by_name(channel_0_output, mixer_input_1)
        else:
            Logger.warning(f"Mixer input port {mixer_input_1} does not exist")

        # Connect second channel (if mixer has it)
        if self.conn_man.port_exists(mixer_input_2):
            if is_stereo:
                Logger.debug(f"Connecting {channel_1_output} to {mixer_input_2}")
                self.conn_man.connect_by_name(channel_1_output, mixer_input_2)
            else:
                # Mono player: connect output_0 to both mixer inputs for
                # centered sound
                Logger.debug(
                    f"Mono player: Connecting {channel_0_output} to {mixer_input_2}"
                )
                self.conn_man.connect_by_name(channel_0_output, mixer_input_2)
        else:
            Logger.debug(
                f"Mixer input port {mixer_input_2} does not exist (mono mixer)"
            )

    @logged
    def connect_player_to_outputs(
        self,
        player_name: str,
        player_output_prefix: str = "outport",
        selected_outputs: list = None,
        max_retries: int = 30,
        retry_delay: float = 0.5,
        should_abort=None,
        ready=None,
    ):
        """
        Connect a player to specific system outputs based on cue configuration.

        Maps selected output port names to mixer inputs:
        - system:playback_1 → mixer input_1
        - system:playback_2 → mixer input_2

        For stereo audio with a single output selected, both player channels
        are summed to that output. For both outputs, normal stereo routing.

        Args:
            player_name: Name of the player JACK client to connect
            player_output_prefix: Prefix for player's output ports (e.g.,
            'outport')
            selected_outputs: List of output port names (e.g.,
            ['system:playback_1'])
            max_retries: Maximum number of connection attempts
            retry_delay: Delay between retries in seconds
            should_abort: optional predicate, checked on every attempt the
            port is still missing. True ends the wait at once with False. The
            caller passes "the player process has exited": its ports can
            never register then (869f9wqpn -- a STOP/load kills the player
            mid-wait). It does NOT shorten the wait for a live process.
            ready: optional threading.Event the player sets once it reports
            itself started (Player.ready, its "[OK] RUNNING!" line). When
            given, the wiring waits for it before looking at the ports: the
            ports exist before the player has finished starting, and RtAudio
            auto-connects them to system:playback only when its stream starts.
            Wiring earlier finds nothing to disconnect, and the auto-connect
            lands afterwards and stays - the cue then sounds through the mixer
            AND straight to the outputs (869fbyjzx / 869fcvz85). The ready wait
            and the port wait share one budget, today's port-wait ceiling.
            A player that never reports ready is wired on port presence, with
            a WARNING.

        Returns:
            True if every required player→mixer connection was made, False if
            the player ports never registered, no mixer inputs resolved, or any
            connection failed (caller should treat False as a silent cue).
        """
        from time import monotonic, sleep

        # Default to stereo (both outputs) if none specified
        if not selected_outputs:
            selected_outputs = ["system:playback_1", "system:playback_2"]
            Logger.debug(
                f"No outputs specified, defaulting to stereo: {selected_outputs}"
            )

        # Define player output ports - cuems-audioplayer uses "outport 0",
        # "outport 1"
        channel_0_output = f"{player_name}:{player_output_prefix} 0"
        channel_1_output = f"{player_name}:{player_output_prefix} 1"

        # Fail fast when there is no JACK client at all. The retry loop below
        # exists for a TRANSIENT race (player ports registering a beat after
        # the process spawns); a missing JACK server is PERMANENT for this arm
        # attempt, and waiting max_retries * retry_delay (~15s) for it blocked
        # armed_ready — and therefore the cluster GO gate — on every load and
        # re-arm of a host whose jackd is deliberately stubbed (measured
        # load->GO 16s vs 1-2s on the test2 controller, regression window
        # 2026-07-23 -> 24 when this wait first deployed there). The client
        # property retries initialization once on this access, so a jackd
        # that just came up is still picked up.
        if self.conn_man.client is None:
            Logger.error(
                f"No JACK server available - cannot route {player_name} to the"
                f" mixer; cue will be SILENT despite showing armed status."
                f" (jackd absent or stubbed on this host - skipping the"
                f" {max_retries * retry_delay:.0f}s port wait.)"
            )
            return False

        # Wait for the player to report itself started (869fbyjzx). AFTER the
        # no-JACK fail-fast above: a JACK-stubbed host (the test2 controller)
        # must still return at once. Counted slices, not a monotonic deadline,
        # bound the wait, so a test can patch ready.wait. Whatever this phase
        # uses comes off the port wait below: one budget for both.
        port_attempts = max_retries
        if ready is not None:
            ready_slice = 0.05
            # Today's port wait sleeps between its checks, (max_retries - 1)
            # times: that total (14.5 s by default) is the whole budget.
            budget_s = max(0, max_retries - 1) * retry_delay
            ready_slices = max(1, int(round(budget_s / ready_slice)))
            ready_started = monotonic()
            slices_used = 0
            got_ready = False
            for _ in range(ready_slices):
                if ready.wait(ready_slice):
                    got_ready = True
                    break
                slices_used += 1
                if should_abort is not None and should_abort():
                    Logger.warning(
                        f"Player process for {player_name} exited before "
                        f"reporting RUNNING (waited "
                        f"{monotonic() - ready_started:.3f}s) - killed by a "
                        "STOP/load, or crashed. Not waiting any longer."
                    )
                    return False
            if got_ready:
                Logger.info(
                    f"Audio player {player_name} reported RUNNING after "
                    f"{monotonic() - ready_started:.3f}s"
                )
            else:
                Logger.warning(
                    f"Audio player {player_name} never reported RUNNING in "
                    f"{monotonic() - ready_started:.1f}s - wiring on port "
                    "presence (old or unusual player build)"
                )
            if retry_delay > 0:
                spent_attempts = int(slices_used * ready_slice / retry_delay)
                port_attempts = max(1, max_retries - spent_attempts)
            else:
                port_attempts = 1

        # Wait for player JACK ports to be available.
        # NOTE: gate ONLY on port_exists(); get_connections() returns [] (not
        # None) for a missing port, so the old 'connections is not None' guard
        # made this loop break immediately and connect a not-yet-registered
        # port -> jackd 'Unknown source port' -> silent-but-green cue.
        #
        # 869f79ecc: only the FAILURE path left a trace (DEBUG per retry,
        # WARNING on giving up); the success path -- which is every normal
        # arm -- logged nothing, so nobody could tell whether this ~15s
        # ceiling (max_retries * retry_delay) reflects real registration
        # latency or is just an untested guess. It IS a guess -- CLAUDE.md:91
        # explains the pipeline (OSC bind + RtMidi + FFmpeg probe before
        # RtAudio registers the port) but gives no distribution, and the
        # 2026-07 isil multilingual incident shows underestimating it once
        # already cost a real show. Log the success path so the fleet's own
        # journals can answer that instead of another guess.
        wait_started = monotonic()
        for attempt in range(port_attempts):
            if self.conn_man.port_exists(channel_0_output):
                Logger.info(
                    f"JACK port {channel_0_output} registered after "
                    f"{monotonic() - wait_started:.3f}s (attempt {attempt + 1}"
                    f"/{port_attempts})"
                )
                break
            if should_abort is not None and should_abort():
                # WARNING, not ERROR: after a STOP or a load this is the
                # expected end of an arm that was in flight. A crash lands
                # here too, and the caller's "will be SILENT" error covers it.
                Logger.warning(
                    f"Player process for {player_name} exited before "
                    f"registering its JACK ports (waited "
                    f"{monotonic() - wait_started:.3f}s, attempt {attempt + 1}"
                    f"/{port_attempts}) - killed by a STOP/load, or crashed. "
                    "Not waiting any longer."
                )
                return False
            if attempt < port_attempts - 1:
                Logger.debug(
                    f"Waiting for JACK port {channel_0_output} (attempt"
                    f"{attempt + 1}/{port_attempts})"
                )
                sleep(retry_delay)
        else:
            Logger.warning(
                f"JACK port {channel_0_output} not available after"
                f"{port_attempts} attempts"
            )
            return False

        # A stereo player registers outport 1 alongside outport 0, but the two
        # can surface a beat apart. Give outport 1 a brief, bounded grace window
        # before deciding mono vs stereo, so a lagging outport 1 is not mis-read
        # as mono (which would fan outport 0 to both sides and drop the right
        # channel). A genuinely mono player just waits out this short window.
        for _ in range(6):
            if self.conn_man.port_exists(channel_1_output):
                break
            sleep(0.05)

        # Check if player is stereo
        is_stereo = self.conn_man.port_exists(channel_1_output)
        Logger.debug(f"Player {player_name} is {'stereo' if is_stereo else 'mono'}")

        # First, disconnect any existing connections from player outputs
        # Guard with port_exists to avoid operating on destroyed ports.
        if self.conn_man.port_exists(channel_0_output):
            Logger.debug(f"Disconnecting existing connections from {channel_0_output}")
            channel_0_connections = self.conn_man.get_connections(channel_0_output)
            for connection in channel_0_connections:
                self.conn_man.disconnect_by_name(channel_0_output, connection)

        if is_stereo and self.conn_man.port_exists(channel_1_output):
            channel_1_connections = self.conn_man.get_connections(channel_1_output)
            for connection in channel_1_connections:
                self.conn_man.disconnect_by_name(channel_1_output, connection)

        expected = self._expected_edges(
            player_name,
            player_output_prefix,
            selected_outputs,
            is_stereo,
            log_missing_inputs=True,
        )
        if not expected:
            Logger.error(f"No valid mixer inputs found for outputs: {selected_outputs}")
            return False

        Logger.info(
            f"Connecting {player_name} to outputs:"
            f"{selected_outputs} -> {[dst for _src, dst in expected]}"
        )

        all_connected = True
        for src, dst in expected:
            Logger.debug(f"{src} → {dst}")
            ok = self.conn_man.connect_by_name(src, dst)
            all_connected = all_connected and ok

        if not all_connected:
            Logger.error(
                f"One or more mixer connections failed for {player_name};"
                "cue may be silent"
            )
        return all_connected

    def _expected_edges(
        self,
        player_name: str,
        player_output_prefix: str,
        selected_outputs: list,
        is_stereo: bool,
        log_missing_inputs: bool = False,
    ) -> list:
        """The (player outport, mixer input) edges a player should have.

        The ONE copy of the routing, used by the arm-time wiring
        (connect_player_to_outputs), the GO-time check
        (player_connection_diff) and the tests, so they cannot drift apart
        (869fbyjzx). Selected outputs map to mixer inputs through
        audio_outputs; inputs that do not exist are dropped, which shifts the
        L/R pairing exactly as the wiring does. The targets are treated as
        alternating L/R pairs: even-indexed targets (0, 2, 4 ...) get outport
        0, odd-indexed ones outport 1, or outport 0 again on a mono player.
        This covers 1, 2 or any number of outputs uniformly.

        Returns [] when no mixer input resolves.
        """
        if not selected_outputs:
            selected_outputs = ["system:playback_1", "system:playback_2"]
        channel_0_output = f"{player_name}:{player_output_prefix} 0"
        channel_1_output = f"{player_name}:{player_output_prefix} 1"
        output_to_input = {
            name: f"{self.client_name}:input_{i + 1}"
            for i, name in enumerate(self.audio_outputs)
        }
        target_inputs = []
        for output in selected_outputs:
            if output in output_to_input:
                mixer_input = output_to_input[output]
                if self.conn_man.port_exists(mixer_input):
                    target_inputs.append(mixer_input)
                elif log_missing_inputs:
                    Logger.warning(f"Mixer input {mixer_input} does not exist")
        edges = []
        for i, mixer_input in enumerate(target_inputs):
            if i % 2 == 0 or not is_stereo:
                edges.append((channel_0_output, mixer_input))
            else:
                edges.append((channel_1_output, mixer_input))
        return edges

    def player_connection_diff(
        self,
        player_name: str,
        player_output_prefix: str = "outport",
        selected_outputs: list = None,
    ):
        """Compare a player's outport edges with the expected wiring.

        Returns (missing, stray), two lists of (source, destination) edges:
        missing = expected edges that are not connected; stray = edges on the
        player's outports that are not expected (e.g. RtAudio's own
        auto-connect to system:playback, 869fcvz85). An edge is never in
        both. Returns None when the graph cannot be wired at all: outport 0
        does not exist (the subprocess is gone) or no mixer input resolves —
        callers must treat None as a silent cue, never as "correct".

        One get_connections per outport (outport 1 only on a stereo player):
        this runs on the GO path before /offset.
        """
        channel_0_output = f"{player_name}:{player_output_prefix} 0"
        channel_1_output = f"{player_name}:{player_output_prefix} 1"
        if not self.conn_man.port_exists(channel_0_output):
            return None
        is_stereo = self.conn_man.port_exists(channel_1_output)
        expected = self._expected_edges(
            player_name, player_output_prefix, selected_outputs, is_stereo
        )
        if not expected:
            return None
        ports = [channel_0_output] + ([channel_1_output] if is_stereo else [])
        present = {port: list(self.conn_man.get_connections(port)) for port in ports}
        missing = [(src, dst) for src, dst in expected if dst not in present[src]]
        wanted = set(expected)
        stray = [
            (port, dst)
            for port in ports
            for dst in present[port]
            if (port, dst) not in wanted
        ]
        return missing, stray

    def player_connections_correct(
        self,
        player_name: str,
        player_output_prefix: str = "outport",
        selected_outputs: list = None,
    ) -> bool:
        """True when the player is wired exactly as connect_player_to_outputs
        wires it: every expected edge present and nothing else on its
        outports. False on a missing edge, a stray edge, a missing outport 0
        (subprocess gone) or no mixer input. See player_connection_diff.
        """
        diff = self.player_connection_diff(
            player_name, player_output_prefix, selected_outputs
        )
        return diff is not None and not diff[0] and not diff[1]

    def repair_player_connections(self, missing: list, stray: list):
        """Fix a player's wiring edge by edge, never by a full rewire.

        A GO can reach this while the cue is audible (a fresh GO or a 'play'
        action on a playing cue), so a working mixer edge is never
        disconnected: strays are disconnected one by one, missing edges
        connected one by one (869fbyjzx).

        Each stray is re-checked just before its disconnect: one already gone
        (a stale diff, a re-arm wiring the same player) is skipped, because a
        failed disconnect resets the SHARED JACK client under any arm wiring
        at the same moment (JackConnectionManager.disconnect_by_name).

        Returns (connected_ok, strays_left): whether every missing edge got
        connected, and the strays whose disconnect failed.
        """
        strays_left = []
        for src, dst in stray:
            if not self.conn_man.is_connected(src, dst):
                continue
            if not self.conn_man.disconnect_by_name(src, dst):
                strays_left.append((src, dst))
        connected_ok = True
        for src, dst in missing:
            ok = self.conn_man.connect_by_name(src, dst)
            connected_ok = connected_ok and ok
        return connected_ok, strays_left

    @logged
    def disconnect_player(
        self, player_name: str, player_output_prefix: str = "outport"
    ):
        """Disconnect a player's outputs from the mixer.

        Must be called BEFORE the player's JACK client is destroyed (i.e.
        before
        sending /quit), otherwise JACK receives disconnect requests for ports
        that no longer exist, which can corrupt its shared memory registry.

        Args:
            player_name: Name of the player JACK client
            player_output_prefix: Prefix for player's output ports
        """
        channel_0_output = f"{player_name}:{player_output_prefix} 0"
        channel_1_output = f"{player_name}:{player_output_prefix} 1"

        for port_name in (channel_0_output, channel_1_output):
            if not self.conn_man.port_exists(port_name):
                continue
            connections = self.conn_man.get_connections(port_name)
            for connection in connections:
                Logger.debug(f"Disconnecting {port_name} from {connection}")
                self.conn_man.disconnect_by_name(port_name, connection)


def build_mixer_osc_endpoints(client_name: str, channel_number: int) -> dict:
    """Build OSC endpoint configuration for audio mixer.

    Creates OSC addresses in the format expected by jack-volume
    (audiomixer_routes branch):
    /audiomixer/{client_name}/master
    /audiomixer/{client_name}/0
    /audiomixer/{client_name}/1
    etc.

    Args:
        client_name: Name of the mixer client instance (JACK client name)
        channel_number: Number of audio channels in the mixer

    Returns:
        Dictionary of OSC endpoints with their configuration
    """
    endpoints = {}
    base_path = f"/audiomixer/{client_name}"

    # Master volume control
    endpoints[f"{base_path}/master"] = [ValueType.Float, None, 1.0]

    # Individual channel volume controls
    for i in range(channel_number):
        endpoints[f"{base_path}/{i}"] = [ValueType.Float, None, 1.0]

    return endpoints


class MixerClient(PlayerClient):
    """OSC Client for controlling the AudioMixer via jack-volume.

    Provides methods to control volume for individual channels and master
    volume.
    Uses OSC addresses: /audiomixer/<instance>/<channel>
    where channel can be 'master' or '0', '1', '2', etc.
    """

    def __init__(self, player_port: int, channel_number: int, mixer_id: str):
        """Initialize the MixerClient.

        Args:
            player_port: OSC port where jack-volume is listening
            channel_number: Number of audio channels in the mixer
            mixer_id: Unique identifier for this mixer
        """
        self.client_name = get_mixer_client_name(mixer_id)
        self.channel_number = channel_number

        # Shadow of the gain commanded to jack-volume via the typed setters
        # (jack-volume is write-only — it cannot be read back). Keys are
        # "master" and channel indices as strings ("0", "1", …); values are
        # linear gains. reset_volumes populates it (through apply_volume); the
        # node snapshots it to the controller after each reset so the UI can
        # read back the true (post-reset) mixer volume.
        self._gain_state: dict[str, float] = {}

        # Build OSC endpoint configuration for jack-volume
        endpoints = build_mixer_osc_endpoints(self.client_name, channel_number)

        super().__init__(
            player_port=player_port,
            endpoints=endpoints,
            name=f"mixer-{mixer_id}",
        )

    @logged
    def apply_volume(self, channel, gain: float) -> bool:
        """Send a volume to jack-volume AND record it in `_gain_state`.

        The typed setters (set_master_volume / set_channel_volume, hence
        reset_volumes) route through here, so a reset populates _gain_state with
        the values it commanded. The node snapshots that state to the controller
        right after each reset, letting the UI read back the true (post-reset)
        mixer gain — jack-volume itself is write-only.

        (Live per-cue UI writes stay on the raw set_value path and are shadowed
        controller-side; they are not recorded here because the node snapshots
        only on reset, never per write — a per-write report would race the
        controller's optimistic populate.)

        Args:
            channel: "master" or a 0-indexed channel (int or numeric string)
            gain: Volume gain (0.0 to 1.0)

        Returns:
            True if applied; False if gain/channel was invalid (no OSC sent,
            no state change) — same reject-and-no-op semantics the typed
            setters have always had.
        """
        if not 0.0 <= gain <= 1.0:
            Logger.error(f"Invalid gain value: {gain}. Must be between 0.0 and 1.0")
            return False

        ch = str(channel)
        if ch == "master":
            path = f"/audiomixer/{self.client_name}/master"
        else:
            try:
                ch_i = int(ch)
            except (TypeError, ValueError):
                Logger.error(f"Invalid mixer channel: {channel!r}")
                return False
            if not 0 <= ch_i < self.channel_number:
                Logger.error(f"Invalid channel: {ch_i}. Max: {self.channel_number - 1}")
                return False
            ch = str(ch_i)
            path = f"/audiomixer/{self.client_name}/{ch_i}"

        Logger.debug(f"Setting mixer {ch} volume to {gain}")
        self.set_value(path, gain)
        self._gain_state[ch] = gain
        return True

    def snapshot(self) -> dict:
        """Return a copy of the authoritative gain state for reporting.

        Shape: {"master": gain, "0": gain, "1": gain, …}.
        """
        return dict(self._gain_state)

    @logged
    def set_master_volume(self, gain: float):
        """Set the master volume gain.

        Args:
            gain: Volume gain (0.0 to 1.0)
        """
        self.apply_volume("master", gain)

    @logged
    def set_channel_volume(self, channel: int, gain: float):
        """Set volume for a specific channel.

        Args:
            channel: Channel number (0-indexed)
            gain: Volume gain (0.0 to 1.0)
        """
        self.apply_volume(channel, gain)

    @logged
    def set_all_channels_volume(self, gain: float):
        """Set volume for all channels (excluding master).

        Args:
            gain: Volume gain (0.0 to 1.0)
        """
        for i in range(self.channel_number):
            self.set_channel_volume(i, gain)

    @logged
    def reset_volumes(self):
        """Reset all volumes to maximum (1.0).

        Call this when loading a project or starting playback to ensure
        consistent volume levels.
        """
        Logger.info("Resetting mixer volumes to default (1.0)")
        self.set_master_volume(1.0)
        self.set_all_channels_volume(1.0)

    @logged
    def mute_channel(self, channel: int):
        """Mute a specific channel by setting its volume to 0.0.

        Args:
            channel: Channel number (0-indexed)
        """
        self.set_channel_volume(channel, 0.0)

    @logged
    def unmute_channel(self, channel: int, gain: float = 1.0):
        """Unmute a specific channel by setting its volume.

        Args:
            channel: Channel number (0-indexed)
            gain: Volume gain to restore (0.0 to 1.0), defaults to 1.0
        """
        self.set_channel_volume(channel, gain)

    @logged
    def mute_master(self):
        """Mute master volume."""
        self.set_master_volume(0.0)

    @logged
    def unmute_master(self, gain: float = 1.0):
        """Unmute master volume.

        Args:
            gain: Volume gain to restore (0.0 to 1.0), defaults to 1.0
        """
        self.set_master_volume(gain)

    @logged
    def add_to_oscquery_server(self, oscquery_server):
        """Add this mixer's OSC routes to a local OSCQuery server.

        This allows the mixer controls to be visible and controllable
        through the OSCQuery server interface.

        Args:
            oscquery_server: OssiaServer instance to add endpoints to
        """
        Logger.info(f"Adding mixer {self.client_name} to OSCQuery server")

        # Get endpoints from this client
        endpoints = self.get_endpoints()
        Logger.debug(f"Mixer endpoints: {list(endpoints.keys())}")

        # Create callback that forwards values from server to this client
        def server_to_client_callback(value):
            """Forward OSC values from server to mixer client."""
            Logger.debug(f"Forwarding value to mixer: {value}")
            # The value will be automatically sent to jack-volume via the OSC
            # client

        # Add callback to all endpoints
        endpoints_with_callbacks = add_callback_to_all(
            endpoints, server_to_client_callback
        )

        # Add endpoints to the OSCQuery server
        oscquery_server.add_endpoints(endpoints_with_callbacks)

        Logger.info(
            f"Mixer {self.client_name} added to OSCQuery server with"
            f"{len(endpoints)} endpoints"
        )


@logged
def start_audio_mixer(
    audio_outputs: list,
    port: int,
    mixer_id: str,
    path: str = None,
    args: str | None = None,
    timeout: float = 5.0,
) -> tuple[AudioMixer, MixerClient]:
    """Start an audio mixer and its OSC client.

    This function creates and starts a jack-volume mixer process and
    sets up an OSC client to control it.

    Args:
        audio_outputs: List of audio output configurations
        port: OSC port for jack-volume communication
        mixer_id: Unique identifier for this mixer
        path: Optional path to jack-volume binary
        args: Additional arguments for jack-volume
        timeout: Maximum time to wait for mixer to start (seconds)

    Returns:
        Tuple containing the AudioMixer and MixerClient instances

    Raises:
        RuntimeError: If mixer fails to start within timeout or thread dies
    """
    # Create the mixer
    mixer = AudioMixer(
        audio_outputs=audio_outputs,
        port=port,
        mixer_id=mixer_id,
        path=path,
        args=args,
    )

    # Start with timeout handling
    mixer.start(timeout=timeout)

    # Wait for jack-volume to fully initialize before connecting
    sleep(2)

    # Connect JACK ports
    mixer.connect_to_jack()

    # Create OSC client for controlling the mixer
    client = MixerClient(
        player_port=port, channel_number=len(audio_outputs), mixer_id=mixer_id
    )

    Logger.info(f"Audio mixer {mixer_id} started on port {port}")
    return mixer, client


# ###
# Helper functions
# ###
def get_mixer_client_name(mixer_id: str) -> str:
    """Get the client name for the mixer.

    Args:
        mixer_id: Unique identifier for this mixer

    Returns:
        Client name for the mixer
    """
    return f"{mixer_id}_mixer"
