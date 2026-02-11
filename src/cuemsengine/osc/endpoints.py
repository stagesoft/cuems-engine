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

OSC_AUDIOMIXER_CONF = {
    '/master' : [ValueType.Float, None],
    '/0' : [ValueType.Float, None],
    '/1' : [ValueType.Float, None],
    '/2' : [ValueType.Float, None],
    '/3' : [ValueType.Float, None],
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
    '/jadeo/offset' : [ValueType.Int, None],  # Changed to Int - xjadeo handles /jadeo/offset with "i" type
    '/jadeo/midi/connect' : [ValueType.String, None],
    '/jadeo/midi/disconnect' : [ValueType.Int, None],
    '/jadeo/ontop' : [ValueType.Bool, None]
}

OSC_PLAYERS_DICT = {
    'audio/cue': OSC_AUDIOPLAYER_CONF,
    'audio/mixer': OSC_AUDIOMIXER_CONF,
    'dmx/mixer': OSC_DMXPLAYER_CONF,
    'video/mixer': OSC_VIDEOPLAYER_CONF
}

OSC_ENGINE_CMD_CONF = {
    '/engine/command/load' : [ValueType.String, None],
    '/engine/command/loadcue' : [ValueType.String, None],
    '/engine/command/go' : [ValueType.String, None],
    '/engine/command/gocue' : [ValueType.String, None],
    '/engine/command/pause' : [ValueType.String, None],
    '/engine/command/stop' : [ValueType.String, None],
    '/engine/command/resetall' : [ValueType.String, None],
    '/engine/command/preload' : [ValueType.String, None],
    '/engine/command/unload' : [ValueType.String, None],
    '/engine/command/hwdiscovery' : [ValueType.Impulse, None],
    '/engine/command/deploy' : [ValueType.String, None],
    '/engine/command/test' : [ValueType.String, None],
    '/engine/command/update' : [ValueType.String, None]
}
