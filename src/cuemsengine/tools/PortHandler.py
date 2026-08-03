# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

import socket
from random import sample
from threading import RLock

from cuemsutils.helpers import CuemsDict
from cuemsutils.log import Logger

from .system_ports import get_used_ports

# olad ports defaults to 9090 9010, raise de initial port to skip these ports
INITIAL_PORT = 9190
MAX_PORT = 9999

# Candidates bind-probed per batch before escalating to a system rescan.
PROBE_ATTEMPTS = 5


def port_is_bindable(port: int) -> bool:
    """
    True if nothing currently holds `port` on either TCP or UDP.

    Deliberately does NOT set SO_REUSEADDR: a socket lingering in TIME_WAIT
    should count as taken. IPv4 only — the whole CUEMS stack (avahi, the <ip>
    in network_map.xml, the NNG bus) is IPv4, and probing a family nothing
    uses would only mask real conflicts.

    Inherently advisory: the probe releases the port before the real consumer
    binds it. It shrinks the race window from "permanently blind" to
    microseconds, which is the same bargain tests/helpers.py::free_udp_port
    already makes.
    """
    for sock_type in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
        try:
            with socket.socket(socket.AF_INET, sock_type) as s:
                s.bind(("", port))
        except OSError:
            return False
    return True


class PortHandler(object):
    def __new__(cls):
        """
        Singleton class responsible for handling port objects.

        Ports come in three kinds, and they are NOT interchangeable:

        - *Reservations* — `_all_used_ports` (per cue), `_random_ports` (OSC
          clients) and `_pending` (drawn, not yet registered). These are ports
          this handler handed out. Double-booking one is a real error and may
          raise.
        - *Declarations* — `_config_ports`. Named service/config ports out of
          settings.xml. A declaration is a statement of fact, not a request to
          allocate, so registering one must never raise: two names may
          legitimately share a port, and a declared port may already be bound.
        - *Observations* — `_system_ports`. What `ss` currently sees bound on
          the host. Also never raises.

        All three are excluded from allocation; only reservations are
        validated by check_ports(). Conflating them is what made
        NodeEngine.__init__ crash in every earlier attempt at this fix
        (869ed9wf7).

        Thread-safe: internal state mutations are guarded by an RLock.
        """
        if not hasattr(cls, "_instance"):
            cls._instance = super(PortHandler, cls).__new__(cls)
            cls._instance._lock = RLock()
            cls._instance._ports = {None: {}}
            cls._instance._all_used_ports = []
            cls._instance._all_available_ports = set(range(INITIAL_PORT, MAX_PORT))
            cls._instance._random_ports = []
            cls._instance._pending = set()
            cls._instance._config_ports = set()
            cls._instance._system_ports = set()
        return cls._instance

    def assign_ports(self, names: list[str], cue: CuemsDict = None) -> dict:
        """Assign free ports to a list of names

        This method is thread-safe and should be the preferred way to assign
        ports to a list of names for a cue or config.

        Args:
            names: The names to assign ports to
            cue: The cue to assign ports to
        """
        # No outer lock: get_free_ports() and set_ports()/add_config_ports()
        # each lock internally. Holding it here would serialize every other
        # PORT_HANDLER operation behind the bind probes — and, on the degraded
        # path, behind an `ss` subprocess.
        new_ports = self.get_free_ports(len(names))
        out = {k: new_ports[i] for i, k in enumerate(names)}
        if cue is None:
            self.add_config_ports(out)
        else:
            self.set_ports(cue, out)
        return out

    def get_ports(self, cue: CuemsDict) -> dict | None:
        """
        Get the ports for a cue
        """
        with self._lock:
            return self._ports.get(cue, None)

    @staticmethod
    def _as_dict(ports: dict) -> dict:
        """
        Defensive copy of a caller's port mapping.

        Never alias the stored dict: add_config_ports() used to hand
        set_ports() the very object `_ports[None]` already held, making the
        `previous_ports == ports` comparison an identity check that always
        short-circuited — which is why the exclusion list stayed empty.
        """
        return dict(ports)

    def _release(self, values) -> None:
        """
        Drop these ports from the cue-scope reservations (multiset-safe).
        """
        with self._lock:
            remaining = list(self._all_used_ports)
            for p in values:
                if p in remaining:
                    remaining.remove(p)
            self._all_used_ports = remaining

    def set_ports(self, cue: CuemsDict, ports: dict, check_range: bool = True) -> None:
        """
        Set the ports for a cue, replacing any it previously held.

        Cue scope only — config ports go through add_config_ports(), which
        cannot raise.
        """
        if cue is None:
            raise ValueError(
                "set_ports() is cue-scoped; use add_config_ports() for config"
            )
        with self._lock:
            new_ports = self._as_dict(ports)
            previous_ports = self._ports.get(cue)
            if previous_ports == new_ports:
                return
            # Claim our own draws before validating, or check_ports() would
            # reject them as "already in use" against _pending.
            self._pending -= set(new_ports.values())
            # Release this cue's own reservations first, so re-arming onto a
            # port it already holds validates cleanly.
            if previous_ports:
                self._release(previous_ports.values())
            try:
                ports_list = self.check_ports(new_ports, check_range)
            except ValueError:
                if previous_ports:
                    self._all_used_ports.extend(previous_ports.values())
                raise
            self._all_used_ports.extend(ports_list)
            self._ports[cue] = new_ports

    def remove_ports(self, cue: CuemsDict):
        """
        Remove the ports for a cue
        """
        with self._lock:
            p = self._ports.pop(cue, None)
            if p is None:
                return
            self._release(p.values())

    def _reserved_ports(self) -> set[int]:
        """
        Ports THIS handler handed out — what double-booking is judged against.

        Deliberately excludes config declarations and system observations:
        those coinciding with a port is expected, not an error.
        """
        with self._lock:
            return (
                set[int](self._all_used_ports)
                | set[int](self._random_ports)
                | self._pending
            )

    def get_all_used_ports(self) -> set[int]:
        """
        Every port the allocator must avoid: reservations, config
        declarations and observed system sockets.
        """
        with self._lock:
            Logger.debug(f"All used ports: {self._all_used_ports}")
            Logger.debug(f"Random ports: {self._random_ports}")
            Logger.debug(f"Config ports: {sorted(self._config_ports)}")
            return self._reserved_ports() | self._config_ports | self._system_ports

    def check_ports(self, ports: list | dict, check_range: bool = True) -> list:
        """
        Check the ports for a cue and return the list of ports if they are
        valid

        Args:
            ports: The ports to check
            check_range: Whether to check the port range

        Returns:
            The ports list if they are valid

        Raises:
            ValueError:
            - If duplicate ports are found
            - If ports are already reserved
            - If check_range is True and the port range is invalid
        """
        if isinstance(ports, dict):
            ports = [i for i in ports.values()]
        if len(ports) > len(set[int](ports)):
            raise ValueError("Duplicate ports found")
        # Validate against reservations only — never get_all_used_ports().
        reserved = self._reserved_ports()
        if reserved & set[int](ports):
            raise ValueError(f"Ports already in use: {reserved & set[int](ports)}")
        if check_range:
            self.check_port_range(ports)
        return ports

    @staticmethod
    def check_port_range(ports: list) -> None:
        """
        Check the port range
        """
        for port in ports:
            if port > MAX_PORT:
                raise ValueError(f"Port {port} is too high")
            if port < INITIAL_PORT:
                raise ValueError(f"Port {port} is too low")

    def get_free_port(self) -> int:
        """
        Draw a free port and reserve it.

        The returned port is added to `_pending`, so a concurrent draw cannot
        return it too. It leaves `_pending` when set_ports(),
        add_config_ports() or store_random_port() registers it properly, or
        when release_pending()/clean_random_ports() gives it back.

        Candidates are bind-probed before being handed out — the startup
        snapshot alone cannot see anything that bound after it was taken.

        Returns:
            The free port

        Raises:
            ValueError: If no free port could be found and verified. Never
            returns an unverified port: handing one out is exactly the bug
            this method exists to prevent, and doing it when the pool is
            already degraded is the worst possible moment.
        """
        for attempt in range(3):
            if attempt == 2:
                # The cheap picture is stale. Now it is worth paying for a
                # rescan before giving up.
                Logger.warning(
                    f"No bindable port in {2 * PROBE_ATTEMPTS} draws; "
                    "rescanning system ports"
                )
                self.add_system_ports()
            with self._lock:
                available = self._all_available_ports - self.get_all_used_ports()
            if not available:
                raise ValueError("No free ports found")
            candidates = sample(sorted(available), min(len(available), PROBE_ATTEMPTS))
            # Probe outside the lock: bind/close syscalls must not serialize
            # every other PORT_HANDLER operation on the cue-arm path.
            for port in candidates:
                if not port_is_bindable(port):
                    continue
                with self._lock:
                    if port in self.get_all_used_ports():
                        continue  # raced with a concurrent draw
                    self._pending.add(port)
                    return port
        raise ValueError("No bindable free port found")

    def get_free_ports(self, n: int) -> list:
        """
        Get n free ports, in draw order.

        Distinct by construction: each draw reserves into `_pending` before
        returning, so the next one cannot pick it again.
        """
        return [self.get_free_port() for _ in range(n)]

    def release_pending(self, port: int):
        """
        Give back a port drawn by get_free_port() that will not be registered.
        """
        with self._lock:
            self._pending.discard(port)

    def find_system_ports(self) -> set[int]:
        """
        Find all ports currently bound on the system
        """
        return get_used_ports()

    def add_system_ports(self):
        """
        Snapshot every port currently bound on this host (observation only).
        """
        # Scan outside the lock — it spawns an `ss` subprocess.
        ports = self.find_system_ports()
        with self._lock:
            self._system_ports = ports

    def add_config_ports(self, ports: dict):
        """
        Merge named config/service ports into the config scope.

        NEVER raises. A config port is a *declaration* ("this port belongs to
        that service"), not a request to allocate. Two names may legitimately
        map to one port — stock settings.xml has `osc_in_port_base` 7000 and
        the videocomposer default is also 7000 — and a declared port may
        already be bound, as `oscquery_ws_port` 9190 is on a controller while
        the node engine starts. Neither is an error; both used to crash
        NodeEngine.__init__ once check_ports()'s guards were reachable.
        """
        with self._lock:
            self._ports[None].update(self._as_dict(ports))
            declared = set()
            for value in ports.values():
                try:
                    declared.add(int(value))
                except (TypeError, ValueError):
                    continue  # e.g. mtc_port is an ALSA client name
            self._config_ports |= declared
            self._pending -= declared

    def new_random_port(self) -> int:
        """
        Get a new random port and store it
        """
        port = self.get_free_port()
        self.store_random_port(port)
        return port

    def store_random_port(self, port: int):
        """
        Store a random port to the random ports set
        """
        with self._lock:
            self._random_ports.append(port)
            self._pending.discard(port)

    def remove_random_port(self, port: int):
        """
        Remove a specific port from the random ports list, freeing it for
        reuse.
        Called when an OSC client that owned the port is closed.
        """
        with self._lock:
            try:
                self._random_ports.remove(port)
            except ValueError:
                pass

    def clean_random_ports(self):
        """
        Clean the random ports set by keeping only ports that are in use by the
        system, and refresh the system snapshot with the scan it already pays
        for.

        Note this only started doing real work once get_used_ports() could see
        other users' sockets: the old scan returned almost nothing, so this
        wiped `_random_ports` wholesale on every project load. It now keeps
        genuinely-bound ports, and still self-heals — a port whose client died
        and released the socket drops out on the next load.
        """
        sys_ports = self.find_system_ports()
        with self._lock:
            self._system_ports = sys_ports
            self._random_ports = [i for i in self._random_ports if i in sys_ports]
            # Draws that were never registered are not coming back.
            self._pending.clear()


# ---------------------------
# Singleton
# ---------------------------

PORT_HANDLER = PortHandler()
