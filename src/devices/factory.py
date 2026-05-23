"""Device factory - creates the appropriate device type based on model prefix."""

from __future__ import annotations

from src.devices.audio_doorbell import AudioDoorbell
from src.devices.base import Device
from src.devices.camera import Camera
from src.devices.video_doorbell import VideoDoorbell

MODEL_PREFIX_MAP = {
    "VMC": Camera,
    "VML": Camera,
    "ABC": Camera,
    "FB": Camera,
    "AAD": AudioDoorbell,
    "AVD": VideoDoorbell,
}


def create_device(serial_number: str, ip: str, hostname: str, model: str, registration: dict) -> Device:
    for prefix, device_class in MODEL_PREFIX_MAP.items():
        if model.startswith(prefix):
            return device_class(
                serial_number=serial_number,
                ip=ip,
                hostname=hostname,
                model=model,
                registration=registration,
            )
    return Camera(
        serial_number=serial_number,
        ip=ip,
        hostname=hostname,
        model=model,
        registration=registration,
    )
