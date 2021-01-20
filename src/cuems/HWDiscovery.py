from subprocess import Popen, PIPE, STDOUT, CalledProcessError
from jack import Client
from pprint import pprint
from .CuemsScript import CuemsScript
from .XmlReaderWriter import XmlWriter
from .log import logger
from Xlib import display
from Xlib.ext import xinerama

def hw_discovery():
    # Calling audioplayer-cuems in a subprocess
    class Outputs(dict):
        pass

    outputs_object = Outputs()
    outputs_object['audio'] = {}
    outputs_object['video'] = {'outputs':{'output':[]}, 'default_output':''}
    outputs_object['dmx'] = {}

    # Audio outputs
    jc = Client('CuemsHWDiscovery')
    ports = jc.get_ports(is_audio=True, is_physical=True, is_input=True)
    if ports:
        outputs_object['audio']['outputs'] = {'output':[]}
        outputs_object['audio']['default_output'] = ''

        for port in ports:
            outputs_object['audio']['outputs']['output'].append({'name':port.name, 'mappings':{'mapped_to':[port.name, ]}})

        outputs_object['audio']['default_output'] = outputs_object['audio']['outputs']['output'][0]['name']

    # Audio inputs
    ports = jc.get_ports(is_audio=True, is_physical=True, is_output=True)
    if ports:
        outputs_object['audio']['inputs'] = {'input':[]}
        outputs_object['audio']['default_input'] = ''

        for port in ports:
            outputs_object['audio']['inputs']['input'].append({'name':port.name, 'mappings':{'mapped_to':[port.name, ]}})

        outputs_object['audio']['default_input'] = outputs_object['audio']['inputs']['input'][0]['name']

    jc.close()

    # Video
    try:
        # Xlib video outputs retreival through xinerama extension
        disp = display.Display()
        screen = disp.screen()
        window = screen.root.create_window(0, 0, 1, 1, 1, screen.root_depth)

        qs = xinerama.query_screens(window)
        if qs._data['number'] > 0:
            for index, screen in enumerate(qs._data['screens']):
                outputs_object['video']['outputs']['output'].append({'name':f'{index}', 'mappings':{'mapped_to':[f'{index}', ]}})

    except Exception as e:
        logger.exception(e)
        outputs_object['video']['outputs'] = {'output':[]}

    if outputs_object['video']['outputs']['output']:
        outputs_object['video']['default_output'] = outputs_object['video']['outputs']['output'][0]['name']
    else:
        outputs_object['video']['default_output'] = ''

    # XML Writer
    writer = XmlWriter(schema = '/etc/cuems/project_mappings.xsd', xmlfile = '/etc/cuems/default_mappings.xml', xml_root_tag='CuemsProjectMappings')

    try:
        writer.write_from_object(outputs_object)
    except Exception as e:
        logger.exception(e)

    logger.info(f'Hardware discovery completed. Default mappings writen to {writer.xmlfile}')

    return False

