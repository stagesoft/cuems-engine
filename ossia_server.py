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

video_osd=local_device.add_node("/node{}/videoplayer/osd".format(config.node_id))
#video_node.critical = True
video_osd_parameter = video_osd.create_parameter(ossia.ValueType.Int)
video_osd_parameter.access_mode = ossia.AccessMode.Set
video_osd_parameter.value = 0

video_load=local_device.add_node("/node{}/videoplayer/load".format(config.node_id))
#video_node.critical = True
video_load_parameter = video_load.create_parameter(ossia.ValueType.String)
video_load_parameter.access_mode = ossia.AccessMode.Set

video_seek=local_device.add_node("/node{}/videoplayer/seek".format(config.node_id))
#video_node.critical = True
video_seek_parameter = video_seek.create_parameter(ossia.ValueType.Int)
video_seek_parameter.access_mode = ossia.AccessMode.Set

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
      if not video_player[display_id] is None:
        if not video_player[display_id].is_alive():
          video_player[display_id] = None

      if video_player[display_id] is None:
        video_player[display_id] = VideoPlayer(config.video_osc_port + display_id, display_id)
        video_player[display_id].start()
        print("video player started")

      elif __debug__:
        logging.debug("{} - Display index out of range: {}, number of displays: {}".format(value, display_id, config.number_of_displays))
  else:
    
    if video_player[display_id].is_alive():
      video_player[display_id].kill()
      video_player[display_id] = None
    else:
      video_player[display_id] = None


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


video_node_parameter.add_callback(start_video_callback)
video_osd_parameter.add_callback(osd_video_callback)
video_load_parameter.add_callback(load_video_callback)
video_seek_parameter.add_callback(seek_video_callback)

# SECOND WAY : attach a message queue to a device and register the parameter to the queue
messageq = ossia.MessageQueue(local_device)
messageq.register(audio_node_parameter)
messageq.register(video_node_parameter)


while(True):
  message = messageq.pop()
  if(message != None):
    parameter, value = message
    
    print("messageq : " +  str(parameter.node) + " " + str(value))
  time.sleep(0.01)
