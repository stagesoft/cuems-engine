import pyossia as ossia
import time

def iterate_on_children(node):

    for child in node.children():
        print(str(child))
        iterate_on_children(child)


dev = ossia.OSCQueryDevice("test-remote", "ws://192.168.1.101:6666", 4546)
dev.update()
iterate_on_children(dev.root_node)

print(dev)
globq = ossia.GlobalMessageQueue(dev)
while(True):
  res = globq.pop()
  while(res != None):
    parameter, value = res
    print("globq: Got " +  str(parameter.node) + " => " + str(value))
    res = globq.pop()

  time.sleep(0.1)

