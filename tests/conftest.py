"""Shared test fixtures."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.api.app import create_app
from src.api.routes_snapshot import SnapshotCache
from src.config import Settings
from src.devices.camera import Camera
from src.devices.registry import DeviceRegistry
from src.state.database import Database


@pytest.fixture
def settings():
    return Settings(database_path=":memory:")


@pytest_asyncio.fixture
async def db(settings):
    database = Database(settings.database_path)
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def registry():
    return DeviceRegistry()


@pytest.fixture
def sample_registration():
    return {
        "Type": "registration",
        "ID": 1234,
        "SystemSerialNumber": "4N72777366D7B",
        "SystemModelNumber": "VMC3030",
        "UpdateSystemModelNumber": "VMC3030",
        "SystemFirmwareVersion": "1.4.9.6_16671",
        "Capabilities": [],
    }


@pytest.fixture
def sample_camera(sample_registration):
    return Camera(
        serial_number="4N72777366D7B",
        ip="192.168.4.8",
        hostname="VMC3030-66D7B",
        model="VMC3030",
        registration=sample_registration,
    )


@pytest_asyncio.fixture
async def app(settings, db, registry, sample_camera):
    application = create_app()
    application.state.registry = registry
    application.state.db = db
    application.state.settings = settings
    application.state.snapshot_cache = SnapshotCache(ttl=300)
    application.state.go2rtc = None
    registry.register(sample_camera)
    return application


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
