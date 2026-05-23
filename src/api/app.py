"""FastAPI application factory."""

from __future__ import annotations

import time

from fastapi import FastAPI

from src.api.routes_admin import router as admin_router
from src.api.routes_device import router as device_router
from src.api.routes_snapshot import router as snapshot_router


def create_app() -> FastAPI:
    app = FastAPI(title="arlo-cam-api", version="2.0.0")
    app.state.start_time = time.time()
    app.include_router(device_router)
    app.include_router(snapshot_router)
    app.include_router(admin_router)

    @app.get("/")
    async def ping():
        return "PING"

    return app
