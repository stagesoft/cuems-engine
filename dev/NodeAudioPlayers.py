class NodeAudioPlayers():
    # class to group  al the audio players in a node

    def __init__(self, audioplayer_settings):
        #initialize array to store the player with the number of audio cards we have ( no more players than audio outputs for the moment)
        self.aplayer=[None]*audioplayer_settings["audio_cards"]
        #start a remote controller for each audio output (could be multiple channels), it will controll it own player
        for i, v in enumerate(self.aplayer):
            self.aplayer[i] = AudioPlayerRemote(audioplayer_settings["instance"][i]["osc_in_port"], i, audioplayer_settings["path"])
    
    def __getitem__(self, subscript):
        return self.aplayer[subscript]

    def len(self):
        return len(self.aplayer)
