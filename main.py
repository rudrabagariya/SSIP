"""
Main entry point for Smart Checkout Kiosk
"""
import sys
import os
import time
import threading

# Enable Qt Virtual Keyboard BEFORE importing Qt
os.environ["QT_IM_MODULE"] = "qtvirtualkeyboard"

from PySide6.QtWidgets import QApplication

from config import TELEGRAM_BOT_TOKEN
from database import init_db
from flask_server import run_flask
from telegram_bot import run_telegram_bot
from ui_main import SmartKiosk

def main():
    """Main application entry point"""
    # Initialize database
    init_db()
    
    # Start Flask server in background
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Start Telegram bot if configured
    if TELEGRAM_BOT_TOKEN:
        bot_thread = threading.Thread(target=run_telegram_bot, daemon=True)
        bot_thread.start()
        time.sleep(1)  # Give bot time to initialize
    
    time.sleep(0.5)
    
    # Start Qt application
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    kiosk = SmartKiosk()
    kiosk.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

