import pyossia as ossia

from log import *
import config


class Node():
    def __init__(self, node_id):
        print("init")
        self.id = node_id
