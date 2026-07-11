"""Admin and health endpoints."""

from __future__ import annotations

import time

from fastapi import APIRouter, Request

from src.devices.camera import Camera

router = APIRouter()


@router.get("/health")
async def health(request: Request):
    registry = request.app.state.registry
    return {
        "status": "ok",
        "devices_registered": len(registry),
        "uptime": time.time() - request.app.state.start_time,
    }


@router.get("/devices/status")
async def devices_status(request: Request):
    registry = request.app.state.registry
    settings = request.app.state.settings
    go2rtc = getattr(request.app.state, "go2rtc", None)
    runtime_streams = await go2rtc.get_runtime_streams() if go2rtc else None
    runtime_available = runtime_streams is not None
    threshold = settings.device_offline_threshold
    now = time.time()

    devices = []
    for device in registry.get_all():
        elapsed = now - device.last_seen
        summary = {
            "serial_number": device.serial_number,
            "friendly_name": device.friendly_name,
            "ip": device.ip,
            "model": device.model,
            "online": elapsed < threshold,
            "last_seen": device.last_seen,
            "seconds_ago": round(elapsed),
            "streaming": None,
        }
        if isinstance(device, Camera):
            runtime = runtime_streams.get(go2rtc.stream_name(device), {}) if runtime_available else {}
            if not isinstance(runtime, dict):
                runtime = {}
            producers = runtime.get("producers") or []
            consumers = runtime.get("consumers") or []
            producer_active = any(bool(producer.get("medias")) for producer in producers if isinstance(producer, dict))
            summary.update(
                {
                    "streaming": producer_active if runtime_available else None,
                    "commanded_streaming": device.is_streaming,
                    "go2rtc_status_available": runtime_available,
                    "go2rtc_producer_active": producer_active if runtime_available else None,
                    "go2rtc_consumer_count": len(consumers) if runtime_available else None,
                }
            )
            summary.update(device.cached_stream_status())
        devices.append(summary)

    return {
        "total": len(devices),
        "online": sum(1 for d in devices if d["online"]),
        "offline": sum(1 for d in devices if not d["online"]),
        "devices": devices,
    }
