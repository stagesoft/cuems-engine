from conn_jack import JackConnectionManager
from cuemsengine.players.Player import Player
from time import sleep

JACK_VOUME_PATH = '/usr/local/bin/jack-volume'
# usage: jack-volume [-c <jack_client_name>] [-s <jack_server_name>] [-p <osc_port>] [-n <number_of_channels>]

class AudioMixer(Player):

    def __init__(self, audio_outputs, port, node_uuid, path=None):
        self.conn_man = JackConnectionManager()
        self.node_uuid = node_uuid
        self.ports = self.conn_man.get_ports()
        if not self.path:
            self.path = JACK_VOUME_PATH
        self.channel_number = len(audio_outputs)
        self.args =[]
        self.args.append(f'-c')
        self.args.append(f'{self.node_uuid}_mixer')
        self.args.append(f'-p')
        self.args.append(str(port))
        self.args.append(f'-n')
        self.args.append(f'{self.channel_number}')
        self.run()
        sleep(2)  # wait for jack-volume to start up before connecting to it
        self.connect_to_jack()
    #    self.connect_player_to_mixe(self, player_id)



    def connect_to_jack(self):
        for i in range(self.channel_number):
            self.conn_man.connect_by_name(f"{self.node_uuid}_mixer:output_{i+1}", "system:playback_{i+1}")

    def connect_player_to_mixer(self, player_id):
        self.conn_man.connect_by_name(f"a", "{self.node_uuid}_mixer:input_1")
        self.conn_man.connect_by_name(f"a", "{self.node_uuid}_mixer:input_2")

    def run(self):
        process_call_list = [self.path]
        for arg in self.args.split():
            process_call_list.append(arg)
        self.call_subprocess(process_call_list)
        