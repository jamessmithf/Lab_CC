#!/usr/bin/env bash
# ==============================================================================
# 01_gcp_init_project.sh - Google Cloud Project & Region Initialization
# ==============================================================================
set -euo pipefail

if [ -d "$HOME/google-cloud-sdk/bin" ]; then
    export PATH="$HOME/google-cloud-sdk/bin:$PATH"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLUSTER_ENV="$SCRIPT_DIR/gcp_cluster_info.env"

PROJECT_ID="${1:-parcs-integration-$(date +%s)}"
# Sanitize project ID if angle brackets were passed as a string (e.g. "<PROJECT_ID>")
if [[ "$PROJECT_ID" == *"<"* ]] || [[ "$PROJECT_ID" == *">"* ]]; then
    echo "[NOTICE] Detected placeholder brackets in project argument. Auto-generating compliant project ID..."
    PROJECT_ID="parcs-integration-$(date +%s)"
fi
REGION="${2:-europe-north1}"
ZONE="${3:-europe-north1-b}"

echo "======================================================================"
echo " GCP Project Setup: $PROJECT_ID"
echo " Region: $REGION | Zone: $ZONE"
echo "======================================================================"

# 1. Authentication check
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q "@"; then
    echo "[INFO] No active GCP account found. Opening authentication..."
    gcloud auth login
fi

ACTIVE_ACCOUNT=$(gcloud auth list --filter=status:ACTIVE --format="value(account)" | head -n1)
echo "[INFO] Using active account: $ACTIVE_ACCOUNT"

# 2. Check if project exists or create new
if gcloud projects describe "$PROJECT_ID" &>/dev/null; then
    echo "[INFO] Project '$PROJECT_ID' already exists."
else
    echo "[INFO] Creating GCP project '$PROJECT_ID'..."
    gcloud projects create "$PROJECT_ID" --name="PARCS Python Lab"
fi

# 2.1 Link billing account if available
BILLING_ACCOUNT=$(gcloud billing accounts list --filter="open=true" --format="value(name)" 2>/dev/null | head -n1 || true)
if [ -n "$BILLING_ACCOUNT" ]; then
    echo "[INFO] Linking billing account '$BILLING_ACCOUNT' to project '$PROJECT_ID'..."
    gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT" 2>/dev/null || true
else
    echo "[NOTICE] No open billing account found via CLI or permissions pending. Compute Engine will use the default account."
fi

# 3. Set current project configuration
echo "[INFO] Configuring project settings..."
gcloud config set project "$PROJECT_ID"
gcloud config set compute/region "$REGION"
gcloud config set compute/zone "$ZONE"

# 4. Enable Compute Engine API
echo "[INFO] Enabling Google Compute Engine API (compute.googleapis.com)..."
gcloud services enable compute.googleapis.com

# 5. Persist cluster info
cat <<EOF > "$CLUSTER_ENV"
export GCP_PROJECT_ID="$PROJECT_ID"
export GCP_REGION="$REGION"
export GCP_ZONE="$ZONE"
export GCP_ACCOUNT="$ACTIVE_ACCOUNT"
EOF

echo "[SUCCESS] Project configuration saved to $CLUSTER_ENV"
echo "Current project details:"
gcloud config list
