from Xlib import X, display
from Xlib.ext import randr

d = display.Display()
s = d.screen()
window = s.root.create_window(0, 0, 1, 1, 1, s.root_depth)

res = randr.get_screen_resources(window)
for mode in res.modes:
    w, h = mode.width, mode.height
    print("Width: {}, height: {}".format(w, h))

o = randr.get_screen_resources(window).outputs
print(o)

print(randr.get_output_info(window, o[0], 0))
print(randr.get_output_info(window, o[1], 0))
print(randr.get_output_info(window, o[2], 0))
print(randr.get_output_info(window, o[3], 0))