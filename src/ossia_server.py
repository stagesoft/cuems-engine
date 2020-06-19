import pyossia as ossia
import time
import re

import config

from VideoPlayer import NodeVideoPlayers
from AudioPlayer import NodeAudioPlayers
from log import *
from Settings import Settings

if __debug__:
    logging.debug("Debug mode")

settings = Settings("settings.xsd", "settings.xml")
settings.read()


#print(settings.schema)

settings_node_0 = settings["node"][0]

videoplayer_settings = settings_node_0["videoplayer"]
audioplayer_settings = settings_node_0["audioplayer"]

video_players = NodeVideoPlayers(videoplayer_settings)
audio_players = NodeAudioPlayers(audioplayer_settings)


local_device = ossia.LocalDevice("Node {}".format(settings_node_0["@id"]))

local_device.create_oscquery_server(
    settings_node_0['osc_out_port'], settings_node_0['osc_in_port'], True)

print("OscQuery device listening on port {}".format(
    settings_node_0['osc_in_port']))

video_nodes = {}
audio_nodes = {}


for display_id, videoplayer in enumerate(video_players):

    # TODO: extract parameters from html

    video_nodes["start{}".format(display_id)] = local_device.add_node(
        "/node{}/videoplayer{}/start".format(config.settings["node_id"], display_id))
    #video_node.critical = True
    video_nodes["start{}".format(display_id)].create_parameter(
        ossia.ValueType.Bool)
    video_nodes["start{}".format(
        display_id)].parameter.access_mode = ossia.AccessMode.Bi
    video_nodes["start{}".format(display_id)].parameter.value = False

    video_nodes["load{}".format(display_id)] = local_device.add_node(
        "/node{}/videoplayer{}/load".format(config.settings["node_id"], display_id))
    video_nodes["load{}".format(display_id)].create_parameter(
        ossia.ValueType.String)
    video_nodes["load{}".format(
        display_id)].parameter.access_mode = ossia.AccessMode.Set

    video_nodes["seek{}".format(display_id)] = local_device.add_node(
        "/node{}/videoplayer{}/seek".format(config.settings["node_id"], display_id))
    video_nodes["seek{}".format(display_id)].create_parameter(
        ossia.ValueType.Int)
    video_nodes["seek{}".format(
        display_id)].parameter.access_mode = ossia.AccessMode.Set


# end video nodes

for card_id, audioplayer in enumerate(audio_players):

    audio_nodes["start{}".format(card_id)] = local_device.add_node(
        "/node{}/audioplayer{}/start".format(config.settings["node_id"], card_id))
    #audio_node.critical = True
    audio_nodes["start{}".format(card_id)].create_parameter(
        ossia.ValueType.Bool)
    audio_nodes["start{}".format(
        card_id)].parameter.access_mode = ossia.AccessMode.Bi
    audio_nodes["start{}".format(card_id)].parameter.value = False

    audio_nodes["load{}".format(card_id)] = local_device.add_node(
        "/node{}/audioplayer{}/load".format(config.settings["node_id"], card_id))
    audio_nodes["load{}".format(card_id)].create_parameter(
        ossia.ValueType.String)
    audio_nodes["load{}".format(
        card_id)].parameter.access_mode = ossia.AccessMode.Set

    audio_nodes["level{}".format(card_id)] = local_device.add_node(
        "/node{}/audioplayer{}/level".format(config.settings["node_id"], card_id))
    audio_nodes["level{}".format(card_id)].create_parameter(
        ossia.ValueType.Int)
    audio_nodes["level{}".format(
        card_id)].parameter.access_mode = ossia.AccessMode.Set


# end audio nodes


messageq_local = ossia.MessageQueue(local_device)


for node in video_nodes.values():
    messageq_local.register(node.parameter)

for node in audio_nodes.values():
    messageq_local.register(node.parameter)


p = re.compile(r'/(\w*)(\d)/(\w*)(\d)/(\w*)')

while(True):
    message = messageq_local.pop()

    if(message != None):
        parameter, value = message

        b = p.search(str(parameter.node))

        # TODO: parameters from XML

        if str(b.group(3)) == "videoplayer":
            # videoplayer cases
            if str(b.group(5)) == "start":
                if value == True:
                    video_players[int(b.group(4))].start()
                else:
                    video_players[int(b.group(4))].quit()

            if str(b.group(5)) == "load":

                video_players[int(b.group(4))].load(value)

            if str(b.group(5)) == "seek":

                video_players[int(b.group(4))].seek(value)

        if str(b.group(3)) == "audioplayer":
            # audioplayer cases
            if str(b.group(5)) == "start":
                if value == True:
                    audio_players[int(b.group(4))].start()
                else:
                    audio_players[int(b.group(4))].quit()

            if str(b.group(5)) == "load":

                audio_players[int(b.group(4))].load(value)

            if str(b.group(5)) == "level":

                audio_players[int(b.group(4))].level(value)

        print("messageq : " + str(parameter.node) + " " + str(value))
