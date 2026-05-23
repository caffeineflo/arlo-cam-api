"""Camera device implementation."""

from __future__ import annotations

import asyncio
import time

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

STREAM_WATCHDOG_TIMEOUT = 45.0


class Camera(Device):
    port = 4000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._stream_active: bool = False
        self._stream_started_at: float = 0
        self._stream_watchdog: asyncio.Task | None = None

    @property
    def is_streaming(self) -> bool:
        return self._stream_active

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
        if result and RA_PARAMS.get(quality):
            await self.send_ra_params(quality)
        return result is not None

    async def arm(self, values: dict) -> bool:
        msg = build_register_set_message(self.next_id, values)
        result = await self.send_message(msg)
        return result is not None

    async def set_user_stream_active(self, active: bool) -> bool:
        msg = build_user_stream_active_message(self.next_id, active)
        result = await self.send_message(msg)
        if result is not None:
            self._stream_active = active
            if active:
                self._stream_started_at = time.time()
                self._reset_stream_watchdog()
            else:
                self._cancel_stream_watchdog()
        return result is not None

    def refresh_stream(self) -> None:
        """Called by the stream consumer to signal it's still watching."""
        if self._stream_active:
            self._reset_stream_watchdog()

    def _reset_stream_watchdog(self) -> None:
        self._cancel_stream_watchdog()
        self._stream_watchdog = asyncio.ensure_future(self._stream_watchdog_task())

    def _cancel_stream_watchdog(self) -> None:
        if self._stream_watchdog and not self._stream_watchdog.done():
            self._stream_watchdog.cancel()
            self._stream_watchdog = None

    async def _stream_watchdog_task(self) -> None:
        """Auto-stop the stream if no refresh is received within the timeout."""
        await asyncio.sleep(STREAM_WATCHDOG_TIMEOUT)
        if self._stream_active:
            from structlog import get_logger
            get_logger().info("stream_watchdog_timeout", device=self.serial_number)
            await self.set_user_stream_active(False)

    async def request_snapshot(self, url: str) -> bool:
        msg = build_snapshot_message(self.next_id, url)
        result = await self.send_message(msg)
        return result is not None

    async def send_register_set(self, values: dict) -> bool:
        msg = build_register_set_message(self.next_id, values)
        result = await self.send_message(msg)
        return result is not None
