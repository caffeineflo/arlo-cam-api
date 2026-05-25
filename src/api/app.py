"""FastAPI application factory."""

from __future__ import annotations

import time

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from src.api.routes_admin import router as admin_router
from src.api.routes_device import router as device_router
from src.api.routes_snapshot import router as snapshot_router
from src.api.routes_streams import router as streams_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="arlo-cam-api",
        version="2.0.0",
        description="Local base station emulator for Arlo cameras with go2rtc RTSP streaming.",
    )
    app.state.start_time = time.time()
    app.include_router(device_router)
    app.include_router(snapshot_router)
    app.include_router(admin_router)
    app.include_router(streams_router)

    @app.get("/", response_class=HTMLResponse)
    async def landing(request: Request):
        return await _build_landing_page(request)

    @app.get("/ping")
    async def ping():
        return "PING"

    return app


async def _build_landing_page(request: Request) -> str:
    host = request.headers.get("host", "localhost:5000").split(":")[0]
    registry = request.app.state.registry
    settings = request.app.state.settings
    go2rtc = request.app.state.go2rtc

    rtsp_port = settings.go2rtc_rtsp_port if settings.go2rtc_enabled else 8554
    api_port = settings.go2rtc_api_port if settings.go2rtc_enabled else 1984

    from src.devices.camera import Camera, ALWAYS_ON_STREAM_LIMIT
    cameras = []
    for device in registry.get_all():
        if not isinstance(device, Camera):
            continue
        stream_name = go2rtc._stream_name(device) if go2rtc else device.serial_number
        cameras.append({
            "serial": device.serial_number,
            "name": device.friendly_name or device.serial_number,
            "ip": device.ip,
            "stream_name": stream_name,
            "rtsp_url": f"rtsp://{host}:{rtsp_port}/{stream_name}",
            "streaming": device.is_streaming,
            "always_on": device.always_on,
        })

    camera_rows = ""
    ha_streams = ""
    for cam in cameras:
        status = "streaming" if cam["streaming"] else ("always-on" if cam["always_on"] else "on-demand")
        camera_rows += f"""<tr>
            <td>{cam['name']}</td>
            <td><code>{cam['serial']}</code></td>
            <td><code>{cam['rtsp_url']}</code></td>
            <td>{status}</td>
        </tr>"""
        ha_streams += f"  {cam['stream_name']}:\n    - {cam['rtsp_url']}\n"

    return f"""<!DOCTYPE html>
<html>
<head>
    <title>arlo-cam-api</title>
    <style>
        body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; color: #333; }}
        h1 {{ border-bottom: 2px solid #eee; padding-bottom: 10px; }}
        h2 {{ margin-top: 30px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background: #f5f5f5; }}
        code {{ background: #f0f0f0; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; }}
        pre {{ background: #f5f5f5; padding: 15px; border-radius: 5px; overflow-x: auto; }}
        .links {{ display: flex; gap: 15px; margin: 15px 0; }}
        .links a {{ color: #0066cc; }}
    </style>
</head>
<body>
    <h1>arlo-cam-api</h1>
    <p>{len(cameras)} camera(s) registered.</p>

    <div class="links">
        <a href="/docs">API Documentation (Swagger)</a>
        <a href="http://{host}:{api_port}">go2rtc Web UI</a>
        <a href="/streams">Stream JSON</a>
        <a href="/health">Health</a>
    </div>

    <h2>Cameras</h2>
    <table>
        <tr><th>Name</th><th>Serial</th><th>RTSP URL</th><th>Status</th></tr>
        {camera_rows if camera_rows else '<tr><td colspan="4">No cameras registered yet.</td></tr>'}
    </table>

    <h2>Home Assistant Setup</h2>
    <p>Add to your HA go2rtc configuration:</p>
    <pre>streams:
{ha_streams if ha_streams else '  # No cameras registered yet'}</pre>
    <p>HA's go2rtc integration will auto-create camera entities from these streams.</p>

    <h2>Always-On Streaming (USB-Powered Cameras)</h2>
    <p>For cameras with external power, enable continuous streaming (no wake latency):</p>
    <pre>curl -X POST http://{host}:5000/device/SERIAL/registerset \\
  -H "Content-Type: application/json" \\
  -d '{{"MaxUserStreamTimeLimit": 86400, "MaxStreamTimeLimit": 86400}}'</pre>
    <p>To revert to on-demand mode, set both values to <code>1800</code>.</p>

    <h2>Notes</h2>
    <ul>
        <li>On-demand cameras take 5-60s to start streaming (camera must wake from sleep)</li>
        <li>Always-on cameras stream immediately with no delay</li>
        <li>Consumer-side RTSP transport must be TCP (go2rtc handles this automatically)</li>
        <li>Cameras wake faster with <code>MaxMissedBeaconTime: 10</code> (set via <code>/device/SERIAL/registerset</code>)</li>
    </ul>
</body>
</html>"""
