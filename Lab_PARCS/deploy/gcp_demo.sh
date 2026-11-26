#!/usr/bin/env bash
# ==============================================================================
# gcp_demo.sh - Live Defense Preparation Helper for GCP PARCS Cluster
#
# Updates 'parcs-allow-web' to your CURRENT public IP (e.g. university Wi-Fi),
# generates demo input files, and prints the step-by-step live defense guide.
# ==============================================================================
set -euo pipefail

if [ -d "$HOME/google-cloud-sdk/bin" ]; then
    export PATH="$HOME/google-cloud-sdk/bin:$PATH"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CLUSTER_ENV="$SCRIPT_DIR/gcp_cluster_info.env"

if [ -f "$CLUSTER_ENV" ]; then
    # shellcheck disable=SC1090
    source "$CLUSTER_ENV"
fi

ZONE="${GCP_ZONE:-$(gcloud config get-value compute/zone 2>/dev/null || echo europe-north1-b)}"
MASTER_NAME="${MASTER_NAME:-master}"

echo "======================================================================"
echo " PARCS Live Defense Setup"
echo "======================================================================"

echo "[1/3] Checking running cluster instances..."
gcloud compute instances list --filter="name ~ '^(master|worker[0-9]+)$'" \
    --format="table(name,zone.basename(),machineType.basename(),INTERNAL_IP,EXTERNAL_IP,status)"

MASTER_EXT="$(gcloud compute instances describe "$MASTER_NAME" --zone="$ZONE" --format="get(networkInterfaces[0].accessConfigs[0].natIP)")"

echo ""
echo "[2/3] Updating 'parcs-allow-web' firewall rule for your current IP..."
MY_IP="$(curl -sf --max-time 10 https://api.ipify.org)"
if gcloud compute firewall-rules describe parcs-allow-web &>/dev/null; then
    gcloud compute firewall-rules update parcs-allow-web --source-ranges="${MY_IP}/32"
else
    gcloud compute firewall-rules create parcs-allow-web \
        --network=default --allow=tcp:8080 --source-ranges="${MY_IP}/32" --target-tags=parcs-node
fi
echo "[OK] Port 8080 opened exclusively for your current IP: $MY_IP"

echo ""
echo "[3/3] Preparing demo input files in demo/ ..."
mkdir -p "$PROJECT_ROOT/demo"
python3 "$PROJECT_ROOT/src/generate_input.py" -n 10000000 -o "$PROJECT_ROOT/demo/input_10m.txt"
python3 "$PROJECT_ROOT/src/generate_input.py" -n 50000000 -o "$PROJECT_ROOT/demo/input_50m.txt"
python3 "$PROJECT_ROOT/src/generate_input.py" -n 100000000 -o "$PROJECT_ROOT/demo/input_100m.txt"

URL="http://${MASTER_EXT}:8080"
echo ""
echo "======================================================================"
echo " LIVE DEFENSE CHECKLIST"
echo "======================================================================"
echo " 1. GCP Console  : Compute Engine -> VM instances (5 VMs RUNNING)"
echo " 2. Nodes page   : ${URL}/workers  (4 registered workers)"
echo " 3. Add Job page : ${URL}/add_job"
echo "      - Job Name      : demo_integration"
echo "      - Solution File : $PROJECT_ROOT/src/solver.py"
echo "      - Input File    : $PROJECT_ROOT/demo/input_50m.txt"
echo " 4. Jobs page    : ${URL}/jobs -> Click 'Output' (integral, error, # TIMING)"
echo " 5. Compare 1 vs 4 workers: Disable 3 workers on /workers and re-run job"
echo " 6. Quick automated benchmark (~1 min):"
echo "      python3 $SCRIPT_DIR/05_gcp_run_benchmark.py --quick --wait"
echo " 7. AFTER DEFENSE (MANDATORY):"
echo "      $SCRIPT_DIR/06_gcp_cleanup.sh"
echo "======================================================================"
