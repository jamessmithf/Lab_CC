#!/bin/bash
# Start local PARCS cluster with 1 Master and 4 Workers
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Starting PARCS cluster (Master + 4 Workers)..."
docker compose up -d

echo "Waiting for cluster to initialize..."
sleep 3

echo "Querying registered workers:"
curl -s http://localhost:8080/api/worker | jq . 2>/dev/null || curl -s http://localhost:8080/api/worker
echo ""
echo "PARCS Master Web UI is available at: http://localhost:8080"
