#!/usr/bin/env python3
"""
Test pyossia GlobalMessageQueue without python-daemon.

FINDINGS (2024):
================
GMQ failures are NOT due to python-daemon. The root cause is:

pyossia LocalDevice.create_osc_server() and create_oscquery_server()
return True but DON'T ACTUALLY OPEN NETWORK PORTS.

Verified by:
1. socket.bind() succeeds on the "listening" ports (they're not bound)
2. socket.connect() fails on TCP ports (nothing listening)
3. No messages ever received via GMQ or callbacks

The pyossia server functionality appears broken/incomplete in the
Python bindings. Only the client functionality (OSCDevice) works.

CONCLUSION:
- Keep using NNG for bus communication
- Keep using pythonosc for any server-side OSC needs
- pyossia is only reliable as an OSC CLIENT
"""

import sys
import time
import threading

sys.path.insert(0, '/home/stagelab/src/cuems-engine/src')
sys.path.insert(0, '/home/stagelab/src/cuems-utils/src')


def test_gmq_basic():
    """Test basic GlobalMessageQueue functionality."""
    print("\n" + "="*60)
    print("TEST: GlobalMessageQueue Basic Functionality")
    print("="*60)
    
    from pyossia import ossia, LocalDevice, ValueType
    from pythonosc.udp_client import SimpleUDPClient
    
    # Create local device with OSC server
    ld = LocalDevice('gmq_test_server')
    ld.create_osc_server('127.0.0.1', 19020, 19021, False)
    print("✓ LocalDevice created with OSC server on port 19020")
    
    # Add test parameter
    node = ld.add_node('/test/value')
    param = node.create_parameter(ValueType.Int)
    print("✓ Test parameter created at /test/value")
    
    # Create GlobalMessageQueue
    gmq = ossia.GlobalMessageQueue(ld)
    print("✓ GlobalMessageQueue created")
    
    # Create OSC client to send messages
    osc_client = SimpleUDPClient('127.0.0.1', 19020)
    print("✓ OSC client ready to send to port 19020")
    
    # Send some values
    print("\nSending 10 test values...")
    for i in range(10):
        osc_client.send_message('/test/value', i * 100)
        time.sleep(0.05)
    
    time.sleep(0.3)  # Wait for messages
    
    # Pop messages from GMQ
    print("\nPopping messages from GlobalMessageQueue...")
    received = []
    message = gmq.pop()
    while message:
        received.append(message)
        print(f"  Received: {message}")
        message = gmq.pop()
    
    print(f"\nResults:")
    print(f"  Messages sent: 10")
    print(f"  Messages received via GMQ: {len(received)}")
    
    if len(received) >= 8:
        print("✓ TEST PASSED: GMQ working")
        return True
    else:
        print("✗ TEST FAILED: Messages lost in GMQ")
        return False


def test_gmq_extended():
    """Extended GMQ test - 30 seconds of operation."""
    print("\n" + "="*60)
    print("TEST: GlobalMessageQueue Extended (30 seconds)")
    print("="*60)
    
    from pyossia import ossia, LocalDevice, ValueType
    from pythonosc.udp_client import SimpleUDPClient
    
    # Setup
    ld = LocalDevice('gmq_extended')
    ld.create_osc_server('127.0.0.1', 19025, 19026, False)
    
    node = ld.add_node('/counter')
    param = node.create_parameter(ValueType.Int)
    
    gmq = ossia.GlobalMessageQueue(ld)
    osc_client = SimpleUDPClient('127.0.0.1', 19025)
    
    print("Setup complete, starting extended test...")
    
    # Receiver thread
    received_count = [0]
    stop_flag = threading.Event()
    
    def receiver():
        while not stop_flag.is_set():
            msg = gmq.pop()
            if msg:
                received_count[0] += 1
            else:
                time.sleep(0.01)  # Small sleep when no messages
    
    receiver_thread = threading.Thread(target=receiver, daemon=True)
    receiver_thread.start()
    
    # Send messages for 30 seconds
    sent_count = 0
    start_time = time.time()
    
    while time.time() - start_time < 30:
        osc_client.send_message('/counter', sent_count)
        sent_count += 1
        time.sleep(0.1)  # 10 messages per second
        
        elapsed = int(time.time() - start_time)
        if sent_count % 50 == 0:
            print(f"  {elapsed}s: sent {sent_count}, received {received_count[0]}")
    
    time.sleep(0.5)  # Final flush
    stop_flag.set()
    
    loss_rate = (sent_count - received_count[0]) / sent_count * 100 if sent_count > 0 else 100
    
    print(f"\nResults:")
    print(f"  Duration: 30 seconds")
    print(f"  Messages sent: {sent_count}")
    print(f"  Messages received: {received_count[0]}")
    print(f"  Loss rate: {loss_rate:.2f}%")
    
    if loss_rate < 5:
        print("✓ TEST PASSED: GMQ reliable over extended period")
        return True
    else:
        print("✗ TEST FAILED: High message loss in GMQ")
        return False


def main():
    print("="*60)
    print("PYOSSIA GLOBALMESSAGEQUEUE TEST (Without python-daemon)")
    print("="*60)
    print("\nThis tests GMQ reliability now that python-daemon is removed.")
    print("GMQ was previously replaced with HTTP polling due to unreliability")
    print("which was likely caused by python-daemon thread corruption.")
    
    results = []
    
    results.append(("GMQ Basic", test_gmq_basic()))
    results.append(("GMQ Extended (30s)", test_gmq_extended()))
    
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
        print("\nGlobalMessageQueue is reliable without python-daemon!")
        print("Consider re-enabling GMQ in NodeEngine.")
    else:
        print("OVERALL: ✗ SOME TESTS FAILED")
        print("\nGMQ has issues beyond python-daemon. Keep using NNG.")
    print("="*60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
