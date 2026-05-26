# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""Tests for pyossia OSC client and server functionality.

These tests verify basic OSC communication using pyossia, replacing
the old pythonosc-based tests.
"""
import time
from pyossia import ossia, ValueType


def test_osc_device_creation():
    """Test creating an OSC device."""
    # Arrange & Act
    device = ossia.OSCDevice("test_client", "127.0.0.1", 19990, 19991)

    # Assert
    assert device is not None
    assert device.root_node is not None


def test_osc_device_add_node():
    """Test adding nodes to OSC device."""
    # Arrange
    device = ossia.OSCDevice("test_client", "127.0.0.1", 19992, 19993)

    # Act
    node = device.root_node.add_node("/test")
    param = node.create_parameter(ValueType.Int)

    # Assert
    assert node is not None
    assert param is not None
    assert param.value_type == ValueType.Int


def test_osc_parameter_value_setting():
    """Test setting parameter values."""
    # Arrange
    device = ossia.OSCDevice("test_client", "127.0.0.1", 19994, 19995)
    node = device.root_node.add_node("/test")
    param = node.create_parameter(ValueType.Int)

    # Act
    param.value = 42

    # Assert
    assert param.value == 42


def test_osc_parameter_callback():
    """Test parameter callbacks."""
    # Arrange
    callback_values = []

    def callback(value):
        callback_values.append(value)

    device = ossia.OSCDevice("test_client", "127.0.0.1", 19996, 19997)
    node = device.root_node.add_node("/test")
    param = node.create_parameter(ValueType.Int)
    param.add_callback(callback)

    # Act
    param.value = 10
    time.sleep(0.01)  # Allow callback to fire
    param.value = 20
    time.sleep(0.01)

    # Assert
    assert 10 in callback_values
    assert 20 in callback_values


def test_osc_multiple_parameters():
    """Test creating multiple parameters with different types."""
    # Arrange
    device = ossia.OSCDevice("test_client", "127.0.0.1", 19998, 19999)
    root = device.root_node

    # Act
    int_param = root.add_node("/int").create_parameter(ValueType.Int)
    float_param = root.add_node("/float").create_parameter(ValueType.Float)
    string_param = root.add_node("/string").create_parameter(ValueType.String)
    list_param = root.add_node("/list").create_parameter(ValueType.List)

    int_param.value = 42
    float_param.value = 3.14
    string_param.value = "hello"
    list_param.value = [1, 2, 3]

    # Assert
    assert int_param.value == 42
    assert abs(float_param.value - 3.14) < 0.01
    assert string_param.value == "hello"
    assert list_param.value == [1, 2, 3]


def test_osc_bundle_sending():
    """Test sending OSC bundles."""
    # Arrange
    sender = ossia.OSCDevice("sender", "127.0.0.1", 20000, 20001)
    receiver = ossia.LocalDevice("receiver")

    # Create parameters
    param1 = sender.root_node.add_node("/param1").create_parameter(ValueType.Int)
    param2 = sender.root_node.add_node("/param2").create_parameter(ValueType.Float)

    # Act - Create and send bundle
    bundle = ossia.Bundle()
    bundle.append(param1, 100)
    bundle.append(param2, 2.5)
    sender.push_bundle(bundle)

    # Assert - Bundle was created and sent without error
    assert len(bundle) == 2


def test_osc_bundle_with_list_parameter():
    """Test sending OSC bundles with list parameters (DMX use case)."""
    # Arrange
    sender = ossia.OSCDevice("sender", "127.0.0.1", 20002, 20003)

    # Create list parameter for DMX-style data
    frame_param = sender.root_node.add_node("/frame").create_parameter(ValueType.List)
    fade_param = sender.root_node.add_node("/fade").create_parameter(ValueType.Float)

    # Act - Create bundle with list data
    bundle = ossia.Bundle()
    dmx_data = [1, 0, 255, 1, 128, 2, 64]  # universe 1, ch0=255, ch1=128, ch2=64
    bundle.append(frame_param, dmx_data)
    bundle.append(fade_param, 2.0)

    sender.push_bundle(bundle)

    # Assert
    assert len(bundle) == 2


def test_local_device_communication():
    """Test communication between local devices."""
    # Arrange
    callback_values = []

    def callback(value):
        callback_values.append(value)

    device = ossia.LocalDevice("test_device")
    node = device.root_node.add_node("/test")
    param = node.create_parameter(ValueType.Int)
    param.add_callback(callback)

    # Act
    param.value = 50
    time.sleep(0.01)
    param.value = 60
    time.sleep(0.01)

    # Assert
    assert param.value == 60
    assert 50 in callback_values
    assert 60 in callback_values


def test_osc_parameter_string_values():
    """Test OSC parameters with string values."""
    # Arrange
    device = ossia.OSCDevice("test", "127.0.0.1", 20004, 20005)
    node = device.root_node.add_node("/test_string")
    param = node.create_parameter(ValueType.String)

    # Act
    param.value = "now"

    # Assert
    assert param.value == "now"

    # Act
    param.value = "01:00:00:00"

    # Assert
    assert param.value == "01:00:00:00"


def test_osc_bundle_multiple_messages():
    """Test bundle with multiple messages to same parameter."""
    # Arrange
    sender = ossia.OSCDevice("sender", "127.0.0.1", 20006, 20007)
    param = sender.root_node.add_node("/frame").create_parameter(ValueType.List)

    # Act - Multiple frames in one bundle
    bundle = ossia.Bundle()
    bundle.append(param, [1, 0, 255])  # Universe 1
    bundle.append(param, [2, 0, 128])  # Universe 2
    bundle.append(param, [3, 0, 64])  # Universe 3

    sender.push_bundle(bundle)

    # Assert
    assert len(bundle) == 3


def test_osc_device_node_hierarchy():
    """Test creating nested node hierarchies."""
    # Arrange
    device = ossia.OSCDevice("test", "127.0.0.1", 20008, 20009)
    root = device.root_node

    # Act
    parent = root.add_node("/parent")
    child = parent.add_node("/child")
    grandchild = child.add_node("/grandchild")
    param = grandchild.create_parameter(ValueType.Int)
    param.value = 123

    # Assert
    assert param.value == 123
    # Verify hierarchy by checking the parameter exists
    assert param is not None
    assert grandchild is not None
    assert child is not None
    assert parent is not None


def test_osc_parameter_types():
    """Test all commonly used OSC parameter types."""
    # Arrange
    device = ossia.OSCDevice("test", "127.0.0.1", 20010, 20011)
    root = device.root_node

    # Act & Assert - Int
    int_param = root.add_node("/int_test").create_parameter(ValueType.Int)
    int_param.value = 42
    assert int_param.value == 42
    assert int_param.value_type == ValueType.Int

    # Act & Assert - Float
    float_param = root.add_node("/float_test").create_parameter(ValueType.Float)
    float_param.value = 3.14159
    assert abs(float_param.value - 3.14159) < 0.0001
    assert float_param.value_type == ValueType.Float

    # Act & Assert - String
    string_param = root.add_node("/string_test").create_parameter(ValueType.String)
    string_param.value = "test_string"
    assert string_param.value == "test_string"
    assert string_param.value_type == ValueType.String

    # Act & Assert - Bool
    bool_param = root.add_node("/bool_test").create_parameter(ValueType.Bool)
    bool_param.value = True
    assert bool_param.value == True
    assert bool_param.value_type == ValueType.Bool

    # Act & Assert - List
    list_param = root.add_node("/list_test").create_parameter(ValueType.List)
    list_param.value = [1, 2, 3, 4, 5]
    assert list_param.value == [1, 2, 3, 4, 5]
    assert list_param.value_type == ValueType.List
