class UI_properties(dict):
    
    def __init__(self, init_dict = None):
        if init_dict:
            super().__init__(init_dict)
    
    @property
    def timeline_position(self):
        return super().__getitem__('timeline_position')