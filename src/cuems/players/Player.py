from subprocess import Popen, PIPE, STDOUT, CalledProcessError
from threading import Thread

from cuemsutils.log import logged, Logger

class Player(Thread):
    """Base class for all players in the system.
        Holds the common methods and attributes for all players.
        Extends the Thread class.
        Can call a subprocess, kill it and start the Thread.

        IMPORTANT: The run method must be implemented in the child classes.

    """
    def __init__(self, daemon: bool = True):
        """Initializes the Player object and a Thread object with the daemon attribute set to True.
        
        Args:
            daemon (bool, optional): Sets the daemon attribute of the Thread object. Defaults to True.
        """
        super().__init__(daemon = daemon)
        self.p = None
        self.firstrun = True
        self.started = False

    def run(self):
        raise NotImplementedError
    
    @logged
    def call_subprocess(self, call_args):
        """Calls a subprocess with the given arguments."""
        try:
            self.p = Popen(call_args, stdout=PIPE, stderr=STDOUT)
            stdout_lines_iterator = iter(self.p.stdout.readline, b'')
            while self.p.poll() is None:
                for line in stdout_lines_iterator:
                    Logger.log_info(line, {'caller': self.ident})
        except CalledProcessError as e:
            if self.p.returncode < 0:
                raise CalledProcessError(self.p.returncode, self.p.args)

    @logged
    def kill(self):
        """Kills the subprocess."""
        if self.p:
            self.p.kill()
            self.started = False
    
    @logged    
    def start(self):
        """Starts the player."""
        if self.firstrun:
            super().start()
            self.firstrun = False
        if not self.is_alive():
            super().start()
        self.started = True
