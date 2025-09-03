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
    # Assign its own audioplayer object
    # try:
    #     cue._player = DmxPlayer(
    #         cue._conf.players_port_index, 
    #         cue._conf.node_conf['dmxplayer']['path'],
    #         str(cue._conf.node_conf['dmxplayer']['args']),
    #         str(
    #             path.join(
    #                 cue._conf.library_path,
    #                 'media',
    #                 cue.media['file_name']
    #             )
    #         )
    #     )
    # except Exception as e:
    #     raise e

    # cue._player.start()

    # And dinamically attach it to the ossia for remote control it
    cue._osc_route = f'/players/dmxplayer-{cue.uuid}'

    # ossia.add_player_nodes(
    #     PlayerOSCConfData( 
    #         device_name=cue._osc_route, 
    #         host=cue._conf.node_conf['osc_dest_host'], 
    #         in_port=cue._player.port,
    #         out_port=cue._player.port + 1, 
    #         dictionary=cue.OSC_DMXPLAYER_CONF
    #     )
    # )

@arm_cue.register
def arm_videoCue(cue: VideoCue):
    PLAYER_HANDLER.set_video_player(cue)
                
    try:
        key = '/jadeo/cmd'
        cue._osc.set_value(key, 'midi disconnect')
        Logger.info(
            key + " " + str(cue._osc.get_value(key)),
            extra = {"caller": cue.__class__.__name__}
        )
    except KeyError:
        Logger.debug(
            f'Key error 1 (disconnect) in arm_callback {key}',
            extra = {"caller": cue.__class__.__name__}
        )

    try:
        key = '/jadeo/load'
        value = str(path.join(cue._conf.library_path, 'media', cue.media.file_name))
        cue._osc.set_value(key, value)
        Logger.info(
            key + " " + str(cue._osc.get_value(key)),
            extra = {"caller": cue.__class__.__name__}
        )
    except KeyError:
        Logger.debug(
            f'Key error 2 (load) in arm_callback {key}',
            extra = {"caller": cue.__class__.__name__}
        )
