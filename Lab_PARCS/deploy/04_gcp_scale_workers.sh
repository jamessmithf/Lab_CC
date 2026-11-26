#!/usr/bin/env bash
# ==============================================================================
# 04_gcp_scale_workers.sh - Provision and Scale Worker VMs in GCP
#
# Passes master internal IP via instance metadata ('parcs-master-ip'), applies
# scoped COS iptables rules, and adds an 8-hour auto-delete safety guard.
# ==============================================================================
set -euo pipefail

if [ -d "$HOME/google-cloud-sdk/bin" ]; then
    export PATH="$HOME/google-cloud-sdk/bin:$PATH"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLUSTER_ENV="$SCRIPT_DIR/gcp_cluster_info.env"

if [ -f "$CLUSTER_ENV" ]; then
    # shellcheck disable=SC1090
    source "$CLUSTER_ENV"
fi

if [ -z "${MASTER_INTERNAL_IP:-}" ]; then
    echo "[ERROR] MASTER_INTERNAL_IP is not set. Run 03_gcp_deploy_master.sh first."
    exit 1
fi

TARGET_COUNT="${1:-4}"
MACHINE_TYPE="${2:-${GCP_MACHINE_TYPE:-n1-standard-1}}"
MAX_RUN_HOURS="${GCP_MAX_RUN_HOURS:-8}"
DISK_SIZE_GB="${GCP_DISK_SIZE_GB:-10}"
ZONE="${GCP_ZONE:-$(gcloud config get-value compute/zone 2>/dev/null || echo europe-north1-b)}"
ZONE_FLAG=(--zone="$ZONE")

echo "======================================================================"
echo " Scaling PARCS Workers on GCP to $TARGET_COUNT instance(s)"
echo " Master Internal IP: $MASTER_INTERNAL_IP | Machine: $MACHINE_TYPE"
echo " Zone: $ZONE | Disk: ${DISK_SIZE_GB}GB | Auto-Delete: ${MAX_RUN_HOURS}h"
echo "======================================================================"

WORKER_NAMES=()
for ((i=1; i<=TARGET_COUNT; i++)); do
    WORKER_NAMES+=("worker${i}")
done

CREATE_LIST=()
for w in "${WORKER_NAMES[@]}"; do
    if gcloud compute instances describe "$w" "${ZONE_FLAG[@]}" &>/dev/null; then
        echo "[INFO] Worker '$w' already exists and is active."
    else
        CREATE_LIST+=("$w")
    fi
done

if [ ${#CREATE_LIST[@]} -gt 0 ]; then
    echo "[INFO] Creating ${#CREATE_LIST[@]} worker instance(s): ${CREATE_LIST[*]} ..."
    WORKER_STARTUP_SCRIPT=$(cat <<'EOF'
#!/bin/bash
iptables -w -C INPUT -p tcp --dport 8080 -j ACCEPT 2>/dev/null || iptables -w -I INPUT -p tcp --dport 8080 -j ACCEPT
iptables -w -C INPUT -s 10.0.0.0/8 -j ACCEPT 2>/dev/null || iptables -w -I INPUT -s 10.0.0.0/8 -j ACCEPT

MD="http://metadata.google.internal/computeMetadata/v1/instance/attributes"
until MASTER_IP="$(curl -sf -H 'Metadata-Flavor: Google' "$MD/parcs-master-ip")" && [ -n "$MASTER_IP" ]; do
    sleep 2
done

while ! docker info >/dev/null 2>&1; do
    sleep 1
done

until docker pull hummer12007/parcs-node:latest; do
    sleep 5
done

docker rm -f parcs-worker >/dev/null 2>&1 || true
docker run -d --name parcs-worker --network host --restart unless-stopped \
    -e "PARCS_ARGS=worker $MASTER_IP" hummer12007/parcs-node:latest
EOF
)
    gcloud compute instances create "${CREATE_LIST[@]}" \
        "${ZONE_FLAG[@]}" \
        --image-family="cos-stable" \
        --image-project="cos-cloud" \
        --machine-type="$MACHINE_TYPE" \
        --tags="parcs-node,parcs-worker" \
        --boot-disk-size="${DISK_SIZE_GB}GB" \
        --boot-disk-type="pd-standard" \
        --max-run-duration="${MAX_RUN_HOURS}h" \
        --instance-termination-action="DELETE" \
        --metadata="parcs-master-ip=$MASTER_INTERNAL_IP,startup-script=$WORKER_STARTUP_SCRIPT"
else
    echo "[INFO] All $TARGET_COUNT target workers are already provisioned."
fi

echo ""
echo "======================================================================"
echo " Current GCP Compute Engine Instances:"
echo "======================================================================"
gcloud compute instances list --format="table(name,zone,machineType.basename(),INTERNAL_IP,EXTERNAL_IP,status)"

# Verify worker registration via Master REST API (external IP or SSH fallback)
echo ""
echo "[INFO] Waiting up to 5 minutes for all $TARGET_COUNT worker(s) to register on Master..."
READY=0
for r in $(seq 1 30); do
    WORKER_RESP=""
    if [ -n "${MASTER_EXTERNAL_IP:-}" ]; then
        WORKER_RESP="$(curl -sf -m 4 "http://${MASTER_EXTERNAL_IP}:8080/api/worker" 2>/dev/null || true)"
    fi
    if [ -z "$WORKER_RESP" ]; then
        WORKER_RESP="$(gcloud compute ssh "${MASTER_NAME:-master}" "${ZONE_FLAG[@]}" \
            --command='curl -sf -m 4 http://127.0.0.1:8080/api/worker' 2>/dev/null || true)"
    fi
    COUNT="$(echo "$WORKER_RESP" | grep -o '"id":' | wc -l || true)"
    if [ "$COUNT" -ge "$TARGET_COUNT" ]; then
        echo "[SUCCESS] All $COUNT worker(s) successfully registered!"
        echo "$WORKER_RESP"
        READY=1
        break
    fi
    echo "[WAIT] Registered $COUNT/$TARGET_COUNT worker(s)... (attempt $r/30)"
    sleep 10
done

if [ "$READY" -ne 1 ]; then
    echo "[WARNING] Not all workers registered within 5 min. Check logs on worker VMs or run ./06_gcp_cleanup.sh if aborting."
fi

echo "[SUCCESS] Worker scaling completed."
