# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

from pyossia import ValueType

OSC_AUDIOPLAYER_CONF = {
    "/quit": [ValueType.Impulse, None],
    "/load": [ValueType.String, None],
    "/vol0": [ValueType.Float, None],
    "/vol1": [ValueType.Float, None],
    "/volmaster": [ValueType.Float, None],
    "/play": [ValueType.Impulse, None],
    "/stop": [ValueType.Impulse, None],
    "/stoponlost": [ValueType.Int, None],
    "/mtcfollow": [ValueType.Int, None],
    "/offset": [ValueType.Float, None],
    "/check": [ValueType.Impulse, None],
    # 869ejxng3 + 1amfwm7e6cw (plan §4.2): sent only to a player that printed
    # "CAPS: loop varispeed". /loop is i:passes [i:period_num i:period_den]
    # (passes 1 = once, N >= 2 = wrap N-1 times, <= 0 = forever). /start_tod is
    # the cue start as MTC position modulo 24 h in whole ms (int32), sent only
    # to a player whose CAPS line carries "dayalign" (cuems-RELATIONS
    # Plans/2026-10-25-mtc-day-align-24h-wrap.md §7.2; it replaced /offset_i).
    # /offset stays Float for every other player. Both with the repetition
    # filter OFF: the same value is re-sent per pass.
    "/loop": [ValueType.List, None, None, False],
    "/start_tod": [ValueType.Int, None, None, False],
}

OSC_AUDIOMIXER_CONF = {
    "/master": [ValueType.Float, None],
    "/0": [ValueType.Float, None],
    "/1": [ValueType.Float, None],
    "/2": [ValueType.Float, None],
    "/3": [ValueType.Float, None],
}

OSC_DMXPLAYER_CONF = {
    "/quit": [ValueType.Impulse, None],
    "/check": [ValueType.Impulse, None],
    # Clear all scenes/fades, send zeros to OLA
    "/blackout": [ValueType.Impulse, None],
    "/stoponlost": [ValueType.Bool, None],
    "/mtcfollow": [ValueType.Bool, None],
    # [universe_id, ch0, val0, ch1, val1, ...]
    "/frame": [ValueType.List, None],
    "/fade_time": [ValueType.Float, None],  # Fade duration in seconds
    "/mtc_time": [
        ValueType.String,
        None,
    ],  # MTC time as string ("now", "+H:M:S", "H:M:S")
    "/start_offset": [ValueType.Int, None],  # Start offset in milliseconds
}

# Endpoint format: path : [ValueType, callback, default_value,
# repetition_filter]
# Impulse endpoints must always use False for repetition_filter (also enforced
# in OssiaNodes.set_parameter) — pyossia silently drops repeated Impulse sends
# when the filter is ON.
OSC_VIDEOPLAYER_CONF = {
    "/videocomposer/check": [
        ValueType.Impulse,
        None,
        None,
        False,
    ],  # no RepetitionFilter (Impulse)
    "/videocomposer/quit": [
        ValueType.Impulse,
        None,
        None,
        False,
    ],  # no RepetitionFilter (Impulse)
    "/videocomposer/display/list": [
        ValueType.Impulse,
        None,
        None,
        False,
    ],  # no RepetitionFilter (Impulse)
    "/videocomposer/display/modes": [ValueType.String, None],
    "/videocomposer/display/resolution_mode": [
        ValueType.String,
        None,
    ],  # e.g. "1080p", "native", "720p", "4k"; "" shows available modes
    "/videocomposer/display/mode": [
        ValueType.List,
        None,
    ],  # [output_name, width, height, refresh_rate]
    "/videocomposer/display/region": [
        ValueType.List,
        None,
    ],  # [output_name, x, y, width, height]
    "/videocomposer/display/blend": [
        ValueType.List,
        None,
    ],  # [output_name, left, right, top, bottom, gamma]
    # [output_name, mesh_path]
    "/videocomposer/display/warp": [ValueType.List, None],
    "/videocomposer/display/save": [ValueType.String, None],  # [file_path]
    "/videocomposer/display/load": [ValueType.String, None],  # [file_path]
    "/videocomposer/reset": [
        ValueType.Impulse,
        None,
        None,
        False,
    ],  # Remove all layers, cancel loads, reset master (Impulse)
    "/videocomposer/layer/load": [
        ValueType.List,
        None,
        None,
        False,
    ],  # [file_path, layer_id] — no RepetitionFilter (command endpoint)
    "/videocomposer/layer/load_shared": [
        ValueType.List,
        None,
        None,
        False,
    ],  # [file_path, layer_id, driver_layer_id] — shared decoder
    "/videocomposer/layer/unload": [
        ValueType.String,
        None,
        None,
        False,
    ],  # [layer_id] — no RepetitionFilter (command endpoint)
    "/videocomposer/output/capture": [
        ValueType.List,
        None,
    ],  # [ status|disable|[enable width height] ]
}

OSC_VIDEOPLAYER_LAYER_CONF = {
    "/videocomposer/layer/{}/play": [ValueType.Impulse, None],
    "/videocomposer/layer/{}/pause": [ValueType.Impulse, None],
    "/videocomposer/layer/{}/offset": [ValueType.Int, None],
    "/videocomposer/layer/{}/mtcfollow": [
        ValueType.Int,
        None,
    ],  # 1 = enable, 0 = disable
    "/videocomposer/layer/{}/visible": [ValueType.Int, None, -1],
    "/videocomposer/layer/{}/autounload": [ValueType.Int, None],  # 0 or 1
    "/videocomposer/layer/{}/loop": [
        ValueType.Int,
        None,
    ],  # 1 = enable loop, 0 = disable
    # opacity (0.0 to 1.0)
    "/videocomposer/layer/{}/opacity": [ValueType.Float, None],
    "/videocomposer/layer/{}/position": [
        ValueType.List,
        None,
    ],  # [x, y] (x and y are pixel coordinates of the screen)
    "/videocomposer/layer/{}/scale": [
        ValueType.List,
        None,
    ],  # [x, y] (x and y are scale ratio of the layer)
    # rotation in degrees
    "/videocomposer/layer/{}/rotation": [ValueType.Float, None],
    "/videocomposer/layer/{}/zorder": [
        ValueType.Int,
        None,
    ],  # z-order of the layer (higher numbers are in front)
    "/videocomposer/layer/{}/corner_deform": [
        ValueType.List,
        None,
    ],  # [x0, y0, offset0, ..., x3, y3, offset3] corner pixel coords
    "/videocomposer/layer/{}/corner_deform_enable": [
        ValueType.Int,
        None,
    ],  # Enable / Disable corner deformation [0 or 1]
    "/videocomposer/layer/{}/corner_deform_hq": [
        ValueType.Int,
        None,
    ],  # Enable / Disable high-quality mode [0 or 1]
}

OSC_PLAYERS_DICT = {
    "audio/cue": OSC_AUDIOPLAYER_CONF,
    "audio/mixer": OSC_AUDIOMIXER_CONF,
    "dmx/mixer": OSC_DMXPLAYER_CONF,
    "video/mixer": OSC_VIDEOPLAYER_CONF,
}

OSC_ENGINE_CMD_CONF = {
    "/engine/command/load": [ValueType.String, None],
    "/engine/command/loadcue": [ValueType.String, None],
    "/engine/command/go": [ValueType.Impulse, None],
    "/engine/command/gocue": [ValueType.Impulse, None],
    "/engine/command/pause": [ValueType.Impulse, None],
    "/engine/command/stop": [ValueType.Impulse, None],
    "/engine/command/resetall": [ValueType.String, None],
    "/engine/command/preload": [ValueType.String, None],
    "/engine/command/unload": [ValueType.String, None],
    "/engine/command/hwdiscovery": [ValueType.Impulse, None],
    "/engine/command/deploy": [ValueType.String, None],
    "/engine/command/test": [ValueType.String, None],
    "/engine/command/update": [ValueType.String, None],
}
