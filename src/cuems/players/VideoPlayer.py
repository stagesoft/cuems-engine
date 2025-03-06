from subprocess import Popen, PIPE, STDOUT, CalledProcessError
from cuemsutils.log import logged

from .Player import Player

class VideoPlayer(Player):
    def __init__(self, port, output, path, args, media):
        super().__init__()
        self._port = port
        self.output = output
        self.path = path
        self.args = args
        self.media = media

        self.stdout = None
        self.stderr = None

    @logged
    def run(self):
        # Calling xjadeo in a subprocess
        process_call_list = [self.path]
        if self.args:
            for arg in self.args.split():
                process_call_list.append(arg)
        process_call_list.extend(['--osc', str(self._port), '--start-screen', self.output, self.media])

        self.call_subprocess(process_call_list)

    def port(self):
        return self._port
