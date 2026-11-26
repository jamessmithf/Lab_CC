#!/usr/bin/env bash
# ==============================================================================
# 06_gcp_cleanup.sh - Safe Teardown & Post-Cleanup Audit of All GCP Resources
#
# Deletes all PARCS VM instances (--delete-disks=all), any orphaned disks,
# and all parcs-* firewall rules, then verifies that ZERO billable cluster
# resources remain in the project.
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

echo "======================================================================"
echo " TEARDOWN: Cleaning up all Google Cloud Platform PARCS Resources"
echo "======================================================================"

# 1. Delete all PARCS VM instances (grouped by zone) along with boot disks
INST_LINES="$(gcloud compute instances list --filter="name ~ '^(master|worker[0-9]+)$'" --format="value(name,zone.basename())" || true)"
if [ -n "$INST_LINES" ]; then
    echo "[INFO] Deleting VM instances and their disks..."
    while IFS=$'\t' read -r NAME ZONE; do
        [ -z "$NAME" ] && continue
        echo "  - Deleting VM '$NAME' (zone: $ZONE)..."
        gcloud compute instances delete "$NAME" --zone="$ZONE" --delete-disks=all --quiet
    done <<< "$INST_LINES"
    echo "[SUCCESS] All PARCS VM instances deleted."
else
    echo "[INFO] No active PARCS VM instances found."
fi

# 2. Delete any orphaned disks belonging to master/worker*
DISK_LINES="$(gcloud compute disks list --filter="name ~ '^(master|worker[0-9]+)$'" --format="value(name,zone.basename())" || true)"
if [ -n "$DISK_LINES" ]; then
    echo "[INFO] Deleting orphaned PARCS disks..."
    while IFS=$'\t' read -r DNAME DZONE; do
        [ -z "$DNAME" ] && continue
        echo "  - Deleting disk '$DNAME' (zone: $DZONE)..."
        gcloud compute disks delete "$DNAME" --zone="$DZONE" --quiet
    done <<< "$DISK_LINES"
fi

# 3. Delete all PARCS firewall rules (including legacy parcs-allow-all)
FW_RULES="$(gcloud compute firewall-rules list --filter="name ~ '^parcs-'" --format="value(name)" || true)"
if [ -n "$FW_RULES" ]; then
    echo "[INFO] Deleting firewall rules: $(echo "$FW_RULES" | tr '\n' ' ')"
    # shellcheck disable=SC2086
    gcloud compute firewall-rules delete $FW_RULES --quiet
    echo "[SUCCESS] PARCS firewall rules deleted."
else
    echo "[INFO] No PARCS firewall rules found."
fi

# 4. Clean local cluster environment file
if [ -f "$CLUSTER_ENV" ]; then
    rm -f "$CLUSTER_ENV"
    echo "[INFO] Removed local cluster environment file: $CLUSTER_ENV"
fi

# 5. Final Verification Audit
echo ""
echo "======================================================================"
echo " POST-CLEANUP VERIFICATION AUDIT"
echo "======================================================================"
LEFT_INST="$(gcloud compute instances list --filter="name ~ '^(master|worker[0-9]+)$'" --format="value(name)" || true)"
LEFT_DISK="$(gcloud compute disks list --filter="name ~ '^(master|worker[0-9]+)$'" --format="value(name)" || true)"
LEFT_FW="$(gcloud compute firewall-rules list --filter="name ~ '^parcs-'" --format="value(name)" || true)"
ALL_INST="$(gcloud compute instances list --format="value(name)" || true)"
ALL_DISK="$(gcloud compute disks list --format="value(name)" || true)"
ALL_ADDR="$(gcloud compute addresses list --format="value(name)" || true)"

count_lines() { [ -z "$1" ] && echo 0 || echo "$1" | wc -l; }

N_LEFT_INST="$(count_lines "$LEFT_INST")"
N_LEFT_DISK="$(count_lines "$LEFT_DISK")"
N_LEFT_FW="$(count_lines "$LEFT_FW")"
N_ALL_INST="$(count_lines "$ALL_INST")"
N_ALL_DISK="$(count_lines "$ALL_DISK")"
N_ALL_ADDR="$(count_lines "$ALL_ADDR")"

echo "  Remaining PARCS VMs            : $N_LEFT_INST"
echo "  Remaining PARCS Disks          : $N_LEFT_DISK"
echo "  Remaining PARCS Firewall Rules : $N_LEFT_FW"
echo "  Project Totals                 : VMs=$N_ALL_INST, Disks=$N_ALL_DISK, Static IPs=$N_ALL_ADDR"
echo "======================================================================"

if [ "$N_LEFT_INST" -eq 0 ] && [ "$N_LEFT_DISK" -eq 0 ] && [ "$N_LEFT_FW" -eq 0 ]; then
    echo "[OK] Zero PARCS resources remain in GCP. No further charges will incur."
    echo "     Billing console: https://console.cloud.google.com/billing"
else
    echo "[WARNING] Some PARCS resources still remain! Re-run ./06_gcp_cleanup.sh or remove manually in GCP Console."
    exit 1
fi
