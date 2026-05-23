"""Video doorbell device implementation."""

from __future__ import annotations

from src.devices.camera import Camera


class VideoDoorbell(Camera):
    port = 4000

    async def send_message_on_doorbell_port(self, message: dict) -> dict | None:
        return await self.send_message(message, port=4100)
