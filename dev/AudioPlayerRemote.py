class AudioPlayerRemote():
    # class that exposes osc control of the player and manages the player
    def __init__(self, port, card_id, path, args, media):
        self.port = port
        self.card_id = card_id
        self.audioplayer = AudioPlayer(self.port, self.card_id, path, args, media)
        self.__start_remote()

    def __start_remote(self):
        self.remote_osc_audioplayer = ossia.ossia.OSCDevice("remoteAudioPlayer{}".format(self.card_id), "127.0.0.1", self.port, self.port+1)

        self.remote_audioplayer_quit_node = self.remote_osc_audioplayer.add_node("/audioplayer/quit")
        self.audioplayer_quit_parameter = self.remote_audioplayer_quit_node.create_parameter(ossia.ValueType.Impulse)

        self.remote_audioplayer_level_node = self.remote_osc_audioplayer.add_node("/audioplayer/level")
        self.audioplayer_level_parameter = self.remote_audioplayer_level_node.create_parameter(ossia.ValueType.Int)

        self.remote_audioplayer_load_node = self.remote_osc_audioplayer.add_node("/audioplayer/load")
        self.audioplayer_load_parameter = self.remote_audioplayer_load_node.create_parameter(ossia.ValueType.String)

    def start(self):
        self.audioplayer.start()

    def kill(self):
        self.audioplayer.kill()

    def load(self, load_path):
        self.audioplayer_load_parameter.value = load_path

    def level(self, level):
        self.audioplayer_level_parameter.value = level

    def quit(self):
        self.audioplayer.kill()
        self.audioplayer_quit_parameter.value = True
