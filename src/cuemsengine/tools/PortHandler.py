from cuemsutils.helpers import CuemsDict
from .system_ports import get_used_ports_with_pid

INITIAL_PORT = 9090
MAX_PORT = 9999

class PortHandler(object):
    ports = {None: {}}
    all_ports = []
    
    def __new__(cls):
        """
        Singleton pattern
        """
        if not hasattr(cls, '_instance'):
            cls._instance = super(PortHandler, cls).__new__(cls)
        return cls._instance
    
    def last_port(cls):
        return cls.ports[-1]
    
    def get_ports(cls, cue: CuemsDict):
        """
        Get the ports for a cue
        """
        return cls.ports.get(cue, None)
    
    def set_ports(cls, cue: CuemsDict, ports: list | dict, check_range: bool = True):
        """
        Set the ports for a cue
        """
        if cls.ports.get(cue) == ports:
            return
        ports_list = cls.check_ports(ports, check_range)
        cls.ports[cue] = ports
        cls.all_ports.extend(ports_list)

    def remove_ports(cls, cue: CuemsDict):
        """
        Remove the ports for a cue
        """
        if cls.ports.get(cue):
            p = cls.ports.pop(cue)
            new_ports = set(cls.all_ports) - set(p.values())
            cls.all_ports = list(new_ports)

    def get_all_ports(cls):
        return cls.all_ports

    def check_ports(cls, ports: list | dict, check_range: bool = True) -> list:
        """
        Check the ports for a cue
        """
        if isinstance(ports, dict):
            ports = [i for i in ports.values()]
        if len(ports) > len(set(ports)):
            raise ValueError(f"Duplicate ports found")
        if set(cls.all_ports) & set(ports):
            raise ValueError(f"Ports already in use: {set(cls.all_ports) & set(ports)}")
        if check_range:
            cls.check_port_range(ports)
        return ports

    def check_port_range(cls, ports: list) -> None:
        """
        Check the port range
        """
        for port in ports:
            if port > MAX_PORT:
                raise ValueError(f"Port {port} is too high")
            if port < INITIAL_PORT:
                raise ValueError(f"Port {port} is too low")

    def get_free_port(cls) -> int:
        """
        Get a free port
        """
        for port in range(INITIAL_PORT, MAX_PORT):
            if not set([port]) & set(cls.all_ports):
                return port
        raise ValueError(f"No free ports found")

    def find_system_ports(cls) -> list:
        """
        Find all system ports used on the system
        """
        return get_used_ports_with_pid()

    def add_system_ports(cls):
        """
        Add all system ports to the configuration dictionary
        """
        cls.add_config_ports(cls.find_system_ports())
    
    def add_config_ports(cls, ports: list | dict):
        """
        Add new ports to the configuration dictionary
        """
        config_ports = cls.get_ports(None)
        config_ports.update(ports)
        cls.set_ports(None, config_ports, check_range=False)
