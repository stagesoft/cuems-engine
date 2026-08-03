# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

#!/usr/bin/env python3
"""
Test pyossia MidiDevice functionality.

FINDINGS (2024):
================
pyossia.MidiDevice exists but CANNOT be instantiated from Python:

1. Constructor requires: ossia_network_context, str name, ossia::net::midi::midi_info
   - ossia_network_context is NOT exposed in Python bindings
   - midi_info requires handle attribute which throws TypeError on access

2. list_midi_devices() returns MidiInfo objects but:
   - MidiInfo.handle throws: TypeError: Unregistered type : libremidi::port_information

3. Attempting MidiDevice() with any arguments fails:
   - MidiDevice("name") → TypeError (needs 3 args)
   - MidiDevice("name", "input") → TypeError (needs 3 args)  
   - No way to get ossia_network_context

CONCLUSION:
- MidiDevice bindings are incomplete
- MIDI-OSC bridging via pyossia is NOT possible with current Python bindings
- Alternative: Use mido for MIDI + pythonosc/pyossia.OSCDevice for OSC routing
"""

import sys
sys.path.insert(0, '/home/stagelab/src/cuems-engine/src')
sys.path.insert(0, '/home/stagelab/src/cuems-utils/src')


def test_midi_device_availability():
    """Test if MidiDevice can be imported."""
    print("\n" + "="*60)
    print("TEST: MidiDevice Import/Availability")
    print("="*60)
    
    try:
        from pyossia import ossia
        MidiDevice = ossia.MidiDevice
        print(f"✓ MidiDevice class exists: {MidiDevice}")
        return True
    except (ImportError, AttributeError) as e:
        print(f"✗ MidiDevice not available: {e}")
        return False


def test_midi_device_instantiation():
    """Test if MidiDevice can be instantiated."""
    print("\n" + "="*60)
    print("TEST: MidiDevice Instantiation (Expected to FAIL)")
    print("="*60)
    
    from pyossia import ossia
    MidiDevice = ossia.MidiDevice
    
    # Try various instantiation attempts
    attempts = [
        ("MidiDevice()", lambda: MidiDevice()),
        ("MidiDevice('test')", lambda: MidiDevice('test')),
        ("MidiDevice('test', 'input')", lambda: MidiDevice('test', 'input')),
    ]
    
    for desc, func in attempts:
        try:
            result = func()
            print(f"✓ {desc} succeeded: {result}")
            return True  # Unexpected success
        except TypeError as e:
            print(f"✗ {desc} → TypeError: {e}")
        except Exception as e:
            print(f"✗ {desc} → {type(e).__name__}: {e}")
    
    print("\nReason: MidiDevice requires ossia_network_context which isn't exposed")
    return False  # Expected failure


def test_list_midi_devices():
    """Test list_midi_devices() function."""
    print("\n" + "="*60)
    print("TEST: list_midi_devices()")
    print("="*60)
    
    from pyossia import ossia
    
    try:
        devices = ossia.list_midi_devices()
        print(f"✓ list_midi_devices() returned: {type(devices)}")
        print(f"  Count: {len(devices)}")
        
        for i, dev in enumerate(devices):
            print(f"\n  Device {i}: {dev}")
            print(f"    Type: {type(dev)}")
            
            # Try to access attributes
            for attr in ['handle', 'type', 'virtual', 'port', 'name']:
                try:
                    val = getattr(dev, attr)
                    print(f"    {attr}: {val}")
                except TypeError as e:
                    print(f"    {attr}: TypeError - {e}")
                except AttributeError:
                    pass
        
        return len(devices) > 0
    except Exception as e:
        print(f"✗ list_midi_devices() failed: {e}")
        return False


def test_midi_with_mido():
    """Compare with mido for MIDI access."""
    print("\n" + "="*60)
    print("TEST: mido MIDI Access (Alternative)")
    print("="*60)
    
    try:
        import mido
        
        print("Input ports:")
        for port in mido.get_input_names():
            print(f"  IN:  {port}")
        
        print("\nOutput ports:")
        for port in mido.get_output_names():
            print(f"  OUT: {port}")
        
        print("\n✓ mido can access MIDI ports directly")
        return True
    except Exception as e:
        print(f"✗ mido failed: {e}")
        return False


def main():
    print("="*60)
    print("PYOSSIA MIDIDEVICE TEST")
    print("="*60)
    print("\nTesting if pyossia can be used for MIDI-OSC bridging...")
    
    results = []
    
    results.append(("MidiDevice Available", test_midi_device_availability()))
    results.append(("MidiDevice Instantiation", test_midi_device_instantiation()))
    results.append(("list_midi_devices()", test_list_midi_devices()))
    results.append(("mido Alternative", test_midi_with_mido()))
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    for name, passed in results:
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"  {name}: {status}")
    
    print("\n" + "="*60)
    print("CONCLUSION: pyossia MidiDevice cannot be used from Python")
    print("")
    print("The bindings are incomplete:")
    print("- ossia_network_context not exposed")
    print("- MidiInfo.handle throws TypeError (unregistered type)")
    print("")
    print("RECOMMENDATION: Use mido + OSCDevice for MIDI-OSC routing")
    print("="*60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
