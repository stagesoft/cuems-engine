#!/usr/bin/env python3

import click

from log import *

from functools import partial
from Cue import Cue
from CueList import CueList
from CueProcessor import CuePriorityQueu, CueQueueProcessor
from MtcListener import MtcListener






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


    

    c1 = Cue('0:0:5:0')
    c2 = Cue('0:0:6:0')
    c3 = Cue('0:0:7:0')
    c4 = Cue('0:0:10:0')
    time_list = CueList([c1, c3, c4, c2])

    

    cue_queue = CuePriorityQueu()
    cue_processor = CueQueueProcessor(cue_queue)
    mtc_listener = MtcListener(step_callback=partial(check_cues, queue=cue_queue, timelist=time_list), reset_callback=partial(reset_all, queue=cue_queue, list=time_list), port=port)



main()

