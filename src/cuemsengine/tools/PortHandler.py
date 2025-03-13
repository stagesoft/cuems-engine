from cuemsutils.cues import Cue

INITIAL_PORT = 9090
MAX_PORT = 9999

class PortHandler(object):
    ports = {}
    
    def __new__(cls):
        """
        Singleton pattern
        """
        if not hasattr(cls, '_instance'):
            cls._instance = super(PortHandler, cls).__new__(cls)
        return cls._instance
    
    def last_port(cls):
        return cls.ports[-1]
    
    
    def get_ports(cls, cue: Cue):
        """
        Get the ports for a cue
        """
        return cls.ports.get(cue, None)
    
    def set_ports(cls, cue: Cue, ports: list):
        """
        Set the ports for a cue
        """
        cls.ports[cue] = ports
        return True
    
