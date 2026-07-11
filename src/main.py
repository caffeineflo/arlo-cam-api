"""Application entrypoint - runs TCP servers and FastAPI."""

from __future__ import annotations

import asyncio
import json
import logging

import structlog
import uvicorn

from src.api.app import create_app
from src.api.routes_snapshot import SnapshotCache
from src.config import load_settings
from src.devices.camera import Camera
from src.devices.registry import DeviceRegistry
from src.protocol.connection import ConnectionHandler
from src.protocol.server import start_tcp_server
from src.state.database import Database
from src.webhooks.manager import WebhookManager

LOG_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


def _otel_trace_injector(logger, method_name, event_dict):
    from opentelemetry import trace as otel_trace

    span = otel_trace.get_current_span()
    ctx = span.get_span_context()
    if ctx and ctx.trace_id:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict


def configure_logging(level: str) -> None:
    numeric = LOG_LEVEL_MAP.get(level.upper(), logging.INFO)
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            _otel_trace_injector,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric),
    )


logger = structlog.get_logger()


async def main() -> None:
    settings = load_settings("/app/config.yaml")
    configure_logging(settings.log_level)
    logger.info("config_loaded", quality=settings.video_quality_default, country=settings.wifi_country_code)

    db = Database(settings.database_path)
    await db.connect()

    registry = DeviceRegistry()
    await registry.restore_from_db(db)
    webhooks = WebhookManager(settings)
    handler = ConnectionHandler(registry, db, settings, webhooks)

    go2rtc_mgr = None
    if settings.go2rtc_enabled:
        from src.go2rtc.manager import Go2RTCManager

        go2rtc_mgr = Go2RTCManager(registry, settings)
        await go2rtc_mgr.generate_config()

    handler.go2rtc_manager = go2rtc_mgr

    app = create_app()
    app.state.registry = registry
    app.state.db = db
    app.state.settings = settings
    app.state.snapshot_cache = SnapshotCache(ttl=settings.snapshot_cache_ttl)
    app.state.go2rtc = go2rtc_mgr

    camera_server = await start_tcp_server(handler, settings.camera_port, "camera")
    doorbell_server = await start_tcp_server(handler, settings.doorbell_port, "doorbell")

    config = uvicorn.Config(app, host="0.0.0.0", port=settings.api_port, log_level="info")
    server = uvicorn.Server(config)

    logger.info(
        "server_starting",
        camera_port=settings.camera_port,
        doorbell_port=settings.doorbell_port,
        api_port=settings.api_port,
    )

    async def activate_always_on_cameras():
        await asyncio.sleep(5)
        for device in registry.get_all():
            if not isinstance(device, Camera):
                continue
            async with device.policy_lock:
                desired = await db.get_desired_state(device.serial_number)
                if not desired:
                    device.configure_stream_policy(None, {})
                    continue
                stored = json.loads(desired.get("register_set_values", "{}"))
                device.configure_stream_policy(desired.get("power_mode"), stored)
                if device.always_on:
                    await device.set_user_stream_active(True)
                    logger.info("always_on_startup_activate", serial=device.serial_number)

    asyncio.create_task(activate_always_on_cameras())

    async def deactivate_all_streams():
        cameras = []
        for device in registry.get_all():
            if isinstance(device, Camera):
                cameras.append(device)
                logger.info("shutdown_stream_deactivate", serial=device.serial_number)
        if cameras:
            results = await asyncio.gather(
                *(camera.quiesce_stream(force=True) for camera in cameras),
                return_exceptions=True,
            )
            for camera, result in zip(cameras, results, strict=True):
                if result is not True:
                    logger.error(
                        "shutdown_stream_deactivate_failed",
                        serial=camera.serial_number,
                        result=str(result),
                    )

    try:
        await server.serve()
    finally:
        await deactivate_all_streams()
        camera_server.close()
        doorbell_server.close()
        await webhooks.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
