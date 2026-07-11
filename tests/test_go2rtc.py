"""Tests for go2rtc config generation and stream naming."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.config import Settings, load_settings
from src.devices.camera import Camera
from src.devices.registry import DeviceRegistry
from src.go2rtc.manager import Go2RTCManager

REPOSITORY_ROOT = os.path.dirname(os.path.dirname(__file__))
STREAM_HELPER = os.path.join(REPOSITORY_ROOT, "stream_helper.sh")


def _write_executable(path, contents):
    path.write_text(contents)
    path.chmod(0o755)


def _wait_for_file(path, timeout=6):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.05)
    pytest.fail(f"Timed out waiting for {path.name}")


def _helper_environment(tmp_path, power_mode, release_failures=0, emit_media=True):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    _write_executable(
        bin_dir / "curl",
        """#!/bin/sh
method=GET
url=
data=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --request)
      method="$2"
      shift 2
      ;;
    --data)
      data="$2"
      shift 2
      ;;
    http://*)
      url="$1"
      shift
      ;;
    *)
      shift
      ;;
  esac
done

if [ "$method" = POST ]; then
  printf '%s\n' "$url" >"$TEST_STATE_DIR/acquire_url"
  printf '%s\n' "$data" >"$TEST_STATE_DIR/acquire_body"
  printf '{"lease_id":"lease-test","power_mode":"%s","lease_ttl_seconds":5}\n' "$TEST_POWER_MODE"
  exit 0
fi

count=0
if [ -f "$TEST_STATE_DIR/release_attempts" ]; then
  read -r count <"$TEST_STATE_DIR/release_attempts"
fi
count=$((count + 1))
printf '%s\n' "$count" >"$TEST_STATE_DIR/release_attempts"
if [ "$count" -le "$TEST_RELEASE_FAILURES" ]; then
  exit 22
fi
printf '%s\n' "$url" >"$TEST_STATE_DIR/release_url"
printf '{}\n'
""",
    )
    _write_executable(bin_dir / "ping", "#!/bin/sh\nexit 0\n")
    _write_executable(bin_dir / "nc", "#!/bin/sh\nexit 0\n")
    _write_executable(
        bin_dir / "setsid",
        """#!/usr/bin/env python3
import os
import sys

os.setsid()
os.execvp(sys.argv[1], sys.argv[1:])
""",
    )
    _write_executable(
        bin_dir / "ffmpeg",
        """#!/bin/sh
printf '%s\n' "$$" >>"$TEST_STATE_DIR/ffmpeg_pids"
for output do :; done
exec 3>"$output"
if [ "$TEST_EMIT_MEDIA" = 1 ]; then
  count=0
  while [ "$count" -lt 10 ]; do
    printf G >&3
    dd if=/dev/zero bs=187 count=1 >&3 2>/dev/null
    count=$((count + 1))
  done
fi
sleep 300 &
printf '%s\n' "$!" >>"$TEST_STATE_DIR/ffmpeg_child_pids"
wait
""",
    )

    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{bin_dir}:{environment['PATH']}",
            "TEST_STATE_DIR": str(state_dir),
            "TEST_POWER_MODE": power_mode,
            "TEST_RELEASE_FAILURES": str(release_failures),
            "TEST_EMIT_MEDIA": "1" if emit_media else "0",
            "ARLO_BATTERY_STREAM_MAX_SECONDS": "5",
            "ARLO_FFMPEG_STOP_GRACE_SECONDS": "0",
            "ARLO_MEDIA_START_TIMEOUT_SECONDS": "2",
        }
    )
    return environment, state_dir


def _start_stream_helper(environment):
    return subprocess.Popen(
        ["/bin/sh", STREAM_HELPER, "camera-serial", "192.0.2.10", "-"],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )


def _stop_stream_helper(process):
    if process.poll() is None:
        process.send_signal(signal.SIGINT)
    try:
        return process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        return process.communicate(timeout=5)


def _process_exists(pid):
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    return True


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
    assert mgr.stream_name(cam) == "vmc3030_66d7b"


def test_stream_name_from_friendly_name(registry_with_cameras, settings):
    mgr = Go2RTCManager(registry_with_cameras, settings)
    cam = registry_with_cameras.get("4N72777560C4E")
    assert mgr.stream_name(cam) == "front_porch"


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
    assert "{output}" not in stream_line
    assert " -#killsignal=2#killtimeout=5" in stream_line
    assert config["exec"]["allow_paths"] == ["/app/stream_helper.sh"]


@pytest.mark.asyncio
async def test_generate_config_rtsp_ports(registry_with_cameras, settings):
    mgr = Go2RTCManager(registry_with_cameras, settings)
    await mgr.generate_config()

    with open(settings.go2rtc_config_path) as f:
        config = json.load(f)

    assert config["rtsp"]["listen"] == ":8554"
    assert config["api"]["listen"] == ":1984"
    assert oct(os.stat(settings.go2rtc_config_path).st_mode & 0o777) == "0o600"


@pytest.mark.asyncio
async def test_generate_config_protects_http_api(registry_with_cameras, settings):
    settings.go2rtc_api_username = "arlo-api"
    settings.go2rtc_api_password = "secret"
    mgr = Go2RTCManager(registry_with_cameras, settings)

    await mgr.generate_config()

    with open(settings.go2rtc_config_path) as config_file:
        config = json.load(config_file)
    assert config["api"] == {
        "listen": ":1984",
        "username": "arlo-api",
        "password": "secret",
        "local_auth": True,
    }


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


@pytest.mark.parametrize(
    "values",
    [
        {"go2rtc_api_username": "arlo-api"},
        {"go2rtc_api_password": "secret"},
        {"go2rtc_require_api_auth": True},
    ],
)
def test_settings_reject_incomplete_required_go2rtc_auth(values):
    with pytest.raises(ValidationError):
        Settings(**values)


def test_battery_helper_stops_once_and_waits_for_go2rtc(tmp_path):
    environment, state_dir = _helper_environment(tmp_path, "battery", release_failures=2)
    process = _start_stream_helper(environment)
    media_marker = Path(f"/tmp/arlo-stream-camera-serial-{process.pid}.media")

    try:
        _wait_for_file(media_marker)
        _wait_for_file(state_dir / "release_url")
        time.sleep(0.2)
        ffmpeg_pids = (state_dir / "ffmpeg_pids").read_text().splitlines()
        ffmpeg_child_pids = (state_dir / "ffmpeg_child_pids").read_text().splitlines()
        result = {
            "running_after_budget": process.poll() is None,
            "ffmpeg_start_count": len(ffmpeg_pids),
            "ffmpeg_group_alive": any(_process_exists(pid) for pid in ffmpeg_pids + ffmpeg_child_pids),
            "release_attempts": (state_dir / "release_attempts").read_text().strip(),
            "release_url": (state_dir / "release_url").read_text().strip(),
            "request_body": json.loads((state_dir / "acquire_body").read_text()),
        }
    finally:
        _, stderr = _stop_stream_helper(process)

    assert result == {
        "running_after_budget": True,
        "ffmpeg_start_count": 1,
        "ffmpeg_group_alive": False,
        "release_attempts": "3",
        "release_url": "http://127.0.0.1:5000/device/camera-serial/stream/leases/lease-test",
        "request_body": {"owner": "go2rtc", "ttl_seconds": 5},
    }, stderr


def test_external_helper_ignores_lease_ttl_and_streams_until_closed(tmp_path):
    environment, state_dir = _helper_environment(tmp_path, "external")
    process = _start_stream_helper(environment)

    try:
        _wait_for_file(state_dir / "ffmpeg_pids")
        time.sleep(1.2)
        result = {
            "running_after_lease_ttl": process.poll() is None,
            "released_while_running": (state_dir / "release_url").exists(),
        }
    finally:
        _, stderr = _stop_stream_helper(process)

    result["released_on_close"] = (state_dir / "release_url").exists()
    result["ffmpeg_alive_on_close"] = _process_exists((state_dir / "ffmpeg_pids").read_text().strip())

    assert result == {
        "running_after_lease_ttl": True,
        "released_while_running": False,
        "released_on_close": True,
        "ffmpeg_alive_on_close": False,
    }, stderr


def test_battery_helper_exits_if_no_media_arrives_before_budget(tmp_path):
    environment, state_dir = _helper_environment(
        tmp_path,
        "battery",
        emit_media=False,
    )
    process = _start_stream_helper(environment)

    stdout, stderr = process.communicate(timeout=8)

    assert (
        process.returncode,
        stdout,
        (state_dir / "release_url").exists(),
        "did not produce media within 2s" in stderr,
    ) == (1, "", True, True)


def test_external_helper_exits_if_no_media_arrives(tmp_path):
    environment, state_dir = _helper_environment(
        tmp_path,
        "external",
        emit_media=False,
    )
    process = _start_stream_helper(environment)

    stdout, stderr = process.communicate(timeout=6)

    assert (
        process.returncode,
        stdout,
        (state_dir / "release_url").exists(),
        "did not produce media within 2s" in stderr,
    ) == (1, "", True, True)
