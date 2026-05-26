"""Async webhook dispatcher."""

from __future__ import annotations

import time

import httpx
import structlog
from opentelemetry import trace

from src.config import Settings
from src.devices.base import Device
from src.telemetry import tracer

logger = structlog.get_logger()


class WebhookManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=settings.webhook_timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def fire_registration(self, device: Device | None, registration: dict) -> None:
        url = self.settings.registration_webhook_url
        if not url or not self.settings.notify_registered_and_status_update:
            return
        payload = self._base_payload(device)
        payload["registration"] = _json_str(registration)
        payload["time"] = time.time()
        await self._post(url, payload, "registration")

    async def fire_status(self, device: Device | None, status: dict) -> None:
        url = self.settings.status_update_webhook_url
        if not url or not self.settings.notify_registered_and_status_update:
            return
        payload = self._base_payload(device)
        payload["status"] = _json_str(status)
        payload["time"] = time.time()
        await self._post(url, payload, "status")

    async def fire_motion(self, device: Device | None, zones: list) -> None:
        url = self.settings.motion_recording_webhook_url
        if not url or not self.settings.notify_on_motion_alert:
            return
        payload = self._base_payload(device)
        payload["zone"] = zones
        payload["file_name"] = ""
        payload["time"] = time.time()
        await self._post(url, payload, "motion")

    async def fire_motion_timeout(self, device: Device | None) -> None:
        url = self.settings.motion_timeout_webhook_url
        if not url or not self.settings.notify_on_motion_timeout_alert:
            return
        payload = self._base_payload(device)
        payload["time"] = time.time()
        await self._post(url, payload, "motion_timeout")

    async def fire_button_press(self, device: Device | None, triggered: bool) -> None:
        url = self.settings.button_press_webhook_url
        if not url or not self.settings.notify_on_button_press_alert:
            return
        payload = self._base_payload(device)
        payload["triggered"] = str(triggered).lower()
        payload["time"] = time.time()
        await self._post(url, payload, "button_press")

    async def fire_audio(self, device: Device | None) -> None:
        url = self.settings.audio_recording_webhook_url
        if not url or not self.settings.notify_on_audio_alert:
            return
        payload = self._base_payload(device)
        payload["time"] = time.time()
        await self._post(url, payload, "audio")

    async def _post(self, url: str, payload: dict, event_type: str) -> None:
        with tracer.start_as_current_span(
            "webhook.dispatch",
            attributes={"webhook.event_type": event_type, "webhook.url": url},
        ) as span:
            for attempt in range(self.settings.webhook_retries):
                try:
                    resp = await self._client.post(url, json=payload)
                    if resp.status_code < 400:
                        span.set_attribute("webhook.attempts", attempt + 1)
                        return
                    logger.warning("webhook_http_error", url=url, event=event_type, status=resp.status_code)
                except httpx.RequestError as e:
                    logger.warning("webhook_request_error", url=url, event=event_type, attempt=attempt + 1, error=str(e))
            span.set_attribute("webhook.attempts", self.settings.webhook_retries)
            span.set_status(trace.StatusCode.ERROR, f"all {self.settings.webhook_retries} attempts failed")

    @staticmethod
    def _base_payload(device: Device | None) -> dict:
        if not device:
            return {"ip": "", "friendly_name": "", "hostname": "", "serial_number": ""}
        return {
            "ip": device.ip,
            "friendly_name": device.friendly_name,
            "hostname": device.hostname,
            "serial_number": device.serial_number,
        }


def _json_str(d: dict) -> str:
    import json
    return json.dumps(d)
