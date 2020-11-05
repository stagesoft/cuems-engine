class UI_properties(dict):
    
    def __init__(self, init_dict=None):
        empty_keys= {"timeline_position": ""}
        if (init_dict):
            super().__init__(init_dict)
        else:
            super().__init__(empty_keys)
    
    @property
    def timeline_position(self):
        return super().__getitem__('timeline_position')