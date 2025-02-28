class VideoPlayerRemote():
    def __init__(self, port, monitor_id, path, args, media):
        self.port = port
        self.monitor_id = monitor_id
        self.videoplayer = VideoPlayer(self.port, self.monitor_id, path, args, media)
        self.__start_remote()

    def __start_remote(self):
        self.remote_osc_xjadeo = ossia.ossia.OSCDevice("remoteXjadeo{}".format(self.monitor_id), "127.0.0.1", self.port, self.port+1)

        self.remote_xjadeo_quit_node = self.remote_osc_xjadeo.add_node("/jadeo/quit")
        self.xjadeo_quit_parameter = self.remote_xjadeo_quit_node.create_parameter(ossia.ValueType.Impulse)

        self.remote_xjadeo_seek_node = self.remote_osc_xjadeo.add_node("/jadeo/seek")
        self.xjadeo_seek_parameter = self.remote_xjadeo_seek_node.create_parameter(ossia.ValueType.Int)

        self.remote_xjadeo_load_node = self.remote_osc_xjadeo.add_node("/jadeo/load")
        self.xjadeo_load_parameter = self.remote_xjadeo_load_node.create_parameter(ossia.ValueType.String)

    def start(self):
        self.videoplayer.start()

    def kill(self):
        self.videoplayer.kill()

    def load(self, load_path):
        self.xjadeo_load_parameter.value = load_path

    def seek(self, frame):
        self.xjadeo_seek_parameter.value = frame

    def quit(self):
        self.xjadeo_quit_parameter.value = True
