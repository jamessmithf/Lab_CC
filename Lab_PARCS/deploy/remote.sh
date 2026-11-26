#!/usr/bin/env bash
# ==============================================================================
# remote.sh - Runs ON THE MASTER VM (invoked over SSH by 05_gcp_run_benchmark.py
#             or manually) to execute driver.py INSIDE the parcs-master container.
#
# Usage:
#   sudo bash lab/remote.sh start [SIZES] [RUNS] [WORKERS]
#   sudo bash lab/remote.sh status
#   sudo bash lab/remote.sh collect
# ==============================================================================
set -euo pipefail

LAB="$(cd "$(dirname "$0")" && pwd)"
CMD="${1:-status}"

# Auto-detect PARCS master container name
CONTAINER="parcs-master"
if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    if docker ps --format '{{.Names}}' | grep -qx "parcs"; then
        CONTAINER="parcs"
    fi
fi

driver_running() {
    docker exec "$CONTAINER" sh -c 'for p in /proc/[0-9]*; do tr "\0" " " < "$p/cmdline" 2>/dev/null | grep -q "[d]river[.]py" && exit 0; done; exit 1'
}

case "$CMD" in
start)
    SIZES="${2:-10000000,25000000,50000000,100000000}"
    RUNS="${3:-3}"
    WORKERS="${4:-1,2,3,4}"

    if driver_running; then
        echo "driver is already running - wait for it to finish (status) before starting a new run"
        exit 1
    fi

    docker exec "$CONTAINER" rm -rf /lab
    docker cp "$LAB/src" "$CONTAINER:/lab"
    docker exec "$CONTAINER" rm -rf /lab/results /lab/driver.log /lab/__pycache__
    docker exec -d "$CONTAINER" sh -c \
        "cd /lab && python driver.py --sizes $SIZES --runs $RUNS --workers $WORKERS --out /lab/results > /lab/driver.log 2>&1"
    sleep 3
    echo "driver started inside $CONTAINER: sizes=$SIZES runs=$RUNS workers=$WORKERS"
    docker exec "$CONTAINER" sh -c 'tail -n 5 /lab/results/progress.log 2>/dev/null; tail -n 5 /lab/driver.log 2>/dev/null' || true
    ;;
status)
    if docker exec "$CONTAINER" test -f /lab/results/DONE; then
        echo "STATE: DONE"
    elif docker exec "$CONTAINER" test -f /lab/results/FAILED; then
        echo "STATE: FAILED"
        docker exec "$CONTAINER" tail -n 20 /lab/driver.log || true
    elif driver_running; then
        echo "STATE: RUNNING"
    else
        echo "STATE: FAILED (driver is not running and did not finish)"
        docker exec "$CONTAINER" tail -n 20 /lab/driver.log || true
    fi
    docker exec "$CONTAINER" tail -n 15 /lab/results/progress.log 2>/dev/null || true
    ;;
collect)
    rm -rf "$LAB/results"
    docker cp "$CONTAINER:/lab/results" "$LAB/results"
    docker cp "$CONTAINER:/lab/driver.log" "$LAB/results/driver.log" 2>/dev/null || true
    docker logs "$CONTAINER" > "$LAB/results/parcs-master.log" 2>&1 || true
    chown -R "${SUDO_USER:-$(id -un)}" "$LAB/results"
    echo "collected: $(ls "$LAB/results" | tr '\n' ' ')"
    ;;
*)
    echo "Unknown command: $CMD (expected: start | status | collect)"
    exit 1
    ;;
esac
