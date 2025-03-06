from ..src.cuemsengine.CTimecode import CTimecode

class Media(dict):
    def __init__(self, init_dict = None):
        if init_dict:
            super().__init__(init_dict)
    
    @property
    def file_name(self):
        return super().__getitem__('file_name')

    @file_name.setter
    def file_name(self, file_name):
        super().__setitem__('file_name', file_name)

    @property
    def regions(self):
        return super().__getitem__('regions')

    @regions.setter
    def regions(self, regions):
        super().__setitem__('regions', regions)

class region(dict):
    def __init__(self, init_dict=None):
        empty_keys= {"id": "0"}
        if (init_dict):
            super().__init__(init_dict)
        else:
            super().__init__(empty_keys)
    
    @property
    def id(self):
        return super().__getitem__('id')

    @id.setter
    def id(self, id):
        super().__setitem__('id', id)

    @property
    def loop(self):
        return super().__getitem__('loop')

    @loop.setter
    def loop(self, loop):
        super().__setitem__('loop', loop)

    @property
    def in_time(self):
        return super().__getitem__('in_time')

    @in_time.setter
    def in_time(self, in_time):
        super().__setitem__('in_time', in_time)

    @property
    def out_time(self):
        return super().__getitem__('out_time')

    @out_time.setter
    def out_time(self, out_time):
        super().__setitem__('out_time', out_time)

    def __setitem__(self, key, value):
        if (key in ['in_time', 'out_time']) and (value not in (None, "")):
            if isinstance(value, CTimecode):
                ctime_value = value
            else:
                if isinstance(value, (int, float)):
                    ctime_value = CTimecode(start_seconds = value)
                    ctime_value.frames = ctime_value.frames + 1
                elif isinstance(value, str):
                    ctime_value = CTimecode(value)
                elif isinstance(value, dict):
                    dict_timecode = value.pop('CTimecode', None)
                    if dict_timecode is None:
                        ctime_value = CTimecode()
                    elif isinstance(dict_timecode, int):
                        ctime_value = CTimecode(start_seconds = dict_timecode)
                    else:
                        ctime_value = CTimecode(dict_timecode)

            super().__setitem__(key, ctime_value)

        else:
            super().__setitem__(key, value)
