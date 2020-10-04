
from cuems.log import logger 
from cuems.cuems_editor import CuemsWsServer




server = CuemsWsServer()
logger.info('start server')
server.start(9092)
