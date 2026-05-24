#!/bin/sh
SERIAL="$1"
CAMERA_IP="$2"
OUTPUT="$3"
API="http://127.0.0.1:5000"

curl -sf -X POST "$API/device/$SERIAL/userstreamactive" \
  -H "Content-Type: application/json" -d '{"active":1}' >/dev/null

(while true; do
  sleep 30
  curl -sf -X POST "$API/device/$SERIAL/streamrefresh" >/dev/null
done) &
KEEPALIVE=$!

cleanup() {
  kill $KEEPALIVE 2>/dev/null
  curl -sf -X POST "$API/device/$SERIAL/userstreamactive" \
    -H "Content-Type: application/json" -d '{"active":0}' >/dev/null || true
}
trap cleanup EXIT INT TERM

exec ffmpeg -hide_banner -loglevel warning \
  -rtsp_transport udp -i "rtsp://$CAMERA_IP:554/live" \
  -c copy -f rtsp "$OUTPUT"
