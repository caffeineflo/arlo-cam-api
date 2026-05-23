"""Audio doorbell device implementation."""

from __future__ import annotations

from src.devices.base import Device


class AudioDoorbell(Device):
    port = 4100
