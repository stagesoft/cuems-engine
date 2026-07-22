# pyossia Architecture Evaluation Results

**Date:** February 2026  
**Context:** Evaluated after python-daemon removal

---

## Executive Summary

**DECISION: Hybrid Approach (Keep current architecture with refinements)**

pyossia's **client functionality works reliably**, but its **server and MIDI bindings are broken**. The GMQ failures were NOT caused by python-daemon - they're caused by pyossia's server ports never actually opening.

---

## Test Results

### Test 1: pyossia OSC Client (OSCDevice) ✓ PASSED

```
Messages sent: 300
Messages received: 300
Loss rate: 0.00%
Duration: 30 seconds
```

**Finding:** pyossia.OSCDevice reliably sends OSC messages. The `set_value()` method used throughout CUEMS works correctly.

### Test 2: pyossia MidiDevice ✗ NOT USABLE

```
MidiDevice constructor requires:
1. ossia_network_context (NOT exposed to Python)
2. string name
3. ossia::net::midi::midi_info (handle attribute throws TypeError)

Attempts:
- MidiDevice() → TypeError
- MidiDevice("name") → TypeError  
- MidiDevice("name", "input") → TypeError
```

**Finding:** MidiDevice class exists but cannot be instantiated from Python. The bindings are incomplete - `ossia_network_context` is not exposed and `MidiInfo.handle` throws "Unregistered type: libremidi::port_information".

### Test 3: pyossia Server (LocalDevice) ✗ BROKEN

```
LocalDevice.create_osc_server() returns: True
LocalDevice.create_oscquery_server() returns: True

Actual port binding test:
- UDP port: NOT bound (socket.bind succeeds)
- TCP port: NOT listening (connection refused)

Messages received via GMQ: 0
Messages received via callback: 0
```

**Finding:** LocalDevice.create_*_server() methods return True but **don't actually open network ports**. No messages can ever be received. This is why GlobalMessageQueue was unreliable - it had nothing to do with python-daemon.

### Additional Finding: GIL/Threading Issues

When using callbacks with certain pyossia operations, Python crashes with:
```
pybind11::handle::dec_ref() is being called while the GIL is either not held or invalid
```

---

## Root Cause Analysis

### What Works
| Component | Status | Evidence |
|-----------|--------|----------|
| pyossia.OSCDevice | ✓ Works | 0% message loss over 30s |
| pyossia.OSCQueryDevice | ✓ Works | Used for player discovery |
| set_value() method | ✓ Works | Reliable OSC sending |

### What's Broken
| Component | Status | Root Cause |
|-----------|--------|------------|
| LocalDevice OSC Server | ✗ Broken | Ports never bind |
| LocalDevice OSCQuery Server | ✗ Broken | Ports never bind |
| GlobalMessageQueue | ✗ Broken | Server doesn't receive |
| Callbacks | ✗ Broken | GIL issues, server broken |
| MidiDevice | ✗ Broken | Incomplete Python bindings |

### Historical "Unreliability" Explained

| Issue | Blamed On | Actual Cause |
|-------|-----------|--------------|
| GlobalMessageQueue failures | python-daemon | pyossia server doesn't open ports |
| Callbacks not firing | python-daemon | pyossia server doesn't receive |
| WebSocket issues | python-daemon | Possibly daemon, but server also broken |
| OSC to xjadeo fails | pyossia | Actually works! oscsend was unnecessary |

---

## Decision Matrix Application

Per the plan's decision matrix:

| Condition | Our Result |
|-----------|------------|
| pyossia OSC client works | ✓ Yes |
| pyossia OSC server works | ✗ No |
| pyossia MIDI works | ✗ No |

**Applicable Row:** "pyossia OSC works, MIDI doesn't"  
**Decision:** Hybrid: pyossia for OSC client, mido for MIDI, custom router if needed

---

## Recommended Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    RECOMMENDED (Hybrid)                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Bus Communication:  pynng (NNG)      ← KEEP (proven reliable)  │
│                                                                  │
│  OSC SENDING:        pyossia.OSCDevice ← KEEP (reliable)        │
│    - VideoPlayer                                                │
│    - AudioPlayer                                                │
│    - DMXPlayer                                                  │
│                                                                  │
│  OSC RECEIVING:      pythonosc        ← USE (if needed)         │
│    - External control                                           │
│    - OSC servers                                                │
│                                                                  │
│  MIDI:               mido             ← USE (for MIDI-OSC)      │
│    - MIDI input/output                                          │
│    - MTC (already using)                                        │
│                                                                  │
│  MIDI-OSC Router:    Custom           ← BUILD (if needed)       │
│    - mido (MIDI side)                                           │
│    - pyossia.OSCDevice (OSC side)                              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Action Items

### Immediate (No Change Needed)
- [x] Keep NNG for ControllerEngine ↔ NodeEngine communication
- [x] Keep pyossia.OSCDevice for audio/DMX/video player control
- [x] Keep mido for MTC

### Potential Cleanup
- [ ] **Remove oscsend workaround** - pyossia OSCDevice is reliable, oscsend subprocess calls are unnecessary
- [ ] Remove GlobalMessageQueue code/tests if unused

### Future MIDI-OSC Routing
If MIDI↔OSC bridging is needed, build a simple custom router:

```python
# Example MIDI-OSC router (future implementation)
import mido
from pyossia.ossia_python import OSCDevice

class MidiOscRouter:
    def __init__(self, midi_port, osc_host, osc_port):
        self.midi = mido.open_input(midi_port, callback=self._on_midi)
        self.osc = OSCDevice("midi_router", osc_host, osc_port, 0)
        
    def _on_midi(self, msg):
        # Route MIDI CC to OSC
        if msg.type == 'control_change':
            node = self.osc.root_node.add_node(f'/midi/cc/{msg.control}')
            param = node.create_parameter(ValueType.Int)
            param.value = msg.value
```

---

## Conclusion

**pyossia is valuable but limited in Python:**

1. **Keep using** pyossia.OSCDevice for OSC client operations - it works reliably
2. **Don't use** pyossia for OSC server features - the server never binds ports
3. **Don't use** pyossia.MidiDevice - bindings are incomplete
4. **Don't use** GlobalMessageQueue - it can't receive messages

The oscsend workaround for video can be removed since pyossia OSC sending is reliable. The NNG workaround should stay because pyossia cannot receive OSC reliably.

For future MIDI↔OSC routing, use mido + pyossia.OSCDevice as a simple custom solution.
