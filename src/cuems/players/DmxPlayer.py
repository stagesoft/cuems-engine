from cuemsutils.log import logged

from .Player import Player

class DmxPlayer(Player):
    def __init__(self, port_index, path, args, media):
        self.port = port_index['start']
        while self.port in port_index['used']:
            self.port += 2

        port_index['used'].append(self.port)
            
        self.stdout = None
        self.stderr = None
        # self.card_id = card_id
        self.path = path
        self.args = args
        self.media = media

    @logged
    def run(self):
        """Call dmxplayer-cuems in a subprocess"""
        process_call_list = [self.path]
        if self.args is not None:
            for arg in self.args.split():
                process_call_list.append(arg)
        process_call_list.extend(['--port', str(self.port), self.media])
        self.call_subprocess(process_call_list)
