from cuemsutils.helpers import CuemsDict
from cuemsutils.log import Logger
from random import choice
from threading import RLock

from .system_ports import get_used_ports_with_pid
 # olad ports defaults to 9090 9010, raise de initial port to skip these ports
INITIAL_PORT = 9190
MAX_PORT = 9999

class PortHandler(object):
    def __new__(cls):
        """
        Singleton class responsible for handling port objects.

        Holds a list of used ports and manages the assignment of new ports.
        The ports are assigned to a cue
        Config ports are ports that are ports assigned with None as key
        Thread-safe: internal state mutations are guarded by a Lock.
        """
        if not hasattr(cls, '_instance'):
            cls._instance = super(PortHandler, cls).__new__(cls)
            cls._instance._lock = RLock()
            cls._instance._ports = {None: {}}
            cls._instance._all_used_ports = []
            cls._instance._all_available_ports = set(range(INITIAL_PORT, MAX_PORT))
            cls._instance._random_ports = []
        return cls._instance
    
    def assign_ports(self, names: list[str], cue: CuemsDict = None) -> dict:
        """Assign free ports to a list of names

        This method is thread-safe and should be the preferred way to assign ports to a list of names for a cue or config.
        
        Args:
            names: The names to assign ports to
            cue: The cue to assign ports to
        """
        with self._lock:
            new_ports = self.get_free_ports(len(names))
        out = {k: new_ports[i] for i,k in enumerate(names)}
        if cue is None:
            self.add_config_ports(out)
        else:
            self.set_ports(cue, out)
        return out

    def last_port(self) -> int:
        """
        Get the last port
        """
        with self._lock:
            return self._ports[-1]
    
    def get_ports(self, cue: CuemsDict) -> dict | None:
        """
        Get the ports for a cue
        """
        with self._lock:
            return self._ports.get(cue, None)
    
    def set_ports(self, cue: CuemsDict, ports: list | dict, check_range: bool = True) -> None:
        """
        Set the ports for a cue
        """
        previous_ports = self.get_ports(cue)
        if previous_ports == ports:
            return
        ports_list = self.check_ports(ports, check_range)
        self._all_used_ports.extend(ports_list)
        if previous_ports is not None:
            ports.update(previous_ports)
        self._ports[cue] = ports

    def remove_ports(self, cue: CuemsDict):
        """
        Remove the ports for a cue
        """
        if self.get_ports(cue) is not None:
            with self._lock:
                p = self._ports.pop(cue)
                new_ports = set(self._all_used_ports) - set(p.values())
                self._all_used_ports = list(new_ports)

    def get_all_used_ports(self) -> list:
        """
        Get the list of all used ports
        """
        with self._lock:
            Logger.debug(f"All used ports: {self._all_used_ports}")
            Logger.debug(f'Random ports: {self._random_ports}')
            result = self._all_used_ports.extend(self._random_ports)
            if result is None:
                Logger.warning("get_all_used_ports is returning None")
                return set()
            else:
                return result

    def check_ports(self, ports: list | dict, check_range: bool = True) -> list:
        """
        Check the ports for a cue and return the list of ports if they are valid

        Args:
            ports: The ports to check
            check_range: Whether to check the port range

        Returns:
            The ports list if they are valid

        Raises:
            ValueError:
            - If duplicate ports are found
            - If ports are already in use
            - If check_range is True and the port range is invalid
        """
        if isinstance(ports, dict):
            ports = [i for i in ports.values()]
        if len(ports) > len(set(ports)):
            raise ValueError(f"Duplicate ports found")
        all_used_ports = set(self.get_all_used_ports())
        if all_used_ports & set(ports):
            raise ValueError(f"Ports already in use: {all_used_ports & set(ports)}")
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
        Get a free port

        Thread-safe: internal state mutations are guarded by a Lock.
        
        Returns:
            The free port
        Raises:
            ValueError: If no free ports are found
        """
        available_ports = self._all_available_ports - set(self.get_all_used_ports())
        if not available_ports:
            raise ValueError(f"No free ports found")
        return choice(list(available_ports))

    def get_free_ports(self, n: int) -> list:
        """
        Get n free ports
        """
        return [self.get_free_port() for _ in range(n)]

    def find_system_ports(self) -> list:
        """
        Find all system ports used on the system
        """
        return get_used_ports_with_pid()

    def add_system_ports(self):
        """
        Add all system ports to the configuration dictionary
        """
        self.add_config_ports(self.find_system_ports())
    
    def add_config_ports(self, ports: list | dict):
        """
        Add new ports to the configuration dictionary
        """
        with self._lock:
            config_ports = self.get_ports(None)
            config_ports.update(ports)
            self.set_ports(None, config_ports, check_range=False)

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

    def clean_random_ports(self):
        """
        Clean the random ports set by keeping only ports that are in use by the system
        """
        sys_ports = [i for i in self.find_system_ports().values() if i in self._random_ports]
        with self._lock:
            self._random_ports = [i for i in self._random_ports if i in sys_ports]

# ---------------------------
# Singleton
# ---------------------------

PORT_HANDLER = PortHandler()
