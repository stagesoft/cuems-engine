class Media(dict):
    
    def __init__(self, init_dict=None):
        empty_keys= {"file_name": ""}
        if (init_dict):
            super().__init__(init_dict)
        else:
            super().__init__(empty_keys)
    
    @property
    def file_name(self):
        return super().__getitem__('file_name')