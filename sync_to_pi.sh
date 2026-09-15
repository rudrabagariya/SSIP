#!/usr/bin/env bash
# ==============================================================================
# Fast Sync Script: Linux PC -> Raspberry Pi
# Syncs code changes in milliseconds without having to copy-paste.
# ==============================================================================

# --- CONFIGURATION (Edit these to match your Raspberry Pi) ---
PI_USER="${PI_USER:-pi}"
PI_HOST="${PI_HOST:-raspberrypi.local}"   # Or replace with Pi IP, e.g., 192.168.1.50
PI_DIR="${PI_DIR:-~/PHASE_2_V1}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

sync_files() {
    echo "[$(date +'%H:%M:%S')] Syncing files to ${PI_USER}@${PI_HOST}:${PI_DIR} ..."
    rsync -avz --delete \
        --exclude '.git' \
        --exclude '__pycache__' \
        --exclude '*.pyc' \
        --exclude 'dataset_venv' \
        --exclude 'venv' \
        --exclude '.env' \
        --exclude 'load_cell_test/calibration.json' \
        "$SCRIPT_DIR/" "${PI_USER}@${PI_HOST}:${PI_DIR}/"
    echo "[$(date +'%H:%M:%S')] ✅ Sync complete!"
}

if [ "$1" == "--watch" ]; then
    echo "👀 Watch mode enabled. Auto-syncing on file change..."
    sync_files
    if command -v inotifywait >/dev/null 2>&1; then
        while true; do
            inotifywait -r -e modify,create,delete,move \
                --exclude '(\.git|__pycache__|dataset_venv|\.swp)' \
                "$SCRIPT_DIR" >/dev/null 2>&1
            sync_files
            sleep 1
        done
    else
        echo "Tip: Install inotify-tools ('sudo apt install inotify-tools') for instant change detection."
        echo "Falling back to polling every 3 seconds..."
        while true; do
            sleep 3
            rsync -avzu --dry-run \
                --exclude '.git' --exclude '__pycache__' --exclude 'dataset_venv' \
                "$SCRIPT_DIR/" "${PI_USER}@${PI_HOST}:${PI_DIR}/" 2>&1 | grep -q 'sent ' || sync_files
        done
    fi
else
    sync_files
    echo ""
    echo "💡 Tip: Run './sync_to_pi.sh --watch' to continuously auto-sync every time you save a file."
fi
