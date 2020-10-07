
import logging
import logging.handlers

logger = logging.getLogger('Cuems_control')
logger.setLevel(logging.DEBUG)
logger.propagate = False


handler = logging.handlers.SysLogHandler(address = '/dev/log', facility = 'local0')

# set a format 
# formatter = logging.Formatter('Cuems:engine: (%(threadName)-9s) %(message)s')
formatter = logging.Formatter('Cuems:engine: (PID: %(process)d)-%(threadName)-9s)-(%(funcName)s) %(message)s')

# tell the handler to use this format
handler.setFormatter(formatter)
logger.addHandler(handler)
