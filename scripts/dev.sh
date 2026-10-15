#!/usr/bin/env bash
#
# Start all three AutoParts AI services with one command.
#
#   bash scripts/dev.sh            # start everything
#   bash scripts/dev.sh --setup    # also install deps + build dataset + train
#
# Ctrl-C stops all three (they are started as children of this script).
#
# Ports: vision 8000 · API 4000 · web app 5173
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
LOGDIR="$ROOT/.logs"
mkdir -p "$LOGDIR"

PIDS=()
cleanup() {
  echo
  echo "==> shutting down"
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM

port_busy() {
  "$PY" - "$1" <<'PY' 2>/dev/null
import socket, sys
s = socket.socket(); s.settimeout(0.4)
sys.exit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
PY
}

wait_for() { # port, name, seconds
  local port="$1" name="$2" limit="${3:-40}"
  for _ in $(seq 1 "$limit"); do
    if port_busy "$port"; then echo "    $name ready on :$port"; return 0; fi
    sleep 0.5
  done
  echo "    !! $name did not come up on :$port — see $LOGDIR/" >&2
  return 1
}

# ---------------------------------------------------------------- optional setup
if [[ "${1:-}" == "--setup" ]]; then
  echo "==> installing dependencies"
  ( cd backend  && npm install --no-audit --no-fund )
  ( cd frontend && npm install --no-audit --no-fund )
  "$PY" -c "import fastapi, torch, numpy, PIL" 2>/dev/null || \
    "$PY" -m pip install -r ai-service/requirements.txt
fi

# ---------------------------------------------------------------- preflight
echo "==> preflight"
if ! "$PY" -c "import fastapi, uvicorn" 2>/dev/null; then
  echo "    !! python deps missing. Run:  pip install -r ai-service/requirements.txt" >&2
  echo "       or:  bash scripts/dev.sh --setup" >&2
  exit 1
fi
[ -d backend/node_modules ]  || { echo "    !! backend deps missing. Run: bash scripts/dev.sh --setup" >&2; exit 1; }
[ -d frontend/node_modules ] || { echo "    !! frontend deps missing. Run: bash scripts/dev.sh --setup" >&2; exit 1; }

if [ ! -d data/images ] || [ -z "$(ls -A data/images/*.jpg 2>/dev/null)" ]; then
  echo "    dataset missing — generating a synthetic one so training can run"
  ( cd ai-service && "$PY" -m app.download_images --synthetic --per-class 60 --out ../data/images >/dev/null )
fi
if [ ! -f ai-service/models/part_classifier.pt ]; then
  echo "    no checkpoint — training one (takes a few seconds)"
  ( cd ai-service && "$PY" train/train.py --data data/images --epochs 80 | tail -8 )
fi

# ---------------------------------------------------------------- start
# Skip any service whose port is already taken, so re-running this script is safe
# and it never spawns a duplicate that dies with EADDRINUSE.
start_service() { # <port> <label> <logname> <workdir> <command...>
  local port="$1" label="$2" logname="$3" workdir="$4"; shift 4
  if port_busy "$port"; then
    echo "==> $label (:$port) — already running, leaving it alone"
    return 0
  fi
  echo "==> $label (:$port)"
  ( cd "$workdir" && exec "$@" ) > "$LOGDIR/$logname.log" 2>&1 &
  PIDS+=($!)
}

start_service 8000 "vision service" vision ai-service "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
start_service 4000 "API"            api    backend    node src/server.js
start_service 5173 "web app"        web    frontend   npm run dev

echo
echo "==> waiting for services"
wait_for 8000 "vision service" || true
wait_for 4000 "API"            || true
wait_for 5173 "web app"        || true

echo
cat <<EOF
────────────────────────────────────────────────────────────
  AutoParts AI is up

    Web app          http://localhost:5173      <-- open this
    API              http://localhost:4000/api
    Vision service   http://localhost:8000/docs

  Logs: $LOGDIR/{vision,api,web}.log

  Try it: pick a vehicle (Maruti Suzuki -> Swift -> 2019),
  then either upload a photo or type part number 16510-61A31.

  Ctrl-C to stop everything.
────────────────────────────────────────────────────────────
EOF

wait
