#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
else
  printf "Missing .env file. Create it from .env.example first.\n"
  exit 1
fi

"$ROOT_DIR/scripts/checks.sh"

if [[ ! -d "$ROOT_DIR/f1-stream/node_modules" ]]; then
  printf "Installing stream dependencies (npm ci --prefix f1-stream)...\n"
  npm ci --prefix "$ROOT_DIR/f1-stream"
fi

STREAM_HOST="${STREAM_HOST:-127.0.0.1}"
STREAM_PORT="${STREAM_PORT:-5173}"
STREAM_URL="${STREAM_URL:-http://${STREAM_HOST}:${STREAM_PORT}}"
STREAM_CMD="${STREAM_CMD:-npm run dev --prefix f1-stream -- --host ${STREAM_HOST} --port ${STREAM_PORT}}"

stream_pid=""
agent_pid=""

cleanup() {
  local pids_to_kill=()
  if [[ -n "$agent_pid" ]] && kill -0 "$agent_pid" >/dev/null 2>&1; then
    pids_to_kill+=("agent:$agent_pid")
  fi
  if [[ -n "$stream_pid" ]] && kill -0 "$stream_pid" >/dev/null 2>&1; then
    pids_to_kill+=("stream:$stream_pid")
  fi
  if [[ ${#pids_to_kill[@]} -gt 0 ]]; then
    printf "Stopping remaining processes: %s\n" "${pids_to_kill[*]}"
  fi
  for entry in "${pids_to_kill[@]}"; do
    kill "${entry#*:}" >/dev/null 2>&1 || true
  done
}

trap cleanup EXIT INT TERM

printf "Starting replay stream: %s\n" "$STREAM_CMD"
bash -lc "$STREAM_CMD" &
stream_pid=$!

printf "Waiting for stream at %s ...\n" "$STREAM_URL"
for _ in {1..45}; do
  if curl -fsS "$STREAM_URL" >/dev/null 2>&1; then
    printf "Stream is up.\n"
    break
  fi
  sleep 1
done

if ! curl -fsS "$STREAM_URL" >/dev/null 2>&1; then
  printf "Stream did not become reachable at %s\n" "$STREAM_URL"
  exit 1
fi

printf "Starting agent loop: %s\n" "$AGENT_LOOP_CMD"
bash -lc "$AGENT_LOOP_CMD" &
agent_pid=$!

wait -n "$stream_pid" "$agent_pid" && exit_code=0 || exit_code=$?

stream_alive=true
agent_alive=true
kill -0 "$stream_pid" >/dev/null 2>&1 || stream_alive=false
kill -0 "$agent_pid"  >/dev/null 2>&1 || agent_alive=false

if [[ "$stream_alive" == false ]]; then
  printf "ERROR: Stream process (PID %s) exited unexpectedly (exit code %s). Shutting down.\n" \
    "$stream_pid" "$exit_code"
  exit 1
fi

if [[ "$agent_alive" == false ]]; then
  printf "Agent (PID %s) exited with code %s.\n" "$agent_pid" "$exit_code"
  exit "$exit_code"
fi

printf "WARNING: wait -n returned but both processes still running. Re-waiting.\n"
wait -n "$stream_pid" "$agent_pid" && exit_code=0 || exit_code=$?
kill -0 "$stream_pid" >/dev/null 2>&1 || {
  printf "ERROR: Stream process (PID %s) exited unexpectedly (exit code %s). Shutting down.\n" \
    "$stream_pid" "$exit_code"
  exit 1
}
printf "Agent (PID %s) exited with code %s.\n" "$agent_pid" "$exit_code"
exit "$exit_code"
