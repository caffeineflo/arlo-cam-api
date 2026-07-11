"""Camera device implementation and stream lifecycle policy."""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

import structlog

from src.devices.base import Device
from src.messages.quality_presets import QUALITY_REGISTER_SETS, RA_PARAMS
from src.messages.templates import (
    build_epoch_time_message,
    build_ra_params_message,
    build_register_set_message,
    build_snapshot_message,
    build_status_request_message,
    build_user_stream_active_message,
)

ALWAYS_ON_STREAM_LIMIT = 86400
BATTERY_SESSION_LIMIT_SECONDS = 180
BATTERY_USER_STREAM_LIMIT_SECONDS = 30
BATTERY_STREAM_LIMIT_SECONDS = 180
BATTERY_MOTION_STREAM_LIMIT_SECONDS = 30
BATTERY_COOLDOWN_SECONDS = 30
LEGACY_LEASE_TTL_SECONDS = 45
STOP_RETRY_DELAYS_SECONDS = (1.0, 2.0)

PowerMode = Literal["battery", "external"]

logger = structlog.get_logger()


@dataclass
class StreamLease:
    lease_id: str
    owner: str
    expires_at: float


class StreamLeaseRejectedError(Exception):
    """Raised when a battery camera is inside its enforced cooldown."""

    def __init__(self, retry_after: int):
        super().__init__("battery stream cooldown is active")
        self.retry_after = retry_after


class Camera(Device):
    port = 4000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._stream_active = False
        self._stream_started_at: float | None = None
        self._pending_stream_active: bool | None = None
        self._pending_stream_since: float | None = None
        self._last_stream_result: dict | None = None
        self._stop_reconciliation_task: asyncio.Task | None = None
        self._stream_command_lock = asyncio.Lock()
        self._stream_command_supported: bool | None = None
        self.policy_lock = asyncio.Lock()

        self.power_mode: PowerMode | None = None
        self._stream_limits = {
            "MaxUserStreamTimeLimit": BATTERY_USER_STREAM_LIMIT_SECONDS,
            "MaxStreamTimeLimit": BATTERY_STREAM_LIMIT_SECONDS,
        }
        self._stream_leases: dict[str, StreamLease] = {}
        self._legacy_lease_id: str | None = None
        self._legacy_lease_lock = asyncio.Lock()
        self._session_started_at: float | None = None
        self._session_deadline: float | None = None
        self._last_session_started_at: float | None = None
        self._last_session_deadline: float | None = None
        self._cooldown_until: float | None = None
        self._lifecycle_task: asyncio.Task | None = None
        self._lifecycle_lock = asyncio.Lock()

    @property
    def is_streaming(self) -> bool:
        return self._stream_active

    @property
    def effective_power_mode(self) -> PowerMode:
        return self.power_mode or "battery"

    @property
    def always_on(self) -> bool:
        return self.effective_power_mode == "external" and all(
            self._stream_limits[name] >= ALWAYS_ON_STREAM_LIMIT
            for name in ("MaxUserStreamTimeLimit", "MaxStreamTimeLimit")
        )

    @property
    def lease_count(self) -> int:
        return len(self._stream_leases)

    def configure_stream_policy(self, power_mode: str | None, register_values: dict) -> None:
        self.power_mode = power_mode if power_mode in ("battery", "external") else None
        for name in ("MaxUserStreamTimeLimit", "MaxStreamTimeLimit"):
            value = register_values.get(name)
            if isinstance(value, int) and not isinstance(value, bool):
                self._stream_limits[name] = value

    async def apply_stream_policy(self, power_mode: str | None, register_values: dict) -> bool | None:
        async with self._lifecycle_lock:
            was_always_on = self.always_on
            self.configure_stream_policy(power_mode, register_values)

            now = time.time()
            if was_always_on and not self.always_on and self._stream_leases:
                self._session_started_at = now
                self._session_deadline = now + BATTERY_SESSION_LIMIT_SECONDS
                for lease in self._stream_leases.values():
                    lease.expires_at = min(lease.expires_at, self._session_deadline)
            elif not was_always_on and self.always_on:
                self._last_session_started_at = self._session_started_at
                self._last_session_deadline = self._session_deadline
                self._session_started_at = None
                self._session_deadline = None
                self._cooldown_until = None
            self._schedule_lifecycle_check(now)

            if self.always_on:
                if not self.is_streaming or self._pending_stream_active is False:
                    return await self.set_user_stream_active(True)
                return None
            if not self.always_on and not self._stream_leases:
                should_stop = self.is_streaming or self._pending_stream_active is not None
                if should_stop or was_always_on or self._session_deadline is not None:
                    self._begin_cooldown(time.time())
                if should_stop:
                    return await self.set_user_stream_active(False)
            return None

    async def quiesce_stream(self, force: bool = False) -> bool:
        """Stop an unmanaged stream and cancel all local lifecycle ownership."""
        async with self._lifecycle_lock:
            self._stream_leases.clear()
            self._legacy_lease_id = None
            self._session_started_at = None
            self._session_deadline = None
            self._cooldown_until = None
            lifecycle_task = self._lifecycle_task
            if lifecycle_task and lifecycle_task is not asyncio.current_task() and not lifecycle_task.done():
                lifecycle_task.cancel()
            self._lifecycle_task = None

            should_stop = force or self.always_on or self.is_streaming or self._pending_stream_active is not None
            if not should_stop:
                return True
            delivered = await self.set_user_stream_active(False)
            reconciliation = self._stop_reconciliation_task
            if not delivered and reconciliation:
                await reconciliation
            return self._pending_stream_active is None and not self.is_streaming

    async def send_initial_config(self, config: dict) -> dict | None:
        msg = build_register_set_message(self.next_id, config)
        return await self.send_message(msg)

    async def send_ra_params(self, quality: str) -> dict | None:
        params = RA_PARAMS.get(quality)
        if not params:
            return None
        msg = build_ra_params_message(self.next_id, params)
        return await self.send_message(msg)

    async def send_epoch_time(self) -> dict | None:
        msg = build_epoch_time_message(self.next_id)
        return await self.send_message(msg)

    async def status_request(self) -> dict | None:
        msg = build_status_request_message(self.next_id)
        return await self.send_message(msg)

    async def set_quality(self, quality: str) -> bool:
        register_values = QUALITY_REGISTER_SETS.get(quality)
        if not register_values:
            return False
        msg = build_register_set_message(self.next_id, register_values)
        result = await self.send_message(msg)
        acknowledged = self._is_acknowledged(msg, result)
        if acknowledged and RA_PARAMS.get(quality):
            await self.send_ra_params(quality)
        return acknowledged

    async def arm(self, values: dict) -> bool:
        msg = build_register_set_message(self.next_id, values)
        result = await self.send_message(msg)
        return self._is_acknowledged(msg, result)

    @staticmethod
    def _is_acknowledged(message: dict, result: dict | None) -> bool:
        return isinstance(result, dict) and result.get("ID") == message["ID"] and result.get("Response", "Ack") == "Ack"

    async def set_user_stream_active(self, active: bool) -> bool:
        """Send one camera stream-state command and reconcile failed stops."""
        if active:
            self._cancel_stop_reconciliation()
        async with self._stream_command_lock:
            result = await self._send_stream_state_once(active)
        if not result and not active and self._stream_command_supported is not False:
            self._ensure_stop_reconciliation()
        return result

    async def _send_stream_state_once(self, active: bool) -> bool:
        if self._stream_command_supported is False:
            return False
        previous_attempts = 0
        if self._pending_stream_active == active and self._last_stream_result:
            previous_attempts = self._last_stream_result.get("attempts", 0)

        attempted_at = time.time()
        msg = build_user_stream_active_message(self.next_id, active)
        result = await self.send_message(msg)
        success = self._is_acknowledged(msg, result)
        unsupported = (
            isinstance(result, dict)
            and result.get("Response") == "Ack with Errors"
            and "Error Handling Register UserStreamActive" in result.get("Errors", [])
        )
        self._last_stream_result = {
            "requested_active": active,
            "success": success,
            "attempts": previous_attempts + 1,
            "last_attempt_at": attempted_at,
            "error": (
                None
                if success
                else (
                    "camera does not support UserStreamActive"
                    if unsupported
                    else "camera did not acknowledge stream command"
                )
            ),
            "retries_exhausted": unsupported,
        }

        if success:
            self._stream_command_supported = True
            self._pending_stream_active = None
            self._pending_stream_since = None
            self._stream_active = active
            self._stream_started_at = attempted_at if active else None
            if not active:
                self._cancel_stop_reconciliation()
        elif unsupported:
            self._stream_command_supported = False
            self._pending_stream_active = None
            self._pending_stream_since = None
        else:
            if self._pending_stream_active != active:
                self._pending_stream_since = attempted_at
            self._pending_stream_active = active
        return success

    def _ensure_stop_reconciliation(self) -> None:
        if self._stop_reconciliation_task and not self._stop_reconciliation_task.done():
            return
        self._stop_reconciliation_task = asyncio.create_task(self._reconcile_stop())

    def _cancel_stop_reconciliation(self) -> None:
        task = self._stop_reconciliation_task
        if task and task is not asyncio.current_task() and not task.done():
            task.cancel()
        if task is not asyncio.current_task():
            self._stop_reconciliation_task = None

    async def _reconcile_stop(self) -> None:
        for delay in STOP_RETRY_DELAYS_SECONDS:
            await asyncio.sleep(delay)
            async with self._stream_command_lock:
                if self._pending_stream_active is not False:
                    return
                if await self._send_stream_state_once(False):
                    return
        if self._last_stream_result and self._pending_stream_active is False:
            self._last_stream_result["retries_exhausted"] = True
            logger.warning(
                "stream_stop_retries_exhausted",
                device=self.serial_number,
                attempts=self._last_stream_result["attempts"],
            )

    async def deliver_pending_stream(self) -> bool | None:
        async with self._stream_command_lock:
            active = self._pending_stream_active
            if active is None:
                return None
            result = await self._send_stream_state_once(active)
        if not result and not active and self._stream_command_supported is not False:
            self._ensure_stop_reconciliation()
        return result

    async def acquire_stream_lease(self, owner: str, ttl_seconds: int) -> dict:
        await self._process_lifecycle_deadlines()
        async with self._lifecycle_lock:
            now = time.time()
            if not self.always_on:
                if self._cooldown_until and now < self._cooldown_until:
                    raise StreamLeaseRejectedError(max(1, math.ceil(self._cooldown_until - now)))
                if self._cooldown_until:
                    self._cooldown_until = None
                if self._session_deadline is None:
                    self._session_started_at = now
                    self._session_deadline = now + BATTERY_SESSION_LIMIT_SECONDS
                if now >= self._session_deadline:
                    self._begin_cooldown(now)
                    raise StreamLeaseRejectedError(BATTERY_COOLDOWN_SECONDS)
                expires_at = min(now + ttl_seconds, self._session_deadline)
            else:
                expires_at = now + ttl_seconds

            lease_id = str(uuid4())
            self._stream_leases[lease_id] = StreamLease(lease_id, owner, expires_at)
            if self._pending_stream_active is True:
                delivered = False
            elif self._pending_stream_active is False:
                delivered = await self.set_user_stream_active(True)
            elif self.is_streaming:
                delivered = True
            else:
                delivered = await self.set_user_stream_active(True)
            self._schedule_lifecycle_check(now)
            return {
                "result": True,
                "lease_id": lease_id,
                "expires_at": expires_at,
                "lease_ttl_seconds": max(1, math.ceil(expires_at - now)),
                "session_deadline": self._session_deadline,
                "power_mode": self.effective_power_mode,
                "always_on": self.always_on,
                "streaming": self.is_streaming,
                "stream_command_delivered": delivered,
                "lease_count": self.lease_count,
            }

    async def release_stream_lease(self, lease_id: str) -> dict:
        await self._process_lifecycle_deadlines()
        async with self._lifecycle_lock:
            lease = self._stream_leases.pop(lease_id, None)
            if lease_id == self._legacy_lease_id:
                self._legacy_lease_id = None
            delivered: bool | None = None
            if lease and not self._stream_leases and not self.always_on:
                now = time.time()
                self._begin_cooldown(now)
                if self.is_streaming or self._pending_stream_active is True:
                    delivered = await self.set_user_stream_active(False)
            self._schedule_lifecycle_check(time.time())
            return {
                "result": True,
                "released": lease is not None,
                "streaming": self.is_streaming,
                "stream_command_delivered": delivered,
                "lease_count": self.lease_count,
            }

    async def set_legacy_stream_active(self, active: bool) -> bool:
        async with self._legacy_lease_lock:
            if active:
                if self._legacy_lease_id in self._stream_leases:
                    return await self._refresh_legacy_stream()
                lease = await self.acquire_stream_lease(
                    "legacy-userstreamactive",
                    LEGACY_LEASE_TTL_SECONDS,
                )
                self._legacy_lease_id = lease["lease_id"]
                return True

            if self._legacy_lease_id:
                result = await self.release_stream_lease(self._legacy_lease_id)
                return bool(result["result"])
            if not self._stream_leases and not self.always_on:
                return await self.set_user_stream_active(False)
            return True

    async def refresh_legacy_stream(self) -> bool:
        async with self._legacy_lease_lock:
            return await self._refresh_legacy_stream()

    async def _refresh_legacy_stream(self) -> bool:
        await self._process_lifecycle_deadlines()
        async with self._lifecycle_lock:
            lease = self._stream_leases.get(self._legacy_lease_id or "")
            if not lease:
                self._legacy_lease_id = None
                return False
            now = time.time()
            expires_at = now + LEGACY_LEASE_TTL_SECONDS
            if not self.always_on and self._session_deadline is not None:
                expires_at = min(expires_at, self._session_deadline)
            lease.expires_at = expires_at
            self._schedule_lifecycle_check(now)
            return True

    async def _process_lifecycle_deadlines(self) -> None:
        async with self._lifecycle_lock:
            now = time.time()
            expired_ids: list[str] = []
            deadline_reached = (
                not self.always_on and self._session_deadline is not None and now >= self._session_deadline
            )
            if deadline_reached:
                self._stream_leases.clear()
                self._legacy_lease_id = None
            else:
                expired_ids = [lease_id for lease_id, lease in self._stream_leases.items() if now >= lease.expires_at]
                for lease_id in expired_ids:
                    self._stream_leases.pop(lease_id)
                    if lease_id == self._legacy_lease_id:
                        self._legacy_lease_id = None

            session_ended = not self.always_on and not self._stream_leases and (deadline_reached or bool(expired_ids))
            should_stop = (
                not self._stream_leases
                and not self.always_on
                and (self.is_streaming or self._pending_stream_active is True)
                and (deadline_reached or bool(expired_ids))
            )
            if session_ended:
                self._begin_cooldown(now)
            if should_stop:
                await self.set_user_stream_active(False)
            self._schedule_lifecycle_check(now)

    def _begin_cooldown(self, now: float) -> None:
        self._last_session_started_at = self._session_started_at
        self._last_session_deadline = self._session_deadline
        self._session_started_at = None
        self._session_deadline = None
        self._cooldown_until = max(self._cooldown_until or 0, now + BATTERY_COOLDOWN_SECONDS)

    def _schedule_lifecycle_check(self, now: float) -> None:
        task = self._lifecycle_task
        if task and task is not asyncio.current_task() and not task.done():
            task.cancel()

        wake_times = [lease.expires_at for lease in self._stream_leases.values()]
        if not self.always_on and self._session_deadline is not None:
            wake_times.append(self._session_deadline)
        if not wake_times:
            self._lifecycle_task = None
            return

        delay = max(0, min(wake_times) - now)
        self._lifecycle_task = asyncio.create_task(self._lifecycle_waiter(delay))

    async def _lifecycle_waiter(self, delay: float) -> None:
        await asyncio.sleep(delay)
        await self._process_lifecycle_deadlines()

    def cached_stream_status(self) -> dict:
        def cached_value(name: str):
            for source in (self.status or {}, self.registration or {}):
                if name in source:
                    return source[name]
            return None

        now = time.time()
        cooldown_remaining = 0
        if self._cooldown_until and self._cooldown_until > now:
            cooldown_remaining = math.ceil(self._cooldown_until - now)
        return {
            "power_mode": self.power_mode,
            "effective_power_mode": self.effective_power_mode,
            "always_on": self.always_on,
            "battery_percentage": cached_value("BatteryPercentage"),
            "pir_events": cached_value("PIREvents"),
            "user_stream_seconds": cached_value("AmountOfTimeUserStreamed"),
            "stream_seconds": cached_value("AmountOfTimeStreamed"),
            "failed_streams": cached_value("FailedStreams"),
            "signal_strength": cached_value("SignalStrengthIndicator"),
            "temperature": cached_value("Temperature"),
            "lease_count": self.lease_count,
            "pending_stream_active": self._pending_stream_active,
            "stream_command_supported": self._stream_command_supported,
            "pending_stream_since": self._pending_stream_since,
            "stream_started_at": self._stream_started_at,
            "session_started_at": self._session_started_at,
            "session_deadline": self._session_deadline,
            "last_session_started_at": self._last_session_started_at,
            "last_session_deadline": self._last_session_deadline,
            "cooldown_until": self._cooldown_until,
            "cooldown_remaining_seconds": cooldown_remaining,
            "last_stream_result": self._last_stream_result,
        }

    async def request_snapshot(self, url: str) -> bool:
        msg = build_snapshot_message(self.next_id, url)
        result = await self.send_message(msg)
        return result is not None

    async def send_register_set(self, values: dict) -> bool:
        msg = build_register_set_message(self.next_id, values)
        result = await self.send_message(msg)
        return self._is_acknowledged(msg, result)
