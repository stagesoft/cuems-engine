
import logging
import logging.handlers

logger = logging.getLogger('Cuems_control')
logger.setLevel(logging.DEBUG)


handler = logging.handlers.SysLogHandler(address = '/dev/log', facility = 'local0')

# set a format 
formatter = logging.Formatter('Cuems:osc_control: (%(threadName)-9s) %(message)s')
# tell the handler to use this format
handler.setFormatter(formatter)
logger.addHandler(handler)
