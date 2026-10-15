#!/usr/bin/env bash
#
# Run every check in the project.
#
#   bash scripts/test.sh              # all suites
#   bash scripts/test.sh --offline    # skip the suites that need running services
#
# Suites:
#   1. ai-service/tests/test_cloud_vision.py   no services needed, no network needed
#   2. scripts/verify.sh                       needs the API :4000 and vision :8000
#
# Start the services first with `bash scripts/dev.sh` if the second suite should run.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
FAILED=0

port_busy() {
  "$PY" - "$1" <<'PY' 2>/dev/null
import socket, sys
s = socket.socket(); s.settimeout(0.4)
sys.exit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
PY
}

echo "════════════════════════════════════════════════════════"
echo " 1. Cloud vision provider (unit)"
echo "════════════════════════════════════════════════════════"
if "$PY" ai-service/tests/test_cloud_vision.py; then
  echo "  -> suite passed"
else
  echo "  -> suite FAILED"; FAILED=1
fi

echo
echo "════════════════════════════════════════════════════════"
echo " 2. Acceptance checks (integration)"
echo "════════════════════════════════════════════════════════"
if [[ "${1:-}" == "--offline" ]]; then
  echo "  skipped (--offline)"
elif port_busy 4000 && port_busy 8000; then
  if bash scripts/verify.sh; then
    echo "  -> suite passed"
  else
    echo "  -> suite FAILED"; FAILED=1
  fi
else
  echo "  SKIPPED — services not running on :4000 and :8000."
  echo "  Start them with:  bash scripts/dev.sh"
fi

echo
echo "════════════════════════════════════════════════════════"
if [ "$FAILED" -eq 0 ]; then
  echo " ALL SUITES PASSED"
else
  echo " SOME SUITES FAILED"
fi
echo "════════════════════════════════════════════════════════"
exit "$FAILED"
