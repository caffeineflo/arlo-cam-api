"""Tests for model-aware capability filtering."""

from __future__ import annotations

from src.devices.capabilities import (
    BASE_CAMERA_KEYS,
    filter_register_set,
    get_supported_keys,
)


def test_vmc3030_gets_base_keys_only():
    keys = get_supported_keys("VMC3030")
    assert "PIRTargetState" in keys
    assert "VideoOutputResolution" in keys
    assert "ArloSmart" not in keys
    assert "HdrControl" not in keys
    assert "UserStreamActive" not in keys


def test_vmc5040_gets_ultra_keys():
    keys = get_supported_keys("VMC5040")
    assert "PIRTargetState" in keys
    assert "ArloSmart" in keys
    assert "HdrControl" in keys
    assert "VideoMode" in keys


def test_unknown_model_gets_base_keys():
    keys = get_supported_keys("UNKNOWN123")
    assert keys == BASE_CAMERA_KEYS


def test_capabilities_from_registration_augment():
    registration = {"Capabilities": ["CustomKey1", "CustomKey2"]}
    keys = get_supported_keys("VMC3030", registration)
    assert "CustomKey1" in keys
    assert "CustomKey2" in keys
    assert "PIRTargetState" in keys


def test_filter_register_set_removes_unsupported():
    values = {
        "PIRTargetState": "Armed",
        "ArloSmart": True,
        "HdrControl": "auto",
        "VideoOutputResolution": "720p",
    }
    filtered = filter_register_set(values, "VMC3030")
    assert "PIRTargetState" in filtered
    assert "VideoOutputResolution" in filtered
    assert "ArloSmart" not in filtered
    assert "HdrControl" not in filtered


def test_filter_register_set_keeps_all_for_ultra():
    values = {
        "PIRTargetState": "Armed",
        "ArloSmart": True,
        "HdrControl": "auto",
    }
    filtered = filter_register_set(values, "VMC5040")
    assert filtered == values
