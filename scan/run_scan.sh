#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
python3 scan/aruba_scan.py
echo "Inventory ready at www/data/inventory.json"
