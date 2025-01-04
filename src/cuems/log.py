# DEV: Move to cuems-utils
import logging
import logging.handlers

logger = logging.getLogger() # no name = root logger
logger.setLevel(logging.DEBUG)

logger.propagate = False

handler = logging.handlers.SysLogHandler(address = '/dev/log', facility = 'local0')

formatter = logging.Formatter('Cuems:engine: (PID: %(process)d)-%(threadName)-9s)-(%(funcName)s) %(message)s')

handler.setFormatter(formatter)
logger.addHandler(handler)