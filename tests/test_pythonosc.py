from cuemsengine.osc.PyOsc import PyOscClient, PyOscServer

from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient
from pythonosc.osc_message import OscMessage
from unittest.mock import patch

def test_new_osc_client():
    # Arrange
    # Act
    client = PyOscClient()
    # Assert
    assert client.host == "127.0.0.1"
    assert client.port == 10001
    assert isinstance(client.client, SimpleUDPClient)

def test_client_call_send_message():
    # Arrange
    client = PyOscClient()
    with patch.object(SimpleUDPClient, "send_message") as mock_send_message:
        # Act
        client.send_message("/test", 1, 2, 3)
        # Assert
        mock_send_message.assert_called_once_with("/test", (1, 2, 3))

def test_server_call_start():
    # Arrange
    server = PyOscServer()
    with patch.object(ThreadingOSCUDPServer, "serve_forever") as mock_serve_forever:
        # Act
        server.start()
        # Assert
        mock_serve_forever.assert_called_once()


## Helper classes
class store_response():
        def __init__(self):
            self.responses = {}
        
        def set(self, address, *args) -> tuple[str, str]:
            self.responses[address] = [value for value in args]
            return (address, "OK")

server_res = store_response()
server_endpoints = {
    "/test": server_res.set,
    "/test2": server_res.set
}

def test_server_endpoints():
    # Arrange
    from pythonosc.dispatcher import Handler
    # Act
    server = PyOscServer(endpoints = server_endpoints)
    # Assert
    assert server.server.server_address == ('127.0.0.1', 10001)
    assert len(server.handlers) == 2
    assert ["/test", "/test2"] == [i for i in server.handlers.keys()]
    assert isinstance(server.handlers["/test"], Handler)
    assert isinstance(server.handlers["/test2"], Handler)
    assert server_res.responses == {}

def test_server_start():
    # Arrange
    server = PyOscServer(endpoints = server_endpoints)
    server.start()
    client = PyOscClient()

    # Act
    client.send_message("/test", 30)
    msg = client.get_first_message()
    msg2 = client.send_with_response("/test2", [30, 40])
    
    # Assert
    assert server_res.responses["/test"] == [30]
    assert isinstance(msg, OscMessage)
    assert msg.address == "/test"
    assert msg.params == ["OK"]
    
    assert server_res.responses["/test2"] == [[30, 40]]
    assert isinstance(msg2, OscMessage)
    assert msg2.address == "/test2"
    assert msg2.params == ["OK"]

    # Cleanup
    server.stop()
