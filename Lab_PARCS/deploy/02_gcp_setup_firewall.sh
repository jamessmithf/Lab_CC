#!/usr/bin/env bash
# ==============================================================================
# 02_gcp_setup_firewall.sh - Scoped GCP Network & Firewall Configuration
#
# Creates least-privilege firewall rules tagged with 'parcs-node':
#   1. parcs-allow-internal : all internal cluster traffic (10.0.0.0/8)
#                             for Master REST (8080) and random Pyro4 RPC ports
#   2. parcs-allow-ssh      : SSH (tcp:22) if default-allow-ssh is absent
#   3. parcs-allow-web      : PARCS Web UI/API (tcp:8080) ONLY from your
#                             current public IP (/32) to prevent unauthorized RCE
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

NETWORK_NAME="default"
TAG="parcs-node"
RULE_INTERNAL="parcs-allow-internal"
RULE_SSH="parcs-allow-ssh"
RULE_WEB="parcs-allow-web"

echo "======================================================================"
echo " Configuring Least-Privilege Firewall Rules for PARCS Cluster"
echo " Network: $NETWORK_NAME | Target Tag: $TAG"
echo "======================================================================"

# Ensure default VPC exists
if ! gcloud compute networks describe "$NETWORK_NAME" &>/dev/null; then
    echo "[INFO] Creating VPC network '$NETWORK_NAME'..."
    gcloud compute networks create "$NETWORK_NAME" --subnet-mode=auto
fi

# 1. Internal cluster communication (Pyro4 uses dynamic ports inside VPC)
if gcloud compute firewall-rules describe "$RULE_INTERNAL" &>/dev/null; then
    echo "[INFO] Firewall rule '$RULE_INTERNAL' already exists."
else
    echo "[INFO] Creating '$RULE_INTERNAL' (10.0.0.0/8 -> tag:$TAG)..."
    gcloud compute firewall-rules create "$RULE_INTERNAL" \
        --network="$NETWORK_NAME" \
        --direction=INGRESS \
        --priority=1000 \
        --action=ALLOW \
        --rules=tcp,udp,icmp \
        --source-ranges=10.0.0.0/8 \
        --target-tags="$TAG"
fi

# 2. SSH access (if default-allow-ssh does not already exist)
if gcloud compute firewall-rules describe "default-allow-ssh" &>/dev/null || \
   gcloud compute firewall-rules describe "$RULE_SSH" &>/dev/null; then
    echo "[INFO] SSH firewall rule already active."
else
    echo "[INFO] Creating '$RULE_SSH' (tcp:22 -> tag:$TAG)..."
    gcloud compute firewall-rules create "$RULE_SSH" \
        --network="$NETWORK_NAME" \
        --direction=INGRESS \
        --priority=1000 \
        --action=ALLOW \
        --rules=tcp:22 \
        --source-ranges=0.0.0.0/0 \
        --target-tags="$TAG"
fi

# 3. Restrict PARCS Web UI / REST API (port 8080) to student's current public IP
MY_IP="$(curl -sf --max-time 10 https://api.ipify.org || true)"
if [[ "$MY_IP" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]]; then
    if gcloud compute firewall-rules describe "$RULE_WEB" &>/dev/null; then
        echo "[INFO] Updating '$RULE_WEB' source-ranges to ${MY_IP}/32..."
        gcloud compute firewall-rules update "$RULE_WEB" --source-ranges="${MY_IP}/32"
    else
        echo "[INFO] Creating '$RULE_WEB' (tcp:8080 ONLY from ${MY_IP}/32 -> tag:$TAG)..."
        gcloud compute firewall-rules create "$RULE_WEB" \
            --network="$NETWORK_NAME" \
            --direction=INGRESS \
            --priority=1000 \
            --action=ALLOW \
            --rules=tcp:8080 \
            --source-ranges="${MY_IP}/32" \
            --target-tags="$TAG"
    fi
    echo "[SUCCESS] Web UI (port 8080) allowed exclusively for your IP: $MY_IP"
else
    echo "[WARNING] Could not detect public IP via api.ipify.org; '$RULE_WEB' not configured."
    echo "          Benchmarks via SSH (05_gcp_run_benchmark.py) still work without port 8080 open."
fi

echo ""
gcloud compute firewall-rules list --filter="name ~ '^parcs-'" \
    --format="table(name,network,sourceRanges.list():label=SRC_RANGES,allowed[].map().list():label=ALLOWED,targetTags.list():label=TAGS)"
