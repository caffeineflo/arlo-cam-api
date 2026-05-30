#!/bin/sh
SERIAL="$1"
CAMERA_IP="$2"
OUTPUT="$3"
API="${ARLO_API_URL:-http://127.0.0.1:5000}"
MAX_WAIT=80
RETRY_INTERVAL=10

cleanup() {
  kill $KEEPALIVE 2>/dev/null
  curl -sf -X POST "$API/device/$SERIAL/userstreamactive" \
    -H "Content-Type: application/json" -d '{"active":0}' >/dev/null || true
}
trap cleanup EXIT INT TERM

elapsed=0
while [ $elapsed -lt $MAX_WAIT ]; do
  # Ping triggers AP to buffer frame and signal camera via TIM beacon
  ping -c 3 -W 1 "$CAMERA_IP" >/dev/null 2>&1 &

  curl -sf -X POST "$API/device/$SERIAL/userstreamactive" \
    -H "Content-Type: application/json" -d '{"active":1}' >/dev/null

  waited=0
  while [ $waited -lt $RETRY_INTERVAL ] && [ $elapsed -lt $MAX_WAIT ]; do
    if nc -z -w 2 "$CAMERA_IP" 554 2>/dev/null; then
      break 2
    fi
    sleep 2
    waited=$((waited + 2))
    elapsed=$((elapsed + 2))
  done
done

if ! nc -z -w 2 "$CAMERA_IP" 554 2>/dev/null; then
  echo "Camera $SERIAL ($CAMERA_IP) did not become reachable within ${MAX_WAIT}s" >&2
  exit 1
fi

(while true; do
  sleep 30
  curl -sf -X POST "$API/device/$SERIAL/streamrefresh" >/dev/null
done) &
KEEPALIVE=$!

exec ffmpeg -hide_banner -loglevel warning \
  -rtsp_transport udp -i "rtsp://$CAMERA_IP:554/live" \
  -c copy -f rtsp "$OUTPUT"
