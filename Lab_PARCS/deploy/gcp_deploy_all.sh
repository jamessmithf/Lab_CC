#!/usr/bin/env bash
# ==============================================================================
# gcp_deploy_all.sh - End-to-End GCP PARCS Cluster Provisioning
#
# Usage:
#   ./gcp_deploy_all.sh [PROJECT_ID] [WORKERS_COUNT] [REGION] [ZONE] [MACHINE_TYPE]
# Example:
#   ./gcp_deploy_all.sh parcs-lab-vsikora 4 europe-north1 europe-north1-b n1-standard-1
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

DEFAULT_PROJECT="${GCP_PROJECT_ID:-parcs-lab-$(date +%s)}"
PROJECT_NAME="${1:-$DEFAULT_PROJECT}"
if [[ "$PROJECT_NAME" == *"<"* ]] || [[ "$PROJECT_NAME" == *">"* ]]; then
    echo "[NOTICE] Detected placeholder brackets in project argument. Auto-generating compliant project ID..."
    PROJECT_NAME="parcs-lab-$(date +%s)"
fi
WORKERS_COUNT="${2:-4}"
REGION="${3:-europe-north1}"
ZONE="${4:-europe-north1-b}"
MACHINE_TYPE="${5:-n1-standard-1}"

echo "======================================================================"
echo " PARCS-Python Google Cloud Platform End-to-End Automated Deployment"
echo " Project: $PROJECT_NAME | Workers: $WORKERS_COUNT | Zone: $ZONE | VM: $MACHINE_TYPE"
echo "======================================================================"

"$SCRIPT_DIR/00_install_gcloud.sh"
"$SCRIPT_DIR/01_gcp_init_project.sh" "$PROJECT_NAME" "$REGION" "$ZONE"
"$SCRIPT_DIR/02_gcp_setup_firewall.sh"
"$SCRIPT_DIR/03_gcp_deploy_master.sh" "$MACHINE_TYPE" "$WORKERS_COUNT"
"$SCRIPT_DIR/04_gcp_scale_workers.sh" "$WORKERS_COUNT" "$MACHINE_TYPE"

echo ""
echo "======================================================================"
echo " GCP PARCS CLUSTER DEPLOYMENT COMPLETE!"
echo "======================================================================"
if [ -f "$SCRIPT_DIR/gcp_cluster_info.env" ]; then
    # shellcheck disable=SC1090
    source "$SCRIPT_DIR/gcp_cluster_info.env"
    echo " Master Web UI URL : $MASTER_URL"
    echo " Master Internal IP: $MASTER_INTERNAL_IP"
    echo " Master External IP: $MASTER_EXTERNAL_IP"
fi
echo ""
echo " Next steps:"
echo " 1. Smoke test (~1 min) : python3 $SCRIPT_DIR/05_gcp_run_benchmark.py --quick --wait"
echo " 2. Full benchmarks     : python3 $SCRIPT_DIR/05_gcp_run_benchmark.py --wait"
echo " 3. Live defense helper : $SCRIPT_DIR/gcp_demo.sh"
echo " 4. MANDATORY cleanup   : $SCRIPT_DIR/06_gcp_cleanup.sh"
echo "======================================================================"
