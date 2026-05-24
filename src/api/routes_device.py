"""Device API routes - compatible with arlo-local Scrypted plugin."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request

from src.devices.capabilities import filter_register_set

router = APIRouter()


def _get_registry(request: Request):
    return request.app.state.registry


def _get_db(request: Request):
    return request.app.state.db


async def _merge_desired_state(db, serial: str, new_values: dict, quality_preset: str | None = None) -> None:
    """Merge new register values into the existing desired state."""
    existing = await db.get_desired_state(serial)
    if existing:
        current = json.loads(existing.get("register_set_values", "{}"))
        current.update(new_values)
        merged = current
    else:
        merged = new_values
    await db.upsert_desired_state(serial, merged, quality_preset)


@router.get("/device")
async def list_devices(request: Request):
    registry = _get_registry(request)
    return [d.to_summary() for d in registry.get_all()]


@router.get("/device/{serial}")
async def get_device_status(serial: str, request: Request):
    registry = _get_registry(request)
    device = registry.get(serial)
    if not device:
        raise HTTPException(404, "Device not found")
    return device.status or {}


@router.delete("/device/{serial}")
async def delete_device(serial: str, request: Request):
    registry = _get_registry(request)
    db = _get_db(request)
    if not registry.remove(serial):
        raise HTTPException(404, "Device not found")
    await db.delete_device(serial)
    return {"result": True}


@router.get("/device/{serial}/registration")
async def get_registration(serial: str, request: Request):
    registry = _get_registry(request)
    device = registry.get(serial)
    if not device:
        raise HTTPException(404, "Device not found")
    return device.registration or {}


@router.get("/device/{serial}/desired")
async def get_desired_state(serial: str, request: Request):
    db = _get_db(request)
    desired = await db.get_desired_state(serial)
    if not desired:
        return {"register_set_values": {}, "quality_preset": None}
    return {
        "register_set_values": json.loads(desired.get("register_set_values", "{}")),
        "quality_preset": desired.get("quality_preset"),
    }


@router.post("/device/{serial}/statusrequest")
async def status_request(serial: str, request: Request):
    registry = _get_registry(request)
    device = registry.get(serial)
    if not device:
        raise HTTPException(404, "Device not found")
    from src.devices.camera import Camera
    if isinstance(device, Camera):
        result = await device.status_request()
        return {"result": result is not None}
    return {"result": False}


@router.post("/device/{serial}/userstreamactive")
async def user_stream_active(serial: str, request: Request):
    body = await request.json()
    registry = _get_registry(request)
    device = registry.get(serial)
    if not device:
        raise HTTPException(404, "Device not found")
    from src.devices.camera import Camera
    if isinstance(device, Camera):
        active = bool(body.get("active", 0))
        result = await device.set_user_stream_active(active)
        return {"result": result}
    return {"result": False}


@router.post("/device/{serial}/streamrefresh")
async def refresh_stream(serial: str, request: Request):
    """Called by stream consumers to keep the stream alive (resets watchdog timer)."""
    registry = _get_registry(request)
    device = registry.get(serial)
    if not device:
        raise HTTPException(404, "Device not found")
    from src.devices.camera import Camera
    if isinstance(device, Camera):
        device.refresh_stream()
        return {"result": True, "streaming": device.is_streaming}
    return {"result": False}


@router.post("/device/{serial}/arm")
async def arm_device(serial: str, request: Request):
    body = await request.json()
    registry = _get_registry(request)
    db = _get_db(request)
    device = registry.get(serial)
    if not device:
        raise HTTPException(404, "Device not found")
    from src.devices.camera import Camera
    if isinstance(device, Camera):
        filtered = filter_register_set(body, device.model, device.registration)
        await _merge_desired_state(db, serial, filtered)
        result = await device.arm(filtered)
        return {"result": result}
    return {"result": False}


@router.post("/device/{serial}/quality")
async def set_quality(serial: str, request: Request):
    body = await request.json()
    quality = body.get("quality", "")
    registry = _get_registry(request)
    db = _get_db(request)
    device = registry.get(serial)
    if not device:
        raise HTTPException(404, "Device not found")
    from src.devices.camera import Camera
    if isinstance(device, Camera):
        from src.messages.quality_presets import QUALITY_REGISTER_SETS
        register_values = QUALITY_REGISTER_SETS.get(quality, {})
        filtered = filter_register_set(register_values, device.model, device.registration)
        await _merge_desired_state(db, serial, filtered, quality_preset=quality)
        result = await device.set_quality(quality)
        return {"result": result}
    return {"result": False}


@router.post("/device/{serial}/snapshot")
async def request_snapshot(serial: str, request: Request):
    body = await request.json()
    url = body.get("url", "")
    if not url:
        raise HTTPException(400, "url required")
    registry = _get_registry(request)
    device = registry.get(serial)
    if not device:
        raise HTTPException(404, "Device not found")
    from src.devices.camera import Camera
    if isinstance(device, Camera):
        result = await device.request_snapshot(url)
        return {"result": result}
    return {"result": False}


@router.post("/device/{serial}/friendlyname")
async def set_friendly_name(serial: str, request: Request):
    body = await request.json()
    name = body.get("name", "")
    if not name:
        raise HTTPException(400, "name required")
    registry = _get_registry(request)
    db = _get_db(request)
    device = registry.get(serial)
    if not device:
        raise HTTPException(404, "Device not found")
    device.friendly_name = name
    await db.update_friendly_name(serial, name)
    return {"result": True}


@router.post("/device/{serial}/registerset")
async def send_register_set(serial: str, request: Request):
    body = await request.json()
    registry = _get_registry(request)
    db = _get_db(request)
    device = registry.get(serial)
    if not device:
        raise HTTPException(404, "Device not found")
    from src.devices.camera import Camera
    if isinstance(device, Camera):
        filtered = filter_register_set(body, device.model, device.registration)
        await _merge_desired_state(db, serial, filtered)
        result = await device.send_register_set(filtered)
        return {"result": result}
    return {"result": False}
