#!/bin/bash
# Trade Journal — Start Script (Mac / Linux)
set -e
cd "$(dirname "$0")"

echo ""
echo "  ╔══════════════════════════════════╗"
echo "  ║     TRADE JOURNAL  v1.0          ║"
echo "  ╚══════════════════════════════════╝"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "  ERROR: Python 3 not found."
    echo "  Install from: https://python.org/downloads"
    read -p "  Press Enter to exit..."
    exit 1
fi

echo "  Python: $(python3 --version)"

# Create venv if needed
if [ ! -d ".venv" ]; then
    echo "  Creating virtual environment (first run only)..."
    python3 -m venv .venv
fi

# Activate
source .venv/bin/activate

# Install dependencies
echo "  Installing/checking dependencies..."
pip install -q -r requirements.txt

echo ""
echo "  ✓ Server starting..."
echo "  ✓ Open your browser and go to:"
echo ""
echo "      http://127.0.0.1:5000"
echo ""
echo "  Press Ctrl+C to stop."
echo ""

# Open browser after 2s
(sleep 2 && open http://127.0.0.1:5000 2>/dev/null || true) &

python3 server.py
