"""Admin and health endpoints."""

from __future__ import annotations

import time

from fastapi import APIRouter, Request

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
    threshold = settings.device_offline_threshold
    now = time.time()

    devices = []
    for device in registry.get_all():
        elapsed = now - device.last_seen
        devices.append({
            "serial_number": device.serial_number,
            "friendly_name": device.friendly_name,
            "ip": device.ip,
            "model": device.model,
            "online": elapsed < threshold,
            "last_seen": device.last_seen,
            "seconds_ago": round(elapsed),
            "streaming": getattr(device, "is_streaming", False),
        })

    return {
        "total": len(devices),
        "online": sum(1 for d in devices if d["online"]),
        "offline": sum(1 for d in devices if not d["online"]),
        "devices": devices,
    }
