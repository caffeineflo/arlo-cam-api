# arlo-cam-api

A local base station emulator for Arlo cameras. Lets you use base-station-dependent Arlo cameras (Pro, Pro 2, Ultra, Essential, Doorbells) without Arlo's cloud or a physical base station. Cameras connect via Wi-Fi and stream RTSP locally.

Forked from [brianschrameck/arlo-cam-api](https://github.com/brianschrameck/arlo-cam-api), rebuilt from scratch with:

- Persistent device state (survives restarts)
- Model-aware capability filtering (no more "Ack with Errors" on older cameras)
- Working on-demand RTSP activation
- Stream watchdog (auto-stops orphaned streams to save battery)
- Async architecture (asyncio + FastAPI)
- Health/status monitoring

## Tested Hardware

| Model | Type | Status |
|-------|------|--------|
| VMC3030 | Camera (720p) | Verified |
| VMC4030 | Pro 2 | Expected |
| VMC5040 | Ultra (4K) | Expected |
| VML4030 | Pro 3 Floodlight | Expected |
| FB1001 | Floodlight | Expected |
| AAD1001 | Audio Doorbell | Expected |
| AVD1001 | Video Doorbell | Expected |

## Quick Start

```bash
docker run -d \
  -p 4000:4000 -p 4100:4100 -p 5000:5000 \
  -v ./config.yaml:/app/config.yaml \
  -v ./data:/data \
  caffeineflo/arlo-cam-api:latest
```

Or with compose:

```yaml
services:
  arlo-cam-api:
    image: caffeineflo/arlo-cam-api:latest
    ports:
      - "4000:4000"   # Camera TCP
      - "4100:4100"   # Doorbell TCP
      - "5000:5000"   # REST API
    volumes:
      - ./config.yaml:/app/config.yaml
      - ./data:/data
    restart: unless-stopped
```

## Network Setup

Cameras connect to port 4000 on their default gateway. You need to redirect that traffic to this container. Two options:

### Option A: Container IS the gateway (simplest)

Run this container on the same host that serves as the cameras' default gateway (e.g., the router itself, or a Linux box running dnsmasq for the camera VLAN).

### Option B: NAT redirect (recommended for VLANs)

If cameras are on a separate VLAN, set up DNAT on the gateway to forward port 4000 traffic to the container host:

- **UniFi** (Network 8.3.32+): Settings > Routing > NAT > Create DNAT rule
- **Linux**: `iptables -t nat -A PREROUTING -d <gateway_ip> -p tcp --dport 4000 -j DNAT --to <container_host_ip>`
- **OPNsense/pfSense**: Port forward on the camera VLAN interface

You also need a masquerade/SNAT rule so return traffic from the container reaches cameras through the gateway.

## Pairing Cameras

Cameras must be paired via WPS PBC to a Wi-Fi network with the same SSID and PSK as your production network:

1. Set up hostapd on a Linux box with a compatible Wi-Fi adapter
2. Configure it with your camera SSID + PSK + WPS enabled
3. Run `hostapd_cli wps_pbc`, then press SYNC on the camera
4. Camera pairs in ~15 seconds
5. Stop hostapd - camera reconnects to your production AP automatically

The SSID must match exactly between the pairing AP and the production AP.

## Configuration

Create a `config.yaml`:

```yaml
WifiCountryCode: "US"
VideoAntiFlickerRate: 60
VideoQualityDefault: "insane"

# Notifications
NotifyOnMotionAlert: true
NotifyOnMotionTimeoutAlert: false
NotifyOnAudioAlert: false
NotifyOnButtonPressAlert: true

# Webhooks (leave empty to disable)
MotionRecordingWebHookUrl: ""
StatusUpdateWebHookUrl: ""
RegistrationWebHookUrl: ""
ButtonPressWebHookUrl: ""
MotionTimeoutWebHookUrl: ""
AudioRecordingWebHookUrl: ""

# Optional (shown with defaults)
DatabasePath: "/data/arlo.db"
SnapshotCacheTTL: 300
DeviceOfflineThreshold: 300
WebhookRetries: 3
WebhookTimeout: 5
LogLevel: "INFO"
```

All settings can also be set via environment variables (snake_case, e.g. `VIDEO_QUALITY_DEFAULT=insane`).

## API

### Devices

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/device` | List all registered devices |
| GET | `/device/:serial` | Get device status |
| GET | `/device/:serial/registration` | Get registration data |
| GET | `/device/:serial/desired` | Get stored desired state |
| POST | `/device/:serial/userstreamactive` | Start/stop RTSP stream |
| POST | `/device/:serial/arm` | Arm/disarm motion detection |
| POST | `/device/:serial/quality` | Set video quality preset |
| POST | `/device/:serial/registerset` | Send arbitrary register values |
| POST | `/device/:serial/snapshot` | Request a snapshot |
| POST | `/device/:serial/statusrequest` | Request status update |
| POST | `/device/:serial/streamrefresh` | Reset stream watchdog timer |
| POST | `/device/:serial/friendlyname` | Set display name |
| DELETE | `/device/:serial` | Remove device |

### Snapshots

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/snapshot/:id` | Upload snapshot (camera callback) |
| GET | `/snapshot/:id` | Retrieve cached snapshot |

### Admin

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Ping |
| GET | `/health` | Service health + uptime |
| GET | `/devices/status` | All devices with online/offline state |

### Streaming

```bash
# Start stream
curl -X POST http://localhost:5000/device/SERIAL/userstreamactive \
  -H "Content-Type: application/json" -d '{"active": 1}'

# Stream is now available at rtsp://CAMERA_IP/live (port 554)
# For 4K cameras, use port 555

# Keep stream alive (call every ~30s)
curl -X POST http://localhost:5000/device/SERIAL/streamrefresh

# Stop stream
curl -X POST http://localhost:5000/device/SERIAL/userstreamactive \
  -H "Content-Type: application/json" -d '{"active": 0}'
```

If no refresh is received within 45 seconds, the stream is automatically stopped to preserve battery.

### Webhooks

When configured, the server POSTs JSON to your webhook URLs on camera events:

- **Registration**: camera connected/reconnected
- **Status**: battery, signal, temperature updates
- **Motion**: PIR motion detected (includes zones)
- **Motion timeout**: motion event ended
- **Button press**: doorbell button pressed
- **Audio**: audio alert triggered

## Quality Presets

| Preset | Resolution | Bitrate |
|--------|-----------|---------|
| low | 720p | 400 kbps |
| medium | 1080p | 600 kbps |
| high | 1080p | 1250 kbps |
| subscription | 1080p | 1250 kbps |
| insane | 1080p | 2000 kbps |

Note: VMC3030 maxes out at 720p regardless of setting.

## Desired State

Unlike the original project, this version persists your camera settings. When you set quality, arm state, or send a register set via the API, those values are saved. When a camera reconnects (power cycle, Wi-Fi drop), it automatically receives its stored configuration.

## Development

```bash
pip install ".[dev]"
pytest tests/ -v
```

## License

MIT
