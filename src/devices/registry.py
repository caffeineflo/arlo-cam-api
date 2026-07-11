"""In-memory device registry with presence tracking."""

from __future__ import annotations

import structlog

from src.devices.base import Device
from src.devices.factory import create_device

logger = structlog.get_logger()


class DeviceRegistry:
    def __init__(self):
        self._devices: dict[str, Device] = {}

    def register(self, device: Device) -> None:
        self._devices[device.serial_number] = device

    def get(self, serial_number: str) -> Device | None:
        return self._devices.get(serial_number)

    def get_by_ip(self, ip: str) -> Device | None:
        for device in self._devices.values():
            if device.ip == ip:
                return device
        return None

    def get_all(self) -> list[Device]:
        return list(self._devices.values())

    def remove(self, serial_number: str) -> bool:
        if serial_number in self._devices:
            del self._devices[serial_number]
            return True
        return False

    def __len__(self) -> int:
        return len(self._devices)

    async def restore_from_db(self, db) -> None:
        """Restore devices into registry from database on startup."""
        rows = await db.get_all_devices()
        for row in rows:
            serial = row.get("serial_number", "")
            if not serial or serial in self._devices:
                continue
            ip = row.get("ip", "")
            hostname = row.get("hostname", serial)
            registration = row.get("registration") or {}
            model = registration.get("SystemModelNumber", "")
            friendly_name = row.get("friendly_name", serial)
            device = create_device(serial, ip, hostname, model, registration)
            device.friendly_name = friendly_name
            device.status = row.get("status")
            device.last_seen = row.get("last_seen") or 0
            self._devices[serial] = device
        if rows:
            logger.info("registry_restored", count=len(rows))
