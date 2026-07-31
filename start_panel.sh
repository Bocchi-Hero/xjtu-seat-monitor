#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
echo "XJTU Seat Monitor panel"
echo "Keep this terminal open."
echo "URL: http://127.0.0.1:18730/"
python3 -c "import flask" 2>/dev/null || pip3 install flask
exec python3 -u panel_app.py
