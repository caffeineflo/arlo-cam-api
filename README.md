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

The included `compose.yaml` matches the production dockerhost layout. It expects the dockerhost to own `192.168.40.11` and stores runtime state outside the repository. From the development machine:

```bash
git clone https://github.com/caffeineflo/arlo-cam-api.git
cd arlo-cam-api
ssh Proxmox 'mkdir -p /rpool/dockerfs/arlocam/v2-data /rpool/dockerfs/stacks/arlocam'
ssh Proxmox 'umask 077; { printf "GO2RTC_API_USERNAME=arlo-api\\nGO2RTC_API_PASSWORD="; openssl rand -hex 32; } > /rpool/dockerfs/arlocam/go2rtc.env'
scp compose.yaml stream_helper.sh Proxmox:/rpool/dockerfs/stacks/arlocam/
scp config.yaml Proxmox:/rpool/dockerfs/arlocam/config.yaml
ssh Proxmox 'chmod 0755 /rpool/dockerfs/stacks/arlocam/stream_helper.sh && docker compose -f /rpool/dockerfs/stacks/arlocam/compose.yaml up -d'
```

This starts arlo-cam-api and the pinned go2rtc sidecar. Camera listeners use ports 4000 and 4100. RTSP streams become available at `rtsp://192.168.40.11:8554/<camera_name>` once cameras register. The REST API is not published directly; Traefik exposes it only through `https://arlocam.iflorian.com` with the `chain-local-only` middleware.

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

The checked-in `config.yaml` is the non-secret production baseline:

```yaml
WifiCountryCode: "DE"
VideoAntiFlickerRate: 50
VideoQualityDefault: "high"
NotifyOnMotionAlert: true
NotifyOnMotionTimeoutAlert: false
NotifyOnAudioAlert: false
NotifyOnButtonPressAlert: true
MotionRecordingWebHookUrl: "https://hass.iflorian.com/api/webhook/CHANGE_ME"
DatabasePath: "/data/arlo.db"
Go2RTCEnabled: true
Go2RTCConfigPath: "/data/go2rtc.yaml"
Go2RTCApiUrl: "http://arlo-go2rtc:1984"
```

Copy this file to `/dockerfs/arlocam/config.yaml` before deployment and replace `CHANGE_ME` only in that live copy. Keep credentials and webhook tokens out of the repository. The production Compose file requires `/dockerfs/arlocam/go2rtc.env` with `GO2RTC_API_USERNAME` and `GO2RTC_API_PASSWORD`; startup fails closed if either is absent. Settings can also be set via environment variables using snake case, for example `VIDEO_QUALITY_DEFAULT=high`.

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
| PUT | `/device/:serial/power` | Persist `battery` or `external` power mode |
| POST | `/device/:serial/snapshot` | Request a snapshot |
| POST | `/device/:serial/statusrequest` | Request status update |
| POST | `/device/:serial/streamrefresh` | Reset stream watchdog timer |
| POST | `/device/:serial/stream/leases` | Acquire a bounded stream lease |
| DELETE | `/device/:serial/stream/leases/:lease_id` | Release a stream lease |
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

### Streams

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/streams` | List all streams with RTSP URLs |
| POST | `/streams/reload` | Regenerate go2rtc config and reload |

## go2rtc Integration

The recommended deployment uses go2rtc as a sidecar container that provides stable RTSP URLs for consumers (Home Assistant, Frigate, etc.). Consumers connect to go2rtc, which handles camera wake-up, stream activation, and keepalives automatically.

### Deployment

Use the included `compose.yaml`:

```bash
docker compose up -d
```

This starts:

- **arlo-cam-api** with camera TCP on port 4000 and doorbell TCP on port 4100. Its REST API remains inside Docker and is reachable externally only through local-only Traefik.
- **go2rtc 1.9.14** with RTSP on `192.168.40.11:8554`. Its HTTP API is not published directly. The image is pinned by tag and multi-platform digest.

The containers share Compose's private default network and communicate through Docker DNS:

- arlo-cam-api reaches go2rtc at `http://arlo-go2rtc:1984`
- go2rtc reaches arlo-cam-api at `http://arlo-cam-api:5000`

Both containers join the private default network. go2rtc also joins `web` only for the local-only, HTTPS `/go2rtc/` route. Native Basic auth protects every go2rtc HTTP endpoint, `local_auth` prevents Docker-network bypass, and `exec.allow_paths` limits commands to `/app/stream_helper.sh`. WebRTC port 8555 is not published.

For non-compose deployments, keep the default localhost behavior or set:

```yaml
Go2RTCApiUrl: "http://arlo-go2rtc:1984"
```

And pass the API URL to the go2rtc helper:

```bash
ARLO_API_URL=http://arlo-cam-api:5000
```

### Consuming Streams

Once deployed, streams are available at:

```
rtsp://192.168.40.11:8554/<stream_name>
```

Discover available streams:

```bash
curl https://arlocam.iflorian.com/streams
```

The go2rtc API is available to authenticated local clients at `https://arlocam.iflorian.com/go2rtc/`. Read the username and password from the protected live environment file and use HTTP Basic auth. Traefik supplies TLS and the existing `chain-local-only` network boundary; unauthenticated requests return 401.

### How It Works

When a consumer connects to an RTSP stream:

1. go2rtc runs `stream_helper.sh` which pings the camera (triggering AP power-save wake via 802.11 TIM)
2. Acquires a bounded API lease and sends a stream command when the model supports it
3. Waits up to 80 seconds for the camera's RTSP server to come online
4. Relays MPEG-TS to go2rtc over the helper's stdout pipe

Cameras in battery mode sleep between viewer sessions. Externally powered cameras remain available continuously.

### Power Profiles

Power source is persisted explicitly as `battery` or `external`. A legacy camera without a stored mode defaults to `battery`, which is the safe failure mode. An external camera becomes always-on only when its mode is `external` and both `MaxUserStreamTimeLimit` and `MaxStreamTimeLimit` are at least 86400.

The production assignments are:

| Camera | Serial | Power mode | Stream policy |
|--------|--------|------------|---------------|
| Front Entrance | `4N72777366D7B` | battery | On-demand, 30-second user/motion limit, 180-second general ceiling |
| Garden Right | `4N72777560C4E` | external | Always-on |
| House Right Side | `4N72777Y669BB` | external | Always-on |
| Garden Left | `4N72777V66D82` | external | Always-on |
| Front Left | `4N72777H60692` | external | Always-on |
| Front Right | `4N72777B5E401` | external | Always-on |

Apply Front Entrance's battery-safe stream profile atomically, then set its sensitivity and quality:

```bash
api=https://arlocam.iflorian.com
serial=4N72777366D7B

curl --fail-with-body -X PUT "$api/device/$serial/power" \
  -H 'Content-Type: application/json' \
  -d '{"mode":"battery"}'
curl --fail-with-body -X POST "$api/device/$serial/registerset" \
  -H 'Content-Type: application/json' \
  -d '{"PIRStartSensitivity":80}'
curl --fail-with-body -X POST "$api/device/$serial/quality" \
  -H 'Content-Type: application/json' \
  -d '{"quality":"low"}'
```

Apply each external-power profile atomically:

```bash
api=https://arlocam.iflorian.com

for serial in \
  4N72777560C4E \
  4N72777Y669BB \
  4N72777V66D82 \
  4N72777H60692 \
  4N72777B5E401
do
  curl --fail-with-body -X PUT "$api/device/$serial/power" \
    -H 'Content-Type: application/json' \
    -d '{"mode":"external"}'
done
```

`GET /device/:serial/desired` reports the stored and effective power mode. Do not infer battery safety from stream-limit values alone. Direct `/arm` or `/registerset` calls that conflict with the active profile return HTTP 400; older two-step power-profile scripts must migrate to the single `PUT /power` operation.

### Front Entrance Consumer Rules

Front Entrance must remain on-demand across every consumer:

- Keep Scrypted Rebroadcast and Prebuffer disabled.
- On the existing `Arlo Front Door AEEC` accessory, set Snapshot's `Disable Snapshot` option. Do not delete, recreate, or re-pair the accessory; preserving its Scrypted device and HomeKit pairing preserves Apple Home identity and client-side metadata.
- Do not add Front Entrance to HA's HomeKit bridge or any persistent go2rtc consumer.
- Do not leave an auto-refreshing camera dashboard open. A viewer or snapshot request is a real wake-up.
- Keep motion clips to 15-20 seconds. The HA recording automation owns clip duration; the API power profile only bounds the underlying stream.
- Use a stream lease for every recording or live-view session and release it in cleanup. The TTL is the final safety net if a consumer crashes.

The API enforces one shared 180-second session budget for a battery camera, regardless of how many leases or go2rtc producer reconnects occur. The camera profile separately caps user and motion streams at 30 seconds, which covers the 20-second recording while returning the radio to sleep sooner. `MaxStreamTimeLimit` remains 180 because VMC3030 rejects lower values. After the API budget or the final lease ends, a 30-second cooldown rejects new leases with HTTP 429 and `Retry-After`. This prevents a persistent consumer from chaining helper processes into an unlimited battery session.

VMC3030 firmware rejects the `UserStreamActive` register. The API detects that exact response, stops retrying the unsupported command, and relies on the RTSP producer lifetime plus the camera's hardware limits. Use `go2rtc_producer_active` from `/devices/status` as the authoritative live-stream state.

## Home Assistant Integration

Add the RTSP streams to HA's go2rtc configuration:

```yaml
# /config/go2rtc.yaml (or via go2rtc addon config)
streams:
  front_entrance:
    - rtsp://192.168.40.11:8554/front_entrance
  front_right:
    - rtsp://192.168.40.11:8554/front_right
  garden_left:
    - rtsp://192.168.40.11:8554/garden_left
```

HA's built-in go2rtc handles buffering and serves WebRTC/HLS to dashboards. The go2rtc integration auto-creates camera entities from these streams.

**Important notes for HA:**

- Consumer-side RTSP transport must be TCP (go2rtc handles this automatically)
- On-demand cameras take 5-60s to start on first viewer connect
- Always-on cameras are instant
- Use the authenticated `https://arlocam.iflorian.com/go2rtc/api/streams` endpoint to verify actual producers and consumers
- A visible live card can keep Front Entrance awake; do not use preload or automatic refresh for that camera
- Battery, PIR-count, streamed-seconds, failed-stream, lease, cooldown, and actual go2rtc state sensors should read `/devices/status` instead of polling the physical camera

### Streaming (Low-Level API)

For direct stream control without go2rtc, acquire a bounded lease. Multiple consumers can hold independent leases; the camera stops only after the final lease is released or expires.

```bash
api=https://arlocam.iflorian.com
serial=SERIAL

curl --fail-with-body -X POST "$api/device/$serial/stream/leases" \
  -H 'Content-Type: application/json' \
  -d '{"owner":"manual-view","ttl_seconds":180}'

# The response contains the lease_id. Release that same ID in cleanup.
lease_id=RETURNED_LEASE_ID
curl --fail-with-body -X DELETE \
  "$api/device/$serial/stream/leases/$lease_id"
```

The TTL must cover expected startup and use but remain bounded. It prevents a crashed consumer from holding a battery camera indefinitely. Consumers should always release their lease in a `finally` block or equivalent cleanup path.

The legacy `/userstreamactive` and `/streamrefresh` endpoints remain available for compatibility, but new integrations should use leases so overlapping consumers cannot stop one another.

### Webhooks

When configured, the server POSTs JSON to your webhook URLs on camera events:

- **Registration**: camera connected/reconnected
- **Status**: battery, signal, temperature updates
- **Motion**: PIR motion detected (includes zones)
- **Motion timeout**: motion event ended
- **Button press**: doorbell button pressed
- **Audio**: audio alert triggered

Webhook consumers should treat the event type as the webhook URL contract, not as a guaranteed payload field. For example, `MotionRecordingWebHookUrl` receives motion events; the payload does not include `alert_type`.

#### Motion webhook payload

`MotionRecordingWebHookUrl` receives this JSON shape:

```json
{
  "ip": "192.168.4.8",
  "friendly_name": "Front Entrance",
  "hostname": "VMC3030-66D7B",
  "serial_number": "4N72777366D7B",
  "zone": [],
  "file_name": "",
  "time": 1780233785.7613697
}
```

Use `serial_number` as the stable camera identifier. Do not key consumers on `serial` or `alert_type`; those fields are not emitted by the motion webhook.

#### Home Assistant webhook example

```yaml
- id: arlo_motion_webhook
  alias: Arlo Motion Webhook
  mode: parallel
  triggers:
    - trigger: webhook
      webhook_id: CHANGE_ME
      allowed_methods: [POST]
      local_only: true
  variables:
    serial: "{{ trigger.json.serial_number | default('') }}"
    timer_entity: >-
      {{ {
        '4N72777366D7B': 'timer.arlo_front_entrance_motion'
      }.get(serial, '') }}
  conditions:
    - condition: template
      value_template: "{{ timer_entity != '' }}"
  actions:
    - action: timer.start
      target:
        entity_id: "{{ timer_entity }}"
      data:
        duration: "00:01:00"
```

For motion recording, battery-powered cameras need an explicit stream lifecycle around the recording:

1. POST `/device/:serial/stream/leases` with a stable owner name and bounded TTL.
2. Wait for the camera stream to wake.
3. Record with Basic auth from `https://arlocam.iflorian.com/go2rtc/api/stream.mp4?src=<stream_name>`.
4. DELETE `/device/:serial/stream/leases/:lease_id` in cleanup after recording completes.

Externally powered always-on cameras do not need this wake/stop wrapper when their explicit mode is `external` and both stream limits are at least 86400.

## UniFi Protect / ONVIF

`compose.protect-onvif.yaml` is an optional topology for ONVIF discovery. go2rtc uses host networking so WS-Discovery can reach UniFi Protect, but the REST API still is not published on port 5000. The host-networked helper calls `https://arlocam.iflorian.com`, which retains the local-only Traefik boundary. arlo-cam-api reaches host-networked go2rtc through the `arlo-go2rtc:host-gateway` mapping.

Host networking exposes go2rtc's enabled listeners on the dockerhost. Use this topology only when ONVIF discovery is required and firewall those listeners to trusted camera and management networks. The default production `compose.yaml` is narrower and intentionally omits ONVIF/WebRTC port 8555.

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
ruff check .
pytest tests/ -v
```

## CI and Deployment

Pull requests and pushes to `main` run Ruff and pytest with read-only repository permissions. A push to `main` builds and publishes multi-platform GHCR images only after that test job passes. It publishes both `latest` and the immutable commit SHA.

For a controlled rollout, wait for CI to finish and deploy the immutable SHA first:

```bash
cd /rpool/dockerfs/stacks/arlocam
export ARLO_CAM_API_IMAGE=ghcr.io/caffeineflo/arlo-cam-api:GITHUB_COMMIT_SHA
docker compose pull arlo-cam-api
docker compose up -d --no-deps arlo-cam-api
docker compose up -d --no-deps --force-recreate go2rtc
docker compose ps
curl --fail-with-body https://arlocam.iflorian.com/health
```

Recreating go2rtc is required on this first rollout so it loads the newly generated authenticated config and the updated stdout-pipe helper. Verify that unauthenticated go2rtc HTTP requests return 401, authenticated requests succeed through the local-only HTTPS route, Front Entrance is `battery` with user/general limits `30/180`, and the five USB cameras are `external` with `86400/86400`. Then verify camera registration, stream process counts, and Front Entrance sleep behavior before allowing automation to follow `latest`. To roll back, repeat the same commands with the last known-good SHA tag. Do not build or copy an unverified local working tree onto the dockerhost.

## License

MIT
