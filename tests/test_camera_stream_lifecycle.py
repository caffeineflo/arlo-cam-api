"""Behavior tests for camera power policy and stream leases."""

from __future__ import annotations

import asyncio

import pytest

from src.devices import camera as camera_module
from src.devices.camera import StreamLeaseRejectedError


def _cancel_lifecycle_task(camera) -> None:
    if camera._lifecycle_task:
        camera._lifecycle_task.cancel()


@pytest.fixture
def acknowledged_camera(sample_camera, monkeypatch):
    calls = []

    async def send_message(message):
        calls.append(message["SetValues"]["UserStreamActive"])
        return {"ID": message["ID"], "Response": "Ack"}

    monkeypatch.setattr(sample_camera, "send_message", send_message)
    return sample_camera, calls


def test_unknown_power_mode_defaults_to_battery(sample_camera):
    assert sample_camera.effective_power_mode == "battery"


def test_large_limits_are_not_always_on_without_external_mode(sample_camera):
    sample_camera.configure_stream_policy(
        None,
        {"MaxUserStreamTimeLimit": 86400, "MaxStreamTimeLimit": 86400},
    )

    assert sample_camera.always_on is False


def test_external_mode_requires_both_large_stream_limits(sample_camera):
    sample_camera.configure_stream_policy(
        "external",
        {"MaxUserStreamTimeLimit": 86400, "MaxStreamTimeLimit": 180},
    )

    assert sample_camera.always_on is False


def test_external_mode_with_both_large_limits_is_always_on(sample_camera):
    sample_camera.configure_stream_policy(
        "external",
        {"MaxUserStreamTimeLimit": 86400, "MaxStreamTimeLimit": 86400},
    )

    assert sample_camera.always_on is True


@pytest.mark.asyncio
async def test_overlapping_leases_start_camera_once(acknowledged_camera):
    camera, calls = acknowledged_camera
    await camera.acquire_stream_lease("first", 180)
    await camera.acquire_stream_lease("second", 180)
    _cancel_lifecycle_task(camera)

    assert calls == [0]


@pytest.mark.asyncio
async def test_new_lease_supersedes_a_pending_stop(acknowledged_camera):
    camera, calls = acknowledged_camera
    camera._stream_active = True
    camera._pending_stream_active = False

    await camera.acquire_stream_lease("new-viewer", 180)
    _cancel_lifecycle_task(camera)

    assert (calls, camera._pending_stream_active) == ([0], None)


@pytest.mark.asyncio
async def test_releasing_one_lease_does_not_stop_another(acknowledged_camera):
    camera, calls = acknowledged_camera
    first = await camera.acquire_stream_lease("first", 180)
    await camera.acquire_stream_lease("second", 180)

    result = await camera.release_stream_lease(first["lease_id"])
    _cancel_lifecycle_task(camera)

    assert (result["lease_count"], calls) == (1, [0])


@pytest.mark.asyncio
async def test_releasing_last_battery_lease_stops_camera(acknowledged_camera):
    camera, calls = acknowledged_camera
    lease = await camera.acquire_stream_lease("recorder", 180)

    result = await camera.release_stream_lease(lease["lease_id"])

    assert (result["lease_count"], calls) == (0, [0, 1])


@pytest.mark.asyncio
async def test_new_lease_cannot_extend_battery_session_deadline(
    acknowledged_camera,
    monkeypatch,
):
    camera, _calls = acknowledged_camera
    now = [100.0]
    monkeypatch.setattr(camera_module.time, "time", lambda: now[0])
    first = await camera.acquire_stream_lease("first", 180)
    now[0] = 150.0

    second = await camera.acquire_stream_lease("second", 180)
    _cancel_lifecycle_task(camera)

    assert second["session_deadline"] == first["session_deadline"] == 280.0


@pytest.mark.asyncio
async def test_switching_external_lease_to_battery_clamps_deadline(
    acknowledged_camera,
    monkeypatch,
):
    camera, _calls = acknowledged_camera
    now = [100.0]
    monkeypatch.setattr(camera_module.time, "time", lambda: now[0])
    camera.configure_stream_policy(
        "external",
        {"MaxUserStreamTimeLimit": 180, "MaxStreamTimeLimit": 180},
    )
    lease = await camera.acquire_stream_lease("viewer", 3600)

    await camera.apply_stream_policy(
        "battery",
        {"MaxUserStreamTimeLimit": 180, "MaxStreamTimeLimit": 180},
    )
    status = camera.cached_stream_status()
    _cancel_lifecycle_task(camera)

    assert (
        status["session_deadline"],
        camera._stream_leases[lease["lease_id"]].expires_at,
    ) == (280.0, 280.0)


@pytest.mark.asyncio
async def test_switching_battery_session_to_external_clears_deadline(
    acknowledged_camera,
):
    camera, _calls = acknowledged_camera
    await camera.acquire_stream_lease("viewer", 180)

    await camera.apply_stream_policy(
        "external",
        {"MaxUserStreamTimeLimit": 86400, "MaxStreamTimeLimit": 86400},
    )
    status = camera.cached_stream_status()
    _cancel_lifecycle_task(camera)

    assert (status["session_deadline"], status["cooldown_until"]) == (None, None)


@pytest.mark.asyncio
async def test_reapplying_battery_profile_stops_orphaned_stream(acknowledged_camera):
    camera, calls = acknowledged_camera
    camera.configure_stream_policy(
        "battery",
        {"MaxUserStreamTimeLimit": 180, "MaxStreamTimeLimit": 180},
    )
    camera._stream_active = True

    await camera.apply_stream_policy(
        "battery",
        {"MaxUserStreamTimeLimit": 180, "MaxStreamTimeLimit": 180},
    )

    assert (camera.is_streaming, calls) == (False, [1])


@pytest.mark.asyncio
async def test_updating_idle_battery_profile_does_not_start_cooldown(acknowledged_camera):
    camera, _calls = acknowledged_camera

    await camera.apply_stream_policy(
        "battery",
        {"MaxUserStreamTimeLimit": 180, "MaxStreamTimeLimit": 180},
    )

    assert camera.cached_stream_status()["cooldown_until"] is None


@pytest.mark.asyncio
async def test_release_starts_battery_cooldown(acknowledged_camera):
    camera, _calls = acknowledged_camera
    lease = await camera.acquire_stream_lease("recorder", 180)
    await camera.release_stream_lease(lease["lease_id"])

    with pytest.raises(StreamLeaseRejectedError):
        await camera.acquire_stream_lease("reconnect", 180)


@pytest.mark.asyncio
async def test_expired_inactive_session_ends_without_busy_loop(
    acknowledged_camera,
    monkeypatch,
):
    camera, _calls = acknowledged_camera
    now = [100.0]
    monkeypatch.setattr(camera_module.time, "time", lambda: now[0])
    await camera.acquire_stream_lease("viewer", 180)
    camera._stream_active = False
    camera._pending_stream_active = None
    now[0] = 281.0

    await camera._process_lifecycle_deadlines()

    assert (
        camera.cached_stream_status()["session_deadline"],
        camera._lifecycle_task,
    ) == (None, None)


@pytest.mark.asyncio
async def test_old_release_cannot_remove_new_lease(
    acknowledged_camera,
    monkeypatch,
):
    camera, _calls = acknowledged_camera
    now = [100.0]
    monkeypatch.setattr(camera_module.time, "time", lambda: now[0])
    old_lease = await camera.acquire_stream_lease("old", 5)
    now[0] = 106.0
    await camera._process_lifecycle_deadlines()
    now[0] = 137.0
    new_lease = await camera.acquire_stream_lease("new", 180)

    result = await camera.release_stream_lease(old_lease["lease_id"])
    await camera.release_stream_lease(new_lease["lease_id"])

    assert (result["released"], result["lease_count"]) == (False, 1)


@pytest.mark.asyncio
async def test_failed_stop_is_retried_three_times(sample_camera, monkeypatch):
    calls = []

    async def send_message(message):
        calls.append(message)
        return None

    monkeypatch.setattr(sample_camera, "send_message", send_message)
    monkeypatch.setattr(camera_module, "STOP_RETRY_DELAYS_SECONDS", (0, 0))

    await sample_camera.set_user_stream_active(False)
    await sample_camera._stop_reconciliation_task

    assert len(calls) == 3


@pytest.mark.asyncio
async def test_failed_stop_reports_exhausted_reconciliation(sample_camera, monkeypatch):
    async def send_message(_message):
        return None

    monkeypatch.setattr(sample_camera, "send_message", send_message)
    monkeypatch.setattr(camera_module, "STOP_RETRY_DELAYS_SECONDS", (0, 0))

    await sample_camera.set_user_stream_active(False)
    await sample_camera._stop_reconciliation_task

    assert sample_camera.cached_stream_status()["last_stream_result"] == {
        "requested_active": False,
        "success": False,
        "attempts": 3,
        "last_attempt_at": sample_camera._last_stream_result["last_attempt_at"],
        "error": "camera did not acknowledge stream command",
        "retries_exhausted": True,
    }


@pytest.mark.asyncio
async def test_quiesce_waits_for_successful_stop_retry(sample_camera, monkeypatch):
    attempts = 0

    async def send_message(message):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return None
        return {"ID": message["ID"], "Response": "Ack"}

    monkeypatch.setattr(sample_camera, "send_message", send_message)
    monkeypatch.setattr(camera_module, "STOP_RETRY_DELAYS_SECONDS", (0, 0))
    sample_camera._stream_active = True

    result = await sample_camera.quiesce_stream(force=True)

    assert (result, attempts, sample_camera.is_streaming) == (True, 3, False)


@pytest.mark.asyncio
async def test_nack_does_not_mark_stream_stopped(sample_camera, monkeypatch):
    sample_camera._stream_active = True

    async def send_message(message):
        return {"ID": message["ID"], "Response": "Nack"}

    monkeypatch.setattr(sample_camera, "send_message", send_message)
    monkeypatch.setattr(camera_module, "STOP_RETRY_DELAYS_SECONDS", (60, 60))

    result = await sample_camera.set_user_stream_active(False)
    sample_camera._stop_reconciliation_task.cancel()

    assert (result, sample_camera.is_streaming, sample_camera._pending_stream_active) == (
        False,
        True,
        False,
    )


@pytest.mark.asyncio
async def test_new_lease_wins_over_in_flight_pending_stop(sample_camera, monkeypatch):
    stop_started = asyncio.Event()
    finish_stop = asyncio.Event()

    async def send_message(message):
        active = message["SetValues"]["UserStreamActive"] == 0
        if not active:
            stop_started.set()
            await finish_stop.wait()
        return {"ID": message["ID"], "Response": "Ack"}

    monkeypatch.setattr(sample_camera, "send_message", send_message)
    sample_camera._stream_active = True
    sample_camera._pending_stream_active = False

    pending_delivery = asyncio.create_task(sample_camera.deliver_pending_stream())
    await stop_started.wait()
    lease_acquisition = asyncio.create_task(sample_camera.acquire_stream_lease("new-viewer", 180))
    finish_stop.set()
    await pending_delivery
    lease = await lease_acquisition
    _cancel_lifecycle_task(sample_camera)

    assert (sample_camera.is_streaming, sample_camera.lease_count, lease["streaming"]) == (
        True,
        1,
        True,
    )


@pytest.mark.asyncio
async def test_concurrent_legacy_starts_share_one_lease(acknowledged_camera):
    camera, _calls = acknowledged_camera

    first, second = await asyncio.gather(
        camera.set_legacy_stream_active(True),
        camera.set_legacy_stream_active(True),
    )
    _cancel_lifecycle_task(camera)

    assert (first, second, camera.lease_count) == (True, True, 1)


def test_cached_status_uses_status_without_requesting_camera(sample_camera):
    sample_camera.registration["BatteryPercentage"] = 90
    sample_camera.status = {
        "BatteryPercentage": 87,
        "PIREvents": 12,
        "AmountOfTimeUserStreamed": 345,
        "AmountOfTimeStreamed": 456,
        "FailedStreams": 2,
        "SignalStrengthIndicator": 3,
        "Temperature": 29,
    }

    status = sample_camera.cached_stream_status()

    assert (
        status["battery_percentage"],
        status["pir_events"],
        status["user_stream_seconds"],
        status["stream_seconds"],
        status["failed_streams"],
        status["signal_strength"],
        status["temperature"],
    ) == (87, 12, 345, 456, 2, 3, 29)
