#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/resources/python-runtime"
BROWSERS_DIR="$ROOT_DIR/resources/ms-playwright"
PYTHON_BIN="${PYTHON_BIN:-python3}"

PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_MAJOR="$("$PYTHON_BIN" -c 'import sys; print(sys.version_info.major)')"
PY_MINOR="$("$PYTHON_BIN" -c 'import sys; print(sys.version_info.minor)')"
if (( PY_MAJOR != 3 || PY_MINOR < 10 )); then
  echo "Expected Python >= 3.10, got $PY_VERSION from $PYTHON_BIN" >&2
  echo "Install a supported Python or run with PYTHON_BIN=/path/to/python3" >&2
  exit 1
fi

rm -rf "$RUNTIME_DIR"
mkdir -p "$ROOT_DIR/resources"
"$PYTHON_BIN" -m venv --copies "$RUNTIME_DIR"

"$RUNTIME_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
"$RUNTIME_DIR/bin/python" -m pip install -r "$ROOT_DIR/python/requirements.txt"

rm -rf "$BROWSERS_DIR"
PLAYWRIGHT_BROWSERS_PATH="$BROWSERS_DIR" "$RUNTIME_DIR/bin/python" -m playwright install chromium

"$RUNTIME_DIR/bin/python" - <<'PY'
import importlib.util
import platform
import sys

required = ["playwright", "greenlet", "httpx", "cryptography", "Crypto", "cv2", "numpy", "openpyxl"]
missing = [name for name in required if importlib.util.find_spec(name) is None]
if missing:
    raise SystemExit(f"Missing packaged modules: {', '.join(missing)}")

import greenlet

print("Python runtime ready")
print("executable:", sys.executable)
print("version:", sys.version.split()[0])
print("machine:", platform.machine())
print("greenlet:", greenlet.__file__)
PY
