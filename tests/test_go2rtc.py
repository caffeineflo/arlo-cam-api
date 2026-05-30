"""Tests for go2rtc config generation and stream naming."""

from __future__ import annotations

import json

import pytest

from src.config import Settings, load_settings
from src.devices.camera import Camera
from src.devices.registry import DeviceRegistry
from src.go2rtc.manager import Go2RTCManager


@pytest.fixture
def registry_with_cameras():
    registry = DeviceRegistry()
    cam1 = Camera(
        serial_number="4N72777366D7B",
        ip="192.168.4.8",
        hostname="VMC3030-66D7B",
        model="VMC3030",
        registration={"SystemModelNumber": "VMC3030"},
    )
    cam2 = Camera(
        serial_number="4N72777560C4E",
        ip="192.168.4.216",
        hostname="VMC3030-60C4E",
        model="VMC3030",
        registration={"SystemModelNumber": "VMC3030"},
    )
    cam2.friendly_name = "Front Porch"
    registry.register(cam1)
    registry.register(cam2)
    return registry


@pytest.fixture
def settings(tmp_path):
    return Settings(
        database_path=":memory:",
        go2rtc_config_path=str(tmp_path / "go2rtc.yaml"),
        go2rtc_rtsp_port=8554,
        go2rtc_api_port=1984,
        go2rtc_start_timeout=90,
    )


def test_stream_name_from_hostname(registry_with_cameras, settings):
    mgr = Go2RTCManager(registry_with_cameras, settings)
    cam = registry_with_cameras.get("4N72777366D7B")
    assert mgr._stream_name(cam) == "vmc3030_66d7b"


def test_stream_name_from_friendly_name(registry_with_cameras, settings):
    mgr = Go2RTCManager(registry_with_cameras, settings)
    cam = registry_with_cameras.get("4N72777560C4E")
    assert mgr._stream_name(cam) == "front_porch"


@pytest.mark.asyncio
async def test_generate_config(registry_with_cameras, settings):
    mgr = Go2RTCManager(registry_with_cameras, settings)
    await mgr.generate_config()

    with open(settings.go2rtc_config_path) as f:
        config = json.load(f)

    assert "streams" in config
    assert len(config["streams"]) == 2
    assert "vmc3030_66d7b" in config["streams"]
    assert "front_porch" in config["streams"]

    stream_line = config["streams"]["vmc3030_66d7b"][0]
    assert "4N72777366D7B" in stream_line
    assert "192.168.4.8" in stream_line
    assert "#starttimeout=90" in stream_line


@pytest.mark.asyncio
async def test_generate_config_rtsp_ports(registry_with_cameras, settings):
    mgr = Go2RTCManager(registry_with_cameras, settings)
    await mgr.generate_config()

    with open(settings.go2rtc_config_path) as f:
        config = json.load(f)

    assert config["rtsp"]["listen"] == ":8554"
    assert config["api"]["listen"] == ":1984"


@pytest.mark.asyncio
async def test_get_streams(registry_with_cameras, settings):
    mgr = Go2RTCManager(registry_with_cameras, settings)
    streams = await mgr.get_streams()

    assert len(streams) == 2
    assert "front_porch" in streams
    assert streams["front_porch"]["serial"] == "4N72777560C4E"
    assert streams["front_porch"]["ip"] == "192.168.4.216"
    assert "8554" in streams["front_porch"]["rtsp_url"]


def test_go2rtc_api_base_defaults_to_localhost(registry_with_cameras, settings):
    mgr = Go2RTCManager(registry_with_cameras, settings)

    assert mgr._api_base == "http://127.0.0.1:1984"


def test_go2rtc_api_base_uses_configured_url(registry_with_cameras, settings):
    settings.go2rtc_api_url = "http://arlo-go2rtc:1984/"
    mgr = Go2RTCManager(registry_with_cameras, settings)

    assert mgr._api_base == "http://arlo-go2rtc:1984"


def test_load_settings_maps_go2rtc_api_url(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text('Go2RTCApiUrl: "http://arlo-go2rtc:1984"\n')

    settings = load_settings(str(config_path))

    assert settings.go2rtc_api_url == "http://arlo-go2rtc:1984"
