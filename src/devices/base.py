"""Base device class with async messaging."""

from __future__ import annotations

import asyncio
import json
import time

import structlog

from src.protocol.codec import read_message, write_message

logger = structlog.get_logger()


class Device:
    port: int = 4000

    def __init__(self, serial_number: str, ip: str, hostname: str, model: str, registration: dict):
        self.serial_number = serial_number
        self.ip = ip
        self.hostname = hostname
        self.model = model
        self.registration = registration
        self.status: dict | None = None
        self.friendly_name: str = serial_number
        self.last_seen: float = time.time()
        self._msg_id: int = 100

    @property
    def next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    async def send_message(self, message: dict, port: int | None = None) -> dict | None:
        target_port = port or self.port
        log = logger.bind(device=self.serial_number, ip=self.ip, port=target_port)
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.ip, target_port),
                timeout=5.0,
            )
        except (OSError, asyncio.TimeoutError) as e:
            log.warning("connection_failed", error=str(e))
            return None

        try:
            await write_message(writer, message)
            response = await asyncio.wait_for(read_message(reader), timeout=5.0)
            log.debug("message_sent", msg_type=message.get("Type"), response_type=response.get("Type") if response else None)
            return response
        except (OSError, asyncio.TimeoutError, json.JSONDecodeError) as e:
            log.warning("send_failed", error=str(e))
            return None
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    def update_ip(self, ip: str) -> None:
        self.ip = ip

    def update_status(self, status: dict) -> None:
        self.status = status
        self.last_seen = time.time()

    def touch(self) -> None:
        self.last_seen = time.time()

    @property
    def online(self) -> bool:
        return (time.time() - self.last_seen) < 300

    def to_summary(self) -> dict:
        return {
            "friendly_name": self.friendly_name,
            "hostname": self.hostname,
            "ip": self.ip,
            "serial_number": self.serial_number,
        }
