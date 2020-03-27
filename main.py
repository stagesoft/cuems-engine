import sys
import liblo
from osc_server import InternalOscServer

import config

internal_osc_server_response_address=liblo.Address(config.settings["internal_osc_dest_host"], config.settings["internal_osc_out_port"], liblo.TCP)

try:
    internal_osc_server = InternalOscServer(config.settings["internal_osc_in_port"] , liblo.UDP, internal_osc_server_response_address)
    internal_osc_server.start()
except liblo.ServerError as err:
    print("InternalOscServer error:{}".format(err))




input("press enter to quit...\n")