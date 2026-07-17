#!/bin/sh
set -eu
set -f

if [ "$#" -eq 4 ] && [ "$1" = "--relay-media" ]; then
  media_fifo="$2"
  media_prefix="$3"
  media_marker="$4"
  probe_bytes=$((188 * 10))
  exec 3<"$media_fifo"
  dd of="$media_prefix" bs=1 count="$probe_bytes" <&3 2>/dev/null || true
  bytes="$(wc -c <"$media_prefix" | tr -d '[:space:]')"
  cat "$media_prefix"
  if [ "$bytes" -ge "$probe_bytes" ]; then
    printf 1 >"$media_marker"
    cat <&3
  fi
  exec 3<&-
  exit 0
fi

if [ "$#" -ne 3 ]; then
  echo "Usage: $0 SERIAL CAMERA_IP OUTPUT" >&2
  exit 2
fi

if ! command -v setsid >/dev/null 2>&1; then
  echo "setsid is required to isolate the ffmpeg process group" >&2
  exit 2
fi

SERIAL="$1"
CAMERA_IP="$2"
OUTPUT="$3"
API="${ARLO_API_URL:-http://127.0.0.1:5000}"
BATTERY_STREAM_MAX_SECONDS="${ARLO_BATTERY_STREAM_MAX_SECONDS:-180}"
MAX_WAIT=80
RETRY_INTERVAL=10
FFMPEG_STOP_GRACE_SECONDS="${ARLO_FFMPEG_STOP_GRACE_SECONDS:-1}"
MEDIA_START_TIMEOUT_SECONDS="${ARLO_MEDIA_START_TIMEOUT_SECONDS:-15}"
LEASE_RELEASE_ATTEMPTS=3
API_DEADLINE_MARGIN_SECONDS=2

LEASE_ID=""
POWER_MODE=""
LEASE_TTL_SECONDS=""
PING_PID=""
RUNTIME_LIMITER_PID=""
FFMPEG_PID=""
FFMPEG_STOPPER_PID=""
HOLD_PID=""
RELAY_PID=""
MEDIA_FIFO=""
MEDIA_PREFIX=""
MEDIA_MARKER=""
MEDIA_WATCHDOG_PID=""
CLEANUP_STARTED=0
BUDGET_EXPIRED=0
MEDIA_START_FAILED=0
SHUTDOWN_REQUESTED=0

case "$BATTERY_STREAM_MAX_SECONDS" in
  '' | *[!0-9]*)
    echo "ARLO_BATTERY_STREAM_MAX_SECONDS must be an integer between 5 and 3600" >&2
    exit 2
    ;;
esac
if [ "$BATTERY_STREAM_MAX_SECONDS" -lt 5 ] || [ "$BATTERY_STREAM_MAX_SECONDS" -gt 3600 ]; then
  echo "ARLO_BATTERY_STREAM_MAX_SECONDS must be an integer between 5 and 3600" >&2
  exit 2
fi
case "$MEDIA_START_TIMEOUT_SECONDS" in
  '' | *[!0-9]*)
    echo "ARLO_MEDIA_START_TIMEOUT_SECONDS must be an integer between 1 and 60" >&2
    exit 2
    ;;
esac
if [ "$MEDIA_START_TIMEOUT_SECONDS" -lt 1 ] || [ "$MEDIA_START_TIMEOUT_SECONDS" -gt 60 ]; then
  echo "ARLO_MEDIA_START_TIMEOUT_SECONDS must be an integer between 1 and 60" >&2
  exit 2
fi

extract_json_string() {
  printf '%s\n' "$2" \
    | sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p"
}

extract_json_integer() {
  printf '%s\n' "$2" \
    | sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p"
}

release_lease() {
  [ -n "$LEASE_ID" ] || return 0

  attempt=1
  while [ "$attempt" -le "$LEASE_RELEASE_ATTEMPTS" ]; do
    if curl --silent --fail --connect-timeout 1 --max-time 1 \
      --request DELETE "$API/device/$SERIAL/stream/leases/$LEASE_ID" \
      >/dev/null; then
      LEASE_ID=""
      return 0
    fi
    [ "$attempt" -eq "$LEASE_RELEASE_ATTEMPTS" ] || sleep 0.25
    attempt=$((attempt + 1))
  done

  echo "Could not release the stream lease for camera $SERIAL after $LEASE_RELEASE_ATTEMPTS attempts" >&2
}

cleanup() {
  if [ -n "$HOLD_PID" ]; then
    kill "$HOLD_PID" 2>/dev/null || true
    wait "$HOLD_PID" 2>/dev/null || true
    HOLD_PID=""
  fi
  [ "$CLEANUP_STARTED" -eq 0 ] || return 0
  CLEANUP_STARTED=1

  if [ -n "$PING_PID" ]; then
    kill "$PING_PID" 2>/dev/null || true
    wait "$PING_PID" 2>/dev/null || true
    PING_PID=""
  fi
  if [ -n "$RUNTIME_LIMITER_PID" ]; then
    kill "$RUNTIME_LIMITER_PID" 2>/dev/null || true
    wait "$RUNTIME_LIMITER_PID" 2>/dev/null || true
    RUNTIME_LIMITER_PID=""
  fi
  if [ -n "$MEDIA_WATCHDOG_PID" ]; then
    kill "$MEDIA_WATCHDOG_PID" 2>/dev/null || true
    wait "$MEDIA_WATCHDOG_PID" 2>/dev/null || true
    MEDIA_WATCHDOG_PID=""
  fi
  if [ -n "$FFMPEG_PID" ]; then
    kill -TERM "-$FFMPEG_PID" 2>/dev/null || true
    (
      sleep "$FFMPEG_STOP_GRACE_SECONDS"
      kill -KILL "-$FFMPEG_PID" 2>/dev/null || true
    ) &
    FFMPEG_STOPPER_PID=$!
  fi

  release_lease

  if [ -n "$FFMPEG_PID" ]; then
    wait "$FFMPEG_PID" 2>/dev/null || true
    if kill -0 "-$FFMPEG_PID" 2>/dev/null; then
      wait "$FFMPEG_STOPPER_PID" 2>/dev/null || true
    else
      kill "$FFMPEG_STOPPER_PID" 2>/dev/null || true
      wait "$FFMPEG_STOPPER_PID" 2>/dev/null || true
    fi
    FFMPEG_PID=""
    FFMPEG_STOPPER_PID=""
  fi
  if [ -n "$RELAY_PID" ]; then
    kill -TERM "-$RELAY_PID" 2>/dev/null || true
    wait "$RELAY_PID" 2>/dev/null || true
    RELAY_PID=""
  fi
  [ -z "$MEDIA_FIFO" ] || rm -f "$MEDIA_FIFO"
  [ -z "$MEDIA_PREFIX" ] || rm -f "$MEDIA_PREFIX"
  [ -z "$MEDIA_MARKER" ] || rm -f "$MEDIA_MARKER"
}

shutdown() {
  exit_code="$1"
  cleanup
  [ "$SHUTDOWN_REQUESTED" -eq 0 ] || exit_code="$SHUTDOWN_REQUESTED"
  exit "$exit_code"
}

hold_for_go2rtc() {
  while :; do
    sleep 3600 &
    HOLD_PID=$!
    wait "$HOLD_PID" 2>/dev/null || true
    [ "$SHUTDOWN_REQUESTED" -eq 0 ] || exit "$SHUTDOWN_REQUESTED"
    HOLD_PID=""
  done
}

enforce_battery_budget() {
  [ "$BUDGET_EXPIRED" -eq 0 ] || {
    if [ "$OUTPUT" = "-" ] && [ -f "$MEDIA_MARKER" ]; then
      echo "Battery stream budget reached for camera $SERIAL; waiting for go2rtc to close the producer" >&2
      cleanup
      [ "$SHUTDOWN_REQUESTED" -eq 0 ] || exit "$SHUTDOWN_REQUESTED"
      hold_for_go2rtc
    fi
    echo "Battery stream budget reached before camera $SERIAL produced media" >&2
    shutdown 1
  }
}

enforce_media_start_timeout() {
  [ "$MEDIA_START_FAILED" -eq 0 ] || {
    echo "Camera $SERIAL did not produce media within ${MEDIA_START_TIMEOUT_SECONDS}s" >&2
    shutdown 1
  }
}

hold_after_early_battery_stream_end() {
  if [ "$POWER_MODE" = "battery" ] && [ "$OUTPUT" = "-" ] && [ -f "$MEDIA_MARKER" ]; then
    echo "Battery camera $SERIAL ended media before the API budget; waiting for go2rtc to close the producer" >&2
    cleanup
    [ "$SHUTDOWN_REQUESTED" -eq 0 ] || exit "$SHUTDOWN_REQUESTED"
    hold_for_go2rtc
  fi
}

watch_for_media_start() {
  helper_pid=$$
  (
    sleep "$MEDIA_START_TIMEOUT_SECONDS"
    if [ ! -f "$MEDIA_MARKER" ]; then
      kill -USR2 "$helper_pid" 2>/dev/null || true
    fi
  ) &
  MEDIA_WATCHDOG_PID=$!
}

start_media_pipeline() {
  if [ "$OUTPUT" = "-" ]; then
    MEDIA_FIFO="/tmp/arlo-stream-$SERIAL-$$.fifo"
    MEDIA_PREFIX="/tmp/arlo-stream-$SERIAL-$$.prefix"
    MEDIA_MARKER="/tmp/arlo-stream-$SERIAL-$$.media"
    rm -f "$MEDIA_FIFO" "$MEDIA_PREFIX" "$MEDIA_MARKER"
    mkfifo "$MEDIA_FIFO"
    setsid "$0" --relay-media "$MEDIA_FIFO" "$MEDIA_PREFIX" "$MEDIA_MARKER" &
    RELAY_PID=$!
    setsid ffmpeg -hide_banner -loglevel warning -nostdin -y \
      -rtsp_transport udp -i "rtsp://$CAMERA_IP:554/live" \
      -an -c:v copy -f mpegts "$MEDIA_FIFO" &
    FFMPEG_PID=$!
    watch_for_media_start
  else
    setsid ffmpeg -hide_banner -loglevel warning \
      -rtsp_transport udp -i "rtsp://$CAMERA_IP:554/live" \
      -c copy -f rtsp "$OUTPUT" &
    FFMPEG_PID=$!
  fi
}

reset_external_media_pipeline() {
  if [ -n "$MEDIA_WATCHDOG_PID" ]; then
    kill "$MEDIA_WATCHDOG_PID" 2>/dev/null || true
    wait "$MEDIA_WATCHDOG_PID" 2>/dev/null || true
    MEDIA_WATCHDOG_PID=""
  fi
  if [ -n "$RELAY_PID" ]; then
    wait "$RELAY_PID" 2>/dev/null || true
    RELAY_PID=""
  fi
  rm -f "$MEDIA_FIFO" "$MEDIA_PREFIX" "$MEDIA_MARKER"
  MEDIA_FIFO=""
  MEDIA_PREFIX=""
  MEDIA_MARKER=""
  FFMPEG_PID=""
  MEDIA_START_FAILED=0
}

trap cleanup EXIT
trap 'SHUTDOWN_REQUESTED=130; if [ "$CLEANUP_STARTED" -eq 0 ]; then shutdown 130; fi' INT
trap 'SHUTDOWN_REQUESTED=143; if [ "$CLEANUP_STARTED" -eq 0 ]; then shutdown 143; fi' TERM
trap 'BUDGET_EXPIRED=1' USR1
trap 'MEDIA_START_FAILED=1' USR2

if ! response="$(
  curl --silent --fail --connect-timeout 2 --max-time 5 \
    --request POST "$API/device/$SERIAL/stream/leases" \
    --header "Content-Type: application/json" \
    --data "{\"owner\":\"go2rtc\",\"ttl_seconds\":$BATTERY_STREAM_MAX_SECONDS}"
)"; then
  echo "Could not acquire a stream lease for camera $SERIAL" >&2
  exit 1
fi

LEASE_ID="$(extract_json_string lease_id "$response")"
POWER_MODE="$(extract_json_string power_mode "$response")"
LEASE_TTL_SECONDS="$(extract_json_integer lease_ttl_seconds "$response")"
case "$POWER_MODE:$LEASE_ID:$LEASE_TTL_SECONDS" in
  battery:?*:0 | battery:?*:*[!0-9]* | external:?*:0 | external:?*:*[!0-9]*)
    echo "Stream lease response for camera $SERIAL was invalid" >&2
    exit 1
    ;;
  battery:?*:[0-9]* | external:?*:[0-9]*) ;;
  *)
    echo "Stream lease response for camera $SERIAL was invalid" >&2
    exit 1
    ;;
esac

if [ "$POWER_MODE" = "battery" ]; then
  local_budget="$LEASE_TTL_SECONDS"
  if [ "$local_budget" -gt "$API_DEADLINE_MARGIN_SECONDS" ]; then
    local_budget=$((local_budget - API_DEADLINE_MARGIN_SECONDS))
  fi
  helper_pid=$$
  (
    # Stop locally before the API deadline can close the RTSP socket. Otherwise
    # ffmpeg could exit first and make go2rtc reconnect the producer.
    sleep "$local_budget"
    kill -USR1 "$helper_pid" 2>/dev/null || true
  ) &
  RUNTIME_LIMITER_PID=$!
fi

elapsed=0
reachable=0
while [ "$elapsed" -lt "$MAX_WAIT" ]; do
  enforce_battery_budget
  # Ping triggers the AP to buffer a frame and signal the camera via a TIM beacon.
  ping -c 3 -W 1 "$CAMERA_IP" >/dev/null 2>&1 &
  PING_PID=$!

  waited=0
  while [ "$waited" -lt "$RETRY_INTERVAL" ] && [ "$elapsed" -lt "$MAX_WAIT" ]; do
    if nc -z -w 2 "$CAMERA_IP" 554 2>/dev/null; then
      reachable=1
      break
    fi
    sleep 2
    waited=$((waited + 2))
    elapsed=$((elapsed + 2))
    enforce_battery_budget
  done
  kill "$PING_PID" 2>/dev/null || true
  wait "$PING_PID" 2>/dev/null || true
  PING_PID=""
  [ "$reachable" -eq 0 ] || break
done

if [ "$reachable" -eq 0 ]; then
  echo "Camera $SERIAL ($CAMERA_IP) did not become reachable within ${MAX_WAIT}s" >&2
  exit 1
fi
enforce_battery_budget

# A new session gives ffmpeg its own process group so cleanup can stop ffmpeg
# and all descendants without signaling this helper. BusyBox sh cannot enable
# job control without a TTY, so set -m is not reliable inside go2rtc.
start_media_pipeline

while :; do
  ffmpeg_status=0
  wait "$FFMPEG_PID" || ffmpeg_status=$?
  enforce_media_start_timeout
  enforce_battery_budget
  hold_after_early_battery_stream_end

  if [ "$POWER_MODE" != "external" ] || [ "$OUTPUT" != "-" ]; then
    shutdown "$ffmpeg_status"
  fi

  echo "External camera $SERIAL ended media; reconnecting without closing the go2rtc producer" >&2
  reset_external_media_pipeline
  sleep 1
  start_media_pipeline
done
