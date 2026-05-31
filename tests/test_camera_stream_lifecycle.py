"""Tests for camera stream lifecycle modes."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_on_demand_stream_starts_watchdog(sample_camera, monkeypatch):
    calls = []

    async def send_message(_message):
        return {"result": True}

    monkeypatch.setattr(sample_camera, "send_message", send_message)
    monkeypatch.setattr(sample_camera, "_reset_stream_watchdog", lambda: calls.append("reset"))

    result = await sample_camera.set_user_stream_active(True)

    assert result is True
    assert sample_camera.is_streaming is True
    assert calls == ["reset"]


@pytest.mark.asyncio
async def test_always_on_stream_does_not_start_watchdog(sample_camera, monkeypatch):
    calls = []
    sample_camera.always_on = True

    async def send_message(_message):
        return {"result": True}

    monkeypatch.setattr(sample_camera, "send_message", send_message)
    monkeypatch.setattr(sample_camera, "_reset_stream_watchdog", lambda: calls.append("reset"))

    result = await sample_camera.set_user_stream_active(True)

    assert result is True
    assert sample_camera.is_streaming is True
    assert calls == []


@pytest.mark.asyncio
async def test_stream_stop_cancels_watchdog(sample_camera, monkeypatch):
    calls = []
    sample_camera._stream_active = True

    async def send_message(_message):
        return {"result": True}

    monkeypatch.setattr(sample_camera, "send_message", send_message)
    monkeypatch.setattr(sample_camera, "_cancel_stream_watchdog", lambda: calls.append("cancel"))

    result = await sample_camera.set_user_stream_active(False)

    assert result is True
    assert sample_camera.is_streaming is False
    assert calls == ["cancel"]
