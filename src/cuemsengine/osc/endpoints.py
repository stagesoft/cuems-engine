# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

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
    '/check' : [ValueType.Impulse, None],
    '/blackout' : [ValueType.Impulse, None],  # Clear all scenes/fades, send zeros to OLA
    '/stoponlost' : [ValueType.Bool, None],
    '/mtcfollow' : [ValueType.Bool, None],
    '/frame' : [ValueType.List, None],        # [universe_id, ch0, val0, ch1, val1, ...]
    '/fade_time' : [ValueType.Float, None],   # Fade duration in seconds
    '/mtc_time' : [ValueType.String, None],   # MTC time as string ("now", "+H:M:S", "H:M:S")
    '/start_offset' : [ValueType.Int, None],  # Start offset in milliseconds
}

# Endpoint format: path : [ValueType, callback, default_value, repetition_filter]
# Impulse endpoints must always use False for repetition_filter (also enforced
# in OssiaNodes.set_parameter) — pyossia silently drops repeated Impulse sends
# when the filter is ON.
OSC_VIDEOPLAYER_CONF = {
    '/videocomposer/check' : [ValueType.Impulse, None, None, False],  # no RepetitionFilter (Impulse)
    '/videocomposer/quit' : [ValueType.Impulse, None, None, False],  # no RepetitionFilter (Impulse)
    '/videocomposer/display/list' : [ValueType.Impulse, None, None, False],  # no RepetitionFilter (Impulse)
    '/videocomposer/display/modes' : [ValueType.String, None],
    '/videocomposer/display/resolution_mode' : [ValueType.String, None], # e.g. "1080p", "native", "maximum", "720p", "4k", "" empty string shows available modes
    '/videocomposer/display/mode' : [ValueType.List, None], # [output_name, width, height, refresh_rate]
    '/videocomposer/display/region' : [ValueType.List, None], # [output_name, x, y, width, height]
    '/videocomposer/display/blend' : [ValueType.List, None], # [output_name, left, right, top, bottom, gamma]
    '/videocomposer/display/warp' : [ValueType.List, None], # [output_name, mesh_path]
    '/videocomposer/display/save' : [ValueType.String, None], # [file_path]
    '/videocomposer/display/load' : [ValueType.String, None], # [file_path]
    '/videocomposer/reset' : [ValueType.Impulse, None, None, False],  # Remove all layers, cancel loads, reset master — no RepetitionFilter (Impulse)
    '/videocomposer/layer/load' : [ValueType.List, None, None, False], # [file_path, layer_id] — no RepetitionFilter (command endpoint)
    '/videocomposer/layer/load_shared' : [ValueType.List, None, None, False], # [file_path, layer_id, driver_layer_id] — shared decoder (same cue, multiple outputs)
    '/videocomposer/layer/unload' : [ValueType.String, None, None, False], # [layer_id] — no RepetitionFilter (command endpoint)
    '/videocomposer/output/capture' : [ValueType.List, None], # [ status|disable|[enable width height] ]
}

OSC_VIDEOPLAYER_LAYER_CONF = {
    '/videocomposer/layer/{}/play' : [ValueType.Impulse, None],
    '/videocomposer/layer/{}/pause' : [ValueType.Impulse, None],
    '/videocomposer/layer/{}/offset' : [ValueType.Int, None],
    '/videocomposer/layer/{}/mtcfollow' : [ValueType.Int, None],  # 1 = enable, 0 = disable
    '/videocomposer/layer/{}/visible' : [ValueType.Int, None, -1],
    '/videocomposer/layer/{}/autounload' : [ValueType.Int, None], # 0 or 1
    '/videocomposer/layer/{}/loop' : [ValueType.Int, None], # 1 = enable loop, 0 = disable
    '/videocomposer/layer/{}/opacity' : [ValueType.Float, None], # opacity (0.0 to 1.0)
    '/videocomposer/layer/{}/position' : [ValueType.List, None], # [x, y] (x and y are pixel coordinates of the screen)
    '/videocomposer/layer/{}/scale' : [ValueType.List, None], # [x, y] (x and y are scale ratio of the layer)
    '/videocomposer/layer/{}/rotation' : [ValueType.Float, None], # rotation in degrees
    '/videocomposer/layer/{}/zorder' : [ValueType.Int, None], # z-order of the layer (higher numbers are in front)
    '/videocomposer/layer/{}/corner_deform' : [ValueType.List, None], # [x0, y0, offset0, ..., x3, y3, offset3] (x and y are pixel coordinates of the corner, offset is the deformation amount)
    '/videocomposer/layer/{}/corner_deform_enable' : [ValueType.Int, None], # Enable / Disable corner deformation [0 or 1]
    '/videocomposer/layer/{}/corner_deform_hq' : [ValueType.Int, None], # Enable / Disable high-quality mode [0 or 1]
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
    '/engine/command/go' : [ValueType.Impulse, None],
    '/engine/command/gocue' : [ValueType.Impulse, None],
    '/engine/command/pause' : [ValueType.Impulse, None],
    '/engine/command/stop' : [ValueType.Impulse, None],
    '/engine/command/resetall' : [ValueType.String, None],
    '/engine/command/preload' : [ValueType.String, None],
    '/engine/command/unload' : [ValueType.String, None],
    '/engine/command/hwdiscovery' : [ValueType.Impulse, None],
    '/engine/command/deploy' : [ValueType.String, None],
    '/engine/command/test' : [ValueType.String, None],
    '/engine/command/update' : [ValueType.String, None]
}
