"""In-memory device registry with presence tracking."""

from __future__ import annotations

from src.devices.base import Device


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
