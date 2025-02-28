class NodeVideoPlayers():
    def __init__(self, videoplayer_settings):
        self.vplayer=[None]*videoplayer_settings["outputs"]
        for i, v in enumerate(self.vplayer):
            self.vplayer[i] = VideoPlayerRemote(videoplayer_settings["instance"][i]["osc_in_port"], i, videoplayer_settings["path"])
    
    def __getitem__(self, subscript):
        return self.vplayer[subscript]

    def len(self):
        return len(self.vplayer)
