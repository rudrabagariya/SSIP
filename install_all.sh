#!/bin/bash
# =============================================================
#  Smart Checkout Kiosk — One-Shot Dependency Installer
#  Usage:  chmod +x install_all.sh && ./install_all.sh
# =============================================================

set -e  # Exit on any error

echo "============================================================"
echo "  Smart Checkout Kiosk — Dependency Installer"
echo "============================================================"
echo ""

# ---------- Step 0: Make sure Python3 is installed ----------
if ! command -v python3 &> /dev/null; then
    echo "[0/3] Python3 not found. Installing Python3..."
    sudo apt-get update -qq
    sudo apt-get install -y python3 python3-pip python3-venv
    echo "✅ Python3 installed"
    echo ""
else
    echo "[0/3] ✅ Python3 found: $(python3 --version)"
    echo ""
fi

# ---------- Detect OS ----------
OS="$(uname -s)"
IS_RASPI=false
if [ -f /proc/device-tree/model ] && grep -qi "raspberry" /proc/device-tree/model 2>/dev/null; then
    IS_RASPI=true
fi

# ---------- Step 1: System-level packages (Linux only) ----------
if [ "$OS" = "Linux" ]; then
    echo "[1/3] Installing system packages (sudo required)..."
    sudo apt-get update -qq
    sudo apt-get install -y \
        python3-pip \
        python3-dev \
        python3-venv \
        libusb-1.0-0 \
        libusb-dev \
        libjpeg-dev \
        zlib1g-dev \
        libxcb-xinerama0 \
        libxcb-cursor0 \
        libxkbcommon0 \
        libgl1 \
        libglib2.0-0 \
        libegl1 \
        libopengl0
    echo "✅ System packages installed"
    echo ""
else
    echo "[1/3] Skipping system packages (not Linux)."
    echo ""
fi

# ---------- Step 2: Python packages ----------
echo "[2/3] Installing Python packages from requirements.txt..."

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REQ_FILE="$SCRIPT_DIR/requirements.txt"

if [ ! -f "$REQ_FILE" ]; then
    echo "❌ requirements.txt not found at $REQ_FILE"
    exit 1
fi

# On Raspberry Pi / system Python use --break-system-packages
PIP_EXTRA_FLAGS=""
if [ "$IS_RASPI" = true ] || python3 -c "import sys; sys.exit(0 if sys.prefix == sys.base_prefix else 1)" 2>/dev/null; then
    PIP_EXTRA_FLAGS="--break-system-packages"
fi

pip3 install --upgrade pip $PIP_EXTRA_FLAGS 2>/dev/null || true
pip3 install -r "$REQ_FILE" $PIP_EXTRA_FLAGS

echo "✅ Python packages installed"
echo ""

# ---------- Step 3: Printer USB permissions (Linux only) ----------
if [ "$OS" = "Linux" ]; then
    echo "[3/3] Setting up thermal printer USB permissions..."
    UDEV_RULE='SUBSYSTEM=="usb", ATTR{idVendor}=="0fe6", ATTR{idProduct}=="811e", MODE="0666"'
    UDEV_FILE="/etc/udev/rules.d/99-thermal-printer.rules"

    if [ ! -f "$UDEV_FILE" ]; then
        echo "$UDEV_RULE" | sudo tee "$UDEV_FILE" > /dev/null
        sudo udevadm control --reload-rules
        sudo udevadm trigger
        echo "✅ Printer USB permissions configured"
    else
        echo "✅ Printer USB permissions already configured"
    fi

    # Serial port access (barcode scanner)
    sudo usermod -a -G dialout "$USER" 2>/dev/null || true
    echo ""
else
    echo "[3/3] Skipping USB/serial permission setup (not Linux)."
    echo ""
fi

# ---------- Done ----------
echo "============================================================"
echo "  ✅  ALL DEPENDENCIES INSTALLED!"
echo "============================================================"
echo ""
echo "  To run the kiosk:"
echo "    python3 main.py"
echo ""
echo "  NOTE: If this is your first run, reboot or re-login for"
echo "  serial port (dialout) permissions to take effect."
echo "============================================================"
