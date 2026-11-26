#!/usr/bin/env bash
# ==============================================================================
# 03_gcp_deploy_master.sh - Deploy Master Node VM on Google Compute Engine
#
# Defaults to n1-standard-1 (1 vCPU, 3.75 GB RAM) + 10GB disk so a 5-VM cluster
# fits cleanly inside the GCP Free Trial 8-vCPU quota, with an 8-hour auto-delete
# safety guard (--max-run-duration=8h --instance-termination-action=DELETE).
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

MASTER_NAME="${MASTER_NAME:-master}"
MACHINE_TYPE="${1:-${GCP_MACHINE_TYPE:-n1-standard-1}}"
EXPECTED_WORKERS="${2:-4}"
MAX_RUN_HOURS="${GCP_MAX_RUN_HOURS:-8}"
DISK_SIZE_GB="${GCP_DISK_SIZE_GB:-10}"
CONTAINER_IMAGE="hummer12007/parcs-node:latest"

ZONE="${GCP_ZONE:-$(gcloud config get-value compute/zone 2>/dev/null || echo europe-north1-b)}"
REGION="${GCP_REGION:-${ZONE%-*}}"
ZONE_FLAG=(--zone="$ZONE")

echo "======================================================================"
echo " Deploying PARCS Master VM on GCP Compute Engine"
echo " Instance: $MASTER_NAME | Machine: $MACHINE_TYPE | Zone: $ZONE"
echo " Disk: ${DISK_SIZE_GB}GB | Auto-Delete Guard: ${MAX_RUN_HOURS}h"
echo "======================================================================"

# 0. Pre-flight quota check (CPUS, IN_USE_ADDRESSES, CPUS_ALL_REGIONS)
echo "[INFO] Checking GCP quotas for $((EXPECTED_WORKERS + 1)) VM(s) of type '$MACHINE_TYPE'..."
GUEST_CPUS="$(gcloud compute machine-types describe "$MACHINE_TYPE" "${ZONE_FLAG[@]}" --format='value(guestCpus)' 2>/dev/null || echo 1)"
NEED_VMS=$((EXPECTED_WORKERS + 1))
NEED_CPUS=$((NEED_VMS * GUEST_CPUS))

python3 - "$REGION" "$NEED_CPUS" "$NEED_VMS" <<'PYEOF' || true
import json, subprocess, sys
region, need_cpus, need_vms = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
try:
    reg = json.loads(subprocess.check_output(["gcloud", "compute", "regions", "describe", region, "--format=json"], stderr=subprocess.DEVNULL))
    for metric, need in [("CPUS", need_cpus), ("IN_USE_ADDRESSES", need_vms)]:
        for q in reg.get("quotas", []):
            if q.get("metric") == metric:
                free = float(q["limit"]) - float(q["usage"])
                print("  Quota %-18s: free %.0f / %.0f (need %d)" % (metric, free, float(q["limit"]), need))
                if free < need:
                    print("[WARNING] Insufficient %s quota in %s! Consider changing zone or machine type." % (metric, region))
    proj = json.loads(subprocess.check_output(["gcloud", "compute", "project-info", "describe", "--format=json"], stderr=subprocess.DEVNULL))
    for q in proj.get("quotas", []):
        if q.get("metric") == "CPUS_ALL_REGIONS":
            free = float(q["limit"]) - float(q["usage"])
            print("  Quota %-18s: free %.0f / %.0f (need %d)" % ("CPUS_ALL_REGIONS", free, float(q["limit"]), need_cpus))
            if free < need_cpus:
                print("[WARNING] Insufficient CPUS_ALL_REGIONS quota! Delete unused VMs first.")
except Exception as e:
    print("  [INFO] Quota check skipped (%s)" % e)
PYEOF

# 1. Create Master VM if it does not already exist
if gcloud compute instances describe "$MASTER_NAME" "${ZONE_FLAG[@]}" &>/dev/null; then
    echo "[INFO] Master instance '$MASTER_NAME' already exists."
else
    echo "[INFO] Provisioning master VM instance with Container-Optimized OS..."
    STARTUP_SCRIPT=$(cat <<'EOF'
#!/bin/bash
# COS host firewall drops incoming traffic except SSH by default.
# Open port 8080 (PARCS Web/REST) and internal VPC range 10.0.0.0/8 (Pyro4 RPC).
iptables -w -C INPUT -p tcp --dport 8080 -j ACCEPT 2>/dev/null || iptables -w -I INPUT -p tcp --dport 8080 -j ACCEPT
iptables -w -C INPUT -s 10.0.0.0/8 -j ACCEPT 2>/dev/null || iptables -w -I INPUT -s 10.0.0.0/8 -j ACCEPT

while ! docker info >/dev/null 2>&1; do
    sleep 1
done

until docker pull hummer12007/parcs-node:latest; do
    sleep 5
done

docker rm -f parcs-master >/dev/null 2>&1 || true
docker run -d --name parcs-master --network host --restart unless-stopped \
    -e PARCS_ARGS="master" hummer12007/parcs-node:latest
EOF
)
    gcloud compute instances create "$MASTER_NAME" \
        "${ZONE_FLAG[@]}" \
        --image-family="cos-stable" \
        --image-project="cos-cloud" \
        --machine-type="$MACHINE_TYPE" \
        --tags="parcs-node,parcs-master" \
        --boot-disk-size="${DISK_SIZE_GB}GB" \
        --boot-disk-type="pd-standard" \
        --max-run-duration="${MAX_RUN_HOURS}h" \
        --instance-termination-action="DELETE" \
        --metadata="startup-script=$STARTUP_SCRIPT"
fi

# 2. Extract Master Internal and External IPs
echo "[INFO] Fetching IP addresses..."
MASTER_INTERNAL_IP=$(gcloud compute instances describe "$MASTER_NAME" "${ZONE_FLAG[@]}" --format="get(networkInterfaces[0].networkIP)")
MASTER_EXTERNAL_IP=$(gcloud compute instances describe "$MASTER_NAME" "${ZONE_FLAG[@]}" --format="get(networkInterfaces[0].accessConfigs[0].natIP)")

echo "----------------------------------------------------------------------"
echo " Master Internal IP : $MASTER_INTERNAL_IP"
echo " Master External IP : $MASTER_EXTERNAL_IP"
echo " Web UI / API URL   : http://${MASTER_EXTERNAL_IP}:8080"
echo "----------------------------------------------------------------------"

# 3. Cleanly update environment file (no duplicate entries on re-run)
touch "$CLUSTER_ENV"
grep -vE '^export (MASTER_NAME|MASTER_INTERNAL_IP|MASTER_EXTERNAL_IP|MASTER_URL|GCP_MACHINE_TYPE)=' "$CLUSTER_ENV" > "${CLUSTER_ENV}.tmp" || true
mv "${CLUSTER_ENV}.tmp" "$CLUSTER_ENV"
cat <<EOF >> "$CLUSTER_ENV"
export MASTER_NAME="$MASTER_NAME"
export MASTER_INTERNAL_IP="$MASTER_INTERNAL_IP"
export MASTER_EXTERNAL_IP="$MASTER_EXTERNAL_IP"
export MASTER_URL="http://${MASTER_EXTERNAL_IP}:8080"
export GCP_MACHINE_TYPE="$MACHINE_TYPE"
EOF

# 4. Wait for Master Web service to become responsive
echo "[INFO] Waiting for Master Web service on http://${MASTER_EXTERNAL_IP}:8080 ..."
RETRY_COUNT=0
MAX_RETRIES=36 # 3 minutes max (5s intervals)
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -sf -m 3 "http://${MASTER_EXTERNAL_IP}:8080/api/worker" >/dev/null 2>&1; then
        echo "[SUCCESS] Master Web UI / REST API is online and responsive!"
        break
    fi
    echo "[WAIT] Service starting up... ($((RETRY_COUNT + 1))/$MAX_RETRIES)"
    sleep 5
    RETRY_COUNT=$((RETRY_COUNT + 1))
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "[WARNING] External port 8080 check timed out (check firewall or startup logs via:"
    echo "          gcloud compute ssh $MASTER_NAME --zone=$ZONE --command='sudo docker ps')"
fi

echo "[SUCCESS] Master deployment completed."
