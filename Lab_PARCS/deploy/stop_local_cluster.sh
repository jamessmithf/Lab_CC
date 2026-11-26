#!/bin/bash
# Stop and remove local PARCS cluster containers
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Stopping and tearing down PARCS Docker cluster..."
docker compose down -v
echo "PARCS cluster stopped."
