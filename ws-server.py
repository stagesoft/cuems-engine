
from src.log import logger 
from src.cuems_editor import CuemsWsServer




server = CuemsWsServer()
logger.info('start server')
server.start(9092)
