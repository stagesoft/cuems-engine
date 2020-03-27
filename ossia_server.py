import pyossia as ossia
import time
import re

import config
from video_player import NodeVideoPlayers 
from log import *




video_players=NodeVideoPlayers()



local_device = ossia.LocalDevice("Node {}".format(config.settings["node_id"]))

local_device.create_oscquery_server(3456, 5678, True)
#local_device.create_osc_server("127.0.0.1", 9997, 9996, True)

video_nodes = {}


for display_id, videoplayer in enumerate(video_players):
  print(display_id)
  print(videoplayer)


  video_nodes["start{}".format(display_id)]=local_device.add_node("/node{}/videoplayer{}/start".format(config.settings["node_id"], display_id))
  #video_node.critical = True
  video_nodes["start{}".format(display_id)].create_parameter(ossia.ValueType.Bool)
  video_nodes["start{}".format(display_id)].parameter.access_mode = ossia.AccessMode.Bi
  video_nodes["start{}".format(display_id)].parameter.value = False

  #video_nodes["osd{}".format(display_id)]=local_device.add_node("/node{}/videoplayer{}/osd".format(config.settings["node_id"], display_id))
  #video_node.critical = True
  #video_nodes["osd{}".format(display_id)].create_parameter(ossia.ValueType.Int)
  #video_nodes["osd{}".format(display_id)].parameter.access_mode = ossia.AccessMode.Set
  #video_nodes["osd{}".format(display_id)].parameter.value = 0

  video_nodes["load{}".format(display_id)]=local_device.add_node("/node{}/videoplayer{}/load".format(config.settings["node_id"], display_id))
  video_nodes["load{}".format(display_id)].create_parameter(ossia.ValueType.String)
  video_nodes["load{}".format(display_id)].parameter.access_mode = ossia.AccessMode.Set

  video_nodes["seek{}".format(display_id)]=local_device.add_node("/node{}/videoplayer{}/seek".format(config.settings["node_id"], display_id))
  video_nodes["seek{}".format(display_id)].create_parameter(ossia.ValueType.Int)
  video_nodes["seek{}".format(display_id)].parameter.access_mode = ossia.AccessMode.Set


## end video


audio_node=local_device.add_node("/node{}/audioplayer/start".format(config.settings["node_id"]))
audio_node_parameter = audio_node.create_parameter(ossia.ValueType.Impulse)
audio_node_parameter.access_mode = ossia.AccessMode.Set





""" video_node_parameter.add_callback(start_video_callback)
video_osd_parameter.add_callback(osd_video_callback)
video_load_parameter.add_callback(load_video_callback)
video_seek_parameter.add_callback(seek_video_callback) """

# SECOND WAY : attach a message queue to a device and register the parameter to the queue


messageq_local = ossia.MessageQueue(local_device)


for node in video_nodes.values():
  messageq_local.register(node.parameter)


p = re.compile(r'/(\w*)(\d)/(\w*)(\d)/(\w*)')

while(True):
  message = messageq_local.pop()
  
  if(message != None):
    print("message")
    parameter, value = message
    
    b = p.search(str(parameter.node))


    if str(b.group(5)) == "start":
      if value == True:
        video_players[int(b.group(4))].start()
      else:
        video_players[int(b.group(4))].quit()
    
    if str(b.group(5)) == "load":

        video_players[int(b.group(4))].load(value)

    if str(b.group(5)) == "seek":

        video_players[int(b.group(4))].seek(value)


    print("messageq : " +  str(parameter.node) + " " + str(value))

    

  time.sleep(0.01)
