"""Device API routes - compatible with arlo-local Scrypted plugin."""

from __future__ import annotations

import json
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.devices.camera import (
    ALWAYS_ON_STREAM_LIMIT,
    BATTERY_SESSION_LIMIT_SECONDS,
    Camera,
    StreamLeaseRejectedError,
)
from src.devices.capabilities import filter_register_set
from src.messages.quality_presets import QUALITY_REGISTER_SETS

router = APIRouter()

LIFECYCLE_OWNED_REGISTER_KEYS = {"UserStreamActive"}
PROFILE_STREAM_LIMIT_KEYS = {
    "MaxUserStreamTimeLimit",
    "MaxStreamTimeLimit",
}


class StreamActiveRequest(BaseModel):
    active: bool

    @field_validator("active", mode="before")
    @classmethod
    def reject_string_booleans(cls, value):
        if isinstance(value, bool):
            return value
        if type(value) is int and value in (0, 1):
            return bool(value)
        raise ValueError("active must be a JSON boolean or integer 0 or 1")


class StreamLeaseRequest(BaseModel):
    owner: str = Field(default="api", min_length=1, max_length=64)
    ttl_seconds: Annotated[int, Field(strict=True, ge=5, le=3600)] = 180

    @field_validator("owner")
    @classmethod
    def normalize_owner(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("owner must not be blank")
        return normalized


class PowerModeRequest(BaseModel):
    mode: Literal["battery", "external"]


class QualityRequest(BaseModel):
    quality: Literal["low", "medium", "high", "subscription", "insane"]


StreamLimit = Annotated[int, Field(strict=True, ge=1, le=86400)]


class RegisterSetRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    default_motion_stream_time_limit: StreamLimit | None = Field(
        default=None,
        alias="DefaultMotionStreamTimeLimit",
    )
    max_motion_stream_time_limit: StreamLimit | None = Field(
        default=None,
        alias="MaxMotionStreamTimeLimit",
    )
    max_stream_time_limit: StreamLimit | None = Field(default=None, alias="MaxStreamTimeLimit")
    max_user_stream_time_limit: StreamLimit | None = Field(
        default=None,
        alias="MaxUserStreamTimeLimit",
    )


def _get_registry(request: Request):
    return request.app.state.registry


def _get_db(request: Request):
    return request.app.state.db


def _reject_lifecycle_owned_values(values: dict) -> None:
    blocked = sorted(LIFECYCLE_OWNED_REGISTER_KEYS.intersection(values))
    if blocked:
        raise HTTPException(
            400,
            detail={
                "error": "lifecycle_owned_register",
                "keys": blocked,
                "message": "Use the stream lease API to control UserStreamActive",
            },
        )


def _validate_stream_profile(power_mode: str, values: dict) -> None:
    user_limit = values.get("MaxUserStreamTimeLimit", BATTERY_SESSION_LIMIT_SECONDS)
    stream_limit = values.get("MaxStreamTimeLimit", BATTERY_SESSION_LIMIT_SECONDS)
    if power_mode == "external":
        if user_limit != ALWAYS_ON_STREAM_LIMIT or stream_limit != ALWAYS_ON_STREAM_LIMIT:
            raise HTTPException(
                400,
                detail="External power requires both stream limits to be 86400; use the power endpoint",
            )
        return
    if user_limit > BATTERY_SESSION_LIMIT_SECONDS or stream_limit > BATTERY_SESSION_LIMIT_SECONDS:
        raise HTTPException(
            400,
            detail="Battery stream limits cannot exceed 180 seconds; use the power endpoint",
        )


async def _merge_desired_state(
    db,
    serial: str,
    new_values: dict,
    quality_preset: str | None = None,
    power_mode: str | None = None,
) -> dict:
    """Merge new register values into the existing desired state."""
    existing = await db.get_desired_state(serial)
    if existing:
        current = json.loads(existing.get("register_set_values", "{}"))
        current.update(new_values)
        merged = current
    else:
        merged = new_values
    await db.upsert_desired_state(serial, merged, quality_preset, power_mode)
    return merged


async def _validate_profile_mutation(db, device: Camera, new_values: dict) -> tuple[dict, str]:
    desired = await db.get_desired_state(device.serial_number)
    existing_values = json.loads(desired.get("register_set_values", "{}")) if desired else {}
    preview = {**existing_values, **new_values}
    power_mode = (desired.get("power_mode") if desired else None) or device.effective_power_mode
    if PROFILE_STREAM_LIMIT_KEYS.intersection(new_values):
        _validate_stream_profile(power_mode, preview)
    return preview, power_mode


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
    device = registry.get(serial)
    if not device:
        raise HTTPException(404, "Device not found")

    if isinstance(device, Camera):
        async with device.policy_lock:
            go2rtc = getattr(request.app.state, "go2rtc", None)
            stream_removed = False
            if go2rtc:
                stream_removed = await go2rtc.remove_stream(go2rtc.stream_name(device))
                if not stream_removed:
                    raise HTTPException(502, "Could not remove the go2rtc stream")

            if not await device.quiesce_stream():
                if stream_removed:
                    await go2rtc.add_stream(device)
                raise HTTPException(503, "Camera did not acknowledge stream shutdown")

            await db.delete_device(serial)
            registry.remove(serial)
    else:
        await db.delete_device(serial)
        registry.remove(serial)
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
    registry = _get_registry(request)
    desired = await db.get_desired_state(serial)
    if not desired:
        return {
            "register_set_values": {},
            "quality_preset": None,
            "power_mode": None,
            "effective_power_mode": "battery",
        }
    device = registry.get(serial)
    return {
        "register_set_values": json.loads(desired.get("register_set_values", "{}")),
        "quality_preset": desired.get("quality_preset"),
        "power_mode": desired.get("power_mode"),
        "effective_power_mode": getattr(device, "effective_power_mode", desired.get("power_mode") or "battery"),
    }


@router.post("/device/{serial}/statusrequest")
async def status_request(serial: str, request: Request):
    registry = _get_registry(request)
    device = registry.get(serial)
    if not device:
        raise HTTPException(404, "Device not found")
    if isinstance(device, Camera):
        result = await device.status_request()
        return {"result": result is not None}
    return {"result": False}


@router.post(
    "/device/{serial}/userstreamactive",
    summary="Start or stop a camera stream",
    description=(
        "Legacy compatibility wrapper for battery-powered clients. New consumers should use "
        "the stream lease endpoint so overlapping recordings cannot stop each other. Values "
        "must be JSON booleans or integer 0/1; strings are rejected."
    ),
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "example": {"active": 1},
                },
            },
        },
    },
)
async def user_stream_active(serial: str, body: StreamActiveRequest, request: Request):
    registry = _get_registry(request)
    device = registry.get(serial)
    if not device:
        raise HTTPException(404, "Device not found")
    if isinstance(device, Camera):
        try:
            result = await device.set_legacy_stream_active(body.active)
        except StreamLeaseRejectedError as error:
            raise _cooldown_error(error) from error
        return {"result": result}
    return {"result": False}


@router.post("/device/{serial}/stream/leases", status_code=201)
async def acquire_stream_lease(serial: str, body: StreamLeaseRequest, request: Request):
    registry = _get_registry(request)
    device = registry.get(serial)
    if not device:
        raise HTTPException(404, "Device not found")
    if not isinstance(device, Camera):
        raise HTTPException(400, "Device does not support video streaming")
    try:
        return await device.acquire_stream_lease(body.owner, body.ttl_seconds)
    except StreamLeaseRejectedError as error:
        raise _cooldown_error(error) from error


@router.delete("/device/{serial}/stream/leases/{lease_id}")
async def release_stream_lease(serial: str, lease_id: str, request: Request):
    registry = _get_registry(request)
    device = registry.get(serial)
    if not device:
        raise HTTPException(404, "Device not found")
    if not isinstance(device, Camera):
        raise HTTPException(400, "Device does not support video streaming")
    return await device.release_stream_lease(lease_id)


def _cooldown_error(error) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail={
            "error": "battery_stream_cooldown",
            "retry_after": error.retry_after,
        },
        headers={"Retry-After": str(error.retry_after)},
    )


@router.post(
    "/device/{serial}/streamrefresh",
    summary="Refresh an active on-demand stream",
    description=(
        "Refresh only the legacy userstreamactive compatibility lease. It does not extend "
        "leases created by the stream lease endpoint or a battery session deadline."
    ),
)
async def refresh_stream(serial: str, request: Request):
    """Refresh the legacy compatibility lease."""
    registry = _get_registry(request)
    device = registry.get(serial)
    if not device:
        raise HTTPException(404, "Device not found")
    if isinstance(device, Camera):
        refreshed = await device.refresh_legacy_stream()
        return {"result": refreshed, "streaming": device.is_streaming}
    return {"result": False}


@router.put("/device/{serial}/power")
async def set_power_mode(serial: str, body: PowerModeRequest, request: Request):
    registry = _get_registry(request)
    db = _get_db(request)
    device = registry.get(serial)
    if not device:
        raise HTTPException(404, "Device not found")
    if not isinstance(device, Camera):
        raise HTTPException(400, "Device does not support video streaming")
    async with device.policy_lock:
        desired = await db.get_desired_state(serial)
        register_values = json.loads(desired.get("register_set_values", "{}")) if desired else {}
        stream_limit = ALWAYS_ON_STREAM_LIMIT if body.mode == "external" else BATTERY_SESSION_LIMIT_SECONDS
        profile_values = {
            "MaxUserStreamTimeLimit": stream_limit,
            "MaxStreamTimeLimit": stream_limit,
        }
        register_values.update(profile_values)
        await db.upsert_desired_state(serial, register_values, power_mode=body.mode)
        register_result = await device.send_register_set(profile_values)
        command_result = await device.apply_stream_policy(body.mode, register_values)
    return {
        "result": True,
        "power_mode": device.power_mode,
        "effective_power_mode": device.effective_power_mode,
        "always_on": device.always_on,
        "stream_limits": profile_values,
        "register_command_delivered": register_result,
        "stream_command_delivered": command_result,
    }


@router.post("/device/{serial}/arm")
async def arm_device(serial: str, body: RegisterSetRequest, request: Request):
    values = body.model_dump(by_alias=True, exclude_none=True)
    _reject_lifecycle_owned_values(values)
    registry = _get_registry(request)
    db = _get_db(request)
    device = registry.get(serial)
    if not device:
        raise HTTPException(404, "Device not found")
    if isinstance(device, Camera):
        filtered = filter_register_set(values, device.model, device.registration)
        async with device.policy_lock:
            _, power_mode = await _validate_profile_mutation(db, device, filtered)
            merged = await _merge_desired_state(db, serial, filtered)
            result = await device.arm(filtered)
            await device.apply_stream_policy(power_mode, merged)
        return {"result": result}
    return {"result": False}


@router.post("/device/{serial}/quality")
async def set_quality(serial: str, body: QualityRequest, request: Request):
    registry = _get_registry(request)
    db = _get_db(request)
    device = registry.get(serial)
    if not device:
        raise HTTPException(404, "Device not found")
    if isinstance(device, Camera):
        async with device.policy_lock:
            register_values = QUALITY_REGISTER_SETS[body.quality]
            filtered = filter_register_set(register_values, device.model, device.registration)
            await _merge_desired_state(db, serial, filtered, quality_preset=body.quality)
            result = await device.set_quality(body.quality)
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


@router.post(
    "/device/{serial}/registerset",
    summary="Send and persist camera register values",
    description=(
        "Use this endpoint for settings inside the current power profile. PUT /power is the "
        "only supported way to transition between the canonical battery limits (180 seconds) "
        "and external-power limits (86400 seconds). Conflicting direct limit changes return 400."
    ),
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "motion_sensitivity": {
                            "summary": "Adjust motion sensitivity without changing power mode",
                            "value": {
                                "PIRStartSensitivity": 80,
                            },
                        },
                    },
                },
            },
        },
    },
)
async def send_register_set(serial: str, body: RegisterSetRequest, request: Request):
    registry = _get_registry(request)
    db = _get_db(request)
    device = registry.get(serial)
    if not device:
        raise HTTPException(404, "Device not found")
    if isinstance(device, Camera):
        values = body.model_dump(by_alias=True, exclude_none=True)
        _reject_lifecycle_owned_values(values)
        filtered = filter_register_set(values, device.model, device.registration)
        async with device.policy_lock:
            _, power_mode = await _validate_profile_mutation(db, device, filtered)
            merged = await _merge_desired_state(db, serial, filtered)
            result = await device.send_register_set(filtered)
            await device.apply_stream_policy(power_mode, merged)
        return {"result": result}
    return {"result": False}
