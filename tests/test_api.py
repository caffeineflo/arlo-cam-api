"""Tests for REST API routes."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_ping(client):
    resp = await client.get("/ping")
    assert resp.status_code == 200
    assert resp.json() == "PING"


@pytest.mark.asyncio
async def test_landing_page(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "arlo-cam-api" in resp.text


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["devices_registered"] == 1


@pytest.mark.asyncio
async def test_list_devices(client):
    resp = await client.get("/device")
    assert resp.status_code == 200
    devices = resp.json()
    assert len(devices) == 1
    assert devices[0]["serial_number"] == "4N72777366D7B"
    assert devices[0]["ip"] == "192.168.4.8"


@pytest.mark.asyncio
async def test_get_device_status(client):
    resp = await client.get("/device/4N72777366D7B")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_get_device_not_found(client):
    resp = await client.get("/device/NONEXISTENT")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_registration(client):
    resp = await client.get("/device/4N72777366D7B/registration")
    assert resp.status_code == 200
    data = resp.json()
    assert data["SystemModelNumber"] == "VMC3030"


@pytest.mark.asyncio
async def test_devices_status(client):
    resp = await client.get("/devices/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["devices"][0]["model"] == "VMC3030"
    assert data["devices"][0]["streaming"] is False


@pytest.mark.asyncio
async def test_get_desired_state_empty(client):
    resp = await client.get("/device/4N72777366D7B/desired")
    assert resp.status_code == 200
    data = resp.json()
    assert data["register_set_values"] == {}
    assert data["quality_preset"] is None


@pytest.mark.asyncio
async def test_set_friendly_name(client):
    resp = await client.post(
        "/device/4N72777366D7B/friendlyname",
        json={"name": "Front Door"},
    )
    assert resp.status_code == 200
    assert resp.json()["result"] is True


@pytest.mark.asyncio
async def test_delete_device(client):
    resp = await client.delete("/device/4N72777366D7B")
    assert resp.status_code == 200
    assert resp.json()["result"] is True

    resp = await client.get("/device/4N72777366D7B")
    assert resp.status_code == 404
