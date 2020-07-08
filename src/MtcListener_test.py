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
    if ((timelist) and (timelist[0].time <= timecode)):
        last = timelist.pop(0)
        logger.debug('event')
        logger.debug(last)
        queue.put((2, last), block=True, timeout=None)



def reset_all(queue, list):
    queue.clear()



@click.command()
@click.option('--port', '-p', help='name of MIDI port to connect to')

def main(port):


    

    c1 = Cue('0:0:5:0')
    c2 = Cue('0:0:6:0')
    c3 = Cue('0:0:7:0')
    c4 = Cue('0:0:10:0')
    c5 = Cue(time=None)
    c6 = Cue(time=None)
    c7 = Cue(time=None)
    time_list = CueList([c1, c3, c4, c2, c5, c6, c7])

    

    cue_queue = CuePriorityQueu()
    cue_processor = CueQueueProcessor(cue_queue)
    mtc_listener = MtcListener(step_callback=partial(check_cues, queue=cue_queue, timelist=time_list), reset_callback=partial(reset_all, queue=cue_queue, list=time_list), port=port)



main() # pylint: disable=no-value-for-parameter

# %%