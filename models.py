"""
Data models and enums for Smart Checkout Kiosk
"""
from enum import Enum
from PySide6.QtCore import QEvent

class PaymentStatus(Enum):
    """Payment status enumeration"""
    IDLE = 0
    PROCESSING = 1
    SUCCESS = 2
    FAILED = 3

class Theme:
    """Theme configuration class"""
    def __init__(self, name, background, foreground, accent, text, secondary):
        self.name = name
        self.background = background
        self.foreground = foreground
        self.accent = accent
        self.text = text
        self.secondary = secondary

# Theme definitions — modern slate + indigo palette
LIGHT_THEME = Theme("light", "#f1f5f9", "#ffffff", "#6366f1", "#0f172a", "#e2e8f0")
DARK_THEME  = Theme("dark",  "#0c1222", "#1e293b", "#818cf8", "#f1f5f9", "#334155")

class BarcodeEvent(QEvent):
    """Custom event for barcode scanning"""
    EVENT_TYPE = QEvent.Type(QEvent.registerEventType())
    
    def __init__(self, barcode):
        super().__init__(self.EVENT_TYPE)
        self.barcode = barcode

