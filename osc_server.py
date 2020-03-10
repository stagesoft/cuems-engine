#!/usr/bin/env python

import liblo
import sys
from dataclasses import dataclass

from log import *
from video_player import VideoPlayer
import config


class InternalOscServer(liblo.ServerThread):

    @dataclass
    class OscCommand:
        path: str
        typespec: str 
        handler: 'typing.Any' 
        docummentation: str

    
    lprotos = {0: 'default', 1: 'UDP', 2: 'UNIX', 4: 'TCP'}

    def __init__(self, osc_in_port, protocol, osc_dest):
        liblo.ServerThread.__init__(self, osc_in_port, protocol)
        self.destination=osc_dest
        
        
        self.video_player=[None]*config.number_of_displays

        self.OSC = [self.OscCommand("/test", "ifs", self.test_callback, "/test int float string"),
                    self.OscCommand("/test", "i", self.test_la_callback, "/test int"),
                    self.OscCommand("/test", None, self.test_na_callback, "test unknow arguments"),
                    self.OscCommand("/node{}/audioplayer/start".format(config.node_id), "i", self.start_video_callback, "start audio player"),
                    self.OscCommand("/node{}/videoplayer/start".format(config.node_id), "i", self.start_video_callback, "start video player"),
                    self.OscCommand("/node{}/get/numberofdisplays".format(config.node_id), None, self.get_num_displays_callback, "Get number of displays"),
                    ]

        for i in self.OSC:
            self.add_method(i.path, i.typespec, i.handler, i.docummentation)


        #catch all
        if __debug__:
            self.add_method(None, None, self.catchall_callback)
            logging.debug('InternalOscServer starting on {} port: {}'.format(self.lprotos[self.protocol], self.port))



    def start_video_callback(self, path, args):
        display_id = args[0]

        if display_id >= 0 and display_id < len(self.video_player):
            if not self.video_player[display_id] is None:
                if not self.video_player[display_id].isAlive():
                    self.video_player[display_id] = None
            
            if self.video_player[display_id] is None:
                self.video_player[display_id] = VideoPlayer(config.video_osc_port + display_id, display_id)
                self.video_player[display_id].start()
        
        elif __debug__:
            logging.debug("{} - Display index out of range: {}, number of displays: {}".format(path, display_id, config.number_of_displays))
        
    def get_num_displays_callback(self, path):
        
        print("received message {}, responding with: {}".format(path, config.number_of_displays))
        liblo.send(self.destination, "/node{}/numberofdisplays".format(config.node_id), config.number_of_displays)
        

    def test_callback(self, path, args):
        i, f, s = args
        print("received message {} with arguments: {}, {}, {}".format(path, i, f, s))
    
    def test_la_callback(self, path, args):
        i = args[0]
        print("received message '%s' with less arguments: %d" % (path, i))
    
    def test_na_callback(self, path, args, types):
        if not args:
            print("received message {} with no arguments: ".format(path))
        else:
            print("received message {} with unknnow arguments: ".format(path))
            for a, t in zip(args, types):
                print("received argument %s of type %s" % (a, t))
    
    if __debug__:
        def catchall_callback(self, path, args, types):
            if not args:
                print("received unknown message {} with no arguments: ".format(path))
            else:
                print("received unknown message {} with arguments: ".format(path))
                for a, t in zip(args, types):
                    print("received argument %s of type %s" % (a, t))