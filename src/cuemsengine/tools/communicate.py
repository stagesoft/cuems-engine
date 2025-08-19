"""Utilites to call the hardware discovery tool."""
from cuemsutils.log import logged, Logger
from cuemsutils.tools.CommunicatorServices import Communicator
import threading
import asyncio
import culsans
import pynng
import json
import time

import pynng

HWDISCOVERY_IPC = '/tmp/hwdiscovery.ipc'
NODECONF_IPC = '/tmp/nodeconf.ipc'
EDITOR_IPC = '/tmp/editor.ipc'
TIMEOUT = 15  # seconds



@logged
def get_hwdiscovery_comm():
    """
    Call the hardware discovery tool
    """
    return Communicator(HWDISCOVERY_IPC)

@logged
def get_nodeconf_comm():
    """
    Call the node configuration tool
    """
    return Communicator(NODECONF_IPC)

@logged
def get_editor_comm():
    """
    Call the editor tool
    """
    return Communicator(EDITOR_IPC)

    

class ComsThread(threading.Thread):
    def __init__(self, async_queue: culsans.SyncQueue[int],  editor_callback: callable):
        Logger.debug('Initializing communications thread')
        self.editor_callback = editor_callback
        self.async_msg_queue = async_queue
        self.timeout = TIMEOUT * 1000
        self.stop_requested = False
        self.send_contexts= []
        threading.Thread.__init__(self, name='Communications', daemon=True)
        self.editor = get_editor_comm()
        self.hw_discovery = get_hwdiscovery_comm()
        self.nodeconf = get_nodeconf_comm()
        
        
 

    def run(self):
        Logger.debug('Comms thread run called')
        self.event_loop = asyncio.new_event_loop()
        self.event_loop.create_task(self.run_asyncio_comms())
        self.event_loop.run_forever()
    def stop(self):
        stop_requested = True
        #self.event_loop.call_soon_threadsafe(self.queue_task.cancel)
        asyncio.run_coroutine_threadsafe(self.stop_async(), self.event_loop)
    
    async def stop_async(self):
        self.event_loop.call_soon_threadsafe(self.event_loop.stop)
        Logger.info('event loop stoped')
                

    async def run_asyncio_comms(self):
        Logger.info('Starting asyncio communications')
        #await self.editor.reply(self.editor_callback)

        # rep = pynng.Rep0(listen= 'ipc:///tmp/editor.ipc')
        # context = rep.new_context()
        # request = await context.arecv()
        # decoded_request = json.loads(request.decode())  # Parse the JSON request
        # Logger.debug(f"Received: {decoded_request}")
        # await self.editor_callback(decoded_request, context)

        #await self.editor.responder_get_request(self.editor_callback)


        editor_task = asyncio.create_task(self.editor_listener())
        #queue_task = asyncio.create_task(self.get_from_queue())
        await editor_task
        #await queue_task
        Logger.debug('asyncio comms finished')
        #
    async def editor_listener(self):
        Logger.info('Editor listener started')
        await self.editor.responder_connect()
        while not self.stop_requested:
            Logger.debug(f'waiting for editor message')
            await self.editor.responder_get_request(self.editor_callback)

    async def respond_to_editor(self, message, context):
        Logger.debug(f'Sending to editor: {message}, with context ')
        await context.asend(json.dumps(message).encode())

    async def get_from_queue(self, destination):
        if self.async_msg_queue.empty():
            msg = await self.async_queue.get()
            return msg
        else: return None                

