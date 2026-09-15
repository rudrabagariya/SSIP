"""
Configuration module for Smart Checkout Kiosk
Loads environment variables and defines application settings
"""
import os
import sys

# Fix for PyInstaller TLS certificate bundle issue
if getattr(sys, 'frozen', False):
    import certifi
    cert_path = certifi.where()
    os.environ['REQUESTS_CA_BUNDLE'] = cert_path
    os.environ['SSL_CERT_FILE'] = cert_path
    os.environ['CURL_CA_BUNDLE'] = cert_path

    # Patch Razorpay's CA bundle path BEFORE importing
    try:
        import razorpay.resources as rz_resources
        rz_resources.CA_BUNDLE = cert_path
        print(f"[DEBUG] Patched razorpay.resources.CA_BUNDLE to: {cert_path}")
    except Exception as e:
        print(f"[DEBUG] Warning: Could not patch razorpay.resources: {e}")

    try:
        import razorpay
        if hasattr(razorpay, 'CA_BUNDLE'):
            razorpay.CA_BUNDLE = cert_path
            print(f"[DEBUG] Patched razorpay.CA_BUNDLE to: {cert_path}")
    except Exception as e:
        print(f"[DEBUG] Warning: Could not patch razorpay module: {e}")

    try:
        import requests
        original_verify = requests.Session.verify
        def patched_verify(self, url=None, **kwargs):
            return cert_path if getattr(sys, 'frozen', False) else original_verify(self, url, **kwargs)
        requests.Session.verify = property(lambda self: patched_verify(self))
        print(f"[DEBUG] Patched requests.Session.verify to use certifi")
    except Exception as e:
        print(f"[DEBUG] Warning: Could not patch requests.Session: {e}")

# Load .env if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Razorpay Configuration
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

# Serial Port Configuration
SERIAL_PORT = os.getenv("SERIAL_PORT", "")
SERIAL_BAUDRATE = int(os.getenv("SERIAL_BAUDRATE", "115200"))

# Store Configuration
STORE_NAME = os.getenv("STORE_NAME", "Smart Store")
STORE_UPI_ID = os.getenv("STORE_UPI_ID", "success@razorpay")

# Admin Configuration
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

# UI Configuration
IDLE_TIMEOUT = int(os.getenv("IDLE_TIMEOUT", "60"))
CLEAR_CART_ON_IDLE = os.getenv("CLEAR_CART_ON_IDLE", "false").lower() == "true"

# SMTP Configuration
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_BOT_USERNAME = None  # Will be set when bot starts

# Flask Configuration
FLASK_PORT = int(os.getenv("FLASK_PORT", "5001"))

# Database Configuration
DB_PATH = os.path.join(os.path.dirname(__file__), "kiosk_db.sqlite3")

# In-memory storage
ORDER_CACHE = {}
PENDING_RECEIPTS = {}

# Scale / Load Cell Configuration
SCALE_ENABLED = os.getenv("SCALE_ENABLED", "true").lower() == "true"
SCALE_DOUT_PIN = int(os.getenv("SCALE_DOUT_PIN", "5"))
SCALE_SCK_PIN = int(os.getenv("SCALE_SCK_PIN", "6"))
SCALE_CALIBRATION_FILE = os.getenv(
    "SCALE_CALIBRATION_FILE",
    os.path.join(os.path.dirname(__file__), "load_cell_test", "calibration.json")
)
SCALE_TARE_SAMPLES = int(os.getenv("SCALE_TARE_SAMPLES", "150"))
SCALE_WEIGHT_TOLERANCE_GRAMS = float(os.getenv("SCALE_WEIGHT_TOLERANCE_GRAMS", "8.0"))
SCALE_WEIGHT_TOLERANCE_PERCENT = float(os.getenv("SCALE_WEIGHT_TOLERANCE_PERCENT", "20.0"))
SCALE_STABILITY_VARIANCE = float(os.getenv("SCALE_STABILITY_VARIANCE", "2.0"))
