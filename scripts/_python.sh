# Resolve a Python 3 interpreter for the bash scripts.
#
# Linux/macOS usually provide `python3`; Windows Python commonly provides
# `python` and/or the `py` launcher instead. The Windows Store alias can exist
# on PATH even when no interpreter is installed, so a command's mere presence
# is not enough — execute a tiny Python statement before choosing it.
#
# Set PYTHON to an executable name/path to override auto-detection, for example:
#   PYTHON=python bash scripts/check-gemini.sh
#
# This file is sourced by the other scripts after they enter the repository root.
# PY_ARGS is deliberately kept separate so the Windows launcher can be invoked
# as `py -3` without putting a space in the executable name.

PY_ARGS=()

if [ -n "${PYTHON:-}" ]; then
  PY="$PYTHON"
  if ! "$PY" "${PY_ARGS[@]}" -c 'import sys; assert sys.version_info.major == 3' >/dev/null 2>&1; then
    echo "ERROR: PYTHON=$PY is not a working Python 3 interpreter." >&2
    echo "       Use PYTHON=python on Windows, or unset PYTHON to auto-detect." >&2
    exit 1
  fi
elif command -v python3 >/dev/null 2>&1 && \
    python3 -c 'import sys; assert sys.version_info.major == 3' >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1 && \
    python -c 'import sys; assert sys.version_info.major == 3' >/dev/null 2>&1; then
  PY=python
elif command -v py >/dev/null 2>&1 && \
    py -3 -c 'import sys; assert sys.version_info.major == 3' >/dev/null 2>&1; then
  PY=py
  PY_ARGS=(-3)
else
  cat >&2 <<'EOF'
ERROR: No working Python 3 interpreter was found.

The scripts tried python3, python, and the Windows py launcher. If Python is
installed but not on PATH, either reopen the terminal after enabling "Add
python.exe to PATH", or point the scripts at it explicitly:

  Windows / Git Bash:   PYTHON=python bash scripts/check-gemini.sh
  Windows / PowerShell: $env:PYTHON="python"; bash scripts/check-gemini.sh

Install Python 3 from https://www.python.org/downloads/ if needed.
EOF
  exit 1
fi

export PY
