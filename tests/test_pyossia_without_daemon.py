#!/usr/bin/env python3
"""
Test pyossia OSC reliability without python-daemon.

This test verifies whether pyossia can reliably send OSC messages
now that python-daemon has been removed from the codebase.

The historical "unreliability" of pyossia with xjadeo was likely
caused by python-daemon corrupting pyossia's sockets/threads.
"""

import sys
import time
import subprocess
from threading import Thread, Event

# Add source path
sys.path.insert(0, '/home/stagelab/src/cuems-engine/src')
sys.path.insert(0, '/home/stagelab/src/cuems-utils/src')

from cuemsutils.log import Logger


def test_pyossia_osc_client():
    """Test basic pyossia OSC client functionality."""
    print("\n" + "="*60)
    print("TEST 1: pyossia OSC Client Basic Test")
    print("="*60)
    
    try:
        from pyossia.ossia_python import OSCDevice
        print("✓ pyossia.ossia_python.OSCDevice imported successfully")
    except ImportError as e:
        print(f"✗ Failed to import OSCDevice: {e}")
        return False
    
    # Create a simple OSC server to receive messages
    try:
        from pythonosc.osc_server import ThreadingOSCUDPServer
        from pythonosc.dispatcher import Dispatcher
        
        received_messages = []
        
        def message_handler(address, *args):
            received_messages.append((address, args))
            print(f"  Received: {address} = {args}")
        
        dispatcher = Dispatcher()
        dispatcher.set_default_handler(message_handler)
        
        # Start server on port 19001
        server = ThreadingOSCUDPServer(("127.0.0.1", 19001), dispatcher)
        server_thread = Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        print("✓ Test OSC server started on port 19001")
        
    except Exception as e:
        print(f"✗ Failed to start test server: {e}")
        return False
    
    # Create pyossia OSC client
    try:
        # OSCDevice(name, host, remote_port, local_port)
        client = OSCDevice("test_client", "127.0.0.1", 19001, 19002)
        print("✓ pyossia OSCDevice created successfully")
        time.sleep(0.2)  # Allow connection to establish
    except Exception as e:
        print(f"✗ Failed to create OSCDevice: {e}")
        server.shutdown()
        return False
    
    # Create a test node and parameter
    try:
        node = client.add_node("/test/value")
        from pyossia import ValueType
        param = node.create_parameter(ValueType.Int)
        print("✓ Node and parameter created")
    except Exception as e:
        print(f"✗ Failed to create node/parameter: {e}")
        server.shutdown()
        return False
    
    # Send test messages
    print("\nSending 10 test messages...")
    success_count = 0
    for i in range(10):
        try:
            param.push_value(i * 10)
            time.sleep(0.05)  # Small delay between messages
            success_count += 1
        except Exception as e:
            print(f"  ✗ Failed to send message {i}: {e}")
    
    time.sleep(0.3)  # Wait for messages to arrive
    server.shutdown()
    
    print(f"\nResults:")
    print(f"  Messages sent: {success_count}/10")
    print(f"  Messages received: {len(received_messages)}")
    
    if len(received_messages) >= 8:  # Allow some tolerance
        print("✓ TEST PASSED: pyossia OSC client works reliably")
        return True
    else:
        print("✗ TEST FAILED: Messages lost")
        return False


def test_pyossia_set_value():
    """Test pyossia set_value method (used in cue code)."""
    print("\n" + "="*60)
    print("TEST 2: pyossia set_value() Method Test")
    print("="*60)
    
    try:
        from pyossia.ossia_python import OSCDevice
        from pyossia import ValueType
        from pythonosc.osc_server import ThreadingOSCUDPServer
        from pythonosc.dispatcher import Dispatcher
        
        received = []
        
        def handler(address, *args):
            received.append((address, args))
            print(f"  Received: {address} = {args}")
        
        dispatcher = Dispatcher()
        dispatcher.set_default_handler(handler)
        
        server = ThreadingOSCUDPServer(("127.0.0.1", 19003), dispatcher)
        server_thread = Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        
        # Create client with multiple endpoints (like VideoClient)
        client = OSCDevice("video_test", "127.0.0.1", 19003, 19004)
        time.sleep(0.2)
        
        # Create endpoints similar to xjadeo config
        endpoints = {
            '/jadeo/load': ValueType.String,
            '/jadeo/offset': ValueType.Int,
            '/jadeo/cmd': ValueType.String,
        }
        
        for path, vtype in endpoints.items():
            node = client.add_node(path)
            node.create_parameter(vtype)
        
        print("✓ Created video player-like endpoints")
        
        # Test set_value on each endpoint
        test_values = [
            ('/jadeo/load', '/path/to/video.mov'),
            ('/jadeo/offset', -1500),
            ('/jadeo/cmd', 'midi connect Midi Through'),
        ]
        
        print("\nSending test values via set_value()...")
        for path, value in test_values:
            try:
                node = client.find_node(path)
                if node and node.parameter:
                    node.parameter.value = value
                    print(f"  Sent: {path} = {value}")
                else:
                    print(f"  ✗ Node not found: {path}")
            except Exception as e:
                print(f"  ✗ Error setting {path}: {e}")
        
        time.sleep(0.3)
        server.shutdown()
        
        print(f"\nResults:")
        print(f"  Values sent: {len(test_values)}")
        print(f"  Values received: {len(received)}")
        
        if len(received) >= 2:
            print("✓ TEST PASSED: set_value() works reliably")
            return True
        else:
            print("✗ TEST FAILED: Values not received")
            return False
            
    except Exception as e:
        print(f"✗ TEST FAILED with exception: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_pyossia_long_running():
    """Test pyossia reliability over extended period."""
    print("\n" + "="*60)
    print("TEST 3: pyossia Long-Running Reliability Test (30 seconds)")
    print("="*60)
    
    try:
        from pyossia.ossia_python import OSCDevice
        from pyossia import ValueType
        from pythonosc.osc_server import ThreadingOSCUDPServer
        from pythonosc.dispatcher import Dispatcher
        
        received_count = [0]  # Use list for mutable in closure
        stop_event = Event()
        
        def handler(address, *args):
            received_count[0] += 1
        
        dispatcher = Dispatcher()
        dispatcher.set_default_handler(handler)
        
        server = ThreadingOSCUDPServer(("127.0.0.1", 19005), dispatcher)
        server_thread = Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        
        client = OSCDevice("long_test", "127.0.0.1", 19005, 19006)
        time.sleep(0.2)
        
        node = client.add_node("/test/counter")
        param = node.create_parameter(ValueType.Int)
        
        print("Sending messages for 30 seconds (10 per second)...")
        sent_count = 0
        start_time = time.time()
        
        while time.time() - start_time < 30:
            try:
                param.push_value(sent_count)
                sent_count += 1
                time.sleep(0.1)
                
                # Progress indicator
                elapsed = int(time.time() - start_time)
                if sent_count % 50 == 0:
                    print(f"  {elapsed}s: sent {sent_count}, received {received_count[0]}")
                    
            except Exception as e:
                print(f"  ✗ Error at message {sent_count}: {e}")
                break
        
        time.sleep(0.5)
        server.shutdown()
        
        loss_rate = (sent_count - received_count[0]) / sent_count * 100 if sent_count > 0 else 100
        
        print(f"\nResults:")
        print(f"  Duration: 30 seconds")
        print(f"  Messages sent: {sent_count}")
        print(f"  Messages received: {received_count[0]}")
        print(f"  Loss rate: {loss_rate:.2f}%")
        
        if loss_rate < 5:  # Less than 5% loss is acceptable
            print("✓ TEST PASSED: pyossia reliable over extended period")
            return True
        else:
            print("✗ TEST FAILED: High message loss rate")
            return False
            
    except Exception as e:
        print(f"✗ TEST FAILED with exception: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("="*60)
    print("PYOSSIA RELIABILITY TEST (Without python-daemon)")
    print("="*60)
    print("\nThis test verifies pyossia OSC reliability now that")
    print("python-daemon has been removed from the codebase.")
    print("\nThe historical 'unreliability' was likely caused by")
    print("python-daemon corrupting pyossia's sockets/threads.")
    
    results = []
    
    # Test 1: Basic OSC client
    results.append(("Basic OSC Client", test_pyossia_osc_client()))
    
    # Test 2: set_value method
    results.append(("set_value() Method", test_pyossia_set_value()))
    
    # Test 3: Long-running reliability
    results.append(("Long-Running (30s)", test_pyossia_long_running()))
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    all_passed = True
    for name, passed in results:
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False
    
    print("\n" + "="*60)
    if all_passed:
        print("OVERALL: ✓ ALL TESTS PASSED")
        print("\npyossia appears reliable without python-daemon!")
        print("Consider removing oscsend subprocess workarounds.")
    else:
        print("OVERALL: ✗ SOME TESTS FAILED")
        print("\npyossia may have intrinsic issues beyond python-daemon.")
        print("Consider Option B: custom routing with python-osc + mido.")
    print("="*60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
