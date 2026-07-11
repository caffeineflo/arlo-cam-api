"""Per-connection handler for incoming camera messages."""

from __future__ import annotations

import asyncio
import json

import structlog
from opentelemetry import trace

from src.config import Settings
from src.devices.camera import Camera
from src.devices.capabilities import filter_register_set
from src.devices.factory import create_device
from src.devices.registry import DeviceRegistry
from src.messages.quality_presets import QUALITY_REGISTER_SETS
from src.messages.templates import (
    INITIAL_REGISTER_SET_CAMERA,
    build_ack_message,
)
from src.protocol.codec import read_message, write_message
from src.state.database import Database
from src.telemetry import tracer
from src.webhooks.manager import WebhookManager

logger = structlog.get_logger()


class ConnectionHandler:
    def __init__(self, registry: DeviceRegistry, db: Database, settings: Settings, webhooks: WebhookManager):
        self.registry = registry
        self.db = db
        self.settings = settings
        self.webhooks = webhooks
        self.go2rtc_manager = None

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        ip = peer[0] if peer else "unknown"
        log = logger.bind(peer_ip=ip)

        with tracer.start_as_current_span("tcp.handle_connection", attributes={"net.peer.ip": ip}) as span:
            try:
                message = await asyncio.wait_for(read_message(reader), timeout=10.0)
                if not message:
                    return

                msg_type = message.get("Type", "")
                msg_id = message.get("ID", 0)
                span.set_attribute("message.type", msg_type)

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
                span.set_status(trace.StatusCode.ERROR, str(e))
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
            last_seen=device.last_seen,
        )

        if isinstance(device, Camera):
            async with device.policy_lock:
                desired = await self.db.get_desired_state(serial)
                stored_values = {}
                if desired:
                    stored_values = json.loads(desired.get("register_set_values", "{}"))
                    if stored_values:
                        log.info("desired_state_applied", keys=list(stored_values.keys()))
                config = self._build_initial_config(stored_values)

                device.configure_stream_policy(
                    desired.get("power_mode") if desired else None,
                    config,
                )

                filtered = filter_register_set(config, model, message)
                removed = set(config.keys()) - set(filtered.keys())
                if removed:
                    log.info("capability_filtered", removed=list(removed))

                await device.send_initial_config(filtered)
                await device.send_epoch_time()

                quality = (desired.get("quality_preset") if desired else None) or self.settings.video_quality_default
                await device.send_ra_params(quality)

                if device.always_on:
                    await device.set_user_stream_active(True)
                    log.info("always_on_stream_activated", serial=serial)

        if self.go2rtc_manager and isinstance(device, Camera):
            await self.go2rtc_manager.add_stream(device)

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
            if isinstance(device, Camera):
                await device.deliver_pending_stream()
        await self.db.update_status(
            serial,
            message,
            device.last_seen if device else None,
        )
        await self.webhooks.fire_status(device, message)

    async def _handle_alert(self, ip: str, message: dict, log: structlog.BoundLogger) -> None:
        device = self.registry.get_by_ip(ip)
        serial = device.serial_number if device else "unknown"
        alert_type = message.get("AlertType", "")
        log.info("alert_received", serial=serial, alert_type=alert_type)

        if device:
            device.touch()
            await self.db.update_last_seen(device.serial_number, device.last_seen)
            if isinstance(device, Camera):
                await device.deliver_pending_stream()

        if alert_type == "pirMotionAlert":
            zones = message.get("PIRMotion", {}).get("zones", [])
            await self.webhooks.fire_motion(device, zones)
        elif alert_type == "motionTimeoutAlert":
            await self.webhooks.fire_motion_timeout(device)
        elif alert_type == "buttonPressAlert":
            await self.webhooks.fire_button_press(device, True)
        elif alert_type == "audioAlert":
            await self.webhooks.fire_audio(device)

    def _build_initial_config(self, desired_values: dict | None = None) -> dict:
        config = dict(INITIAL_REGISTER_SET_CAMERA)
        config.update(QUALITY_REGISTER_SETS[self.settings.video_quality_default])
        config["WifiCountryCode"] = self.settings.wifi_country_code
        config["VideoAntiFlickerRate"] = self.settings.video_anti_flicker_rate
        if desired_values:
            config.update(desired_values)
        return config
