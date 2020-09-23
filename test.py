
import logging
from src.cuems_editor import CuemsWsServer




server = CuemsWsServer()
logging.info('start server')
server.start(9092)
