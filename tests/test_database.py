"""Tests for database persistence."""

from __future__ import annotations

import json
import sqlite3

import pytest

from src.devices import base as device_base_module
from src.state.database import Database


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
    await db.upsert_desired_state(
        "TEST001",
        values,
        quality_preset="high",
        power_mode="battery",
    )

    state = await db.get_desired_state("TEST001")
    assert state is not None
    assert json.loads(state["register_set_values"]) == values
    assert state["quality_preset"] == "high"
    assert state["power_mode"] == "battery"


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


@pytest.mark.asyncio
async def test_delete_device_also_deletes_desired_state(db):
    await db.upsert_device("TEST001", "10.0.0.1", "host", "name")
    await db.upsert_desired_state("TEST001", {}, power_mode="battery")

    await db.delete_device("TEST001")

    assert await db.get_desired_state("TEST001") is None


@pytest.mark.asyncio
async def test_connect_migrates_existing_desired_state_table(tmp_path):
    path = tmp_path / "arlo.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE devices (
                serial_number TEXT PRIMARY KEY,
                ip TEXT,
                hostname TEXT,
                friendly_name TEXT,
                registration TEXT,
                status TEXT
            )"""
        )
        connection.execute(
            """CREATE TABLE desired_state (
                serial_number TEXT PRIMARY KEY,
                register_set_values TEXT NOT NULL DEFAULT '{}',
                quality_preset TEXT,
                updated_at REAL NOT NULL
            )"""
        )
        connection.execute(
            "INSERT INTO desired_state VALUES (?, ?, ?, ?)",
            (
                "TEST001",
                json.dumps(
                    {
                        "UserStreamActive": 0,
                        "PIRStartSensitivity": 80,
                        "DefaultMotionStreamTimeLimit": 60,
                        "MaxUserStreamTimeLimit": 180,
                        "MaxStreamTimeLimit": 86400,
                        "MaxMotionStreamTimeLimit": 60,
                    }
                ),
                None,
                1.0,
            ),
        )

    database = Database(str(path))
    await database.connect()
    state = await database.get_desired_state("TEST001")
    await database.close()

    assert (
        "power_mode" in state,
        json.loads(state["register_set_values"]),
    ) == (
        True,
        {
            "PIRStartSensitivity": 80,
            "DefaultMotionStreamTimeLimit": 30,
            "MaxUserStreamTimeLimit": 30,
            "MaxStreamTimeLimit": 180,
            "MaxMotionStreamTimeLimit": 30,
        },
    )


@pytest.mark.asyncio
async def test_connect_preserves_external_stream_limits(tmp_path):
    path = tmp_path / "arlo.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """CREATE TABLE devices (
                serial_number TEXT PRIMARY KEY,
                ip TEXT,
                hostname TEXT,
                friendly_name TEXT,
                registration TEXT,
                status TEXT,
                last_seen REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE desired_state (
                serial_number TEXT PRIMARY KEY,
                register_set_values TEXT NOT NULL DEFAULT '{}',
                quality_preset TEXT,
                power_mode TEXT,
                updated_at REAL NOT NULL
            );"""
        )
        connection.execute(
            "INSERT INTO desired_state VALUES (?, ?, ?, ?, ?)",
            (
                "TEST001",
                json.dumps(
                    {
                        "MaxUserStreamTimeLimit": 86400,
                        "MaxStreamTimeLimit": 86400,
                    }
                ),
                None,
                "external",
                1.0,
            ),
        )

    database = Database(str(path))
    await database.connect()
    state = await database.get_desired_state("TEST001")
    await database.close()

    assert json.loads(state["register_set_values"]) == {
        "MaxUserStreamTimeLimit": 86400,
        "MaxStreamTimeLimit": 86400,
    }


@pytest.mark.asyncio
async def test_restore_preserves_offline_last_seen(db, registry, monkeypatch):
    await db.upsert_device(
        "TEST001",
        "10.0.0.1",
        "VMC3030-TEST",
        "Test Camera",
        registration={"SystemModelNumber": "VMC3030"},
        last_seen=100,
    )
    monkeypatch.setattr(device_base_module.time, "time", lambda: 1000)

    await registry.restore_from_db(db)

    assert registry.get("TEST001").online is False
