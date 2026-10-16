#!/usr/bin/env bash
#
# Start the AutoParts AI services with one command.
#
#   bash scripts/dev.sh              # start everything
#   bash scripts/dev.sh --setup      # install deps first (no training, no dataset)
#
# Identification runs on the AI provider (Gemini by default). No model training and
# no image dataset are needed. Without an API key the service still starts and falls
# back to the local model, if one happens to be present.
#
# Ports: identification 8000 · API 4000 · web app 5173
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
  "$PY" -c "import fastapi, uvicorn, numpy, PIL" 2>/dev/null || \
    "$PY" -m pip install -r ai-service/requirements.txt
fi

# ---------------------------------------------------------------- preflight
echo "==> preflight"
if ! "$PY" -c "import fastapi, uvicorn, numpy, PIL" 2>/dev/null; then
  echo "    !! python deps missing. Run:  bash scripts/dev.sh --setup" >&2
  exit 1
fi
[ -d backend/node_modules ]  || { echo "    !! backend deps missing. Run: bash scripts/dev.sh --setup" >&2; exit 1; }
[ -d frontend/node_modules ] || { echo "    !! frontend deps missing. Run: bash scripts/dev.sh --setup" >&2; exit 1; }

# Report the identification engine that will actually answer. torch is NOT required.
PROVIDER="${VISION_PROVIDER:-gemini}"
export VISION_PROVIDER="$PROVIDER"

if [ -z "${VISION_API_KEY:-}" ]; then
  case "$PROVIDER" in
    gemini)    VISION_API_KEY="${GEMINI_API_KEY:-${GOOGLE_API_KEY:-}}" ;;
    openai)    VISION_API_KEY="${OPENAI_API_KEY:-}" ;;
    anthropic) VISION_API_KEY="${ANTHROPIC_API_KEY:-}" ;;
  esac
  [ -n "${VISION_API_KEY:-}" ] && export VISION_API_KEY
fi

if [ -n "${VISION_API_KEY:-}" ]; then
  echo "    identification engine : $PROVIDER (API key found)"
elif [ -f ai-service/models/part_classifier.pt ]; then
  echo "    identification engine : local checkpoint (no API key found)"
  echo "                            accurate on test images, WEAK on real photos:"
  echo "                            export VISION_API_KEY=... for proper identification"
else
  echo "    identification engine : none configured"
  echo "                            photo ID will be degraded; the part-number and"
  echo "                            vehicle-fitment paths still work exactly."
  echo "                            To enable: export VISION_API_KEY=your-key"
fi
if ! "$PY" -c "import torch" 2>/dev/null; then
  echo "    note: torch not installed — fine, it is only needed for the"
  echo "          optional local fallback model."
fi

# ---------------------------------------------------------------- start
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

start_service 8000 "identification service" identify ai-service "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
start_service 4000 "API"                    api      backend    node src/server.js
start_service 5173 "web app"                web      frontend   npm run dev

echo
echo "==> waiting for services"
wait_for 8000 "identification service" || true
wait_for 4000 "API"                    || true
wait_for 5173 "web app"                || true

echo
cat <<EOF
────────────────────────────────────────────────────────────
  AutoParts AI is up

    Web app                http://localhost:5173      <-- open this
    API                    http://localhost:4000/api
    Identification service http://localhost:8000/docs

  Logs: $LOGDIR/{identify,api,web}.log

  Try it: pick a vehicle (Maruti Suzuki -> Swift -> 2019),
  then upload a photo, type part number 16510-61A31,
  or describe the part in words.

  No API key yet?  bash scripts/check-gemini.sh  will tell you whether image
  identification will work, rather than leaving you to find out during a demo.

  Ctrl-C to stop everything.
────────────────────────────────────────────────────────────
EOF

wait
