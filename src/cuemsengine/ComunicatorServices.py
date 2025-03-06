from abc import ABC, abstractmethod
from collections.abc import Callable
import asyncio
import json
from pynng import Req0, Rep0
from cuemsutils.log import logged, Logger

class ComunicatorService(ABC):
    @abstractmethod
    def __init__(self, address:str):
        self.address = address

    @abstractmethod
    def send_request(self, resquest:dict) -> dict:
        """ Send request dic and return response dict  """

    @abstractmethod
    def reply(self, request_processor:Callable[[dict], dict]) -> dict:
        """ Get request, give it to request processor, and return the response from it  """



class Nng_request_response(ComunicatorService):
    """ Communicates over NNG (nanomsg)  """,

    def __init__(self, address, resquester_dials=True):
        """
        Initialize Nng_request_resopone instance with address and dialing/listening mode.

        Parameters:
        - address (str): The address to connect or listen for connections.
        - resquester_dials (bool, optional): If True, the instance requester will dial the address and replier will listen. If False, it will be the oposite way, requester listens and replier dials. Default is True.

        The instance will set up the parameters for request and reply sockets based on the resquester_dials value.
        """
        self.address = address
        if resquester_dials:
            self.params_request = {'dial': self.address}
            self.params_reply = {'listen': self.address}
        else: 
            self.params_request = {'listen': self.address}
            self.params_reply = {'dial': self.address}



    @logged
    async def send_request(self, request):
        """
        Send a request to the specified address and return the response.

        Parameters:
        - request (dict): The request to be sent. It should be a dictionary.

        Returns:
        - dict: The response received from the address. It will be a dictionary.
        """
        with Req0(**self.params_request) as socket:
            while await asyncio.sleep(0, result=True):
                Logger.log_debug(f"Sending: {request}")
                encoded_request = json.dumps(request).encode()
                await socket.asend(encoded_request)
                response = await self._get_response(socket)
                decoded_response = json.loads(response.decode())
                Logger.log_debug(f"receiving: {decoded_response}")
                return decoded_response

    async def _get_response(self, socket):
        response = await socket.arecv()
        return response

    @logged
    async def reply(self, request_processor):
        """
        Asynchronously handle incoming requests and respond using the provided request processor.

        This function sets up a Rep0 socket with parameters based on the instance's configuration.
        It then enters a loop where it listens for incoming requests, processes them using the provided
        request processor, and sends the response back to the requester.
        Parameters:
        - request_processor (Callable[[dict], dict]): A function that takes a request dictionary as input and returns a response dictionary.

        Returns:
        - None: This function is designed to run indefinitely, handling incoming requests and responses.
        """
        with Rep0(**self.params_reply) as socket:
            while await asyncio.sleep(0, result=True):
                request = await socket.arecv()
                decoded_request = json.loads(request.decode())  # Parse the JSON request
                Logger.log_debug(f"Received: {decoded_request}")
                response = request_processor(decoded_request)
                encoded_response = json.dumps(response).encode()
                await self._respond(socket, encoded_response)

    async def _respond(self, socket, encoded_response):
        await socket.asend(encoded_response)

    def sync_send_request(self, request):
        """
        Synchronously send a request to the specified address and return the response.

        This function is a wrapper around the asynchronous `send_request` method. It uses
        `asyncio.run` to run the asynchronous function and wait for its completion.

        Parameters:
        - request (dict): The request to be sent. It should be a dictionary.

        Returns:
        - dict: The response received from the address. It will be a dictionary.
        """
        response = asyncio.run(self.send_request(request))
        return response

    def sync_reply(self, request_processor):
        """
        Synchronously handle incoming requests and respond using the provided request processor.

        This function is a wrapper around the asynchronous `reply` method. It uses
        `asyncio.run` to run the asynchronous function and wait for its completion.

        Parameters:
        - request_processor (Callable[[dict], dict]): A function that takes a request dictionary as input and returns a response dictionary.

        Returns:
        - None
        """
        asyncio.run(self.reply(request_processor))

class Comunicator(ComunicatorService):
    def __init__(self, address, comunicator_service = Nng_request_response, nng_mode=True):
        self.address = address
        self.nng_mode = nng_mode
        self.comunicator_service = comunicator_service(self.address, resquester_dials=self.nng_mode)

    async def send_request(self, request):
        response = await self.comunicator_service.send_request(request)
        return response

    async def reply(self, request_processor):
       await self.comunicator_service.reply(request_processor)


    def sync_send_request(self, request):
        response = self.comunicator_service.sync_send_request(request)
        return response
    
    
    def sync_reply(self, request_processor):
        self.comunicator_service.sync_reply(request_processor)