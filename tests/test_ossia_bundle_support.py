# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

#!/usr/bin/env python3
"""Test script to check if pyossia supports OSC bundle sending.

This test will help determine if we can eliminate DmxOscClient
and use pyossia's native bundle support instead.
"""

import sys
import time

try:
    from pyossia import ossia

    OSSIA_AVAILABLE = True
except ImportError as e:
    print(f"⚠️  Import error: {e}")
    print("\nAttempting to inspect pyossia module structure despite import" "error...")
    OSSIA_AVAILABLE = False
    ossia = None

    # Try to inspect the pyossia package structure
    try:
        import pyossia

        print(f"\n✅ pyossia package found: {pyossia}")
        print(f"   Package location: {pyossia.__file__}")
        print(
            f"   Package attributes:"
            f"{[a for a in dir(pyossia) if not a.startswith('_')]}"
        )

        # Try to see if we can access the module directly
        import importlib

        try:
            ossia_module = importlib.import_module("pyossia.ossia_python")
            print(f"\n✅ ossia_python module found: {ossia_module}")
            _pub = [a for a in dir(ossia_module) if not a.startswith("_")]
            print(f"   Module attributes: {_pub[:30]}")

            # Check for bundle-related items
            bundle_items = [a for a in dir(ossia_module) if "bundle" in a.lower()]
            if bundle_items:
                print(f"   ✅ Bundle-related items found: {bundle_items}")
            else:
                print(f"   ❌ No bundle-related items found")
        except Exception as e2:
            print(f"\n❌ Could not import ossia_python: {e2}")
    except Exception as e3:
        print(f"❌ Could not inspect pyossia package: {e3}")


def test_basic_ossia():
    """Test basic pyossia functionality."""
    print("=" * 60)
    print("TEST 1: Basic pyossia device creation")
    print("=" * 60)

    if not OSSIA_AVAILABLE:
        print("❌ Cannot run test: pyossia import failed")
        return None

    try:
        # Create a local device
        device = ossia.LocalDevice("test_device")
        print("✅ LocalDevice created successfully")

        # Create some nodes
        root = device.root_node
        print(f"✅ Root node: {root}")

        # List available methods
        print("\nAvailable device methods:")
        methods = [m for m in dir(device) if not m.startswith("_")]
        for m in methods[:20]:  # Show first 20
            print(f"  - {m}")

        return device
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def test_osc_protocol():
    """Test OSC protocol and look for bundle methods."""
    print("\n" + "=" * 60)
    print("TEST 2: OSC Protocol and Bundle Support")
    print("=" * 60)

    if not OSSIA_AVAILABLE:
        print("❌ Cannot run test: pyossia import failed")
        return None

    try:
        # Create OSC device with unique ports
        device = ossia.OSCDevice("test_osc", "127.0.0.1", 19996, 19997)
        print("✅ OSCDevice created successfully")

        # Try to get the protocol
        print("\nAvailable OSCDevice methods:")
        methods = [m for m in dir(device) if not m.startswith("_")]
        for m in methods:
            print(f"  - {m}")

        # Check if there's a protocol attribute or method
        if hasattr(device, "protocol"):
            proto = device.protocol
            print(f"\n✅ Protocol attribute found: {proto}")
            print("\nProtocol methods:")
            proto_methods = [m for m in dir(proto) if not m.startswith("_")]
            for m in proto_methods:
                print(f"  - {m}")
        else:
            print("\n❌ No 'protocol' attribute found on OSCDevice")

        # Look for bundle-related methods
        bundle_methods = [
            m for m in dir(device) if "bundle" in m.lower() or "push" in m.lower()
        ]
        if bundle_methods:
            print(f"\n✅ Bundle/push methods found: {bundle_methods}")
        else:
            print("\n❌ No bundle/push methods found on OSCDevice")

        return device
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return None


def test_parameter_bundle():
    """Test if we can send multiple parameters as a bundle."""
    print("\n" + "=" * 60)
    print("TEST 3: Parameter Bundle Test")
    print("=" * 60)

    if not OSSIA_AVAILABLE:
        print("❌ Cannot run test: pyossia import failed")
        return None, None

    try:
        # Create sender and receiver with unique ports
        sender = ossia.OSCDevice("sender", "127.0.0.1", 19998, 19999)
        receiver = ossia.OSCDevice("receiver", "127.0.0.1", 19999, 19998)

        time.sleep(0.5)  # Wait for setup

        # Create parameters on receiver
        root = receiver.root_node
        param1 = root.create_child("param1")
        p1 = param1.create_parameter(ossia.ValueType.Float)

        param2 = root.create_child("param2")
        p2 = param2.create_parameter(ossia.ValueType.Float)

        param3 = root.create_child("param3")
        p3 = param3.create_parameter(ossia.ValueType.String)

        print("✅ Created 3 parameters on receiver")

        # Try to find bundle sending capability
        print("\nLooking for bundle methods on sender...")

        # Check various possible bundle methods
        possible_methods = [
            "push_bundle",
            "send_bundle",
            "push_raw_bundle",
            "send_raw_bundle",
            "bundle",
        ]

        found_methods = []
        for method_name in possible_methods:
            if hasattr(sender, method_name):
                found_methods.append(method_name)
                print(f"  ✅ Found: {method_name}")

        if not found_methods:
            print("  ❌ No bundle methods found")
            print("\n  Attempting to inspect underlying protocol...")

            # Try to access underlying protocol implementation
            for attr in dir(sender):
                obj = getattr(sender, attr)
                if hasattr(obj, "push_bundle") or hasattr(obj, "send_bundle"):
                    print(f"  ✅ Found bundle method on {attr}: {obj}")

        return sender, receiver

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return None, None


def test_libossia_bundle_element():
    """Test if ossia.bundle_element is available."""
    print("\n" + "=" * 60)
    print("TEST 4: ossia.bundle_element Check")
    print("=" * 60)

    if not OSSIA_AVAILABLE:
        print("❌ Cannot run test: pyossia import failed")
        return

    try:
        # Check if bundle_element exists in ossia module
        if hasattr(ossia, "bundle_element"):
            print("✅ ossia.bundle_element found!")
            bundle_elem = ossia.bundle_element
            print(f"   Type: {type(bundle_elem)}")
            print(
                f"   Available attributes:"
                f"{[a for a in dir(bundle_elem) if not a.startswith('_')]}"
            )
        else:
            print("❌ ossia.bundle_element not found")

        # Check what's available in ossia module
        print("\nSearching for 'bundle' in ossia module...")
        bundle_related = [item for item in dir(ossia) if "bundle" in item.lower()]
        if bundle_related:
            print(f"✅ Found: {bundle_related}")
        else:
            print("❌ No bundle-related items found")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()


def main():
    """Run all tests."""
    print("\n" + "🔬 " * 20)
    print("PYOSSIA BUNDLE SUPPORT TEST")
    print("🔬 " * 20 + "\n")

    # Run tests
    device = test_basic_ossia()
    osc_device = test_osc_protocol()
    sender, receiver = test_parameter_bundle()
    test_libossia_bundle_element()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY & RECOMMENDATIONS")
    print("=" * 60)

    print("""
Based on the test results above:

1. If bundle methods are found:
   → We can remove DmxOscClient and use native pyossia bundles
   → This will allow DMX bundles to be sent through OSCQuery
   
2. If NO bundle methods are found:
   → Keep DmxOscClient for bundle creation
   → Use OSCQuery for node routing/discovery
   → Use DmxOscClient for actual bundle transmission
   
3. Alternative approach:
   → Register a single OSCQuery endpoint like /dmxplayer/scene
   → That endpoint accepts serialized scene data
   → The endpoint handler reconstructs and sends the bundle locally
    """)

    print("\n✅ Test complete!")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
