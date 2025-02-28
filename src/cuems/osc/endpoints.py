from pyossia import ValueType

OSC_AUDIOPLAYER_CONF = {
    '/quit' : [ValueType.Impulse, None],
    '/load' : [ValueType.String, None], 
    '/vol0' : [ValueType.Float, None],
    '/vol1' : [ValueType.Float, None],
    '/volmaster' : [ValueType.Float, None],
    '/play' : [ValueType.Impulse, None],
    '/stop' : [ValueType.Impulse, None],
    '/stoponlost' : [ValueType.Int, None],
    '/mtcfollow' : [ValueType.Int, None],
    '/offset' : [ValueType.Float, None],
    '/check' : [ValueType.Impulse, None]
}

OSC_DMXPLAYER_CONF = { 
    '/quit' : [ValueType.Impulse, None],
    '/load' : [ValueType.String, None], 
    '/wait' : [ValueType.Float, None],
    '/play' : [ValueType.Impulse, None],
    '/stop' : [ValueType.Impulse, None],
    '/stoponlost' : [ValueType.Bool, None],
    # TODO '/mtcfollow' : [ValueType.Bool, None],
    '/offset': [ValueType.Float, None],
    '/check' : [ValueType.Impulse, None]
}

OSC_VIDEOPLAYER_CONF = {
    '/jadeo/xscale' : [ValueType.Float, None],
    '/jadeo/yscale' : [ValueType.Float, None], 
    '/jadeo/corners' : [ValueType.List, None],
    '/jadeo/corner1' : [ValueType.List, None],
    '/jadeo/corner2' : [ValueType.List, None],
    '/jadeo/corner3' : [ValueType.List, None],
    '/jadeo/corner4' : [ValueType.List, None],
    '/jadeo/start' : [ValueType.Int, None],
    '/jadeo/load' : [ValueType.String, None],
    '/jadeo/cmd' : [ValueType.String, None],
    '/jadeo/quit' : [ValueType.Int, None],
    '/jadeo/offset' : [ValueType.String, None],
    '/jadeo/offset.1' : [ValueType.Int, None],
    '/jadeo/midi/connect' : [ValueType.String, None],
    '/jadeo/midi/disconnect' : [ValueType.Int, None]
}

"""
OSC_REMOTE_ENGINE_CONF = {
    '/engine/command/load' : [ValueType.String, self.load_project_callback],
    '/engine/command/loadcue' : [ValueType.String, self.load_cue_callback],
    '/engine/command/go' : [ValueType.String, self.go_callback],
    '/engine/command/gocue' : [ValueType.String, self.go_cue_callback],
    '/engine/command/pause' : [ValueType.Impulse, self.pause_callback],
    '/engine/command/stop' : [ValueType.Impulse, self.stop_callback],
    '/engine/command/resetall' : [ValueType.String, self.reset_all_callback],
    '/engine/command/preload' : [ValueType.String, self.load_cue_callback],
    '/engine/command/unload' : [ValueType.String, self.unload_cue_callback],
    '/engine/command/hwdiscovery' : [ValueType.Impulse, self.hwdiscovery_callback],
    '/engine/command/deploy' : [ValueType.String, self.deploy_callback],
    '/engine/command/test' : [ValueType.String, self.test_callback],
    '/engine/comms/type' : [ValueType.String, self.comms_callback],
    '/engine/comms/subtype' : [ValueType.String, None],
    '/engine/comms/action' : [ValueType.String, None],
    '/engine/comms/action_uuid' : [ValueType.String, self.action_uuid_callback],
    '/engine/comms/value' : [ValueType.String, None],
    '/engine/comms/data' : [ValueType.String, None],
    '/engine/status/load' : [ValueType.String, None],
    '/engine/status/loadcue' : [ValueType.String, None],
    '/engine/status/go' : [ValueType.String, None],
    '/engine/status/gocue' : [ValueType.String, None],
    '/engine/status/pause' : [ValueType.String, None],
    '/engine/status/stop' : [ValueType.String, None],
    '/engine/status/resetall' : [ValueType.String, None],
    '/engine/status/preload' : [ValueType.String, None],
    '/engine/status/unload' : [ValueType.String, None],
    '/engine/status/hwdiscovery' : [ValueType.String, None],
    '/engine/status/deploy' : [ValueType.String, None],
    '/engine/status/test' : [ValueType.String, self.test_callback],
    '/engine/status/timecode' : [ValueType.Int, None], 
    '/engine/status/currentcue' : [ValueType.String, None],
    '/engine/status/nextcue' : [ValueType.String, None],
    '/engine/status/running' : [ValueType.Int, None]
}
"""
