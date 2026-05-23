"""Tests for database persistence."""

from __future__ import annotations

import json

import pytest


@pytest.mark.asyncio
async def test_upsert_and_get_device(db):
    await db.upsert_device(
        serial_number="TEST001",
        ip="10.0.0.1",
        hostname="VMC3030-TEST",
        friendly_name="Test Camera",
        registration={"SystemModelNumber": "VMC3030"},
    )

    device = await db.get_device("TEST001")
    assert device is not None
    assert device["ip"] == "10.0.0.1"
    assert device["hostname"] == "VMC3030-TEST"
    assert device["registration"]["SystemModelNumber"] == "VMC3030"


@pytest.mark.asyncio
async def test_upsert_updates_ip(db):
    await db.upsert_device("TEST001", "10.0.0.1", "host", "name")
    await db.upsert_device("TEST001", "10.0.0.2", "host", "name")

    device = await db.get_device("TEST001")
    assert device["ip"] == "10.0.0.2"


@pytest.mark.asyncio
async def test_update_status(db):
    await db.upsert_device("TEST001", "10.0.0.1", "host", "name")
    await db.update_status("TEST001", {"BatteryPercentage": 85})

    device = await db.get_device("TEST001")
    assert device["status"]["BatteryPercentage"] == 85


@pytest.mark.asyncio
async def test_delete_device(db):
    await db.upsert_device("TEST001", "10.0.0.1", "host", "name")
    result = await db.delete_device("TEST001")
    assert result is True

    device = await db.get_device("TEST001")
    assert device is None


@pytest.mark.asyncio
async def test_delete_nonexistent(db):
    result = await db.delete_device("NOPE")
    assert result is False


@pytest.mark.asyncio
async def test_desired_state_upsert_and_get(db):
    values = {"VideoOutputResolution": "720p", "VideoTargetBitrate": 1250}
    await db.upsert_desired_state("TEST001", values, quality_preset="high")

    state = await db.get_desired_state("TEST001")
    assert state is not None
    assert json.loads(state["register_set_values"]) == values
    assert state["quality_preset"] == "high"


@pytest.mark.asyncio
async def test_desired_state_updates_on_conflict(db):
    await db.upsert_desired_state("TEST001", {"key1": "a"}, quality_preset="low")
    await db.upsert_desired_state("TEST001", {"key1": "b", "key2": "c"}, quality_preset="high")

    state = await db.get_desired_state("TEST001")
    parsed = json.loads(state["register_set_values"])
    assert parsed == {"key1": "b", "key2": "c"}
    assert state["quality_preset"] == "high"


@pytest.mark.asyncio
async def test_desired_state_not_found(db):
    state = await db.get_desired_state("NOPE")
    assert state is None


@pytest.mark.asyncio
async def test_get_all_devices(db):
    await db.upsert_device("CAM1", "10.0.0.1", "host1", "Camera 1")
    await db.upsert_device("CAM2", "10.0.0.2", "host2", "Camera 2")

    devices = await db.get_all_devices()
    assert len(devices) == 2
    serials = {d["serial_number"] for d in devices}
    assert serials == {"CAM1", "CAM2"}
