import logging

""" logging.basicConfig(level=logging.DEBUG,
                    format='(%(threadName)-9s) %(message)s',) """

logging.basicConfig(filename='error.log', level=logging.DEBUG,
                    format='(%(threadName)-9s) %(message)s',)

