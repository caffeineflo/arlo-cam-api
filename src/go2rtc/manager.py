"""Manages go2rtc config generation and runtime stream updates."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import httpx
import structlog

from src.devices.registry import DeviceRegistry
from src.telemetry import tracer

logger = structlog.get_logger()


class Go2RTCManager:
    def __init__(self, registry: DeviceRegistry, settings) -> None:
        self._registry = registry
        self._settings = settings
        self._api_base = settings.go2rtc_api_url.rstrip("/") or f"http://127.0.0.1:{settings.go2rtc_api_port}"
        self._auth = (
            httpx.BasicAuth(settings.go2rtc_api_username, settings.go2rtc_api_password)
            if settings.go2rtc_api_username
            else None
        )

    async def generate_config(self) -> None:
        from src.devices.camera import Camera

        streams = {}
        for device in self._registry.get_all():
            if not isinstance(device, Camera):
                continue
            name = self.stream_name(device)
            streams[name] = [self._exec_line(device)]

        api_config = {"listen": f":{self._settings.go2rtc_api_port}"}
        if self._settings.go2rtc_api_username:
            api_config.update(
                {
                    "username": self._settings.go2rtc_api_username,
                    "password": self._settings.go2rtc_api_password,
                    "local_auth": True,
                }
            )
        config = {
            "api": api_config,
            "exec": {"allow_paths": ["/app/stream_helper.sh"]},
            "rtsp": {"listen": f":{self._settings.go2rtc_rtsp_port}"},
            "streams": streams,
        }

        config_path = Path(self._settings.go2rtc_config_path)
        temp_path = config_path.with_name(f".{config_path.name}.tmp")
        with open(
            temp_path,
            "w",
            opener=lambda path, flags: os.open(path, flags, 0o600),
        ) as f:
            json.dump(config, f, indent=2)
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, config_path)

        logger.info("go2rtc_config_generated", streams=len(streams), path=str(config_path))

    async def reload(self) -> bool:
        try:
            async with httpx.AsyncClient(auth=self._auth) as client:
                resp = await client.post(f"{self._api_base}/api/restart", timeout=5)
                return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def add_stream(self, device) -> bool:
        from src.devices.camera import Camera

        if not isinstance(device, Camera):
            return False

        name = self.stream_name(device)
        src = self._exec_line(device)
        with tracer.start_as_current_span(
            "go2rtc.add_stream",
            attributes={"stream.name": name, "device.serial": device.serial_number},
        ):
            try:
                async with httpx.AsyncClient(auth=self._auth) as client:
                    resp = await client.put(
                        f"{self._api_base}/api/streams",
                        params={"name": name, "src": src},
                        timeout=5,
                    )
                    if resp.status_code == 200:
                        logger.info("go2rtc_stream_added", name=name, serial=device.serial_number)
                        return True
            except httpx.HTTPError as e:
                logger.warning("go2rtc_add_stream_failed", name=name, error=str(e))
            return False

    async def remove_stream(self, name: str) -> bool:
        try:
            async with httpx.AsyncClient(auth=self._auth) as client:
                resp = await client.delete(
                    f"{self._api_base}/api/streams",
                    params={"name": name},
                    timeout=5,
                )
                return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def get_runtime_streams(self) -> dict | None:
        try:
            async with httpx.AsyncClient(auth=self._auth) as client:
                response = await client.get(f"{self._api_base}/api/streams", timeout=2)
                response.raise_for_status()
                streams = response.json()
                return streams if isinstance(streams, dict) else None
        except (httpx.HTTPError, ValueError):
            return None

    async def get_streams(self, host: str = "localhost") -> dict:
        from src.devices.camera import Camera

        streams = {}
        for device in self._registry.get_all():
            if not isinstance(device, Camera):
                continue
            name = self.stream_name(device)
            streams[name] = {
                "serial": device.serial_number,
                "ip": device.ip,
                "rtsp_url": f"rtsp://{host}:{self._settings.go2rtc_rtsp_port}/{name}",
            }
        return streams

    def _exec_line(self, device) -> str:
        return f"exec:/app/stream_helper.sh {device.serial_number} {device.ip} -#killsignal=2#killtimeout=5"

    def stream_name(self, device) -> str:
        if device.friendly_name and device.friendly_name != device.serial_number:
            name = device.friendly_name
        else:
            name = device.hostname or device.serial_number
        slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        return slug or device.serial_number
