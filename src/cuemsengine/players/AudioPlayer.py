from cuemsutils.log import logged

from .Player import Player

class AudioPlayer(Player):
    def __init__(self, port_index, path, args, media, uuid=None):
        super().__init__()
        self.port = port_index['start']
        while self.port in port_index['used']:
            self.port += 2

        port_index['used'].append(self.port)

        # self.card_id = card_id
        self.path = path
        self.args = args
        self.media = media
        self.uuid = uuid

    @logged
    def run(self):           
        # Calling audioplayer-cuems in a subprocess
        process_call_list = [self.path]
        if self.args:
            for arg in self.args.split():
                process_call_list.append(arg)
        process_call_list.extend(['--port', str(self.port)])
        if self.uuid != None:
            uuid_slug = self.uuid[32:]
            process_call_list.extend(['--uuid', uuid_slug])
        process_call_list.append(self.media)
        
        self.call_subprocess(process_call_list)
