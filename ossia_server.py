import pyossia as ossia
import time
import re

import config
from video_player import NodeVideoPlayers 
from audio_player import NodeAudioPlayers 
from log import *
from settings import Settings



settings = Settings()
settings.read()

video_players=NodeVideoPlayers(settings)
audio_players=NodeAudioPlayers(settings)


local_device = ossia.LocalDevice("Node {}".format(list(settings['node'].keys())[0]))

local_device.create_oscquery_server(3456, 5678, True)
#local_device.create_osc_server("127.0.0.1", 9997, 9996, True)

video_nodes = {}
audio_nodes = {}


for display_id, videoplayer in enumerate(video_players):
  print(display_id)
  print(videoplayer)


  video_nodes["start{}".format(display_id)]=local_device.add_node("/node{}/videoplayer{}/start".format(config.settings["node_id"], display_id))
  #video_node.critical = True
  video_nodes["start{}".format(display_id)].create_parameter(ossia.ValueType.Bool)
  video_nodes["start{}".format(display_id)].parameter.access_mode = ossia.AccessMode.Bi
  video_nodes["start{}".format(display_id)].parameter.value = False

  video_nodes["load{}".format(display_id)]=local_device.add_node("/node{}/videoplayer{}/load".format(config.settings["node_id"], display_id))
  video_nodes["load{}".format(display_id)].create_parameter(ossia.ValueType.String)
  video_nodes["load{}".format(display_id)].parameter.access_mode = ossia.AccessMode.Set

  video_nodes["seek{}".format(display_id)]=local_device.add_node("/node{}/videoplayer{}/seek".format(config.settings["node_id"], display_id))
  video_nodes["seek{}".format(display_id)].create_parameter(ossia.ValueType.Int)
  video_nodes["seek{}".format(display_id)].parameter.access_mode = ossia.AccessMode.Set


## end video nodes

for card_id, audioplayer in enumerate(audio_players):
  print(card_id)
  print(audioplayer)


  audio_nodes["start{}".format(card_id)]=local_device.add_node("/node{}/audioplayer{}/start".format(config.settings["node_id"], card_id))
  #audio_node.critical = True
  audio_nodes["start{}".format(card_id)].create_parameter(ossia.ValueType.Bool)
  audio_nodes["start{}".format(card_id)].parameter.access_mode = ossia.AccessMode.Bi
  audio_nodes["start{}".format(card_id)].parameter.value = False


  audio_nodes["load{}".format(card_id)]=local_device.add_node("/node{}/audioplayer{}/load".format(config.settings["node_id"], card_id))
  audio_nodes["load{}".format(card_id)].create_parameter(ossia.ValueType.String)
  audio_nodes["load{}".format(card_id)].parameter.access_mode = ossia.AccessMode.Set

  audio_nodes["seek{}".format(card_id)]=local_device.add_node("/node{}/audioplayer{}/seek".format(config.settings["node_id"], card_id))
  audio_nodes["seek{}".format(card_id)].create_parameter(ossia.ValueType.Int)
  audio_nodes["seek{}".format(card_id)].parameter.access_mode = ossia.AccessMode.Set


## end audio nodes



messageq_local = ossia.MessageQueue(local_device)


for node in video_nodes.values():
  messageq_local.register(node.parameter)

for node in audio_nodes.values():
  messageq_local.register(node.parameter)


p = re.compile(r'/(\w*)(\d)/(\w*)(\d)/(\w*)')

while(True):
  message = messageq_local.pop()
  
  if(message != None):
    print("message")
    parameter, value = message
    
    b = p.search(str(parameter.node))

    #TODO: convertir a cases?

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

      if str(b.group(5)) == "seek":

          audio_players[int(b.group(4))].seek(value)

    print("messageq : " +  str(parameter.node) + " " + str(value))

    

  time.sleep(0.01)
