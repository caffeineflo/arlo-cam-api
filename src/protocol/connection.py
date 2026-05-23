"""Per-connection handler for incoming camera messages."""

from __future__ import annotations

import asyncio
import json
import time

import structlog

from src.config import Settings
from src.devices.base import Device
from src.devices.camera import Camera
from src.devices.capabilities import filter_register_set
from src.devices.factory import create_device
from src.devices.registry import DeviceRegistry
from src.messages.templates import (
    INITIAL_REGISTER_SET_CAMERA,
    build_ack_message,
    build_epoch_time_message,
    build_register_set_message,
)
from src.protocol.codec import read_message, write_message
from src.state.database import Database
from src.webhooks.manager import WebhookManager

logger = structlog.get_logger()


class ConnectionHandler:
    def __init__(self, registry: DeviceRegistry, db: Database, settings: Settings, webhooks: WebhookManager):
        self.registry = registry
        self.db = db
        self.settings = settings
        self.webhooks = webhooks

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        ip = peer[0] if peer else "unknown"
        log = logger.bind(peer_ip=ip)

        try:
            message = await asyncio.wait_for(read_message(reader), timeout=10.0)
            if not message:
                return

            msg_type = message.get("Type", "")
            msg_id = message.get("ID", 0)

            ack = build_ack_message(msg_id)
            await write_message(writer, ack)

            if msg_type == "registration":
                await self._handle_registration(ip, message, log)
            elif msg_type == "status":
                await self._handle_status(ip, message, log)
            elif msg_type == "alert":
                await self._handle_alert(ip, message, log)
            else:
                log.debug("unknown_message_type", msg_type=msg_type)

        except asyncio.TimeoutError:
            log.debug("connection_timeout")
        except Exception as e:
            log.error("connection_error", error=str(e))
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    async def _handle_registration(self, ip: str, message: dict, log: structlog.BoundLogger) -> None:
        serial = message.get("SystemSerialNumber", "")
        model = message.get("SystemModelNumber", "")
        hostname = message.get("UpdateSystemModelNumber", model)
        if not serial:
            log.warning("registration_missing_serial")
            return

        hostname_full = f"{hostname}-{serial[-5:]}" if hostname else serial
        log = log.bind(serial=serial, model=model)
        log.info("registration_received")

        device = self.registry.get(serial)
        if device:
            device.update_ip(ip)
            device.registration = message
            device.touch()
        else:
            device = create_device(serial, ip, hostname_full, model, message)
            self.registry.register(device)

        await self.db.upsert_device(
            serial_number=serial,
            ip=ip,
            hostname=hostname_full,
            friendly_name=device.friendly_name,
            registration=message,
        )

        if isinstance(device, Camera):
            config = self._build_initial_config()
            desired = await self.db.get_desired_state(serial)
            if desired:
                stored_values = json.loads(desired.get("register_set_values", "{}"))
                if stored_values:
                    config.update(stored_values)
                    log.info("desired_state_applied", keys=list(stored_values.keys()))

            filtered = filter_register_set(config, model, message)
            removed = set(config.keys()) - set(filtered.keys())
            if removed:
                log.info("capability_filtered", removed=list(removed))

            await device.send_initial_config(filtered)
            await device.send_epoch_time()

            if desired and desired.get("quality_preset"):
                await device.send_ra_params(desired["quality_preset"])

        await self.webhooks.fire_registration(device, message)

    async def _handle_status(self, ip: str, message: dict, log: structlog.BoundLogger) -> None:
        serial = message.get("SystemSerialNumber", "")
        if not serial:
            return

        log.info("status_received", serial=serial)

        device = self.registry.get(serial)
        if device:
            device.update_ip(ip)
            device.update_status(message)
        await self.db.update_status(serial, message)
        await self.webhooks.fire_status(device, message)

    async def _handle_alert(self, ip: str, message: dict, log: structlog.BoundLogger) -> None:
        device = self.registry.get_by_ip(ip)
        serial = device.serial_number if device else "unknown"
        alert_type = message.get("AlertType", "")
        log.info("alert_received", serial=serial, alert_type=alert_type)

        if device:
            device.touch()

        if alert_type == "pirMotionAlert":
            zones = message.get("PIRMotion", {}).get("zones", [])
            await self.webhooks.fire_motion(device, zones)
        elif alert_type == "motionTimeoutAlert":
            await self.webhooks.fire_motion_timeout(device)
        elif alert_type == "buttonPressAlert":
            await self.webhooks.fire_button_press(device, True)
        elif alert_type == "audioAlert":
            await self.webhooks.fire_audio(device)

    def _build_initial_config(self) -> dict:
        config = dict(INITIAL_REGISTER_SET_CAMERA)
        config["WifiCountryCode"] = self.settings.wifi_country_code
        config["VideoAntiFlickerRate"] = self.settings.video_anti_flicker_rate
        return config
