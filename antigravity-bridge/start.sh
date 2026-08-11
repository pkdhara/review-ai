#!/usr/bin/env bash
# antigravity-bridge startup script

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Check for API key
if [ -z "$GEMINI_API_KEY" ]; then
  echo "ERROR: GEMINI_API_KEY is not set."
  echo ""
  echo "Get your free Gemini API key (uses your Google account quota):"
  echo "  https://aistudio.google.com/app/apikey"
  echo ""
  echo "Then run:"
  echo "  export GEMINI_API_KEY=<your-key>"
  echo "  ./start.sh"
  exit 1
fi

# Install dependencies if needed
if ! python3 -c "import fastapi, google.generativeai" 2>/dev/null; then
  echo "Installing dependencies..."
  pip3 install -r requirements.txt
fi

echo "Starting Antigravity Bridge on http://127.0.0.1:${BRIDGE_PORT:-8899}"
echo "Press Ctrl+C to stop"
echo ""

exec python3 bridge.py
