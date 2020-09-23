import logging
import logging.handlers

# Get a logger object
logger = logging.getLogger('Cuems:engine')
# Set logger level
logger.setLevel(logging.DEBUG)
# Deactivate stdouts propagation
logger.propagate = False

# Get a handler to syslog
handler = logging.handlers.SysLogHandler(address = '/dev/log', facility = 'local0')
# Set a formatter
formatter = logging.Formatter('Cuems:engine: [%(threadName)-9s] %(message)s')
# Tell the handler to use this formatter
handler.setFormatter(formatter)

# Assign the handler to our logger
logger.addHandler(handler)