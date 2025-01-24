from mtcmaster import libmtcmaster
from pynng import Req0
import json
import signal

data = {'cmd':'play'}
data_time = {'cmd':'set_time','params':{'nanos':333}}

address = "ipc:///tmp/libmtcmaster.sock"

signal.signal(signal.SIGINT, signal.SIG_DFL)
with Req0(dial=address) as requester:
    requester.send(json.dumps(data).encode())  # Convert the data to JSON and send it
                   
    try:
        reply = requester.recv()
        print (f"Received: {reply}")
    except Exception as e:
        print(f"Error while processing request: {e}")

    requester.send(json.dumps(data_time).encode())  # Convert the data to JSON and send it
                   
    try:
        reply = requester.recv()
        print (f"Received: {reply}")
    except Exception as e:
        print(f"Error while processing request: {e}")

    