"""Tests for REST API routes."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from src.config import Settings
from src.protocol.connection import ConnectionHandler


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
    assert "MotionRecordingWebHookUrl" in resp.text
    assert "serial_number" in resp.text
    assert "UniFi Protect / ONVIF" in resp.text


@pytest.mark.asyncio
async def test_openapi_documents_stream_lifecycle(client):
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    user_stream = paths["/device/{serial}/userstreamactive"]["post"]
    register_set = paths["/device/{serial}/registerset"]["post"]

    assert "battery-powered" in user_stream["description"]
    assert "86400" in register_set["description"]


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
    assert data["devices"][0]["streaming"] is None
    assert data["devices"][0]["commanded_streaming"] is False


@pytest.mark.asyncio
async def test_devices_status_uses_go2rtc_runtime_state(client, app):
    class RuntimeGo2RTC:
        @staticmethod
        def stream_name(_device):
            return "front_entrance"

        @staticmethod
        async def get_runtime_streams():
            return {
                "front_entrance": {
                    "producers": [{"medias": ["video, recvonly, H264"]}],
                    "consumers": [{"url": "rtsp://viewer"}],
                }
            }

    app.state.go2rtc = RuntimeGo2RTC()

    response = await client.get("/devices/status")
    device = response.json()["devices"][0]

    assert (
        device["streaming"],
        device["commanded_streaming"],
        device["go2rtc_status_available"],
        device["go2rtc_producer_active"],
        device["go2rtc_consumer_count"],
    ) == (True, False, True, True, 1)


@pytest.mark.asyncio
async def test_get_desired_state_empty(client):
    resp = await client.get("/device/4N72777366D7B/desired")
    assert resp.status_code == 200
    data = resp.json()
    assert data["register_set_values"] == {}
    assert data["quality_preset"] is None
    assert data["power_mode"] is None
    assert data["effective_power_mode"] == "battery"


@pytest.mark.asyncio
@pytest.mark.parametrize("active", ["false", "0"])
async def test_stream_active_rejects_string_values(client, active):
    resp = await client.post(
        "/device/4N72777366D7B/userstreamactive",
        json={"active": active},
    )

    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["180", 0, 86401, True])
async def test_register_set_rejects_invalid_stream_limits(client, value):
    resp = await client.post(
        "/device/4N72777366D7B/registerset",
        json={"MaxUserStreamTimeLimit": value},
    )

    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["arm", "registerset"])
async def test_register_routes_reject_user_stream_active(client, endpoint):
    resp = await client.post(
        f"/device/4N72777366D7B/{endpoint}",
        json={"UserStreamActive": 0},
    )

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_battery_profile_rejects_unsafe_stream_limit(client):
    resp = await client.post(
        "/device/4N72777366D7B/registerset",
        json={"MaxUserStreamTimeLimit": 181},
    )

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_arm_cannot_bypass_battery_stream_limit(client):
    response = await client.post(
        "/device/4N72777366D7B/arm",
        json={"MaxUserStreamTimeLimit": 86400, "MaxStreamTimeLimit": 86400},
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_quality_rejects_unknown_preset(client):
    resp = await client.post(
        "/device/4N72777366D7B/quality",
        json={"quality": "ultra-mega"},
    )

    assert resp.status_code == 422


def test_settings_reject_unknown_default_quality():
    with pytest.raises(ValidationError):
        Settings(video_quality_default="ultra-mega")


def test_default_quality_is_merged_into_initial_camera_config():
    settings = Settings(video_quality_default="low")
    handler = ConnectionHandler(None, None, settings, None)

    config = handler._build_initial_config()

    assert (config["VideoOutputResolution"], config["VideoTargetBitrate"]) == (
        "720p",
        400,
    )


def test_stored_camera_values_override_default_quality():
    settings = Settings(video_quality_default="low")
    handler = ConnectionHandler(None, None, settings, None)

    config = handler._build_initial_config({"VideoTargetBitrate": 999})

    assert config["VideoTargetBitrate"] == 999


@pytest.mark.asyncio
async def test_power_mode_persists_and_enables_computed_always_on(
    client,
    sample_camera,
    monkeypatch,
):
    async def send_message(message):
        return {"ID": message["ID"], "Response": "Ack"}

    monkeypatch.setattr(sample_camera, "send_message", send_message)
    resp = await client.put(
        "/device/4N72777366D7B/power",
        json={"mode": "external"},
    )

    assert resp.json() == {
        "result": True,
        "power_mode": "external",
        "effective_power_mode": "external",
        "always_on": True,
        "stream_limits": {
            "MaxUserStreamTimeLimit": 86400,
            "MaxStreamTimeLimit": 86400,
        },
        "register_command_delivered": True,
        "stream_command_delivered": True,
    }


@pytest.mark.asyncio
async def test_power_mode_reports_register_nack(client, sample_camera, monkeypatch):
    async def send_message(message):
        if "MaxUserStreamTimeLimit" in message.get("SetValues", {}):
            return {"ID": message["ID"], "Response": "Nack"}
        return {"ID": message["ID"], "Response": "Ack"}

    monkeypatch.setattr(sample_camera, "send_message", send_message)

    response = await client.put(
        "/device/4N72777366D7B/power",
        json={"mode": "battery"},
    )

    assert response.json()["register_command_delivered"] is False


@pytest.mark.asyncio
async def test_profile_mutations_are_serialized(client, sample_camera, monkeypatch):
    power_register_started = asyncio.Event()
    release_power_register = asyncio.Event()

    async def send_message(message):
        values = message.get("SetValues", {})
        if values.get("MaxUserStreamTimeLimit") == 86400:
            power_register_started.set()
            await release_power_register.wait()
        return {"ID": message["ID"], "Response": "Ack"}

    monkeypatch.setattr(sample_camera, "send_message", send_message)
    power_request = asyncio.create_task(
        client.put(
            "/device/4N72777366D7B/power",
            json={"mode": "external"},
        )
    )
    await power_register_started.wait()
    register_request = asyncio.create_task(
        client.post(
            "/device/4N72777366D7B/registerset",
            json={"PIRStartSensitivity": 75},
        )
    )
    await asyncio.sleep(0)

    assert register_request.done() is False

    release_power_register.set()
    power_response, register_response = await asyncio.gather(
        power_request,
        register_request,
    )
    desired = (await client.get("/device/4N72777366D7B/desired")).json()

    assert (
        power_response.status_code,
        register_response.status_code,
        desired["power_mode"],
        desired["register_set_values"]["MaxUserStreamTimeLimit"],
        desired["register_set_values"]["PIRStartSensitivity"],
        sample_camera.always_on,
    ) == (200, 200, "external", 86400, 75, True)


@pytest.mark.asyncio
async def test_lease_api_issues_unique_ids(client, sample_camera, monkeypatch):
    async def send_message(message):
        return {"ID": message["ID"], "Response": "Ack"}

    monkeypatch.setattr(sample_camera, "send_message", send_message)
    first = await client.post(
        "/device/4N72777366D7B/stream/leases",
        json={"owner": "first", "ttl_seconds": 180},
    )
    second = await client.post(
        "/device/4N72777366D7B/stream/leases",
        json={"owner": "second", "ttl_seconds": 180},
    )
    first_id = first.json()["lease_id"]
    second_id = second.json()["lease_id"]
    await client.delete(f"/device/4N72777366D7B/stream/leases/{first_id}")
    await client.delete(f"/device/4N72777366D7B/stream/leases/{second_id}")

    assert first_id != second_id


@pytest.mark.asyncio
async def test_unknown_lease_release_is_idempotent(client):
    resp = await client.delete(
        "/device/4N72777366D7B/stream/leases/already-released",
    )

    assert resp.json()["released"] is False


@pytest.mark.asyncio
async def test_devices_status_exposes_cached_camera_counters(client, sample_camera):
    sample_camera.status = {
        "BatteryPercentage": 82,
        "PIREvents": 14,
        "AmountOfTimeUserStreamed": 123,
        "AmountOfTimeStreamed": 234,
        "FailedStreams": 3,
    }

    resp = await client.get("/devices/status")
    device = resp.json()["devices"][0]

    assert (
        device["effective_power_mode"],
        device["battery_percentage"],
        device["pir_events"],
        device["user_stream_seconds"],
        device["stream_seconds"],
        device["failed_streams"],
        device["lease_count"],
    ) == ("battery", 82, 14, 123, 234, 3, 0)


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


@pytest.mark.asyncio
async def test_delete_device_removes_stream_and_stops_camera(
    client,
    app,
    sample_camera,
    monkeypatch,
):
    class DeleteGo2RTC:
        removed = []

        @staticmethod
        def stream_name(_device):
            return "front_entrance"

        async def remove_stream(self, name):
            self.removed.append(name)
            return True

    async def send_message(message):
        return {"ID": message["ID"], "Response": "Ack"}

    go2rtc = DeleteGo2RTC()
    app.state.go2rtc = go2rtc
    sample_camera._stream_active = True
    monkeypatch.setattr(sample_camera, "send_message", send_message)

    response = await client.delete("/device/4N72777366D7B")

    assert (response.status_code, go2rtc.removed, sample_camera.is_streaming) == (
        200,
        ["front_entrance"],
        False,
    )
