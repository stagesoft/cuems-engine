#!/usr/bin/env python3

import click, mido

import threading
import queue
from functools import partial
import time

# some_file.py

from CTimecode import CTimecode
from log import *

class MtcListener(threading.Thread):
    
    def __init__(self, step_callback=None, reset_callback=None, port=None):
        self.main_tc = CTimecode('0:0:0:0')
        self.__quarter_frames = [0,0,0,0,0,0,0,0]
        self.port_name = None
        self.__open_port(port)

        self.step_callback = step_callback
        self.reset_callback = reset_callback
        super().__init__()
        self.daemon = False
        threading.Thread.start(self)


    def timecode(self):
        return self.main_tc

    def __update_timecode(self, timecode):
        self.main_tc = timecode
        if (self.main_tc.milliseconds == 0):
            if self.step_callback != None:
                self.reset_callback()
        if self.step_callback != None:
            self.step_callback(self.main_tc) 

    def __open_port(self, port):
        if port == None:
            ports = mido.get_input_names()
            mtc_ports = [s for s in ports if "mtc" in s.lower()]
            self.port_name = mtc_ports[-1] if mtc_ports else ports[-1]
            logger.info ('Selected MIDI port: ' + self.port_name)
        else:
            self.port_name = port
            print("hay port")

    def run(self):
        port = mido.open_input(self.port_name, callback= self.__handle_message)

        logger.info('Listening to MIDI messages on > {} <'.format(self.port_name))

    def __handle_message(self, message):
        if message.type == 'quarter_frame':
            
            self.__quarter_frames[message.frame_type] = message.frame_value
            if (message.frame_type == 3) or (message.frame_type == 7):
                self.__update_timecode(self.main_tc + 1)
            #    print('QF+:',self.main_tc)
            if message.frame_type == 7:
                tc = self.__mtc_decode_quarter_frames(self.__quarter_frames)
            #    print('QFC:',tc)
                self.__update_timecode(tc)
        elif message.type == 'sysex':
        # check to see if this is a timecode frame
            if len(message.data) == 8 and message.data[0:4] == (127,127,1,1):
                data = message.data[4:]
                tc = self.__mtc_decode(data)
                logger.debug('FF:' + tc.__str__())
                self.__update_timecode(tc)
            

        else:
            logger.debug(message)
            raise(NotImplementedError)
    
    def __mtc_decode(self, mtc_bytes):
        #print(mtc_bytes)
        rhh, mins, secs, frs = mtc_bytes
        rateflag = rhh >> 5
        hrs      = rhh & 31
        fps = ['24','25','29.97','30'][rateflag]
        # total_frames = frs + float(fps) * (secs + mins * 60 + hrs * 60 * 60) //  TODO: goes to frame 0 in tc, non existent frame, changed to tc 0:0:0:0 = frame 1
        return CTimecode('{}:{}:{}:{}'.format(hrs, mins, secs, frs), framerate=fps)



    def __mtc_decode_full_frame(self, full_frame_bytes):
        mtc_bytes = full_frame_bytes[5:-1]
        return self.__mtc_decode(mtc_bytes)


    def __mtc_decode_quarter_frames(self, frame_pieces):
        mtc_bytes = bytearray(4)
        if len(frame_pieces) < 8:
            return None
        for piece in range(8):
            mtc_index = 3 - piece//2    # quarter frame pieces are in reverse order of mtc_encode
            this_frame = frame_pieces[piece]
            if this_frame is bytearray or this_frame is list:
                this_frame = this_frame[1]
            data = this_frame & 15      # ignore the frame_piece marker bits
            if piece % 2 == 0:
                # 'even' pieces came from the low nibble
                # and the first piece is 0, so it's even
                mtc_bytes[mtc_index] += data
            else:
                # 'odd' pieces came from the high nibble
                mtc_bytes[mtc_index] += data * 16
        return self.__mtc_decode(mtc_bytes)


class CuePriorityQueu(queue.PriorityQueue):
    def __init__(self):
      super().__init__()

    def clear(self):
        while not self.empty():
            logger.debug(str(self.get()) + "deleted")
            self.task_done()

class CueQueueProcessor(threading.Thread):

    def __init__(self, queue):
        self.queue = queue
        self.item = None

        super().__init__()
        self.daemon = False
        threading.Thread.start(self)

    def run(self):
        while True:
            self.item = self.queue.get()
            logger.debug(f'Working on {self.item}')
            time.sleep(4)
            logger.debug(f'Finished {self.item}')
            self.queue.task_done()


class CueTimeList(list):
    def __init__(self, args):
        super().__init__(args)
        self.backup = args
    
    def append(self, item):
        super(CueTimeList, self).append(item)  #append the item to itself (the list)
        self.backup.append(item)

    def reset(self):
        print("reset callback")
        super(CueTimeList, self) == self.backup.copy() #not working

#
################
#






#%%
def check_cues(timecode, queue, timelist):
    if ((timelist) and (timelist[-1] <= timecode)):
        last = timelist.pop()
        logger.debug('event')
        logger.debug(last)
        queue.put((last), block=True, timeout=None)



def reset_all(queue, list):
    queue.clear()
    list.reset()



@click.command()
@click.option('--port', '-p', help='name of MIDI port to connect to')

def main(port):


    

    c1 = CTimecode('0:0:5:0')
    c2 = CTimecode('0:0:6:0')
    c3 = CTimecode('0:0:7:0')
    c4 = CTimecode('0:0:10:0')
    time_list = CueTimeList([c1, c3, c4, c2])
    time_list.sort(reverse=True)

    

    cue_queue = CuePriorityQueu()
    cue_processor = CueQueueProcessor(cue_queue)
    mtc_listener = MtcListener(step_callback=partial(check_cues, queue=cue_queue, timelist=time_list), reset_callback=partial(reset_all, queue=cue_queue, list=time_list), port=port)



main()

