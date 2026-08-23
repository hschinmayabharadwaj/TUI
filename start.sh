#!/bin/bash
# Launch the ESP32 btop-style serial monitor
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# shellcheck disable=SC1091
source venv/bin/activate

python - <<'PY' || pip install -q -r requirements.txt
import rich, serial
PY

echo "Serial ports:"
python esp32_tui.py --list-ports || true
echo
echo "Starting monitor (auto-detect port, 115200 baud)..."
exec python esp32_tui.py "$@"
