#!/usr/bin/env bash
# ==============================================================================
# 00_install_gcloud.sh - Google Cloud CLI Installer & Verification
# According to official KNU guidelines (PARCS-Python_Google_Cloud_0925.pdf)
# ==============================================================================
set -euo pipefail

echo "======================================================================"
echo " Google Cloud SDK / gcloud CLI Installation Check"
echo "======================================================================"

# Check if gcloud is in PATH or already in ~/google-cloud-sdk/bin
if [ -x "$HOME/google-cloud-sdk/bin/gcloud" ]; then
    export PATH="$HOME/google-cloud-sdk/bin:$PATH"
fi

if command -v gcloud &>/dev/null; then
    echo "[INFO] gcloud is already installed:"
    gcloud version
    exit 0
fi

echo "[INFO] gcloud not found. Installing Google Cloud SDK..."

# Check if user has passwordless sudo access
if command -v apt-get &>/dev/null && sudo -n true 2>/dev/null; then
    echo "[INFO] Detected Debian/Ubuntu system with passwordless sudo. Installing via apt repository..."
    sudo apt-get update -y
    sudo apt-get install -y apt-transport-https ca-certificates gnupg curl

    if [ ! -f /usr/share/keyrings/cloud.google.gpg ]; then
        curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg
    fi

    echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | sudo tee -a /etc/apt/sources.list.d/google-cloud-sdk.list
    sudo apt-get update -y
    sudo apt-get install -y google-cloud-cli google-cloud-cli-docker-credential
else
    # Standalone user-level archive install (NO sudo, NO root password required!)
    echo "[INFO] Installing standalone Google Cloud SDK archive into $HOME/google-cloud-sdk (no sudo needed)..."
    INSTALL_DIR="$HOME/google-cloud-sdk"
    ARCHIVE_URL="https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-linux-x86_64.tar.gz"
    TEMP_TAR="/tmp/google-cloud-cli.tar.gz"

    echo "[INFO] Downloading Google Cloud SDK..."
    curl -sSL "$ARCHIVE_URL" -o "$TEMP_TAR"

    echo "[INFO] Extracting to $HOME..."
    tar -xf "$TEMP_TAR" -C "$HOME"
    rm -f "$TEMP_TAR"

    echo "[INFO] Running install script..."
    "$INSTALL_DIR/install.sh" --quiet --path-update true

    export PATH="$INSTALL_DIR/bin:$PATH"
    if ! grep -q "google-cloud-sdk/bin" "$HOME/.bashrc" 2>/dev/null; then
        echo 'export PATH="$HOME/google-cloud-sdk/bin:$PATH"' >> "$HOME/.bashrc"
    fi
fi

echo "[SUCCESS] gcloud installation completed."
export PATH="$HOME/google-cloud-sdk/bin:$PATH"
gcloud version
