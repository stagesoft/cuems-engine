import pyossia as ossia
import time

import config
from video_player import VideoPlayer
from log import *




video_players=[None]*config.number_of_displays



local_device = ossia.LocalDevice("Node {}".format(config.node_id))

local_device.create_oscquery_server(3456, 5678, True)
#local_device.create_osc_server("127.0.0.1", 9997, 9996, True)

video_nodes = {}


for display_id, videoplayer in enumerate(video_players):
  print(display_id)
  print(videoplayer)


  video_nodes["start{}".format(display_id)]=local_device.add_node("/node{}/videoplayer{}/start".format(config.node_id, display_id))
  #video_node.critical = True
  video_nodes["start{}".format(display_id)].create_parameter(ossia.ValueType.Bool)
  video_nodes["start{}".format(display_id)].parameter.access_mode = ossia.AccessMode.Bi
  video_nodes["start{}".format(display_id)].parameter.value = False

  video_nodes["osd{}".format(display_id)]=local_device.add_node("/node{}/videoplayer{}/osd".format(config.node_id, display_id))
  #video_node.critical = True
  video_nodes["osd{}".format(display_id)].create_parameter(ossia.ValueType.Int)
  video_nodes["osd{}".format(display_id)].parameter.access_mode = ossia.AccessMode.Set
  video_nodes["osd{}".format(display_id)].parameter.value = 0

  video_nodes["load{}".format(display_id)]=local_device.add_node("/node{}/videoplayer{}/load".format(config.node_id, display_id))
  #video_node.critical = True
  video_nodes["load{}".format(display_id)].create_parameter(ossia.ValueType.String)
  video_nodes["load{}".format(display_id)].parameter.access_mode = ossia.AccessMode.Set

  video_nodes["seek{}".format(display_id)]=local_device.add_node("/node{}/videoplayer{}/seek".format(config.node_id, display_id))
  #video_node.critical = True
  video_nodes["seek{}".format(display_id)].create_parameter(ossia.ValueType.Int)
  video_nodes["seek{}".format(display_id)].parameter.access_mode = ossia.AccessMode.Set

## end video


audio_node=local_device.add_node("/node{}/audioplayer/start".format(config.node_id))
audio_node_parameter = audio_node.create_parameter(ossia.ValueType.Impulse)
audio_node_parameter.access_mode = ossia.AccessMode.Set

get_displays_node=local_device.add_node("/node{}/get/numberofdisplays".format(config.node_id))
get_displays_node_parameter = get_displays_node.create_parameter(ossia.ValueType.Int)
get_displays_node_parameter.access_mode = ossia.AccessMode.Get
get_displays_node_parameter.value = config.number_of_displays


def start_video_callback(value):
  if value:
    if display_id >= 0 and display_id < len(video_player):
      if not video_players[display_id] is None:
        if not video_players[display_id].is_alive():
          video_players[display_id] = None

      if video_players[display_id] is None:
        video_players[display_id] = VideoPlayer(config.video_osc_port + display_id, display_id)
        video_players[display_id].start()
        print("video player started")

      elif __debug__:
        logging.debug("{} - Display index out of range: {}, number of displays: {}".format(value, display_id, config.number_of_displays))
  else:
    
    if video_players[display_id].is_alive():
      video_players[display_id].kill()
      video_players[display_id] = None
    else:
      video_players[display_id] = None


remote_osc_xjadeo = ossia.ossia.OSCDevice("remoteXjadeo", "127.0.0.1", config.video_osc_port, 4300)
          
remote_xjadeo_quit_node = remote_osc_xjadeo.add_node("/jadeo/quit")
xjadeo_quit_parameter = remote_xjadeo_quit_node.create_parameter(ossia.ValueType.Impulse)

remote_xjadeo_load_node = remote_osc_xjadeo.add_node("/jadeo/load")
xjadeo_load_parameter = remote_xjadeo_load_node.create_parameter(ossia.ValueType.String)

remote_xjadeo_seek_node = remote_osc_xjadeo.add_node("/jadeo/seek")
xjadeo_seek_parameter = remote_xjadeo_seek_node.create_parameter(ossia.ValueType.Int)
xjadeo_seek_parameter.value = 0
xjadeo_seek_parameter.default_value = 0

remote_xjadeo_osd_node = remote_osc_xjadeo.add_node("/jadeo/osd/timecode")
xjadeo_osd_parameter = remote_xjadeo_osd_node.create_parameter(ossia.ValueType.Int)
xjadeo_osd_parameter.value = 0
xjadeo_osd_parameter.default_value = 0



def osd_video_callback(value):
  xjadeo_osd_parameter.value = value

def load_video_callback(value):
  xjadeo_load_parameter.value = value


def seek_video_callback(value):
  xjadeo_seek_parameter.value = value


""" video_node_parameter.add_callback(start_video_callback)
video_osd_parameter.add_callback(osd_video_callback)
video_load_parameter.add_callback(load_video_callback)
video_seek_parameter.add_callback(seek_video_callback) """

# SECOND WAY : attach a message queue to a device and register the parameter to the queue


messageq_local = ossia.MessageQueue(local_device)

messageq_redirect = ossia.MessageQueue(local_device)

nodes_to_local=ossia.ossia.list_node_pattern([local_device.root_node], "//start")
nodes_to_redirect = ossia.ossia.list_node_pattern([local_device.root_node], "/*")
print("#########################")
print(nodes_to_redirect[0].children())
print(nodes_to_local)

for node in nodes_to_local:
  messageq_local.register(node.parameter)

while(True):
  message = messageq_local.pop()
  if(message != None):
    parameter, value = message
    print("messageq : " +  str(parameter.node) + " " + str(value))

    

  time.sleep(0.01)
