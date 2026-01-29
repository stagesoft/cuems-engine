from functools import singledispatch
from os import path

from cuemsutils.cues import AudioCue, DmxCue, VideoCue
from cuemsutils.cues.Cue import Cue
from cuemsutils.log import Logger

from ..players.PlayerHandler import PLAYER_HANDLER
from ..players import AudioClient, DmxClient, VideoClient

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
    
    Note: cue._local should be set by check_mappings() based on the output_name.
    For DMX cues, the output_name format is "{node_uuid}" (just the node UUID).
    A DMX cue can have multiple outputs (one per target node). check_mappings()
    should iterate through all outputs and set _local=True if ANY output_name
    matches the current node UUID. Other outputs are ignored.
    This function is only called for local cues (checked in CueHandler.arm()).
    """
    # Verify that _local is set (should be set by check_mappings() from output_name)
    is_local = getattr(cue, '_local', True)
    if not is_local:
        Logger.warning(
            f'DMX cue {cue.id} is not local but arm_dmxCue was called. '
            f'This should not happen - check_mappings() should set _local from output_name.',
            extra = {"caller": cue.__class__.__name__}
        )
        return
    
    # Get the local DMX player client
    dmx_client = PLAYER_HANDLER.get_dmx_player_client()
    
    if dmx_client is None:
        Logger.error(
            f'No local DMX player available for cue {cue.id}',
            extra = {"caller": cue.__class__.__name__}
        )
        return
    
    # Assign the local DMX player client to the cue
    cue._osc = dmx_client
    Logger.debug(
        f"DMX cue {cue.id} will use local DMX player (output_name inferred _local={is_local})",
        extra = {"caller": cue.__class__.__name__}
    )
    
    # Extract frame data from the DmxScene
    try:
        universe_frames = {}
        
        # Check if the cue has a DmxScene
        if cue.DmxScene is None:
            Logger.warning(
                f"DMX cue {cue.id} has no DmxScene data",
                extra = {"caller": cue.__class__.__name__}
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
                f"DMX cue {cue.id} armed: {len(universe_frames)} universe(s), {total_channels} channel(s)",
                extra = {"caller": cue.__class__.__name__}
            )
        else:
            Logger.warning(
                f"DMX cue {cue.id} armed but no channel data found in DmxScene",
                extra = {"caller": cue.__class__.__name__}
            )
            
    except Exception as e:
        Logger.error(
            f'Error arming DMX cue {cue.id}: {e}',
            extra = {"caller": cue.__class__.__name__}
        )
        Logger.exception(e)
        # Set empty frames to avoid errors when running
        cue._dmx_frames = {}

@arm_cue.register
def arm_videoCue(cue: VideoCue):
    try:
        PLAYER_HANDLER.set_video_player(cue)
    except ValueError as e:
        Logger.error(f'Error arming video player for cue {cue.id}: {e}')
        Logger.exception(e)
        return
                
    try:
        key = '/jadeo/cmd'
        cue._osc.set_value(key, 'midi disconnect')
        Logger.info(
            key + " " + str(cue._osc.get_node(key).parameter.value),
            extra = {"caller": cue.__class__.__name__}
        )
    except KeyError:
        Logger.debug(
            f'Key error 1 (disconnect) in arm_callback {key}',
            extra = {"caller": cue.__class__.__name__}
        )

    # TEMPORARY FIX for xjadeo: Only load the first video per output during arm.
    # xjadeo can only display one video at a time per instance. Loading subsequent
    # cues would overwrite the first one, breaking instant play.
    # Subsequent videos are loaded on-demand in run_videoCue.
    # TODO: Remove this check when migrating to multi-layer video player.
    output_name = PLAYER_HANDLER.get_cue_output_name(cue)
    if PLAYER_HANDLER.is_video_loaded_for_output(output_name):
        Logger.debug(
            f'Skipping video load during arm for cue {cue.id} - output {output_name} already has video loaded',
            extra = {"caller": cue.__class__.__name__}
        )
        return
    
    try:
        key = '/jadeo/load'
        value = PLAYER_HANDLER.media_path(cue.media['file_name'])
        cue._osc.set_value(key, value)
        PLAYER_HANDLER.mark_video_loaded_for_output(output_name)
        Logger.info(
            key + " " + str(cue._osc.get_node(key).parameter.value),
            extra = {"caller": cue.__class__.__name__}
        )
    except KeyError:
        Logger.debug(
            f'Key error 2 (load) in arm_callback {key}',
            extra = {"caller": cue.__class__.__name__}
        )
