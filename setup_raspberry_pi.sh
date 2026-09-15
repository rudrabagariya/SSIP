#!/bin/bash
# =============================================================
# Smart Checkout Kiosk - Raspberry Pi Setup Script
# Run this ONCE on a fresh Raspberry Pi to install everything
# Usage: chmod +x setup_raspberry_pi.sh && ./setup_raspberry_pi.sh
# =============================================================

set -e  # Exit on any error

echo "============================================================"
echo "  Smart Checkout Kiosk - Raspberry Pi Setup"
echo "============================================================"
echo ""

# ---- Step 1: System packages ----
echo "[1/5] Installing system packages..."
sudo apt-get update
sudo apt-get install -y \
    python3-pip \
    python3-dev \
    libusb-1.0-0 \
    libusb-dev \
    libjpeg-dev \
    zlib1g-dev \
    libxcb-xinerama0 \
    libxkbcommon0 \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libegl1 \
    libopengl0
echo "✅ System packages installed"
echo ""

# ---- Step 2: Python libraries ----
echo "[2/5] Installing Python libraries..."
pip3 install --break-system-packages \
    PySide6 \
    PySide6-WebEngine \
    Flask \
    razorpay \
    python-dotenv \
    "qrcode[pil]" \
    Pillow \
    pyserial \
    requests \
    certifi \
    python-telegram-bot \
    python-escpos \
    pyusb
echo "✅ Python libraries installed"
echo ""

# ---- Step 3: USB Printer permissions ----
echo "[3/5] Setting up thermal printer USB permissions..."
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
echo ""

# ---- Step 4: Serial port permissions (for barcode scanner) ----
echo "[4/5] Adding user to dialout group (serial port access)..."
sudo usermod -a -G dialout $USER
echo "✅ Serial port permissions configured"
echo ""

# ---- Step 5: Create launcher script ----
echo "[5/5] Creating launcher script..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cat > "$SCRIPT_DIR/run_kiosk.sh" << 'LAUNCHER'
#!/bin/bash
# Smart Checkout Kiosk Launcher
cd "$(dirname "$0")"
export QT_IM_MODULE=qtvirtualkeyboard
python3 main.py -platform xcb
LAUNCHER
chmod +x "$SCRIPT_DIR/run_kiosk.sh"
echo "✅ Launcher script created: run_kiosk.sh"
echo ""

# ---- Done ----
echo "============================================================"
echo "  ✅ SETUP COMPLETE!"
echo "============================================================"
echo ""
echo "  To run the kiosk:"
echo "    ./run_kiosk.sh"
echo ""
echo "  NOTE: Please reboot or re-login for serial port"
echo "  permissions to take effect."
echo "============================================================"
