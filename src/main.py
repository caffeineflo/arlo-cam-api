"""Application entrypoint - runs TCP servers and FastAPI."""

from __future__ import annotations

import asyncio
import logging

import structlog
import uvicorn

from src.api.app import create_app
from src.api.routes_snapshot import SnapshotCache
from src.config import load_settings
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


def configure_logging(level: str) -> None:
    numeric = LOG_LEVEL_MAP.get(level.upper(), logging.INFO)
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
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

    logger.info("server_starting", camera_port=settings.camera_port, doorbell_port=settings.doorbell_port, api_port=settings.api_port)

    try:
        await server.serve()
    finally:
        camera_server.close()
        doorbell_server.close()
        await webhooks.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
