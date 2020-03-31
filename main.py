import sys
import liblo
from osc_server import InternalOscServer
from log import *

from settings import Settings

settings = Settings()

settings.read()


internal_osc_server_response_address=liblo.Address(settings['node']['0']["internal_osc_dest_host"], settings['node']['0']["internal_osc_out_port"], liblo.TCP)

try:
    internal_osc_server = InternalOscServer(settings['node']['0']["internal_osc_in_port"] , liblo.UDP, internal_osc_server_response_address)
    internal_osc_server.start()
except liblo.ServerError as err:
    logging.debug("InternalOscServer error:{}".format(err))






input("press enter to quit...\n")
settings.write()