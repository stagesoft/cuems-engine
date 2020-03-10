import pyossia as ossia
import time

import config
from video_player import VideoPlayer
from log import *


video_player=[None]*config.number_of_displays
display_id =0



local_device = ossia.LocalDevice("Video player")
local_device.create_oscquery_server(3456, 5678, True)
#local_device.create_osc_server("127.0.0.1", 9997, 9996, True)

video_node=local_device.add_node("/node{}/videoplayer/start".format(config.node_id))
#video_node.critical = True
video_node_parameter = video_node.create_parameter(ossia.ValueType.Bool)
video_node_parameter.access_mode = ossia.AccessMode.Bi
video_node_parameter.value = False

audio_node=local_device.add_node("/node{}/audioplayer/start".format(config.node_id))
audio_node_parameter = audio_node.create_parameter(ossia.ValueType.Impulse)
audio_node_parameter.access_mode = ossia.AccessMode.Set

get_displays_node=local_device.add_node("/node{}/get/numberofdisplays".format(config.node_id))
get_displays_node_parameter = get_displays_node.create_parameter(ossia.ValueType.Int)
get_displays_node_parameter.access_mode = ossia.AccessMode.Get
get_displays_node_parameter.value = config.number_of_displays


def start_video_callback(value):
      # display_id = args[0]
  print("video callback")

  if display_id >= 0 and display_id < len(video_player):
    if not video_player[display_id] is None:
        # TODO now doesnt work but was working, ossia? python version?
        if not video_player[display_id].isAlive():
          pass
          #video_player[display_id] = None

    if video_player[display_id] is None:
      print("video is none")
      video_player[display_id] = VideoPlayer(config.video_osc_port + display_id, display_id)
      video_player[display_id].start()
      video_node_parameter.value = True

    elif __debug__:
      logging.debug("{} - Display index out of range: {}, number of displays: {}".format(value, display_id, config.number_of_displays))

video_node_parameter.add_callback(start_video_callback)


# SECOND WAY : attach a message queue to a device and register the parameter to the queue
messageq = ossia.MessageQueue(local_device)
messageq.register(audio_node_parameter)
#messageq.register(video_node_parameter)


while(True):
  message = messageq.pop()
  if(message != None):
    parameter, value = message
    
    print("messageq : " +  str(parameter.node) + " " + str(value))
  time.sleep(0.01)
