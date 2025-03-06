from functools import singledispatch
from os import path

from .Cue import Cue
from .AudioCue import AudioCue
from .DmxCue import DmxCue
from .VideoCue import VideoCue

from ..log import Logger

@singledispatch
def arm_cue(cue: Cue, ossia):
    """
    Type-specific logic when arming a cue
    """
    pass

@arm_cue.register
def _(cue: AudioCue, ossia):
    if cue._local:
        # Assign its own audioplayer object
        # try:
        #     cue._player = AudioPlayer(
        #         cue._conf.osc_port_index, 
        #         cue._conf.node_conf['audioplayer']['path'],
        #         cue._conf.node_conf['audioplayer']['args'],
        #         str(
        #             path.join(
        #                 cue._conf.library_path,
        #                 'media',
        #                 cue.media['file_name']
        #             )
        #         ),
        #         cue.uuid
        #     )
        # except Exception as e:
        #     raise e

        cue._player.start()

        cue._osc_route = f'/players/audioplayer-{cue.uuid}'

        # And dinamically attach it to the ossia for remote control it
        # ossia.add_player_nodes(
        #     PlayerOSCConfData(
        #         device_name=cue._osc_route, 
        #         host=cue._conf.node_conf['osc_dest_host'], 
        #         in_port=cue._player.port,
        #         out_port=cue._player.port + 1, 
        #         dictionary=cue.OSC_AUDIOPLAYER_CONF
        #     )
        # )



@arm_cue.register
def _(cue: DmxCue, ossia):
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
def _(cue: VideoCue, ossia):
    if cue._local:
        try:
            key = f'{cue._osc_route}/jadeo/cmd'
            ossia.send_message(key, 'midi disconnect')
            Logger.info(
                key + " " + str(ossia._oscquery_registered_nodes[key][0].value),
                extra = {"caller": cue.__class__.__name__}
            )
        except KeyError:
            Logger.debug(
                f'Key error 1 (disconnect) in arm_callback {key}',
                extra = {"caller": cue.__class__.__name__}
            )

        try:
            key = f'{cue._osc_route}/jadeo/load'
            value = str(path.join(cue._conf.library_path, 'media', cue.media.file_name))
            ossia.send_message(key, value)
            Logger.info(
                key + " " + str(ossia._oscquery_registered_nodes[key][0].value),
                extra = {"caller": cue.__class__.__name__}
            )
        except KeyError:
            Logger.debug(
                f'Key error 2 (load) in arm_callback {key}',
                extra = {"caller": cue.__class__.__name__}
            )
