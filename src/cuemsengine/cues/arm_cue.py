# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

from functools import singledispatch

from cuemsutils.cues import AudioCue, DmxCue, VideoCue
from cuemsutils.cues.Cue import Cue
from cuemsutils.log import Logger

from ..players.PlayerHandler import PLAYER_HANDLER


@singledispatch
def arm_cue(cue: Cue):
    """
    Type-specific logic when arming a cue
    """
    pass


@arm_cue.register
def arm_audioCue(cue: AudioCue):
    PLAYER_HANDLER.new_audio_output(cue)


@arm_cue.register
def arm_dmxCue(cue: DmxCue):
    """Arm a DMX cue by extracting DMX scene data.

    The DMX scene data is already loaded in the cue object from the script XML.
    We extract the universe and channel data from cue.DmxScene and store it
    in a format suitable for sending as OSC bundles to the local DMX player.

    Note: cue._local should be set by check_mappings() based on the
    output_name.
    For DMX cues, the output_name format is "{node_uuid}" (just the node UUID).
    A DMX cue can have multiple outputs (one per target node). check_mappings()
    should iterate through all outputs and set _local=True if ANY output_name
    matches the current node UUID. Other outputs are ignored.
    This function is only called for local cues (checked in CueHandler.arm()).
    """
    # Verify that _local is set (should be set by check_mappings() from
    # output_name)
    is_local = getattr(cue, "_local", True)
    if not is_local:
        Logger.warning(
            f"DMX cue {cue.id} is not local but arm_dmxCue was called. "
            f"This should not happen - check_mappings() should set _local"
            f"from output_name.",
            extra={"caller": cue.__class__.__name__},
        )
        return

    # Get the local DMX player client
    dmx_client = PLAYER_HANDLER.get_dmx_player_client()

    if dmx_client is None:
        Logger.error(
            f"No local DMX player available for cue {cue.id}",
            extra={"caller": cue.__class__.__name__},
        )
        return

    # Assign the local DMX player client to the cue
    cue._osc = dmx_client
    Logger.debug(
        f"DMX cue {cue.id} will use local DMX player (output_name inferred"
        f"_local={is_local})",
        extra={"caller": cue.__class__.__name__},
    )

    # Extract frame data from the DmxScene
    try:
        universe_frames = {}

        # Check if the cue has a DmxScene
        if cue.DmxScene is None:
            Logger.warning(
                f"DMX cue {cue.id} has no DmxScene data",
                extra={"caller": cue.__class__.__name__},
            )
            cue._dmx_frames = {}
            return

        # Extract universe data from the DmxScene
        dmx_universe = cue.DmxScene.DmxUniverse
        if dmx_universe is not None:
            universe_num = dmx_universe.universe_num
            channels_data = {}

            # Extract channel data from dmx_channels list
            if dmx_universe.dmx_channels:
                for dmx_channel in dmx_universe.dmx_channels:
                    channel_num = dmx_channel.channel
                    channel_value = dmx_channel.value
                    channels_data[channel_num] = channel_value

            if channels_data:
                universe_frames[universe_num] = channels_data

        # Store the parsed frame data in the cue for use when running
        cue._dmx_frames = universe_frames

        if universe_frames:
            total_channels = sum(len(channels) for channels in universe_frames.values())
            Logger.info(
                f"DMX cue {cue.id} armed: {len(universe_frames)} universe(s),"
                f"{total_channels} channel(s)",
                extra={"caller": cue.__class__.__name__},
            )
        else:
            Logger.warning(
                f"DMX cue {cue.id} armed but no channel data found in DmxScene",
                extra={"caller": cue.__class__.__name__},
            )

    except Exception as e:
        Logger.error(
            f"Error arming DMX cue {cue.id}: {e}",
            extra={"caller": cue.__class__.__name__},
        )
        Logger.exception(e)
        # Set empty frames to avoid errors when running
        cue._dmx_frames = {}


@arm_cue.register
def arm_videoCue(cue: VideoCue):
    try:
        client = PLAYER_HANDLER.get_video_client()
        if client is None:
            Logger.error(f"No video client available for cue {cue.id}")
            return
        cue._osc = client
    except Exception as e:
        Logger.error(f"Error retrieving video client for cue {cue.id}: {e}")
        Logger.exception(e)
        return

    output_names = PLAYER_HANDLER.get_all_cue_output_names(cue)
    if not output_names:
        Logger.error(f"No output names found for video cue {cue.id}")
        return

    video_path = PLAYER_HANDLER.media_path(cue.media["file_name"])
    media_w, media_h = PLAYER_HANDLER.media_dimensions(cue.media["file_name"])
    cue._layer_ids = []

    driver_layer_id = None
    for index, output_name in enumerate(output_names):
        layer_id = f"{cue.id}_{index}"

        if index == 0:
            # First output: normal load (creates decoder)
            client.set_value("/videocomposer/layer/load", [video_path, layer_id])
            driver_layer_id = layer_id
        else:
            # Subsequent outputs: share decoder from first layer
            client.set_value(
                "/videocomposer/layer/load_shared",
                [video_path, layer_id, driver_layer_id],
            )
        client.create_layer_endpoints(layer_id)

        layer_path = f"/videocomposer/layer/{layer_id}"
        client.set_value(f"{layer_path}/visible", 0)
        client.set_value(f"{layer_path}/autounload", 1)

        try:
            output = PLAYER_HANDLER.resolve_video_output_for_cue(cue, output_name)
            x, y = output.get_layer_placement()
            client.set_value(f"{layer_path}/position", [x, y])
            sx, sy = output.get_layer_scale(media_w, media_h)
            client.set_value(f"{layer_path}/scale", [sx, sy])
        except (KeyError, RuntimeError, ValueError) as e:
            Logger.warning(
                f'Video output "{output_name}" placement/scale failed'
                f"({type(e).__name__}: {e}), skipping for layer {layer_id}"
            )
        except Exception:
            Logger.exception(
                f"Unexpected error setting placement/scale for layer"
                f'{layer_id} (output "{output_name}")'
            )

        PLAYER_HANDLER.register_layer(layer_id)
        cue._layer_ids.append(layer_id)

    Logger.info(
        f"Video cue {cue.id} armed: {len(cue._layer_ids)} layer(s) for {video_path}"
    )
