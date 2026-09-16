"""
Main UI module for Smart Checkout Kiosk
Contains the SmartKiosk class with all UI logic
"""
import sys
import time
import sqlite3
import smtplib
import uuid
import threading
from io import BytesIO
from datetime import datetime
from collections import defaultdict
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import qrcode
import requests
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QDialog, QStackedWidget, QFrame, 
    QGridLayout, QComboBox, QSystemTrayIcon,
    QToolButton, QSizePolicy, QTextEdit, QGraphicsDropShadowEffect, 
    QGraphicsOpacityEffect, QSpinBox, QScroller, QTabWidget
)
from PySide6.QtCore import Qt, QTimer, QUrl, Signal, QEvent, QPropertyAnimation, QEasingCurve, QMutex, QRect, QPoint, QSize
from PySide6.QtGui import QPixmap, QColor, QPalette, QImage, QKeyEvent, QIcon
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage

import config
from config import *
from models import *
from database import *
from utils import *
from ui_components import *
from flask_server import client
from thermal_printer import ThermalPrinter, ESCPOS_AVAILABLE
from thermal_printer import ThermalPrinter, ESCPOS_AVAILABLE
from scale_service import ScaleWorker
from camera_service import CameraWorker

# Check if serial is available
try:
    import serial
    SERIAL_AVAILABLE = True
except Exception:
    SERIAL_AVAILABLE = False

class CustomWebEnginePage(QWebEnginePage):
    """Custom QWebEnginePage that captures console messages"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.console_message_callback = None
    
    def javaScriptConsoleMessage(self, level, message, line_number, source_id):
        """Override to capture console messages"""
        if self.console_message_callback:
            try:
                self.console_message_callback(level, message, line_number, source_id)
            except Exception as e:
                print(f"Error in console message callback: {e}")

class BarcodeLineEdit(QLineEdit):
    """
    Custom QLineEdit that prevents virtual keyboard popup when focused programmatically (scanner),
    but allows it when clicked/tapped by user.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        # Default state: No virtual keyboard, strictly for scanner
        self.setAttribute(Qt.WA_InputMethodEnabled, False)
        self.setInputMethodHints(Qt.ImhDigitsOnly)
        self.manual_mode = False

    def mousePressEvent(self, event):
        # User tapped: Enable manual mode and show keyboard
        self.manual_mode = True
        self.setAttribute(Qt.WA_InputMethodEnabled, True)
        QTimer.singleShot(0, lambda: QApplication.inputMethod().show())
        super().mousePressEvent(event)

    def focusInEvent(self, event):
        # If focus comes from mouse/touch, enable virtual keyboard
        if event.reason() == Qt.MouseFocusReason:
            self.manual_mode = True
            self.setAttribute(Qt.WA_InputMethodEnabled, True)
            QTimer.singleShot(0, lambda: QApplication.inputMethod().show())
        else:
            # If focus comes from code (timer/scanner), disable virtual keyboard
            self.manual_mode = False
            self.setAttribute(Qt.WA_InputMethodEnabled, False)
            QTimer.singleShot(0, lambda: QApplication.inputMethod().hide())
        super().focusInEvent(event)
        
    def focusOutEvent(self, event):
        # Reset to scanner mode when focus is lost
        self.manual_mode = False
        self.setAttribute(Qt.WA_InputMethodEnabled, False)
        super().focusOutEvent(event)

    def event(self, event):
        # Intercept the request to show the keyboard to prevent flickering
        if event.type() == QEvent.RequestSoftwareInputPanel:
            if not self.manual_mode:
                return True # Block the event
        return super().event(event)

class SmartKiosk(QMainWindow):
    payment_status_changed = Signal(PaymentStatus)
    theme_changed = Signal(Theme)
    network_error_detected = Signal(str)  # Signal for network errors from console handler

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Smart Checkout Kiosk")
        
        # Initialize thermal printer
        self.thermal_printer = ThermalPrinter()
        self._connect_thermal_printer()
        self.showFullScreen()
        # UI scaling helpers for 7" 1024x600 display
        try:
            screen = QApplication.primaryScreen()
            geo = screen.availableGeometry() if screen else None
            sw = geo.width() if geo else 1024
            sh = geo.height() if geo else 600
        except Exception:
            sw, sh = 1024, 600
        env_scale = os.getenv("UI_SCALE")
        if env_scale:
            try:
                self.ui_scale = max(0.9, min(1.5, float(env_scale)))
            except Exception:
                self.ui_scale = min(sw / 1024.0, sh / 600.0)
        else:
            self.ui_scale = min(sw / 1024.0, sh / 600.0)
        self.ui_scale = max(0.9, min(self.ui_scale, 1.5))
        self.dp = lambda v: int(round(v * self.ui_scale))
        self.fs_px = lambda v: max(10, int(round(v * self.ui_scale)))
        self.settings = self.load_settings()
        self.current_theme = DARK_THEME if self.settings.get('theme', 'light') == 'dark' else LIGHT_THEME
        self.language = self.settings.get('language', 'en')
        # Logo transparency threshold (controls how aggressively white becomes transparent)
        try:
            self.logo_threshold = int(self.settings.get('logo_transparency_threshold', '245'))
        
        except Exception:
            self.logo_threshold = 245
        try:
            self.gst_percent = float(self.settings.get('gst_percent', '5.0'))
        except (ValueError, TypeError):
            self.gst_percent = 5.0 # Fallback to 5% if setting is invalid
        # Removed shared connection - using connection-per-operation for thread safety
        self.cart = []
        self.total = 0.0
        self.payment_status = PaymentStatus.IDLE
        self.last_activity = time.time()
        self.scanning_active = True
        self.payment_in_progress = False
        self.admin_verified = False
        self.admin_screen = None
        self.scale_worker = None
        self.cart_weight_label = None

        self.setup_ui()
        self.theme_changed.connect(self.apply_theme)
        self.network_error_detected.connect(self.handle_network_error_signal)

        self.idle_timer = QTimer(self)
        self.idle_timer.timeout.connect(self.check_idle)
        self.idle_timer.start(1000)

        self.focus_timer = QTimer(self)
        self.focus_timer.timeout.connect(self.ensure_hidden_focus)
        # Disable auto-focus to prevent keyboard flicker
        # self.focus_timer.start(500)
        
        # Buffer for scanner input (since we no longer auto-focus the field)
        self.scan_buffer = ""

        if SERIAL_AVAILABLE and SERIAL_PORT:
            threading.Thread(target=self.serial_scanner_thread, daemon=True).start()

        # Initialize scale worker
        self.scale_worker = None
        self.verification_in_progress = False
        self._unscanned_overlay_active = False
        self._item_removed_overlay_active = False
        self.unscanned_items_weights = []
        if SCALE_ENABLED:
            try:
                self.scale_worker = ScaleWorker(self)
                self.scale_worker.sig_weight_updated.connect(self.on_scale_weight_updated)
                self.scale_worker.sig_weight_settled.connect(self.on_trolley_weight_settled)
                self.scale_worker.start()
                # Run startup tare dialog once UI is rendered
                QTimer.singleShot(700, self.start_startup_tare)
            except Exception as e:
                print(f"[UI] Warning: Could not initialize ScaleWorker: {e}")
                self.scale_worker = None

        try:
            self.camera_worker = CameraWorker()
            self.camera_worker.start()
        except Exception as e:
            print(f"[UI] Warning: Could not initialize CameraWorker: {e}")
            self.camera_worker = None

        # Keyboard visibility handling
        self.original_margins = None
        self.active_dialog_moved = None
        QApplication.inputMethod().keyboardRectangleChanged.connect(self.handle_keyboard_change)
        QApplication.instance().focusChanged.connect(lambda old, new: self.handle_keyboard_change())

    def handle_keyboard_change(self):
        """
        Adjust view when virtual keyboard opens to ensure focused widget is visible.
        Handles main window, QDialogs, and custom OverlayDialogs.
        """
        keyboard_rect = QApplication.inputMethod().keyboardRectangle()
        
        # Case 1: Keyboard is hidden
        if keyboard_rect.isEmpty():
            # Restore main window margins
            if self.original_margins:
                self.central.layout().setContentsMargins(self.original_margins)
                self.original_margins = None
            
            # Restore dialog position
            if self.active_dialog_moved:
                try:
                    dlg, original_pos = self.active_dialog_moved
                    # Check if dialog is still valid and visible
                    if dlg.isVisible():
                        dlg.move(original_pos)
                except Exception:
                    pass
                self.active_dialog_moved = None
                
            # Restore OverlayDialog margins
            if hasattr(self, 'active_overlay_margins') and self.active_overlay_margins:
                try:
                    overlay, margins = self.active_overlay_margins
                    if overlay.isVisible():
                        overlay.layout().setContentsMargins(margins)
                except Exception:
                    pass
                self.active_overlay_margins = None
            return

        # Case 2: Keyboard is visible
        focused_widget = QApplication.focusWidget()
        if not focused_widget:
            return

        # Find top level window of the focused widget
        window = focused_widget.window()
        
        # Check if widget is inside an OverlayDialog
        parent = focused_widget.parent()
        overlay_parent = None
        while parent:
            if isinstance(parent, OverlayDialog):
                overlay_parent = parent
                break
            parent = parent.parent()
        
        # Get widget geometry in global coordinates
        try:
            top_left = focused_widget.mapToGlobal(QPoint(0, 0))
            widget_rect = QRect(top_left, focused_widget.size())
        except Exception:
            return
        
        # Check for overlap
        if widget_rect.bottom() > keyboard_rect.top():
            # Calculate how much we need to shift up
            # Increased padding to ensure field is clearly visible above keyboard
            overlap = widget_rect.bottom() - keyboard_rect.top() + self.dp(100)
            
            if overlay_parent:
                # Handle OverlayDialog shift
                # We shift by increasing the bottom margin of the overlay's main layout
                # This pushes the centered content up
                if not hasattr(self, 'active_overlay_margins') or self.active_overlay_margins is None:
                    current_margins = overlay_parent.layout().contentsMargins()
                    self.active_overlay_margins = (overlay_parent, current_margins)
                    
                    # Apply shift
                    overlay_parent.layout().setContentsMargins(
                        current_margins.left(),
                        current_margins.top(),
                        current_margins.right(),
                        current_margins.bottom() + overlap
                    )
            
            elif window == self:
                # Main window: shift central widget margins
                if self.original_margins is None:
                    self.original_margins = self.central.layout().contentsMargins()
                
                current_margins = self.central.layout().contentsMargins()
                new_top = current_margins.top() - overlap
                self.central.layout().setContentsMargins(
                    current_margins.left(),
                    new_top,
                    current_margins.right(),
                    current_margins.bottom()
                )
                
            elif isinstance(window, QDialog):
                # Dialog: move the window up
                if self.active_dialog_moved and self.active_dialog_moved[0] == window:
                    pass
                else:
                    self.active_dialog_moved = (window, window.pos())
                    new_y = window.y() - overlap
                    window.move(window.x(), new_y)

    def start_startup_tare(self):
        """Display tare animation overlay and trigger zero tare on scale worker."""
        if not self.scale_worker:
            return
        overlay = ScaleTareOverlay(self, self.scale_worker)
        self.scale_worker.request_tare()
        overlay.exec_()

    def on_scale_weight_updated(self, live_weight, is_stable):
        """Update live trolley weight indicator on the cart screen."""
        if hasattr(self, 'cart_weight_label') and self.cart_weight_label:
            dot = "🟢" if is_stable else "🟡"
            disp_weight = max(0.0, live_weight)
            self.cart_weight_label.setText(f"🛒 Trolley: {disp_weight:.1f}g  {dot}")

    def on_trolley_weight_settled(self, delta, total_weight):
        """
        Triggered when weight settles in the trolley.
        If weight drops significantly (item taken out), automatically detect which
        item was removed, remove/decrement it from the cart, and show an auto-closing popup.
        If weight increases significantly without active scan verification, warn customer
        to scan the barcode first.
        """
        if getattr(self, '_clearing_trolley_active', False):
            return

        if getattr(self, 'payment_in_progress', False):
            if abs(delta) >= 10.0:
                expected_w = 0.0
                for item in self.cart:
                    # Calculate expected total weight based on actual measured weights or fall back to standard weight
                    item_w = sum(item.get("actual_weights", [])) if item.get("actual_weights") else (item["qty"] * item.get("weight_grams", 0))
                    expected_w += item_w
                dlg = PaymentWeightWarningOverlay(self, self.scale_worker, expected_w)
                self.payment_error_mutex.lock()
                try:
                    self.payment_error_triggered = True
                finally:
                    self.payment_error_mutex.unlock()
                dlg.exec_()
                self.payment_error_mutex.lock()
                try:
                    self.payment_error_triggered = False
                finally:
                    self.payment_error_mutex.unlock()
            return

        if (getattr(self, 'verification_in_progress', False) or 
            getattr(self, '_unscanned_overlay_active', False) or 
            getattr(self, '_item_removed_overlay_active', False)):
            return

        # An item was removed from the trolley (delta <= -5.0g)
        if delta <= -5.0:
            lost_weight = abs(delta)

            # Check if this removal matches an unscanned item that the user was prompted to remove
            matched_unscanned_idx = None
            for idx, uw in enumerate(getattr(self, 'unscanned_items_weights', [])):
                diff = abs(uw - lost_weight)
                tol = max(SCALE_WEIGHT_TOLERANCE_GRAMS * 1.5, uw * (SCALE_WEIGHT_TOLERANCE_PERCENT / 100.0))
                if diff <= tol:
                    matched_unscanned_idx = idx
                    break

            if matched_unscanned_idx is not None:
                # The user removed the unscanned item as requested
                self.unscanned_items_weights.pop(matched_unscanned_idx)
                return

            if not self.cart:
                return

            self.handle_item_removed_from_trolley(lost_weight)
            return

        # An unscanned item was placed into the trolley (delta >= 5.0g)
        if delta >= 5.0:
            baseline_weight = max(0.0, total_weight - delta)
            self.handle_unscanned_item_placed(delta, baseline_weight)

    def handle_unscanned_item_placed(self, added_weight, baseline_weight=0.0):
        """Show warning popup when an item is placed into the trolley without scanning first."""
        if (getattr(self, 'verification_in_progress', False) or 
            getattr(self, 'payment_in_progress', False) or 
            getattr(self, '_unscanned_overlay_active', False)):
            return

        self._unscanned_overlay_active = True
        try:
            dlg = UnscannedItemOverlay(self, self.scale_worker, added_weight, baseline_weight, getattr(self, 'camera_worker', None))
            dlg.exec_()
        finally:
            self._unscanned_overlay_active = False

    def handle_item_removed_from_trolley(self, lost_weight):
        """Find the cart item whose weight best matches the lost weight and remove one unit."""
        if getattr(self, '_item_removed_overlay_active', False):
            return

        best_match_idx = None
        best_match_diff = float('inf')
        matched_actual_weight = None

        for idx, item in enumerate(self.cart):
            actual_list = item.get("actual_weights", [])
            candidate_weights = actual_list if actual_list else [item.get("weight_grams", 0.0)]
            
            for cw in candidate_weights:
                if cw <= 0:
                    continue
                diff = abs(cw - lost_weight)
                # Flexible tolerance window for removal matching
                tolerance = max(SCALE_WEIGHT_TOLERANCE_GRAMS * 1.5, cw * (SCALE_WEIGHT_TOLERANCE_PERCENT / 100.0))
                if diff <= tolerance and diff < best_match_diff:
                    best_match_diff = diff
                    best_match_idx = idx
                    matched_actual_weight = cw

        if best_match_idx is not None:
            removed_item = self.cart[best_match_idx]
            item_name = removed_item["name"]
            
            # Remove the specific matched actual weight from list
            if removed_item.get("actual_weights") and matched_actual_weight in removed_item["actual_weights"]:
                removed_item["actual_weights"].remove(matched_actual_weight)

            # Decrement quantity
            removed_item["qty"] -= 1
            if removed_item["qty"] <= 0:
                del self.cart[best_match_idx]

            self.refresh_cart_display()

            # Show auto-closing notification popup (5 seconds)
            self._item_removed_overlay_active = True
            try:
                dlg = ItemRemovedOverlay(self, item_name, lost_weight, auto_close_secs=5)
                dlg.exec_()
            finally:
                self._item_removed_overlay_active = False

    def setup_ui(self):
        self.central = QWidget()
        self.setCentralWidget(self.central)
        self.main_layout = QVBoxLayout(self.central)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.setObjectName("stackedWidget")
        self.main_layout.addWidget(self.stacked_widget)
        
        # Create cart screen
        self.cart_screen = QWidget()
        self.cart_screen_layout = QVBoxLayout(self.cart_screen)
        self.cart_screen_layout.setContentsMargins(self.dp(14), self.dp(8), self.dp(14), self.dp(10))
        self.cart_screen_layout.setSpacing(self.dp(8))
        
        # Create payment screen
        self.payment_screen = QWidget()
        # Set white background on payment screen to prevent desktop visibility
        self.payment_screen.setStyleSheet("QWidget { background-color: white; }")
        self.payment_screen_layout = QVBoxLayout(self.payment_screen)
        self.payment_screen_layout.setContentsMargins(10, 10, 10, 10)
        self.payment_screen_layout.setSpacing(15)
        
        # Setup both screens
        self.setup_cart_screen()
        self.setup_payment_screen()
        self.setup_admin_screen()
        
        # Add screens to stacked widget
        self.stacked_widget.addWidget(self.cart_screen)
        self.stacked_widget.addWidget(self.payment_screen)
        self.stacked_widget.addWidget(self.admin_screen)
        
        # Idle Screen (sleep mode) with logo
        self.idle_screen = QWidget()
        idle_layout = QVBoxLayout(self.idle_screen)
        idle_layout.setAlignment(Qt.AlignCenter)
        # Add logo on idle screen
        self.idle_logo = QLabel()
        self.idle_logo.setAlignment(Qt.AlignCenter)
        try:
            base_dir = os.path.dirname(__file__)
            logo_path = os.path.join(base_dir, 'cart.png')
            if os.path.exists(logo_path):
                px = self.load_transparent_logo(logo_path, threshold=self.logo_threshold)
                if px is not None and not px.isNull():
                    self.idle_logo.setPixmap(px.scaled(self.dp(140), self.dp(140), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception:
            pass
        idle_layout.addWidget(self.idle_logo)
        idle_label = QLabel(f"Welcome to {STORE_NAME}\nScan your first item to begin")
        idle_label.setAlignment(Qt.AlignCenter)
        idle_label.setObjectName("idleLabel")
        idle_layout.addWidget(idle_label)
        self.stacked_widget.addWidget(self.idle_screen)
        
        self.apply_theme(self.current_theme)
        self.refresh_texts()
        # Ensure cart UI state is correct on startup (disables checkout button if empty)
        self.refresh_cart_display()

    def apply_card_shadow(self, widget):
        try:
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(24)
            shadow.setXOffset(0)
            shadow.setYOffset(6)
            # Slightly transparent black for soft elevation
            shadow.setColor(QColor(0, 0, 0, 80))
            widget.setGraphicsEffect(shadow)
        except Exception:
            # Graceful degrade if effect is not supported
            pass

    def animate_entrance(self, widget):
        try:
            eff = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(eff)
            widget.setVisible(True)
            anim = QPropertyAnimation(eff, b"opacity", self)
            anim.setDuration(450)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.start(QPropertyAnimation.DeleteWhenStopped)
        except Exception:
            pass

    def start_hero_animation(self, hero_widget: QWidget):
        try:
            # Subtle animation by alternating gradient stop positions
            if hasattr(self, "_hero_anim_timer") and self._hero_anim_timer is not None:
                self._hero_anim_timer.stop()
            self._hero_phase = 0
            self._hero_widget = hero_widget
            self._hero_anim_timer = QTimer(self)
            def tick():
                # phase toggles between 0 and 1 to slightly shift the gradient
                self._hero_phase = (self._hero_phase + 1) % 2
                if self._hero_phase == 0:
                    grad = f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {self.current_theme.accent}, stop:1 {self.current_theme.foreground})"
                else:
                    grad = f"qlineargradient(x1:1, y1:0, x2:0, y2:1, stop:0 {self.current_theme.accent}, stop:1 {self.current_theme.foreground})"
                self._hero_widget.setStyleSheet(
                    f"QFrame#hero {{ background: {grad}; border: 1px solid {self.current_theme.secondary}; border-radius: 14px; }}"
                )
            self._hero_anim_timer.timeout.connect(tick)
            self._hero_anim_timer.start(1800)
            tick()
        except Exception:
            pass

    def load_transparent_logo(self, path: str, threshold: int = 245) -> QPixmap:
        """Load an image and make nearly-white pixels transparent.
        threshold: 0-255; larger means more aggressive transparency.
        Returns a QPixmap, or None on failure.
        """
        try:
            img = QImage(path)
            if img.isNull():
                return None
            # Convert to ARGB so we can set alpha channel
            img = img.convertToFormat(QImage.Format_ARGB32)
            w, h = img.width(), img.height()
            for y in range(h):
                for x in range(w):
                    c = QColor(img.pixel(x, y))
                    if c.red() >= threshold and c.green() >= threshold and c.blue() >= threshold:
                        c.setAlpha(0)
                        img.setPixelColor(x, y, c)
            return QPixmap.fromImage(img)
        except Exception:
            return None

    def refresh_logos(self):
        """Re-render app bar and hero logos using the current transparency threshold."""
        try:
            base_dir = os.path.dirname(__file__)
            # Update app bar logo
            if hasattr(self, 'appbar_logo') and self.appbar_logo is not None:
                app_logo_path = os.path.join(base_dir, 'cart.png')
                if os.path.exists(app_logo_path):
                    px = self.load_transparent_logo(app_logo_path, threshold=self.logo_threshold)
                    if px is not None and not px.isNull():
                        self.appbar_logo.setPixmap(px.scaled(self.dp(44), self.dp(44), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            # Update hero logo
            if hasattr(self, 'hero_logo') and self.hero_logo is not None:
                px = None
                for p in [os.path.join(base_dir, 'logo.png'), os.path.join(base_dir, 'cart.png')]:
                    if os.path.exists(p):
                        px = self.load_transparent_logo(p, threshold=self.logo_threshold)
                        if px is not None and not px.isNull():
                            break
                if px is not None and not px.isNull():
                    self.hero_logo.setPixmap(px.scaled(self.dp(140), self.dp(140), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception:
            pass

    def setup_cart_screen(self):
        # App Bar (header wrapped in a frame for app-like feel)
        app_bar = QFrame()
        app_bar.setObjectName("appBar")
        app_bar_layout = QHBoxLayout(app_bar)
        app_bar_layout.setContentsMargins(self.dp(16), self.dp(8), self.dp(16), self.dp(8))
        # Brand group: logo + store name together
        brand = QWidget()
        brand_layout = QHBoxLayout(brand)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(self.dp(8))
        self.appbar_logo = None
        try:
            logo_path = os.path.join(os.path.dirname(__file__), "cart.png")
            if os.path.exists(logo_path):
                self.appbar_logo = QLabel()
                pix = self.load_transparent_logo(logo_path, threshold=self.logo_threshold)
                if pix is not None and not pix.isNull():
                    self.appbar_logo.setPixmap(pix.scaled(self.dp(40), self.dp(40), Qt.KeepAspectRatio, Qt.SmoothTransformation))
                    brand_layout.addWidget(self.appbar_logo)
        except Exception:
            self.appbar_logo = None
        self.store_label = QLabel(STORE_NAME)
        self.store_label.setObjectName("storeLabel")
        brand_layout.addWidget(self.store_label)
        app_bar_layout.addWidget(brand)
        app_bar_layout.addStretch()

        self.admin_panel_btn = QToolButton()
        self.admin_panel_btn.setObjectName("adminBtn")
        self.admin_panel_btn.setText("⚙")
        self.admin_panel_btn.setFixedSize(self.dp(52), self.dp(52))    # Restrict width only
        app_bar_layout.addWidget(self.admin_panel_btn)
        self.admin_panel_btn.clicked.connect(self.open_admin_panel)
    
        self.theme_btn = QToolButton()
        self.theme_btn.setObjectName("themeBtn")
        self.theme_btn.setText("🌙" if self.current_theme.name == "light" else "☀️")
        self.theme_btn.clicked.connect(self.toggle_theme)
        self.theme_btn.setFixedSize(self.dp(52), self.dp(52))
        app_bar_layout.addWidget(self.theme_btn)
        self.cart_screen_layout.addWidget(app_bar)
        self.lang_combo = QComboBox()
        self.lang_combo.addItems(["English", "Hindi", "Gujarati"])
        # --- FIX STARTS HERE ---
        # Correctly map the loaded language to the dropdown index to support all 3 languages
        lang_map = {'en': 0, 'hi': 1, 'gu': 2}
        initial_index = lang_map.get(self.language, 0) # Default to English if not found
        self.lang_combo.setCurrentIndex(initial_index)
        # --- FIX ENDS HERE ---
        self.lang_combo.currentIndexChanged.connect(self.change_language)
        self.lang_combo.setMinimumHeight(self.dp(52))
        app_bar_layout.addWidget(self.lang_combo)

        self.hidden_input = BarcodeLineEdit()
        self.hidden_input.setObjectName("barcodeInput")
        self.hidden_input.setPlaceholderText("🔍  Scan or enter barcode")
        self.hidden_input.returnPressed.connect(self.on_barcode_scanned)
        self.cart_screen_layout.addWidget(self.hidden_input)

        self.cart_table = QTableWidget(0, 5)
        self.cart_table.setObjectName("cartTable")
        self.cart_table.setShowGrid(False)
        self.cart_table.verticalHeader().setVisible(False)
        self.cart_table.setHorizontalHeaderLabels(["Product", "Price", "Qty", "Total", ""]) 
        for i, width in enumerate([QHeaderView.Stretch, QHeaderView.ResizeToContents, QHeaderView.ResizeToContents, QHeaderView.ResizeToContents, QHeaderView.ResizeToContents]):
            self.cart_table.horizontalHeader().setSectionResizeMode(i, width)
        # Ensure the last column (remove button) does not shrink and clip the button
        self.cart_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        self.cart_table.setSelectionBehavior(QTableWidget.SelectRows)
        # Increase cart table font size for readability on 7" display
        try:
            f = self.cart_table.font()
            f.setPointSize(self.fs_px(18))
            self.cart_table.setFont(f)
            hf = self.cart_table.horizontalHeader().font()
            hf.setPointSize(self.fs_px(16))
            self.cart_table.horizontalHeader().setFont(hf)
        except Exception:
            pass
        # Make rows tall enough so +/- controls are clearly visible
        self.cart_table.verticalHeader().setDefaultSectionSize(self.dp(80))
        self.cart_table.setIconSize(QSize(self.dp(70), self.dp(70)))
        # Ensure Qty column is wide enough for +/- controls
        self.cart_table.setColumnWidth(2, self.dp(190))
        # Ensure Remove column is wide enough for the button (wider to prevent clipping)
        self.cart_table.setColumnWidth(4, self.dp(100))
        
        # Enable kinetic swipe scrolling for touch
        QScroller.grabGesture(self.cart_table.viewport(), QScroller.LeftMouseButtonGesture)
        
        self.cart_screen_layout.addWidget(self.cart_table)
        # Add drop shadow to table to elevate it
        self.apply_card_shadow(self.cart_table)
        self.animate_entrance(self.cart_table)

        # Cart actions
        cart_actions = QHBoxLayout()
        self.clear_btn = QPushButton("🗑 Clear Cart")
        self.clear_btn.setObjectName("clearBtn")
        self.clear_btn.clicked.connect(self.clear_cart)
        self.clear_btn.setMinimumHeight(self.dp(44))
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        cart_actions.addWidget(self.clear_btn)

        cart_actions.addStretch()

        self.cart_weight_label = QLabel("🛒 Trolley: 0.0g  🟢")
        self.cart_weight_label.setObjectName("cartWeightLabel")
        self.cart_weight_label.setStyleSheet(f"font-size: {self.fs_px(15)}px; font-weight: 700; color: #0284c7; padding-right: 12px;")
        cart_actions.addWidget(self.cart_weight_label)

        self.total_label = QLabel("Total: ₹0.00")
        self.total_label.setObjectName("totalLabel")
        cart_actions.addWidget(self.total_label)
        self.cart_screen_layout.addLayout(cart_actions)
        
        
        self.pay_btn = QPushButton("Checkout")
        # Style as primary call-to-action
        self.pay_btn.setObjectName("primaryCta")
        self.pay_btn.setMinimumHeight(self.dp(64))
        self.cart_screen_layout.addWidget(self.pay_btn)
        
        self.pay_btn.clicked.connect(self.on_checkout_clicked)

    def setup_payment_screen(self):
        # Create a container for webview and overlay keyboard with toggle button
        payment_container = QWidget()
        # Set solid white background to prevent desktop from showing through
        payment_container.setStyleSheet("background-color: white;")
        payment_container_layout = QVBoxLayout(payment_container)
        payment_container_layout.setContentsMargins(0, 0, 0, 0)
        payment_container_layout.setSpacing(0)
        
        # Add small keyboard toggle button in top-right corner
        top_bar = QWidget()
        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(0, 5, 5, 0)
        top_bar_layout.addStretch()
        
        # Qt Virtual Keyboard handles input automatically, no toggle button needed
        payment_container_layout.addWidget(top_bar)
        
        # Create a fullscreen loading overlay to prevent desktop from showing during transition
        self.loading_overlay = QWidget(payment_container)
        self.loading_overlay.setStyleSheet("background-color: white;")
        self.loading_overlay.setGeometry(0, 0, 2000, 2000)  # Large enough to cover screen
        self.loading_overlay.raise_()
        self.loading_overlay.setVisible(False)
        
        # Add loading text to overlay
        overlay_layout = QVBoxLayout(self.loading_overlay)
        overlay_layout.setAlignment(Qt.AlignCenter)
        loading_label = QLabel("Loading payment...")
        loading_label.setAlignment(Qt.AlignCenter)
        loading_label.setStyleSheet("font-size: 24px; color: #333;")
        overlay_layout.addWidget(loading_label)
        
        self.webview = QWebEngineView()
        
        # Set solid white background to prevent desktop from showing through during loading
        self.webview.setStyleSheet("background-color: white;")
        
        # Set custom page to capture console messages
        custom_page = CustomWebEnginePage(self.webview)
        custom_page.console_message_callback = self.handle_console_message
        # Set page background color as well
        custom_page.setBackgroundColor(QColor(255, 255, 255))
        self.webview.setPage(custom_page)
        
        self.webview.setVisible(False)
        
        # Enable touch scrolling for the webview
        self.webview.setAttribute(Qt.WA_AcceptTouchEvents, True)
        self.webview.settings().setAttribute(self.webview.settings().WebAttribute.FocusOnNavigationEnabled, False)
        
        try:
            # Enlarge Razorpay UI inside the webview for 7" display - increase zoom significantly
            self.webview.setZoomFactor(0.85)
        except Exception:
            pass
        
        # Enable kinetic touch scrolling for the webview
        # Note: QWebEngineView handles scrolling internally, so we enable touch events
        # and let the web engine handle the scrolling behavior
        try:
            QScroller.grabGesture(self.webview, QScroller.LeftMouseButtonGesture)
        except Exception as e:
            print(f"Could not enable QScroller for webview: {e}")
        
        self.webview.urlChanged.connect(self.on_webview_url_changed)
        # Inject keyboard script when page loads
        self.webview.loadFinished.connect(self.inject_keyboard_for_razorpay)
        # Handle load completion (success or failure)
        self.webview.loadFinished.connect(self.on_webview_load_finished)
        # Hide loading overlay when webview starts loading
        self.webview.loadStarted.connect(self.hide_loading_overlay)
        payment_container_layout.addWidget(self.webview, 1)
        
        # Loading timeout timer - 10 seconds to detect network failures during page load
        self.webview_timeout_timer = QTimer(self)
        self.webview_timeout_timer.timeout.connect(self.on_webview_timeout)
        self.webview_timeout_timer.setSingleShot(True)
        
        # Flag to prevent multiple simultaneous error triggers with mutex for thread safety
        self.payment_error_triggered = False
        self.payment_error_mutex = QMutex()
        
        # Counter for ChunkLoadError to detect network failures after page load
        self.chunk_error_count = 0
        
        # Qt Virtual Keyboard handles input automatically
        # No need for custom OnScreenKeyboard overlay
        
        self.payment_screen_layout.addWidget(payment_container, 1)
        
        # Pre-load webview with a blank white page to ensure it's fully rendered
        # This eliminates any rendering glitch when switching to payment screen
        blank_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {
                    margin: 0;
                    padding: 0;
                    background-color: white;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    font-family: Arial, sans-serif;
                }
                .loading {
                    text-align: center;
                    color: #333;
                }
            </style>
        </head>
        <body>
            <div class="loading">
                <h2>Loading payment...</h2>
            </div>
        </body>
        </html>
        """
        self.webview.setHtml(blank_html)
    
    def hide_loading_overlay(self):
        """Hide the loading overlay when webview starts loading"""
        try:
            if hasattr(self, 'loading_overlay'):
                self.loading_overlay.setVisible(False)
        except Exception as e:
            print(f"Error hiding loading overlay: {e}")
    

        

    def setup_admin_screen(self):
        self.admin_screen = QWidget()
        layout = QVBoxLayout(self.admin_screen)
        layout.setContentsMargins(self.dp(14), self.dp(8), self.dp(14), self.dp(10))
        layout.setSpacing(self.dp(8))

        # ── Header bar ──
        header = QHBoxLayout()
        header.setSpacing(self.dp(12))
        back_btn = QPushButton("← Back to Kiosk")
        back_btn.setObjectName("linkBtn")
        back_btn.clicked.connect(self.show_cart_screen)
        header.addWidget(back_btn)
        header.addStretch()
        title = QLabel("Admin Panel")
        title.setObjectName("storeLabel")
        header.addWidget(title)
        header.addStretch()
        
        self.zero_scale_btn = QPushButton("⚖️ Calibrate")
        self.zero_scale_btn.setStyleSheet("""
            QPushButton { background: #f59e0b; color: white; border: none; 
                          border-radius: 8px; padding: 8px 16px; font-weight: 600; }
            QPushButton:hover { background: #d97706; }
        """)
        self.zero_scale_btn.clicked.connect(self.start_startup_tare)
        header.addWidget(self.zero_scale_btn)

        # Exit app button
        self.admin_exit_btn = QPushButton("⏻ Exit App")
        self.admin_exit_btn.setStyleSheet("""
            QPushButton { background: #ef4444; color: white; border: none; 
                          border-radius: 8px; padding: 8px 16px; font-weight: 600; }
            QPushButton:hover { background: #dc2626; }
        """)
        self.admin_exit_btn.clicked.connect(self.admin_exit)
        header.addWidget(self.admin_exit_btn)
        layout.addLayout(header)

        # ── Tab Widget ──
        self.admin_tabs = QTabWidget()
        self.admin_tabs.setObjectName("adminTabs")

        # --- Tab 1: Dashboard ---
        dash_tab = QWidget()
        dash_layout = QVBoxLayout(dash_tab)
        dash_layout.setContentsMargins(self.dp(8), self.dp(12), self.dp(8), self.dp(8))
        dash_layout.setSpacing(self.dp(12))

        # Stat cards row
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(self.dp(10))
        self.stat_today_rev = self._create_stat_card("₹0", "Today's Revenue", "#6366f1")
        self.stat_today_txn = self._create_stat_card("0", "Today's Orders", "#10b981")
        self.stat_total_rev = self._create_stat_card("₹0", "Total Revenue", "#f59e0b")
        self.stat_success   = self._create_stat_card("0%", "Success Rate", "#8b5cf6")
        cards_layout.addWidget(self.stat_today_rev)
        cards_layout.addWidget(self.stat_today_txn)
        cards_layout.addWidget(self.stat_total_rev)
        cards_layout.addWidget(self.stat_success)
        dash_layout.addLayout(cards_layout)

        # Recent transactions mini-table
        recent_label = QLabel("Recent Transactions")
        recent_label.setStyleSheet(f"font-size: {self.fs_px(16)}px; font-weight: 700; margin-top: {self.dp(4)}px;")
        dash_layout.addWidget(recent_label)

        self.dash_recent_table = QTableWidget(0, 4)
        self.dash_recent_table.setObjectName("cartTable")
        self.dash_recent_table.setShowGrid(False)
        self.dash_recent_table.verticalHeader().setVisible(False)
        self.dash_recent_table.setHorizontalHeaderLabels(["Date", "Amount", "Status", "Payment ID"])
        self.dash_recent_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.dash_recent_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.dash_recent_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.dash_recent_table.verticalHeader().setDefaultSectionSize(self.dp(40))
        QScroller.grabGesture(self.dash_recent_table.viewport(), QScroller.LeftMouseButtonGesture)
        self.dash_recent_table.cellClicked.connect(
            lambda r, c: self.show_transaction_details(self.dash_recent_table.item(r, 3).text() if self.dash_recent_table.item(r, 3) else "")
        )
        dash_layout.addWidget(self.dash_recent_table)

        self.admin_tabs.addTab(dash_tab, "📊 Dashboard")

        # --- Tab 2: Transactions ---
        txn_tab = QWidget()
        txn_layout = QVBoxLayout(txn_tab)
        txn_layout.setContentsMargins(self.dp(8), self.dp(12), self.dp(8), self.dp(8))
        txn_layout.setSpacing(self.dp(8))

        # Filter row
        filter_row = QHBoxLayout()
        filter_row.setSpacing(self.dp(8))
        filter_label = QLabel("Show:")
        filter_label.setStyleSheet(f"font-weight: 600;")
        filter_row.addWidget(filter_label)
        self.txn_filter_combo = QComboBox()
        self.txn_filter_combo.addItems(["All", "Today", "This Week", "This Month", "Captured", "Failed"])
        self.txn_filter_combo.currentIndexChanged.connect(self.refresh_admin_transactions)
        self.txn_filter_combo.setMinimumHeight(self.dp(40))
        filter_row.addWidget(self.txn_filter_combo)
        filter_row.addStretch()
        
        # Transaction count badge
        self.txn_count_label = QLabel("0 transactions")
        self.txn_count_label.setStyleSheet(f"font-size: {self.fs_px(12)}px; color: #94a3b8;")
        filter_row.addWidget(self.txn_count_label)
        txn_layout.addLayout(filter_row)

        # Full transaction table
        self.admin_txn_table = QTableWidget(0, 6)
        self.admin_txn_table.setObjectName("cartTable")
        self.admin_txn_table.setShowGrid(False)
        self.admin_txn_table.verticalHeader().setVisible(False)
        self.admin_txn_table.setHorizontalHeaderLabels(["#", "Date", "Amount", "Items", "Status", "Payment ID"])
        self.admin_txn_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.admin_txn_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.admin_txn_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.admin_txn_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.admin_txn_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.admin_txn_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.admin_txn_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.admin_txn_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.admin_txn_table.verticalHeader().setDefaultSectionSize(self.dp(40))
        QScroller.grabGesture(self.admin_txn_table.viewport(), QScroller.LeftMouseButtonGesture)
        self.admin_txn_table.cellClicked.connect(
            lambda r, c: self.show_transaction_details(self.admin_txn_table.item(r, 5).text() if self.admin_txn_table.item(r, 5) else "")
        )
        txn_layout.addWidget(self.admin_txn_table)

        self.admin_tabs.addTab(txn_tab, "📋 Transactions")

        # --- Tab 3: Inventory ---
        inv_tab = QWidget()
        inv_layout = QVBoxLayout(inv_tab)
        inv_layout.setContentsMargins(self.dp(8), self.dp(12), self.dp(8), self.dp(8))
        inv_layout.setSpacing(self.dp(8))

        # Inventory Action Toolbar
        inv_actions = QHBoxLayout()
        inv_actions.setSpacing(self.dp(10))
        
        self.btn_inv_add = QPushButton("➕ Add Item")
        self.btn_inv_add.clicked.connect(self.admin_inv_add)
        inv_actions.addWidget(self.btn_inv_add)
        
        self.btn_inv_edit = QPushButton("✏️ Edit Item")
        self.btn_inv_edit.clicked.connect(self.admin_inv_edit)
        inv_actions.addWidget(self.btn_inv_edit)
        
        self.btn_inv_delete = QPushButton("🗑️ Delete Item")
        self.btn_inv_delete.setStyleSheet("color: #ef4444;")
        self.btn_inv_delete.clicked.connect(self.admin_inv_delete)
        inv_actions.addWidget(self.btn_inv_delete)
        
        inv_actions.addStretch()
        
        self.btn_inv_import = QPushButton("📁 Import CSV")
        self.btn_inv_import.clicked.connect(self.admin_inv_import_csv)
        inv_actions.addWidget(self.btn_inv_import)
        
        inv_layout.addLayout(inv_actions)
        
        # Inventory stats row
        inv_header = QHBoxLayout()
        self.inv_count_label = QLabel("0 products")
        self.inv_count_label.setStyleSheet(f"font-size: {self.fs_px(14)}px; font-weight: 600;")
        inv_header.addWidget(self.inv_count_label)
        inv_header.addStretch()
        self.inv_low_stock_label = QLabel("")
        self.inv_low_stock_label.setStyleSheet(f"font-size: {self.fs_px(12)}px; color: #ef4444; font-weight: 600;")
        inv_header.addWidget(self.inv_low_stock_label)
        inv_layout.addLayout(inv_header)

        # Inventory table
        self.admin_inv_table = QTableWidget(0, 5)
        self.admin_inv_table.setObjectName("cartTable")
        self.admin_inv_table.setShowGrid(False)
        self.admin_inv_table.verticalHeader().setVisible(False)
        self.admin_inv_table.setHorizontalHeaderLabels(["Barcode", "Product", "Price", "GST %", "Stock"])
        self.admin_inv_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.admin_inv_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.admin_inv_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.admin_inv_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.admin_inv_table.setSelectionMode(QTableWidget.SingleSelection)
        self.admin_inv_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.admin_inv_table.verticalHeader().setDefaultSectionSize(self.dp(40))
        QScroller.grabGesture(self.admin_inv_table.viewport(), QScroller.LeftMouseButtonGesture)
        inv_layout.addWidget(self.admin_inv_table)

        self.admin_tabs.addTab(inv_tab, "📦 Inventory")

        # --- Tab 4: Settings ---
        settings_tab = QWidget()
        settings_layout = QVBoxLayout(settings_tab)
        settings_layout.setContentsMargins(self.dp(16), self.dp(16), self.dp(16), self.dp(16))
        settings_layout.setSpacing(self.dp(12))

        form_layout = QGridLayout()
        form_layout.setVerticalSpacing(self.dp(12))
        form_layout.setHorizontalSpacing(self.dp(12))

        row = 0
        form_layout.addWidget(QLabel(self.t("Store Name:")), row, 0)
        self.settings_store_name = QLineEdit()
        form_layout.addWidget(self.settings_store_name, row, 1)

        row += 1
        form_layout.addWidget(QLabel(self.t("Store Address:")), row, 0)
        self.settings_store_address = QLineEdit()
        form_layout.addWidget(self.settings_store_address, row, 1)

        row += 1
        form_layout.addWidget(QLabel(self.t("Store GSTIN:")), row, 0)
        self.settings_store_gstin = QLineEdit()
        form_layout.addWidget(self.settings_store_gstin, row, 1)

        row += 1
        form_layout.addWidget(QLabel(self.t("UPI ID:")), row, 0)
        self.settings_upi_id = QLineEdit()
        form_layout.addWidget(self.settings_upi_id, row, 1)

        row += 1
        form_layout.addWidget(QLabel(self.t("Razorpay Enabled:")), row, 0)
        self.settings_razorpay = QComboBox()
        self.settings_razorpay.addItems(["Yes", "No"])
        form_layout.addWidget(self.settings_razorpay, row, 1)

        row += 1
        form_layout.addWidget(QLabel(self.t("Logo Transparency Threshold:")), row, 0)
        self.settings_threshold = QSpinBox()
        self.settings_threshold.setRange(200, 255)
        form_layout.addWidget(self.settings_threshold, row, 1)

        settings_layout.addLayout(form_layout)
        settings_layout.addStretch()

        # Save button
        save_btn = QPushButton("💾 Save Settings")
        save_btn.setObjectName("primaryCta")
        save_btn.setMinimumHeight(self.dp(50))
        save_btn.clicked.connect(self._save_admin_settings)
        settings_layout.addWidget(save_btn)

        self.admin_tabs.addTab(settings_tab, "⚙️ Settings")

        # Refresh data when switching tabs
        self.admin_tabs.currentChanged.connect(self._on_admin_tab_changed)

        layout.addWidget(self.admin_tabs)

    def _create_stat_card(self, value_text, label_text, accent_color):
        """Create a styled stat card widget for the dashboard."""
        card = QFrame()
        card.setObjectName("statCard")
        card.setStyleSheet(f"""
            QFrame#statCard {{
                background: {self.current_theme.foreground};
                border-radius: {self.dp(12)}px;
                border-left: 4px solid {accent_color};
                padding: {self.dp(8)}px;
            }}
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(self.dp(14), self.dp(10), self.dp(14), self.dp(10))
        card_layout.setSpacing(self.dp(2))

        val = QLabel(value_text)
        val.setObjectName("statValue")
        val.setStyleSheet(f"font-size: {self.fs_px(22)}px; font-weight: 800; color: {accent_color};")
        card_layout.addWidget(val)

        lbl = QLabel(label_text)
        lbl.setStyleSheet(f"font-size: {self.fs_px(11)}px; color: #94a3b8; font-weight: 600;")
        card_layout.addWidget(lbl)

        # Store reference to value label for updates
        card._value_label = val
        return card

    def _on_admin_tab_changed(self, index):
        """Refresh data when admin tab changes."""
        if index == 0:
            self.refresh_admin_dashboard()
        elif index == 1:
            self.refresh_admin_transactions()
        elif index == 2:
            self.refresh_admin_inventory()
        elif index == 3:
            self._load_admin_settings()

    def refresh_admin_dashboard(self):
        """Refresh dashboard stat cards and recent transactions."""
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            with sqlite3.connect(DB_PATH) as conn:
                cur = conn.cursor()

                # Today's captured stats
                row = cur.execute(
                    "SELECT COUNT(*), COALESCE(SUM(amount),0) FROM transactions WHERE date LIKE ? AND status='captured'",
                    (f"{today}%",)
                ).fetchone()
                today_count = row[0] or 0
                today_rev = (row[1] or 0) / 100.0  # amount is in paise

                # All-time captured stats
                row = cur.execute(
                    "SELECT COUNT(*), COALESCE(SUM(amount),0) FROM transactions WHERE status='captured'"
                ).fetchone()
                total_rev = (row[1] or 0) / 100.0

                # Success rate
                row = cur.execute(
                    "SELECT COUNT(*), SUM(CASE WHEN status='captured' THEN 1 ELSE 0 END) FROM transactions"
                ).fetchone()
                total_all = row[0] or 0
                total_ok = row[1] or 0
                rate = (total_ok / total_all * 100) if total_all > 0 else 0

                # Recent 10 transactions
                recent = cur.execute(
                    "SELECT date, amount, status, razorpay_id FROM transactions ORDER BY id DESC LIMIT 10"
                ).fetchall()

            # Update cards
            self.stat_today_rev._value_label.setText(f"₹{today_rev:,.2f}")
            self.stat_today_txn._value_label.setText(str(today_count))
            self.stat_total_rev._value_label.setText(f"₹{total_rev:,.2f}")
            self.stat_success._value_label.setText(f"{rate:.0f}%")

            # Update recent table
            self.dash_recent_table.setRowCount(len(recent))
            for i, row in enumerate(recent):
                self.dash_recent_table.setItem(i, 0, QTableWidgetItem(str(row[0] or '')))
                amt = (row[1] or 0) / 100.0
                self.dash_recent_table.setItem(i, 1, QTableWidgetItem(f"₹{amt:.2f}"))
                status_item = QTableWidgetItem(str(row[2] or ''))
                self._style_status_item(status_item, row[2])
                self.dash_recent_table.setItem(i, 2, status_item)
                self.dash_recent_table.setItem(i, 3, QTableWidgetItem(str(row[3] or '')))
        except Exception as e:
            print(f"[Admin] Dashboard refresh error: {e}")

    def refresh_admin_transactions(self):
        """Refresh the full transactions table with optional filter."""
        try:
            filter_idx = self.txn_filter_combo.currentIndex() if hasattr(self, 'txn_filter_combo') else 0
            today = datetime.now().strftime('%Y-%m-%d')

            # Build query based on filter
            where = ""
            params = ()
            if filter_idx == 1:    # Today
                where = "WHERE date LIKE ?"
                params = (f"{today}%",)
            elif filter_idx == 2:  # This Week (last 7 days)
                where = "WHERE date >= date('now', '-7 days')"
            elif filter_idx == 3:  # This Month
                month = datetime.now().strftime('%Y-%m')
                where = "WHERE date LIKE ?"
                params = (f"{month}%",)
            elif filter_idx == 4:  # Captured only
                where = "WHERE status='captured'"
            elif filter_idx == 5:  # Failed only
                where = "WHERE status='failed'"

            with sqlite3.connect(DB_PATH) as conn:
                cur = conn.cursor()
                rows = cur.execute(
                    f"SELECT date, amount, status, razorpay_id FROM transactions {where} ORDER BY id DESC LIMIT 500",
                    params
                ).fetchall()

            self.txn_count_label.setText(f"{len(rows)} transaction{'s' if len(rows) != 1 else ''}")
            self.admin_txn_table.setRowCount(len(rows))

            # Load items mapping from CSV
            payment_items = {}
            try:
                import csv, os
                if os.path.exists('transactions.csv'):
                    with open('transactions.csv', newline='', encoding='utf-8') as f:
                        for r in csv.DictReader(f):
                            pid = r.get('payment_id', '')
                            if pid:
                                name = r.get('item_name', 'Unknown')
                                qty = r.get('item_quantity', '1')
                                if pid not in payment_items:
                                    payment_items[pid] = []
                                payment_items[pid].append(f"{qty}x {name}")
            except Exception as e:
                print(f"[Admin] Items CSV load error: {e}")

            for i, row in enumerate(rows):
                # Row number
                num_item = QTableWidgetItem(str(i + 1))
                num_item.setTextAlignment(Qt.AlignCenter)
                self.admin_txn_table.setItem(i, 0, num_item)
                # Date
                self.admin_txn_table.setItem(i, 1, QTableWidgetItem(str(row[0] or '')))
                # Amount
                amt = (row[1] or 0) / 100.0
                amt_item = QTableWidgetItem(f"₹{amt:.2f}")
                amt_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.admin_txn_table.setItem(i, 2, amt_item)
                # Items
                pid = str(row[3] or '')
                items_text = ", ".join(payment_items.get(pid, []))
                if not items_text:
                    items_text = "-"
                items_item = QTableWidgetItem(items_text)
                items_item.setToolTip(items_text)  # Show full text on hover
                self.admin_txn_table.setItem(i, 3, items_item)
                # Status with color
                status_item = QTableWidgetItem(str(row[2] or ''))
                self._style_status_item(status_item, row[2])
                self.admin_txn_table.setItem(i, 4, status_item)
                # Payment ID
                self.admin_txn_table.setItem(i, 5, QTableWidgetItem(pid))
        except Exception as e:
            print(f"[Admin] Transactions refresh error: {e}")

    def show_transaction_details(self, pid):
        if not pid or pid == "-":
            return
            
        # Collect details from CSV
        items = []
        total_amt = "0.00"
        tx_date = ""
        status = ""
        try:
            import csv, os
            if os.path.exists('transactions.csv'):
                with open('transactions.csv', newline='', encoding='utf-8') as f:
                    for r in csv.DictReader(f):
                        if r.get('payment_id') == pid:
                            name = r.get('item_name', 'Unknown')
                            qty = r.get('item_quantity', '1')
                            sub = r.get('item_subtotal', '0.00')
                            items.append({'name': name, 'qty': qty, 'subtotal': sub})
                            if not total_amt or total_amt == "0.00":
                                total_amt = r.get('transaction_total', '0.00')
                                tx_date = f"{r.get('transaction_date', '')} {r.get('transaction_time', '')}"
                                status = r.get('payment_status', '')
        except Exception as e:
            print(f"Error loading details: {e}")
            
        from ui_components import OverlayDialog
        dlg = OverlayDialog(self)
        layout = QVBoxLayout()
        
        receipt_html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: 'Courier New', Courier, monospace; font-size: 14px; line-height: 1.4; }}
                .center {{ text-align: center; }}
                .right {{ text-align: right; }}
                .left {{ text-align: left; }}
                .bold {{ font-weight: bold; }}
                table {{ width: 100%; border-collapse: collapse; }}
                .header-table td {{ padding: 3px; }}
                .items-table th, .items-table td {{ padding: 5px; border-bottom: 1px dashed #555; }}
                .totals-table td {{ padding: 4px; }}
                .line {{ border-top: 2px dashed #555; margin: 6px 0; }}
                h3 {{ font-size: 18px; margin: 0; }}
            </style>
        </head>
        <body>
            <div class="center">
                <h3>{STORE_NAME}</h3>
                <p style="margin:3px 0;">{self.settings.get("store_address", "")}</p>
                <p style="margin:3px 0;"><b>GSTIN: {self.settings.get("store_gstin", "")}</b></p>
                <h4 style="margin:6px 0;">Tax Invoice (Copy)</h4>
            </div>
            <div class="line"></div>
            <table class="header-table">
                <tr>
                    <td class="left">Date: {tx_date}</td>
                </tr>
                <tr>
                    <td class="left">Payment ID: {pid}</td>
                </tr>
                <tr>
                    <td class="left">Status: {status.title()}</td>
                </tr>
            </table>
            <div class="line"></div>
            <table class="items-table">
                <thead>
                    <tr>
                        <th class="left">PARTICULARS</th>
                        <th class="right">QTY</th>
                        <th class="right">RATE</th>
                        <th class="right">VALUE</th>
                    </tr>
                </thead>
                <tbody>
        """
        for itm in items:
            rate = float(itm['subtotal']) / float(itm['qty']) if float(itm['qty']) > 0 else 0
            receipt_html += f"""
                <tr>
                    <td class="left">{itm['name']}</td>
                    <td class="right">{itm['qty']}</td>
                    <td class="right">{rate:.2f}</td>
                    <td class="right">{float(itm['subtotal']):.2f}</td>
                </tr>
            """
        
        receipt_html += f"""
                </tbody>
            </table>
            <div class="line" style="border-style: solid; border-width: 2px;"></div>
            <table class="totals-table">
                <tr>
                    <td class="left bold" style="font-size: 16px;">GRAND TOTAL</td>
                    <td class="right bold" style="font-size: 16px;">₹{total_amt}</td>
                </tr>
            </table>
            <div class="line" style="border-style: solid; border-width: 2px;"></div>
            <div class="center" style="margin-top:10px;">
                <p style="margin:2px 0;">Thank You! Visit Again!</p>
            </div>
        </body>
        </html>
        """
        
        receipt_text = QTextEdit()
        receipt_text.setReadOnly(True)
        receipt_text.setMinimumWidth(450)
        receipt_text.setMinimumHeight(400)
        receipt_text.setStyleSheet(f"border: 1px solid {self.current_theme.secondary}; border-radius: 8px; background: white; color: black;")
        receipt_text.setHtml(receipt_html)
        layout.addWidget(receipt_text)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        def save_to_pdf():
            from PySide6.QtWidgets import QFileDialog
            from PySide6.QtGui import QPdfWriter, QPageSize, QPageLayout
            from PySide6.QtCore import QMarginsF
            fname, _ = QFileDialog.getSaveFileName(self, "Save Receipt as PDF", f"Receipt_{pid}.pdf", "PDF Files (*.pdf)")
            if fname:
                try:
                    writer = QPdfWriter(fname)
                    # Force screen DPI (96) so px units scale correctly on the PDF
                    writer.setResolution(96)
                    # Use A5 for receipts
                    writer.setPageSize(QPageSize.A5)
                    writer.setPageMargins(QMarginsF(10, 10, 10, 10), QPageLayout.Millimeter)
                    
                    receipt_text.document().print_(writer)
                    self.show_message("Success", f"Receipt seamlessly saved to\n{fname}", "info")
                except Exception as e:
                    self.show_message("Error", f"Could not save PDF: {str(e)}", "error")

        pdf_btn = QPushButton("Save as PDF")
        pdf_btn.setMinimumHeight(self.dp(45))
        pdf_btn.clicked.connect(save_to_pdf)
        btn_layout.addWidget(pdf_btn)
        
        close_btn = QPushButton("Close")
        close_btn.setObjectName("primaryCta")
        close_btn.setMinimumHeight(self.dp(45))
        close_btn.clicked.connect(dlg.accept)
        btn_layout.addWidget(close_btn)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        dlg.add_layout(layout)
        dlg.exec_()


    def refresh_admin_inventory(self):
        """Refresh the product inventory table."""
        try:
            with sqlite3.connect(DB_PATH) as conn:
                cur = conn.cursor()
                rows = cur.execute(
                    "SELECT barcode, name, price, gst_percent, quantity FROM products ORDER BY name"
                ).fetchall()

            low_stock = sum(1 for r in rows if (r[4] or 0) <= 5 and (r[4] or 0) > 0)
            out_of_stock = sum(1 for r in rows if (r[4] or 0) == 0)
            self.inv_count_label.setText(f"{len(rows)} products")
            alerts = []
            if low_stock > 0:
                alerts.append(f"⚠ {low_stock} low stock")
            if out_of_stock > 0:
                alerts.append(f"❌ {out_of_stock} out of stock")
            self.inv_low_stock_label.setText("  ·  ".join(alerts))

            self.admin_inv_table.setRowCount(len(rows))
            for i, row in enumerate(rows):
                qty = row[4] or 0
                # Barcode
                self.admin_inv_table.setItem(i, 0, QTableWidgetItem(str(row[0] or '')))
                # Name
                self.admin_inv_table.setItem(i, 1, QTableWidgetItem(str(row[1] or '')))
                # Price
                price_item = QTableWidgetItem(f"₹{row[2]:.2f}")
                price_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.admin_inv_table.setItem(i, 2, price_item)
                # GST %
                gst_item = QTableWidgetItem(f"{row[3]:.1f}%")
                gst_item.setTextAlignment(Qt.AlignCenter)
                self.admin_inv_table.setItem(i, 3, gst_item)
                # Stock with color
                stock_text = str(qty) if qty > 0 else "OUT"
                stock_item = QTableWidgetItem(stock_text)
                stock_item.setTextAlignment(Qt.AlignCenter)
                if qty == 0:
                    stock_item.setForeground(QColor("#ef4444"))
                elif qty <= 5:
                    stock_item.setForeground(QColor("#f59e0b"))
                else:
                    stock_item.setForeground(QColor("#10b981"))
                self.admin_inv_table.setItem(i, 4, stock_item)
        except Exception as e:
            print(f"[Admin] Inventory refresh error: {e}")

    def _open_product_form(self, title, existing_data=None):
        from ui_components import OverlayDialog
        dlg = OverlayDialog(self)
        layout = QVBoxLayout()
        
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet(f"font-size: {self.fs_px(22)}px; font-weight: bold; margin-bottom: 10px;")
        lbl_title.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl_title)
        
        form_layout = QVBoxLayout()
        form_layout.setSpacing(10)
        
        inputs = {}
        fields = [
            ("barcode", "Barcode", ""),
            ("name", "Product Name", ""),
            ("price", "Price (₹)", "0.00"),
            ("gst_percent", "GST %", "0.00"),
            ("hsn_code", "HSN Code", ""),
            ("quantity", "Stock Qty", "0")
        ]
        
        for key, label, default in fields:
            row_layout = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setMinimumWidth(self.dp(120))
            inp = QLineEdit()
            inp.setStyleSheet(f"padding: 8px; border: 1px solid {self.current_theme.secondary}; border-radius: 6px;")
            inp.setMinimumHeight(self.dp(40))
            if existing_data and key in existing_data:
                inp.setText(str(existing_data[key]))
            else:
                inp.setText(default)
            if key == "barcode" and existing_data:
                inp.setReadOnly(True)  # Cannot change barcode of existing item easily without cascading
                inp.setStyleSheet("background-color: #e2e8f0; color: #64748b; padding: 8px; border-radius: 6px;")
            
            inputs[key] = inp
            row_layout.addWidget(lbl)
            row_layout.addWidget(inp)
            form_layout.addLayout(row_layout)
            
        layout.addLayout(form_layout)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        save_btn = QPushButton("Save")
        save_btn.setObjectName("primaryCta")
        save_btn.setMinimumHeight(self.dp(45))
        save_btn.setMinimumWidth(self.dp(120))
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setMinimumHeight(self.dp(45))
        cancel_btn.setMinimumWidth(self.dp(120))
        
        saved_data = None
        
        def on_save():
            nonlocal saved_data
            saved_data = {k: v.text().strip() for k, v in inputs.items()}
            if not saved_data['barcode'] or not saved_data['name']:
                self.show_message("Error", "Barcode and Name are required.", "error")
                return
            try:
                float(saved_data['price'])
                float(saved_data['gst_percent'])
                int(saved_data['quantity'])
            except ValueError:
                self.show_message("Error", "Price, GST%, and Qty must be valid numbers.", "error")
                return
            dlg.accept()
            
        save_btn.clicked.connect(on_save)
        cancel_btn.clicked.connect(dlg.reject)
        
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)
        
        dlg.add_layout(layout)
        if dlg.exec_() == QDialog.Accepted:
            return saved_data
        return None

    def admin_inv_add(self):
        data = self._open_product_form("Add New Product")
        if not data: return
        
        try:
            with sqlite3.connect(DB_PATH) as conn:
                cur = conn.cursor()
                exists = cur.execute("SELECT 1 FROM products WHERE barcode=?", (data['barcode'],)).fetchone()
                if exists:
                    self.show_message("Notice", f"Barcode [{data['barcode']}] already exists.\nPlease select it and choose 'Edit'.", "warning")
                    return
                cur.execute(
                    "INSERT INTO products (barcode, name, price, gst_percent, hsn_code, quantity) VALUES (?, ?, ?, ?, ?, ?)",
                    (data['barcode'], data['name'], float(data['price']), float(data['gst_percent']), data['hsn_code'], int(data['quantity']))
                )
                conn.commit()
            
            # Keep flat CSV in sync
            from database import load_products_from_csv, save_products_to_csv
            products = load_products_from_csv()
            products[data['barcode']] = {
                'name': data['name'], 'price': float(data['price']),
                'gst_percent': float(data['gst_percent']), 'hsn_code': data['hsn_code'],
                'weight_grams': 0.0, 'quantity': int(data['quantity'])
            }
            save_products_to_csv(products)
            
            self.refresh_admin_inventory()
            self.show_message("Success", "Product successfully added.", "info")
        except Exception as e:
            self.show_message("Error", f"Failed to add product: {e}", "error")

    def admin_inv_edit(self):
        selected = self.admin_inv_table.selectedItems()
        if not selected:
            self.show_message("Notice", "Please select a product from the table to edit.", "info")
            return
        
        row = selected[0].row()
        barcode = self.admin_inv_table.item(row, 0).text()
        
        try:
            with sqlite3.connect(DB_PATH) as conn:
                cur = conn.cursor()
                r = cur.execute("SELECT barcode, name, price, gst_percent, hsn_code, quantity FROM products WHERE barcode=?", (barcode,)).fetchone()
                if not r: return
                
                existing = {
                    'barcode': r[0], 'name': r[1], 'price': str(r[2]), 
                    'gst_percent': str(r[3]), 'hsn_code': str(r[4] or ''), 'quantity': str(r[5] or 0)
                }
                
            data = self._open_product_form("Edit Product", existing)
            if not data: return
            
            with sqlite3.connect(DB_PATH) as conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE products SET name=?, price=?, gst_percent=?, hsn_code=?, quantity=? WHERE barcode=?",
                    (data['name'], float(data['price']), float(data['gst_percent']), data['hsn_code'], int(data['quantity']), data['barcode'])
                )
                conn.commit()
                
            from database import load_products_from_csv, save_products_to_csv
            products = load_products_from_csv()
            if data['barcode'] in products:
                products[data['barcode']].update({
                    'name': data['name'], 'price': float(data['price']),
                    'gst_percent': float(data['gst_percent']), 'hsn_code': data['hsn_code'],
                    'quantity': int(data['quantity'])
                })
                save_products_to_csv(products)
                
            self.refresh_admin_inventory()
            self.show_message("Success", "Product successfully updated.", "info")
        except Exception as e:
            self.show_message("Error", f"Failed to edit product: {e}", "error")

    def admin_inv_delete(self):
        selected = self.admin_inv_table.selectedItems()
        if not selected:
            self.show_message("Notice", "Please select a product from the table to delete.", "info")
            return
            
        row = selected[0].row()
        barcode = self.admin_inv_table.item(row, 0).text()
        name = self.admin_inv_table.item(row, 1).text()
        
        from ui_components import OverlayDialog
        dlg = OverlayDialog(self)
        layout = QVBoxLayout()
        lbl = QLabel(f"<p style='text-align:center;'>Are you sure you want to permanently delete:<br><br><b>'{name}'</b>?</p>")
        lbl.setStyleSheet(f"font-size: {self.fs_px(16)}px;")
        layout.addWidget(lbl)
        
        btn_layout = QHBoxLayout()
        n_btn = QPushButton("Cancel")
        n_btn.setMinimumHeight(self.dp(45))
        n_btn.clicked.connect(dlg.reject)
        y_btn = QPushButton("Yes, Delete")
        y_btn.setMinimumHeight(self.dp(45))
        y_btn.setStyleSheet("background-color: #ef4444; color: white;")
        y_btn.clicked.connect(dlg.accept)
        btn_layout.addWidget(n_btn)
        btn_layout.addWidget(y_btn)
        layout.addLayout(btn_layout)
        dlg.add_layout(layout)
        
        if dlg.exec_() == QDialog.Accepted:
            try:
                with sqlite3.connect(DB_PATH) as conn:
                    conn.execute("DELETE FROM products WHERE barcode=?", (barcode,))
                    conn.commit()
                
                from database import load_products_from_csv, save_products_to_csv
                products = load_products_from_csv()
                if barcode in products:
                    del products[barcode]
                    save_products_to_csv(products)
                    
                self.refresh_admin_inventory()
                self.show_message("Success", "Product successfully deleted.", "info")
            except Exception as e:
                self.show_message("Error", f"Failed to delete: {e}", "error")

    def admin_inv_import_csv(self):
        from PySide6.QtWidgets import QFileDialog
        from database import load_products_from_csv, save_products_to_csv
        import csv
        
        fname, _ = QFileDialog.getOpenFileName(self, "Import Products CSV", "", "CSV Files (*.csv)")
        if not fname: return
        
        try:
            # Parse chosen CSV
            imported = 0
            with open(fname, newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                with sqlite3.connect(DB_PATH) as conn:
                    cur = conn.cursor()
                    for row in reader:
                        barcode = row.get('barcode')
                        if not barcode: continue
                        name = row.get('name', 'Unknown')
                        price = float(row.get('price') or 0)
                        gst = float(row.get('gst_percent') or 0)
                        hsn = row.get('hsn_code', '')
                        qty = int(row.get('quantity') or 0)
                        
                        # Upsert logical (check if exists, insert or update)
                        exists = cur.execute("SELECT quantity FROM products WHERE barcode=?", (barcode,)).fetchone()
                        if exists:
                            # Add to existing stock instead of overwriting
                            current_qty = exists[0] or 0
                            new_qty = current_qty + qty
                            cur.execute(
                                "UPDATE products SET name=?, price=?, gst_percent=?, hsn_code=?, quantity=? WHERE barcode=?",
                                (name, price, gst, hsn, new_qty, barcode)
                            )
                        else:
                            cur.execute(
                                "INSERT INTO products (barcode, name, price, gst_percent, hsn_code, quantity) VALUES (?, ?, ?, ?, ?, ?)",
                                (barcode, name, price, gst, hsn, qty)
                            )
                        imported += 1
                    conn.commit()
            
            # ALWAYS Sync flat products.csv locally
            import shutil, os
            dest_file = "products.csv"
            
            # Generate a fresh clean CSV from sqlite.
            fresh_products = {}
            with sqlite3.connect(DB_PATH) as conn:
                for r in conn.execute("SELECT barcode, name, price, gst_percent, hsn_code, quantity FROM products"):
                    fresh_products[r[0]] = {
                        'name': r[1], 'price': r[2], 'gst_percent': r[3],
                        'hsn_code': r[4], 'weight_grams': 0.0, 'quantity': r[5]
                    }
            save_products_to_csv(fresh_products, dest_file)
                
            self.refresh_admin_inventory()
            self.show_message("Success", f"CSV Imported successfully.\nProcessed {imported} products.", "info")
            
        except Exception as e:
            self.show_message("Error", f"Failed to import CSV: {e}", "error")

    def _style_status_item(self, item, status):
        """Apply color to a status table item."""
        status = (status or '').lower()
        if status == 'captured':
            item.setText("✅ Captured")
            item.setForeground(QColor("#10b981"))
        elif status == 'failed':
            item.setText("❌ Failed")
            item.setForeground(QColor("#ef4444"))
        else:
            item.setText(f"⏳ {status.title()}" if status else "⏳ Unknown")
            item.setForeground(QColor("#f59e0b"))
        item.setTextAlignment(Qt.AlignCenter)

    def _load_admin_settings(self):
        """Load current settings into the Settings tab form fields."""
        try:
            self.settings_store_name.setText(self.settings.get('store_name', STORE_NAME))
            self.settings_store_address.setText(self.settings.get('store_address', ''))
            self.settings_store_gstin.setText(self.settings.get('store_gstin', ''))
            self.settings_upi_id.setText(self.settings.get('upi_id', STORE_UPI_ID))
            self.settings_razorpay.setCurrentIndex(0 if self.settings.get('razorpay_enabled', 'true') == 'true' else 1)
            self.settings_threshold.setValue(self.logo_threshold)
        except Exception as e:
            print(f"[Admin] Settings load error: {e}")

    def _save_admin_settings(self):
        """Save settings from the admin Settings tab."""
        try:
            self.save_setting('store_name', self.settings_store_name.text())
            self.save_setting('store_address', self.settings_store_address.text())
            self.save_setting('store_gstin', self.settings_store_gstin.text())
            self.save_setting('upi_id', self.settings_upi_id.text())
            self.save_setting('razorpay_enabled', 'true' if self.settings_razorpay.currentIndex() == 0 else 'false')
            self.logo_threshold = int(self.settings_threshold.value())
            self.save_setting('logo_transparency_threshold', str(self.logo_threshold))

            global STORE_NAME, STORE_UPI_ID
            STORE_NAME = self.settings_store_name.text()
            STORE_UPI_ID = self.settings_upi_id.text()
            self.store_label.setText(STORE_NAME)
            if hasattr(self, 'hero_name') and self.hero_name is not None:
                self.hero_name.setText(STORE_NAME)
            self.refresh_logos()

            self.show_message(self.t("Settings"), "Settings saved successfully! ✅", "info")
        except Exception as e:
            print(f"[Admin] Settings save error: {e}")
            self.show_message(self.t("Settings"), f"Error saving: {e}", "error")

    def show_cart_screen(self):
        self.stacked_widget.setCurrentWidget(self.cart_screen)
        self.ensure_hidden_focus()

    def show_payment_screen(self):
        if not self.cart:
            self.show_message("Empty cart", "Add items before proceeding to payment.", "warning")
            return
        self.stacked_widget.setCurrentWidget(self.payment_screen)
        self.payment_status_changed.emit(PaymentStatus.IDLE)

    def on_checkout_clicked(self):
        if not self.cart:
            self.show_message("Empty cart", "Add items before payment.", "warning")
            return
            
        # Custom Overlay Confirmation Dialog
        dlg = OverlayDialog(self)
        
        layout = QVBoxLayout()
        layout.setSpacing(20)
        
        title = QLabel(self.t("Confirm Checkout"))
        title.setObjectName("paymentTitle")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 24px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title)
        
        msg = QLabel(self.t("Are you sure you want to proceed to payment?"))
        msg.setWordWrap(True)
        msg.setAlignment(Qt.AlignCenter)
        msg.setStyleSheet("font-size: 18px; color: #333;")
        layout.addWidget(msg)

        # Check scale weight vs expected cart weight
        expected_total = sum(item.get("weight_grams", 0.0) * item.get("qty", 1) for item in self.cart)
        if self.scale_worker and expected_total > 0:
            current_scale = self.scale_worker.get_current_weight()
            diff = abs(current_scale - expected_total)
            tolerance = max(SCALE_WEIGHT_TOLERANCE_GRAMS * len(self.cart), expected_total * (SCALE_WEIGHT_TOLERANCE_PERCENT / 100.0))
            if diff > tolerance:
                weight_warn = QLabel(f"⚠️ Trolley Weight Discrepancy:\nTrolley reads {current_scale:.1f}g (Expected ~{expected_total:.1f}g).\nPlease verify items inside the trolley.")
                weight_warn.setWordWrap(True)
                weight_warn.setAlignment(Qt.AlignCenter)
                weight_warn.setStyleSheet("font-size: 14px; color: #b91c1c; background-color: #fef2f2; padding: 10px; border-radius: 8px; border: 1px solid #fca5a5; font-weight: 600;")
                layout.addWidget(weight_warn)
        
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        
        cancel_btn = QPushButton(self.t("Cancel"))
        cancel_btn.setMinimumHeight(50)
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #f5f5f5;
                border: none;
                border-radius: 8px;
                font-size: 16px;
                color: #333;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
        """)
        cancel_btn.clicked.connect(dlg.reject)
        btn_layout.addWidget(cancel_btn)
        
        confirm_btn = QPushButton(self.t("Yes, Proceed"))
        confirm_btn.setObjectName("primaryCta")
        confirm_btn.setMinimumHeight(50)
        confirm_btn.setCursor(Qt.PointingHandCursor)
        confirm_btn.clicked.connect(dlg.accept)
        btn_layout.addWidget(confirm_btn)
        
        layout.addLayout(btn_layout)
        
        dlg.add_layout(layout)
        
        if dlg.exec_() == QDialog.Accepted:
            self.payment_status_changed.emit(PaymentStatus.IDLE)
            self.start_payment_flow()

    def apply_theme(self, theme):
        self.current_theme = theme
        # ── Scaled size tokens ──
        base_fs = self.fs_px(14)
        store_fs = self.fs_px(22)
        total_fs = self.fs_px(20)
        payment_title_fs = self.fs_px(20)
        hero_title_fs = self.fs_px(22)
        hero_sub_fs = self.fs_px(13)
        cta_fs = self.fs_px(17)
        status_fs = self.fs_px(16)
        idle_fs = self.fs_px(28)
        qty_btn = self.dp(36)
        qty_label_fs = self.fs_px(16)
        progress_h = self.dp(8)

        # Derive lighter/darker shades for subtle effects
        if theme.name == "dark":
            border_subtle = "#2d3a4f"
            row_alt       = "#1a2538"
            hover_tint    = "#ffffff0a"
            clear_color   = "#f87171"
            clear_hover   = "#3b1111"
            accent_hover  = "#6366f1"
            accent_end    = "#a5b4fc"
            cta_hover_s   = "#6366f1"
            cta_hover_e   = "#818cf8"
        else:
            border_subtle = "#e2e8f0"
            row_alt       = "#f8fafc"
            hover_tint    = "#6366f10a"
            clear_color   = "#dc2626"
            clear_hover   = "#fee2e2"
            accent_hover  = "#4f46e5"
            accent_end    = "#818cf8"
            cta_hover_s   = "#4f46e5"
            cta_hover_e   = "#6366f1"

        style = f"""
            /* ─────────── BASE ─────────── */
            QWidget {{
                background: {theme.background};
                color: {theme.text};
                font-size: {base_fs}px;
                font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
            }}
            QStackedWidget#stackedWidget {{
                background: {theme.background};
            }}

            /* ─────────── APP BAR ─────────── */
            QFrame#appBar {{
                background: {theme.foreground};
                border: none;
                border-bottom: 1px solid {border_subtle};
                padding: {self.dp(4)}px {self.dp(8)}px;
            }}
            QLabel#storeLabel {{
                font-size: {store_fs}px;
                font-weight: 700;
                color: {theme.accent};
                background: transparent;
            }}

            /* ─────────── BARCODE INPUT ─────────── */
            QLineEdit#barcodeInput {{
                padding: {self.dp(10)}px {self.dp(16)}px;
                border: 1.5px solid {border_subtle};
                border-radius: {self.dp(10)}px;
                background: {theme.foreground};
                color: {theme.text};
                font-size: {base_fs}px;
            }}
            QLineEdit#barcodeInput:focus {{
                border: 2px solid {theme.accent};
            }}

            /* ─────────── CART TABLE ─────────── */
            QTableWidget#cartTable {{
                background: {theme.foreground};
                alternate-background-color: {row_alt};
                border: 1px solid {border_subtle};
                border-radius: {self.dp(12)}px;
                outline: none;
                selection-background-color: {hover_tint};
                selection-color: {theme.text};
            }}
            QTableWidget#cartTable::item {{
                padding: {self.dp(8)}px {self.dp(6)}px;
                border-bottom: 1px solid {border_subtle};
            }}
            QTableWidget#cartTable::item:selected {{
                background: {hover_tint};
                color: {theme.text};
            }}
            QHeaderView::section {{
                background: {theme.foreground};
                color: {theme.text};
                padding: {self.dp(10)}px {self.dp(6)}px;
                border: none;
                border-bottom: 2px solid {theme.accent};
                font-weight: 700;
                font-size: {self.fs_px(13)}px;
            }}

            /* ─────────── BUTTONS (DEFAULT) ─────────── */
            QPushButton {{
                padding: {self.dp(10)}px {self.dp(18)}px;
                border: 1.5px solid {border_subtle};
                border-radius: {self.dp(10)}px;
                background: {theme.foreground};
                color: {theme.text};
                font-weight: 600;
                font-size: {base_fs}px;
            }}
            QPushButton:hover {{
                background: {theme.accent};
                color: #ffffff;
                border-color: {theme.accent};
            }}
            QPushButton:pressed {{
                background: {accent_hover};
                color: #ffffff;
            }}

            /* ─── Clear Cart (subtle link-style) ─── */
            QPushButton#clearBtn {{
                background: transparent;
                border: none;
                color: {clear_color};
                font-weight: 600;
                font-size: {self.fs_px(13)}px;
                padding: {self.dp(8)}px {self.dp(12)}px;
            }}
            QPushButton#clearBtn:hover {{
                color: {clear_color};
                background: {clear_hover};
                border-radius: {self.dp(8)}px;
            }}

            /* ─── Primary CTA (Checkout) ─── */
            QPushButton#primaryCta {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {theme.accent}, stop:1 {accent_end});
                color: #ffffff;
                border: none;
                padding: {self.dp(16)}px {self.dp(24)}px;
                font-size: {cta_fs}px;
                font-weight: 700;
                border-radius: {self.dp(14)}px;
            }}
            QPushButton#primaryCta:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {cta_hover_s}, stop:1 {cta_hover_e});
            }}
            QPushButton#primaryCta:disabled {{
                background: {theme.secondary};
                color: {"rgba(255,255,255,0.45)" if theme.name == "light" else "rgba(255,255,255,0.35)"};
            }}

            /* ─── Link-style back button ─── */
            QPushButton#linkBtn {{
                background: transparent;
                color: {theme.accent};
                border: none;
                padding: 8px 12px;
                font-weight: 700;
            }}
            QPushButton#linkBtn:hover {{
                background: transparent;
                color: {theme.accent};
            }}

            /* ─────────── TOTAL LABEL ─────────── */
            QLabel#totalLabel {{
                font-size: {total_fs}px;
                font-weight: 800;
                color: {theme.accent};
            }}
            QLabel#paymentTitle {{
                font-size: {payment_title_fs}px;
                font-weight: 700;
                padding-bottom: {self.dp(8)}px;
            }}

            /* ─────────── TOOL BUTTONS ─────────── */
            QToolButton {{
                border: 1.5px solid {border_subtle};
                border-radius: {self.dp(22)}px;
                background: {theme.foreground};
                font-size: {self.fs_px(18)}px;
            }}
            QToolButton:hover {{
                background: {theme.accent};
                color: #ffffff;
                border-color: {theme.accent};
            }}

            /* ─────────── INPUTS / COMBOS ─────────── */
            QLineEdit, QComboBox {{
                padding: {self.dp(10)}px {self.dp(14)}px;
                border: 1.5px solid {border_subtle};
                border-radius: {self.dp(10)}px;
                background: {theme.foreground};
                color: {theme.text};
            }}
            QLineEdit:focus, QComboBox:focus {{
                border: 2px solid {theme.accent};
            }}
            QComboBox::drop-down {{
                border: none;
                padding-right: {self.dp(8)}px;
            }}

            /* ─────────── QTY +/- BUTTONS ─────────── */
            QPushButton#qtyDec, QPushButton#qtyInc {{
                min-width: {qty_btn}px; min-height: {qty_btn}px;
                max-width: {qty_btn}px; max-height: {qty_btn}px;
                font-size: {self.fs_px(16)}px;
                font-weight: 700;
                border-radius: {self.dp(8)}px;
                background: {theme.background};
                color: {theme.text};
                border: 1.5px solid {border_subtle};
                padding: 0px;
            }}
            QPushButton#qtyDec:hover, QPushButton#qtyInc:hover {{
                background: {theme.accent};
                color: #ffffff;
                border-color: {theme.accent};
            }}
            QLabel#qtyLabel {{
                font-size: {qty_label_fs}px;
                font-weight: 700;
            }}

            /* ─────────── STATUS / PAY BUTTONS ─────────── */
            QPushButton#payButton, QPushButton#proceedButton {{
                background: {theme.accent};
                color: white;
                border: none;
                padding: {self.dp(14)}px {self.dp(20)}px;
                font-size: {cta_fs}px;
                font-weight: 700;
                border-radius: {self.dp(12)}px;
            }}
            QPushButton#payButton:disabled, QPushButton#proceedButton:disabled {{
                background: {theme.secondary};
            }}
            QLabel#statusLabel {{
                font-size: {status_fs}px;
                font-weight: 600;
            }}

            /* ─────────── HERO BANNER ─────────── */
            QFrame#hero {{
                background: qradialgradient(cx:0.5, cy:0.5, radius:0.85, fx:0.5, fy:0.5,
                    stop:0 {theme.accent}, stop:1 {theme.foreground});
                border: 1px solid {border_subtle};
                border-radius: {self.dp(14)}px;
            }}
            QLabel#heroTitle {{ font-size: {hero_title_fs}px; font-weight: 800; color: #ffffff; }}
            QLabel#heroSub   {{ font-size: {hero_sub_fs}px; color: #f1f5f9; }}

            /* ─────────── IDLE SCREEN ─────────── */
            QLabel#idleLabel {{
                font-size: {idle_fs}px;
                color: {theme.accent};
                font-weight: 300;
            }}

            /* ─────────── PROGRESS BAR ─────────── */
            QProgressBar {{
                border: none;
                border-radius: {self.dp(4)}px;
                background: {border_subtle};
                height: {progress_h}px;
            }}
            QProgressBar::chunk {{
                background: {theme.accent};
                border-radius: {self.dp(4)}px;
            }}

            /* ─────────── SCROLLBARS (thin, modern) ─────────── */
            QScrollBar:vertical {{
                background: transparent;
                width: {self.dp(6)}px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {theme.secondary};
                min-height: {self.dp(30)}px;
                border-radius: {self.dp(3)}px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {theme.accent}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

            QScrollBar:horizontal {{
                background: transparent;
                height: {self.dp(6)}px;
                margin: 0;
            }}
            QScrollBar::handle:horizontal {{
                background: {theme.secondary};
                min-width: {self.dp(30)}px;
                border-radius: {self.dp(3)}px;
            }}
            QScrollBar::handle:horizontal:hover {{ background: {theme.accent}; }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

            /* ─────────── CARD CONTAINER ─────────── */
            QWidget#card {{
                background: {theme.foreground};
                border: 1px solid {border_subtle};
                border-radius: {self.dp(12)}px;
                padding: {self.dp(16)}px;
            }}

            /* ─────────── TAB WIDGET (Admin Panel) ─────────── */
            QTabWidget#adminTabs::pane {{
                border: 1px solid {border_subtle};
                border-radius: {self.dp(10)}px;
                background: {theme.background};
                top: -1px;
            }}
            QTabBar::tab {{
                background: {theme.foreground};
                color: {theme.text};
                border: 1px solid {border_subtle};
                border-bottom: none;
                padding: {self.dp(10)}px {self.dp(18)}px;
                margin-right: {self.dp(2)}px;
                border-top-left-radius: {self.dp(8)}px;
                border-top-right-radius: {self.dp(8)}px;
                font-weight: 600;
                font-size: {self.fs_px(13)}px;
            }}
            QTabBar::tab:selected {{
                background: {theme.accent};
                color: #ffffff;
                border-color: {theme.accent};
            }}
            QTabBar::tab:hover:!selected {{
                background: {border_subtle};
            }}

            /* ─────────── SPINBOX ─────────── */
            QSpinBox {{
                padding: {self.dp(8)}px {self.dp(12)}px;
                border: 1.5px solid {border_subtle};
                border-radius: {self.dp(8)}px;
                background: {theme.foreground};
                color: {theme.text};
            }}
        """
        self.setStyleSheet(style)
        self.theme_btn.setText("☀️" if theme.name == "dark" else "🌙")
        self.refresh_texts()

    def toggle_theme(self):
        new_theme = DARK_THEME if self.current_theme.name == "light" else LIGHT_THEME
        self.theme_changed.emit(new_theme)
        self.save_setting('theme', new_theme.name)

    def change_language(self, index):
        if index == 0:
            self.language = 'en'
        elif index == 1:
            self.language = 'hi'
        else: # index == 2
            self.language = 'gu'
            
        self.save_setting('language', self.language)
        self.refresh_texts()
        # FIX: Redraw the cart contents with the new language.
        self.refresh_cart_display()

    def load_settings(self):
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            rows = cur.execute("SELECT key, value FROM settings").fetchall()
            return {row[0]: row[1] for row in rows}

    def save_setting(self, key, value):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        self.settings[key] = value

    def event(self, event):
        if isinstance(event, BarcodeEvent):
            self.add_barcode_to_cart(event.barcode)
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        """
        Global key listener to capture scanner input without focusing the text field.
        This prevents the virtual keyboard from popping up during scanning.
        """
        # If manual input has focus, let standard processing happen (keyboard entry)
        if self.hidden_input.hasFocus():
            super().keyPressEvent(event)
            return

        # If webview is visible (payment screen), let it handle events
        if self.webview.isVisible():
            super().keyPressEvent(event)
            return

        # Otherwise, capture scanner input
        key = event.key()
        text = event.text()
        
        # Check for Enter (End of scan)
        if key == Qt.Key_Return or key == Qt.Key_Enter:
            if self.scan_buffer:
                # Process the buffered code
                self.on_barcode_scanned(self.scan_buffer)
                self.scan_buffer = ""
            event.accept() # Consume event
        elif text and text.isprintable():
            # Reset buffer if too much time passed (not a scanner burst)
            current_time = time.time()
            if current_time - getattr(self, 'last_key_time', 0) > 0.2:
                self.scan_buffer = ""
            self.last_key_time = current_time
            
            self.scan_buffer += text
            event.accept()
        else:
            super().keyPressEvent(event)

    def ensure_hidden_focus(self):
        if self.scanning_active and not self.webview.isVisible():
            self.hidden_input.setFocus()

    def on_barcode_scanned(self, code=None):
        self.record_activity()
        if code is None:
            code = self.hidden_input.text().strip()
            self.hidden_input.clear()
        
        if code:
            self.hidden_input.clearFocus()
            self.add_barcode_to_cart(code)

    # MODIFIED: Logic to fetch and store GST/HSN info in the cart
    def add_barcode_to_cart(self, barcode, qty=1):
        if getattr(self, 'payment_in_progress', False):
            self.show_message("Action Blocked", "You cannot modify the cart during checkout.", "warning")
            return
            
        if getattr(self, '_unscanned_overlay_active', False):
            self.show_message("Action Blocked", "Please remove the unscanned item first.", "warning")
            return
            
        # Fetch all required product details from the database
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            row = cur.execute("SELECT * FROM products WHERE barcode=?", (barcode,)).fetchone()
            
            if not row:
                self.show_message("Product not found", f"No product for barcode: {barcode}", "warning")
                return

            weight_grams = float(row["weight_grams"] or 0.0) if "weight_grams" in row.keys() else 0.0
            actual_w = weight_grams

            # Active item-by-item verification on trolley
            if self.scale_worker and weight_grams > 0:
                self.verification_in_progress = True
                try:
                    dlg = ItemWeightVerificationOverlay(
                        self, 
                        self.scale_worker, 
                        row["name"], 
                        weight_grams * qty,
                        tolerance_pct=SCALE_WEIGHT_TOLERANCE_PERCENT,
                        tolerance_g=SCALE_WEIGHT_TOLERANCE_GRAMS
                    )
                    if dlg.exec_() != QDialog.Accepted:
                        return
                    actual_w = getattr(dlg, 'measured_weight', weight_grams)
                finally:
                    self.verification_in_progress = False

            # If this weight was previously tracked as unscanned, clear it now that it's verified
            for uw in list(self.unscanned_items_weights):
                if abs(uw - actual_w) <= max(SCALE_WEIGHT_TOLERANCE_GRAMS * 1.5, actual_w * 0.15):
                    self.unscanned_items_weights.remove(uw)
                    break

            # Check if the product is already in the cart
            for item in self.cart:
                if item["barcode"] == barcode:
                    item["qty"] += qty
                    item.setdefault("actual_weights", []).append(actual_w)
                    self.refresh_cart_display()
                    return

            # Add new product to the cart, including GST, HSN, and recorded actual weight
            self.cart.append({
                "barcode": barcode, 
                "name": row["name"], 
                "price": float(row["price"]), 
                "qty": qty,
                "gst_percent": float(row["gst_percent"]),
                "hsn_code": row["hsn_code"],
                "weight_grams": weight_grams,
                "actual_weights": [actual_w]
            })
            self.refresh_cart_display()

    def refresh_cart_display(self):
        self.cart_table.setRowCount(len(self.cart))
        total = 0.0
        for row, item in enumerate(self.cart):
            # Localize product name and price
            name_text = item["name"]
            barcode = item["barcode"]
            prod_item = QTableWidgetItem(name_text)
            
            # Check for both .jpg and .png image formats
            img_base_path = os.path.join(os.path.dirname(__file__), "images", f"{barcode}")
            if os.path.exists(f"{img_base_path}.jpg"):
                prod_item.setIcon(QIcon(f"{img_base_path}.jpg"))
            elif os.path.exists(f"{img_base_path}.png"):
                prod_item.setIcon(QIcon(f"{img_base_path}.png"))
                
            self.cart_table.setItem(row, 0, prod_item)
            price_item = QTableWidgetItem(self.fmt_amount(item['price']))
            price_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.cart_table.setItem(row, 1, price_item)
            
            qty_widget = self.create_quantity_widget(row, item["qty"])
            self.cart_table.setCellWidget(row, 2, qty_widget)
            # Ensure row height accommodates +/- buttons and the product image
            self.cart_table.setRowHeight(row, self.dp(80))
            
            line_total = item["price"] * item["qty"]
            total_item = QTableWidgetItem(self.fmt_amount(line_total))
            total_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.cart_table.setItem(row, 3, total_item)

            remove_btn = QPushButton("×")
            remove_btn.setFixedSize(self.dp(44), self.dp(44))
            # Remove any default padding/margins so it sits flush
            remove_btn.setStyleSheet("padding: 0px; margin: 0px;")
            remove_btn.clicked.connect(lambda _, r=row: self.remove_item(r))
            # Wrap in a container to control alignment and padding within the cell
            rm_container = QWidget()
            rm_layout = QHBoxLayout(rm_container)
            rm_layout.setContentsMargins(0, 0, 0, 0)
            rm_layout.setSpacing(0)
            rm_layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            rm_layout.addWidget(remove_btn, 0, Qt.AlignLeft | Qt.AlignVCenter)
            self.cart_table.setCellWidget(row, 4, rm_container)
            total += line_total
        
        self.total = total
        self.total_label.setText(self.total_label_text())
        has_items = len(self.cart) > 0
        self.pay_btn.setEnabled(has_items)

        # Update live trolley weight indicator
        if hasattr(self, 'cart_weight_label') and getattr(self, 'scale_worker', None) and self.cart_weight_label:
            live_w = max(0.0, self.scale_worker.get_current_weight())
            self.cart_weight_label.setText(f"🛒 Trolley: {live_w:.1f}g  🟢")

    def create_quantity_widget(self, row, qty):
        # Outer wrapper to center content vertically
        wrapper = QWidget()
        outer = QVBoxLayout(wrapper)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addStretch()

        # Inner horizontal layout for - [qty] +
        inner = QWidget()
        qty_layout = QHBoxLayout(inner)
        qty_layout.setContentsMargins(0, 0, 0, 0)
        qty_layout.setSpacing(self.dp(8))

        # Use standard glyphs to match remove button look
        dec_btn = QPushButton("-")
        dec_btn.setObjectName("qtyDec")
        dec_btn.setFixedSize(self.dp(42), self.dp(42))
        # Ensure button content is centered
        dec_btn.setStyleSheet("padding: 0px;")
        dec_btn.clicked.connect(lambda _, r=row: self.change_quantity(r, -1))

        qty_label = QLabel(self.fmt_int(qty))
        qty_label.setObjectName("qtyLabel")
        qty_label.setAlignment(Qt.AlignCenter)
        qty_label.setFixedWidth(self.dp(46))

        inc_btn = QPushButton("+")
        inc_btn.setObjectName("qtyInc")
        inc_btn.setFixedSize(self.dp(42), self.dp(42))
        inc_btn.setStyleSheet("padding: 0px;")
        inc_btn.clicked.connect(lambda _, r=row: self.change_quantity(r, 1))

        for w in [dec_btn, qty_label, inc_btn]:
            qty_layout.addWidget(w)

        outer.addWidget(inner, 0, Qt.AlignHCenter)
        outer.addStretch()
        return wrapper

    def change_quantity(self, row, delta):
        if getattr(self, 'payment_in_progress', False):
            self.show_message("Action Blocked", "You cannot modify the cart during checkout.", "warning")
            return
            
        if 0 <= row < len(self.cart):
            item = self.cart[row]
            if delta > 0 and self.scale_worker and item.get("weight_grams", 0) > 0:
                self.verification_in_progress = True
                try:
                    dlg = ItemWeightVerificationOverlay(
                        self,
                        self.scale_worker,
                        item["name"],
                        item["weight_grams"],
                        tolerance_pct=SCALE_WEIGHT_TOLERANCE_PERCENT,
                        tolerance_g=SCALE_WEIGHT_TOLERANCE_GRAMS
                    )
                    if dlg.exec_() != QDialog.Accepted:
                        return
                    measured_w = getattr(dlg, 'measured_weight', item["weight_grams"])
                    item.setdefault("actual_weights", []).append(measured_w)
                finally:
                    self.verification_in_progress = False
            elif delta < 0:
                if self.scale_worker and item.get("weight_grams", 0) > 0:
                    self.verification_in_progress = True
                    try:
                        dlg = ItemRemovalVerificationOverlay(
                            self,
                            self.scale_worker,
                            item["name"],
                            item["weight_grams"],
                            tolerance_pct=SCALE_WEIGHT_TOLERANCE_PERCENT,
                            tolerance_g=SCALE_WEIGHT_TOLERANCE_GRAMS
                        )
                        if dlg.exec_() != QDialog.Accepted:
                            return
                        if item.get("actual_weights"):
                            item["actual_weights"].pop()
                    finally:
                        self.verification_in_progress = False
                else:
                    if item.get("actual_weights"):
                        item["actual_weights"].pop()

            item["qty"] += delta
            if item["qty"] <= 0:
                del self.cart[row]
                self.refresh_cart_display()
            else:
                self.refresh_cart_display()

    def remove_item(self, row):
        if getattr(self, 'payment_in_progress', False):
            self.show_message("Action Blocked", "You cannot modify the cart during checkout.", "warning")
            return
            
        if 0 <= row < len(self.cart):
            item = self.cart[row]
            if self.scale_worker and item.get("weight_grams", 0) > 0:
                self.verification_in_progress = True
                try:
                    total_expected = sum(item.get("actual_weights", [])) if item.get("actual_weights") else (item["qty"] * item["weight_grams"])
                    if total_expected <= 0:
                        total_expected = item["qty"] * item["weight_grams"]
                    
                    dlg = ItemRemovalVerificationOverlay(
                        self,
                        self.scale_worker,
                        f"All {item['qty']}x {item['name']}",
                        total_expected,
                        tolerance_pct=SCALE_WEIGHT_TOLERANCE_PERCENT,
                        tolerance_g=max(SCALE_WEIGHT_TOLERANCE_GRAMS, SCALE_WEIGHT_TOLERANCE_GRAMS * item["qty"])
                    )
                    if dlg.exec_() != QDialog.Accepted:
                        return
                finally:
                    self.verification_in_progress = False
                    
            del self.cart[row]
            self.refresh_cart_display()

    def clear_cart(self):
        self.cart = []
        self.unscanned_items_weights = []
        self.refresh_cart_display()

    def start_payment_flow(self):
        
        self.scanning_active, self.payment_in_progress = False, True
        self.hidden_input.clearFocus()
        self.payment_status_changed.emit(PaymentStatus.PROCESSING)
        
        # Reset error flag and chunk error counter for new payment attempt
        # Force immediate reset even if delayed reset is pending
        self.payment_error_mutex.lock()
        try:
            self.payment_error_triggered = False
            self.chunk_error_count = 0
        finally:
            self.payment_error_mutex.unlock()
        print("[DEBUG] ✓ Error flag forcefully reset - starting fresh payment attempt")
        
        try:
            order = client.order.create({
                "amount": int(round(self.total * 100)), 
                "currency": "INR",
                "receipt": f"rcpt_{int(time.time())}", 
                "payment_capture": 1
            })
            # Store order with cart data for transaction CSV logging
            ORDER_CACHE[order['id']] = {
                'order': order,
                'cart': self.cart.copy(),
                'total': self.total
            }
            url = f"http://127.0.0.1:{FLASK_PORT}/checkout/{order['id']}"
            
            print(f"[DEBUG] Starting payment flow - Order: {order['id']}, Amount: ₹{self.total}")
            
            # Switch to payment screen BEFORE loading webview to prevent background visibility
            self.stacked_widget.setCurrentWidget(self.payment_screen)
            
            # Show loading overlay immediately to prevent any desktop visibility
            if hasattr(self, 'loading_overlay'):
                self.loading_overlay.setVisible(True)
                self.loading_overlay.raise_()
                # Force immediate repaint
                self.loading_overlay.repaint()
                QApplication.processEvents()
            
            # Start timeout timer (10 seconds) to detect network failures during page load
            # Reduced from 20s to 10s for faster feedback when internet is lost
            self.webview_timeout_timer.start(10000)
            
            # Show checkout inside the embedded WebView
            self.webview.setUrl(QUrl(url))
            self.webview.setVisible(True)
            self.webview.setFocus()
            
            # Show keyboard toggle button but keep keyboard hidden
            # Qt Virtual Keyboard handles this automatically
            pass
            
            # Hide status card to give more space to Razorpay during checkout
            try:
                self.payment_status_widget.setVisible(False)
            except Exception:
                pass
        except requests.Timeout:
            self.show_message(
                "Network Timeout", 
                "Razorpay API request timed out. Please check your internet connection and try again.",
                "error"
            )
            self.reset_payment_state(PaymentStatus.FAILED)
            self.stacked_widget.setCurrentWidget(self.cart_screen)
        except requests.ConnectionError:
            self.show_message(
                "Connection Error", 
                "Unable to connect to Razorpay. Please check your internet connection.",
                "error"
            )
            self.reset_payment_state(PaymentStatus.FAILED)
            self.stacked_widget.setCurrentWidget(self.cart_screen)
        except Exception as e:
            self.show_message("Order creation failed", f"Razorpay error: {e}", "error")
            self.reset_payment_state(PaymentStatus.FAILED)
            self.stacked_widget.setCurrentWidget(self.cart_screen)
    


    
    def on_webview_load_finished(self, success):
        """Handle webview load completion - stop timeout timer"""
        try:
            # Stop the timeout timer since page loaded (successfully or not)
            if hasattr(self, 'webview_timeout_timer'):
                self.webview_timeout_timer.stop()
            
            if not success:
                # Page failed to load - show error and return to cart
                print("Webview failed to load Razorpay page")
                self.show_message(
                    "Payment Error", 
                    "Unable to load payment page. Please check your internet connection and try again.",
                    "error"
                )
                self.cancel_payment_and_return_to_cart()
        except Exception as e:
            print(f"Error in on_webview_load_finished: {e}")
    
    def handle_console_message(self, level, message, line_number, source_id):
        """Handle JavaScript console messages to detect ChunkLoadError"""
        try:
            # Check if webview is visible - ignore messages if not visible
            if not self.webview.isVisible():
                return
            
            # Check if already triggered
            self.payment_error_mutex.lock()
            try:
                if self.payment_error_triggered:
                    return
            finally:
                self.payment_error_mutex.unlock()
            
            # Debug: Print all console messages to see what we're getting
            if 'chunk' in message.lower() or 'error' in message.lower():
                print(f"[CONSOLE DEBUG] Level: {level}, Message: {message[:150]}")
            
            # Detect ChunkLoadError in console messages (case-insensitive)
            message_lower = message.lower()
            if 'chunkloaderror' in message_lower or ('loading chunk' in message_lower and 'failed' in message_lower):
                self.chunk_error_count += 1
                print(f"[DEBUG] ChunkLoadError detected (count: {self.chunk_error_count}): {message[:100]}")
                
                # Trigger immediately on FIRST ChunkLoadError for fastest response
                # ChunkLoadError always indicates network failure - no need to wait
                if self.chunk_error_count >= 1:
                    print("✓ ChunkLoadError detected - network failure during payment, returning to cart immediately")
                    
                    # Thread-safe flag set - check and set atomically
                    self.payment_error_mutex.lock()
                    try:
                        # Double-check flag wasn't set by another thread
                        if self.payment_error_triggered:
                            return
                        self.payment_error_triggered = True
                    finally:
                        self.payment_error_mutex.unlock()
                    
                    # Stop all timers
                    if hasattr(self, 'webview_timeout_timer'):
                        self.webview_timeout_timer.stop()
                    if hasattr(self, 'error_monitor_timer'):
                        self.error_monitor_timer.stop()
                    
                    # Stop and hide webview FIRST to prevent more console messages
                    self.webview.stop()
                    self.webview.setVisible(False)
                    
                    # Emit signal to show error in main GUI thread (safer than direct QMessageBox)
                    self.network_error_detected.emit("Network connection lost during payment.\n\nPlease check your internet connection and try again.")
        except Exception as e:
            print(f"Error in handle_console_message: {e}")
    
    def handle_network_error_signal(self, error_message):
        """Handle network error signal in main GUI thread"""
        try:
            print(f"[DEBUG] Network error signal received: {error_message[:50]}...")
            # Show error message
            self.show_message(
                "Network Error",
                error_message,
                "error"
            )
            # Return to cart
            self.cancel_payment_and_return_to_cart()
        except Exception as e:
            print(f"Error in handle_network_error_signal: {e}")
    
    def on_webview_timeout(self):
        """Handle webview loading timeout - network failure detected"""
        try:
            print("Webview loading timeout - network issue detected")
            # Hide webview and show error
            self.webview.setVisible(False)
            self.show_message(
                "Network Timeout", 
                "Payment page is taking too long to load. Please check your internet connection.\n\nReturning to cart...",
                "error"
            )
            self.cancel_payment_and_return_to_cart()
        except Exception as e:
            print(f"Error in on_webview_timeout: {e}")
    
    def cancel_payment_and_return_to_cart(self):
        """Cancel payment and safely return to cart screen"""
        try:
            print("[DEBUG] Cancelling payment and returning to cart...")
            
            # Stop all timers
            if hasattr(self, 'webview_timeout_timer'):
                self.webview_timeout_timer.stop()
            if hasattr(self, 'error_monitor_timer'):
                self.error_monitor_timer.stop()
            
            # Stop and hide webview FIRST to prevent more console messages
            self.webview.stop()  # Stop loading
            self.webview.setVisible(False)
            
            # Clear the webview to stop any JavaScript execution
            self.webview.setUrl(QUrl("about:blank"))
            
            try:
                # No custom keyboard to hide
                pass
            except:
                pass
            
            # Reset error flag so user can retry payment (but only after webview is stopped)
            # Use a small delay to ensure all pending console messages are ignored
            QTimer.singleShot(500, self.reset_error_flag_delayed)
            print("[DEBUG] Webview stopped, error flag will reset in 500ms")
            
            # Reset payment state
            self.reset_payment_state(PaymentStatus.FAILED)
            
            # Return to cart screen - keep cart items intact
            self.stacked_widget.setCurrentWidget(self.cart_screen)
            
            # Restore focus to barcode scanner
            self.ensure_hidden_focus()
            
        except Exception as e:
            print(f"Error in cancel_payment_and_return_to_cart: {e}")
    
    def reset_error_flag_delayed(self):
        """Reset error flag after a delay to prevent race conditions"""
        try:
            self.payment_error_triggered = False
            self.chunk_error_count = 0
            print("[DEBUG] ✓ Error flag reset - ready for retry")
        except Exception as e:
            print(f"Error in reset_error_flag_delayed: {e}")
    
    def inject_keyboard_for_razorpay(self, success):
        """Inject JavaScript to ensure inputs are focusable in Razorpay page"""
        if not success:
            return
        
        # Script to make inputs accessible AND monitor for chunk load errors
        focus_js = """
        (function() {
            console.log('Razorpay page loaded - setting up input focus and error monitoring');
            
            // Monitor for JavaScript errors (especially ChunkLoadError)
            let errorCount = 0;
            const MAX_ERRORS = 1;  // Trigger on FIRST error for faster response
            
            window.addEventListener('error', function(event) {
                console.error('[JS MONITOR] JavaScript error detected:', event.message);
                errorCount++;
                console.error('[JS MONITOR] Error count:', errorCount);
                
                // If we get errors, likely a network issue
                if (errorCount >= MAX_ERRORS) {
                    console.error('[JS MONITOR] Triggering error - setting title to PAYMENT_ERROR_DETECTED');
                    // Signal to Qt that there's a problem
                    document.title = 'PAYMENT_ERROR_DETECTED';
                }
            });
            
            // Monitor for unhandled promise rejections (ChunkLoadError comes through here)
            window.addEventListener('unhandledrejection', function(event) {
                console.error('[JS MONITOR] Unhandled promise rejection:', event.reason);
                
                // Check if it's a ChunkLoadError or any loading failure
                const reasonStr = event.reason ? event.reason.toString() : '';
                console.error('[JS MONITOR] Reason string:', reasonStr);
                
                if (reasonStr.includes('ChunkLoadError') ||
                    reasonStr.includes('Loading chunk') ||
                    reasonStr.includes('failed')) {
                    errorCount++;
                    console.error('[JS MONITOR] Chunk/resource load error detected, count:', errorCount);
                    
                    if (errorCount >= MAX_ERRORS) {
                        console.error('[JS MONITOR] Triggering error - setting title to PAYMENT_ERROR_DETECTED');
                        document.title = 'PAYMENT_ERROR_DETECTED';
                    }
                }
            });
            
            // Also check for error pages by looking for specific text/elements
            function checkForErrorPage() {
                const bodyText = document.body.innerText || '';
                
                // Check for critical error messages
                const hasCriticalError = 
                    bodyText.includes('Verification failed') ||
                    bodyText.includes('timed out') ||
                    bodyText.includes('HTTPSConnectionPool') ||
                    bodyText.includes('signature verification failed') ||
                    bodyText.includes('DB error');
                
                // Check for general error indicators
                const hasErrorIndicators = 
                    bodyText.includes('Something went wrong') ||
                    bodyText.includes('Error') ||
                    bodyText.includes('failed') ||
                    bodyText.includes('Unable to load') ||
                    document.querySelector('[class*="error"]') !== null ||
                    document.querySelector('[class*="failed"]') !== null;
                
                // Trigger on critical errors OR error indicators on minimal pages
                if (hasCriticalError || (hasErrorIndicators && document.body.children.length < 10)) {
                    console.error('Error page detected - signaling Qt');
                    document.title = 'PAYMENT_ERROR_DETECTED';
                }
            }
            
            // Check for error page after a delay
            setTimeout(checkForErrorPage, 2000);
            setTimeout(checkForErrorPage, 4000);
            setTimeout(checkForErrorPage, 6000);
            
            // Find all inputs and make them focusable
            function setupInputs() {
                document.querySelectorAll('input, textarea').forEach(function(input) {
                    input.addEventListener('focus', function() {
                        console.log('Input focused:', this);
                    });
                    input.addEventListener('click', function() {
                        console.log('Input clicked:', this);
                        this.focus();
                    });
                });
            }
            
            setupInputs();
            
            // Watch for dynamic content
            const observer = new MutationObserver(setupInputs);
            observer.observe(document.body, { childList: true, subtree: true });
        })();
        """
        
        try:
            self.webview.page().runJavaScript(focus_js)
            # Start monitoring the page title for error signals
            self.start_error_monitoring()
        except Exception as e:
            print(f"Failed to inject focus script: {e}")
    
    def start_error_monitoring(self):
        """Monitor webview page title for JavaScript error signals"""
        try:
            # Create a timer to periodically check for errors
            if not hasattr(self, 'error_monitor_timer'):
                self.error_monitor_timer = QTimer(self)
                self.error_monitor_timer.timeout.connect(self.check_for_js_errors)
            
            self.error_monitor_timer.start(1000)  # Check every second
        except Exception as e:
            print(f"Failed to start error monitoring: {e}")
    
    def check_for_js_errors(self):
        """Check if JavaScript has signaled an error via page title or page content"""
        try:
            # Thread-safe check with mutex
            self.payment_error_mutex.lock()
            try:
                if self.payment_error_triggered:
                    return
            finally:
                self.payment_error_mutex.unlock()
                
            if not self.webview.isVisible():
                # Stop monitoring if webview is hidden
                if hasattr(self, 'error_monitor_timer'):
                    self.error_monitor_timer.stop()
                return
            
            # Check page title for error signal
            title = self.webview.title()
            # Only log if title changes (reduce spam)
            if not hasattr(self, '_last_title') or self._last_title != title:
                print(f"[DEBUG] Page title changed: '{title}'")
                self._last_title = title
            
            if title == 'PAYMENT_ERROR_DETECTED':
                print("✓ JavaScript error detected - network failure during payment")
                
                # Thread-safe flag set with mutex
                self.payment_error_mutex.lock()
                try:
                    self.payment_error_triggered = True
                finally:
                    self.payment_error_mutex.unlock()
                
                # Stop monitoring
                if hasattr(self, 'error_monitor_timer'):
                    self.error_monitor_timer.stop()
                
                # Show error and return to cart
                self.show_message(
                    "Network Error",
                    "Network connection lost during payment.\n\nPlease check your internet connection and try again.",
                    "error"
                )
                self.cancel_payment_and_return_to_cart()
                return
            
            # Also check page HTML content for error indicators
            self.webview.page().toHtml(self.check_page_content_for_errors)
            
        except Exception as e:
            print(f"Error in check_for_js_errors: {e}")
    
    def check_page_content_for_errors(self, html):
        """Check if page HTML contains error indicators (sad face, error messages, etc.)"""
        try:
            # Thread-safe check with mutex
            self.payment_error_mutex.lock()
            try:
                if self.payment_error_triggered:
                    return
            finally:
                self.payment_error_mutex.unlock()
                
            if not self.webview.isVisible():
                return
            
            # Look for error indicators in the HTML
            html_lower = html.lower()
            
            # Check if page has payment form elements (indicates normal payment page)
            has_payment_form = any(indicator in html_lower for indicator in [
                'pay now',
                'card number',
                'cvv',
                'expiry',
                'upi',
                'netbanking',
                'wallet',
                'razorpay-container',
                'payment-method'
            ])
            
            # If page has payment form, it's NOT an error page - skip detection
            if has_payment_form:
                # Only log first time we detect a valid payment page
                if not hasattr(self, '_payment_form_detected'):
                    print("[DEBUG] Valid payment form detected - skipping error checks")
                    self._payment_form_detected = True
                return
            
            # Reset flag when we start checking (new page load)
            if hasattr(self, '_payment_form_detected'):
                delattr(self, '_payment_form_detected')
            
            # Check for VISIBLE critical error messages (not just in code)
            # These patterns indicate actual displayed errors
            critical_error_patterns = [
                'verification failed:',  # Colon indicates actual error message
                'httpsconnectionpool(host=',  # Actual connection error
                'read timed out. (read timeout',  # Actual timeout error
                'signature verification failed or db error',  # Actual error message
                'connection refused',
                'network unreachable',
                'ip address could not be found',  # DNS failure
                'server ip address could not be found',  # DNS failure (full text)
                'err_name_not_resolved',  # Chrome DNS error
                'dns_probe_finished_nxdomain'  # Chrome DNS error
            ]
            has_critical_error = any(pattern in html_lower for pattern in critical_error_patterns)
            
            if has_critical_error:
                # Find which pattern matched for debugging
                matched = [pattern for pattern in critical_error_patterns if pattern in html_lower]
                print(f"[DEBUG] Critical error message detected in HTML: {matched}")
            
            # Check for general error keywords
            has_error_keywords = any(keyword in html_lower for keyword in [
                'something went wrong',
                'unable to load',
                'failed to load',
                'error loading',
                'chunk load',
                'network error',
                'connection error'
            ])
            
            # Check for sad face or error icons (common in error pages)
            has_error_icon = any(icon in html for icon in [
                '😞', '☹', '😢',  # Sad emojis
                'sad-face', 'error-icon', 'warning-icon'
            ])
            
            # Check for minimal content (error pages are usually very simple)
            is_minimal = len(html) < 5000 and '<body' in html_lower
            
            # Check for extremely minimal pages (DNS errors, connection failures)
            # These pages are usually < 1000 characters and have no payment form
            is_extremely_minimal = len(html) < 1000 and not has_payment_form
            
            # Only log when something interesting happens (reduce spam)
            if has_critical_error or has_error_keywords or is_minimal or is_extremely_minimal:
                print(f"[DEBUG] HTML check - Critical: {has_critical_error}, Keywords: {has_error_keywords}, Minimal: {is_minimal}, ExtremelyMinimal: {is_extremely_minimal}, Size: {len(html)}, HasForm: {has_payment_form}")
            
            # Trigger if:
            # 1. Critical error messages detected
            # 2. Minimal page with error indicators and no payment form
            # 3. Extremely minimal page (likely DNS/connection error)
            should_trigger = (
                has_critical_error or 
                (is_minimal and (has_error_keywords or has_error_icon) and not has_payment_form) or
                is_extremely_minimal
            )
            
            if should_trigger:
                print("✓ Error page detected via HTML content analysis - triggering recovery")
                
                # Thread-safe flag set with mutex
                self.payment_error_mutex.lock()
                try:
                    self.payment_error_triggered = True
                finally:
                    self.payment_error_mutex.unlock()
                
                # Stop monitoring
                if hasattr(self, 'error_monitor_timer'):
                    self.error_monitor_timer.stop()
                
                # Show error and return to cart
                self.show_message(
                    "Payment Page Error",
                    "The payment page encountered an error.\n\nThis may be due to network issues. Please try again.",
                    "error"
                )
                self.cancel_payment_and_return_to_cart()
                
        except Exception as e:
            print(f"Error in check_page_content_for_errors: {e}")

    def on_webview_url_changed(self, qurl):
        """Handle URL changes when using the embedded WebView (kept for backward-compat).
        The current flow opens the browser directly, so this may not be triggered.
        """
        try:
            url = qurl.toString()
            if "/status/" in url:
                payment_id = url.rstrip('/').rsplit('/', 1)[-1] if '/' in url else None
                QTimer.singleShot(500, lambda: self.finish_payment_handling(payment_id))
            elif "/fail" in url:
                # Treat as failed payment and return to cart; keep items
                QTimer.singleShot(300, lambda: self.finish_payment_handling(None))
        except Exception:
            pass

    def finish_payment_handling(self, payment_id):
        # Stop all timers if still running
        try:
            if hasattr(self, 'webview_timeout_timer'):
                self.webview_timeout_timer.stop()
            if hasattr(self, 'error_monitor_timer'):
                self.error_monitor_timer.stop()
        except:
            pass
        
        # Reset error flag when payment completes (success or failure)
        self.payment_error_triggered = False
        
        self.webview.setVisible(False)
        # Dead keyboard references removed (native_keyboard/kb_toggle_btn were never created)
        
        status, payment = None, None
        if payment_id:
            try:
                payment = client.payment.fetch(payment_id)
                status = payment.get("status")
            except requests.Timeout:
                print("Timeout fetching payment status")
                self.show_message(
                    "Network Timeout", 
                    "Unable to verify payment status due to network timeout.\n\nPlease check transaction history in admin panel.",
                    "error"
                )
            except requests.ConnectionError:
                print("Connection error fetching payment status")
                self.show_message(
                    "Connection Error", 
                    "Unable to verify payment status due to connection error.\n\nPlease check transaction history in admin panel.",
                    "error"
                )
            except Exception as e:
                print("Error fetching payment:", e)
        
        if status == "captured":
            self.payment_status = PaymentStatus.SUCCESS
            
            # Update inventory after successful payment
            try:
                # Update both CSV and database
                update_inventory_in_csv(self.cart)
                update_inventory_in_database(self.cart)
                print("✅ Inventory successfully updated after purchase")
            except Exception as e:
                print(f"⚠️ Warning: Failed to update inventory: {e}")
            
            self.show_receipt(payment)
            self.clear_cart()
            self.stacked_widget.setCurrentWidget(self.idle_screen)
            print("[DEBUG] Payment successful - error flag reset")
        else:
            self.payment_status = PaymentStatus.FAILED
            self.show_message("Payment Info", f"Payment status: {status or 'failed'}.", "warning")
            # On failure, return to cart screen and keep cart items intact
            try:
                self.stacked_widget.setCurrentWidget(self.cart_screen)
            except Exception:
                pass
            print("[DEBUG] Payment failed - error flag reset, ready for retry")
        
        self.reset_payment_state(self.payment_status)

    def reset_payment_state(self, final_status):
        self.scanning_active, self.payment_in_progress = True, False
        self.payment_status_changed.emit(final_status)
        if final_status != PaymentStatus.SUCCESS:
            self.hidden_input.setFocus()
        # Back button removed; no action needed here
        QTimer.singleShot(5000, self.reset_payment_status_to_idle)
        # Restore status widget visibility after finishing payment
        try:
            self.payment_status_widget.setVisible(True)
        except Exception:
            pass
    
    def reset_payment_status_to_idle(self):
        if self.payment_status != PaymentStatus.PROCESSING:
            self.payment_status_changed.emit(PaymentStatus.IDLE)
    
    
    # REWRITTEN: Complete overhaul to generate a professional tax invoice
    def show_receipt(self, payment):
        """
        Show a payment receipt. IMPORTANT: do NOT mutate self.language here.
        We temporarily override self.t to force English-only text for the receipt,
        then restore everything and refresh the UI so combo/signals stay healthy.
        """
        # 1) Keep the original translator callable and replace it with an English passthrough
        original_t = self.t
        self.t = lambda s: s  # force English for receipt generation
        
        # Track if this receipt has been printed (prevent duplicate prints)
        self.receipt_printed = False

        try:
            # Use custom OverlayDialog instead of native QDialog
            dlg = OverlayDialog(self)
            # dlg.setWindowTitle(self.t("Tax Invoice")) # Overlay doesn't use window title
            
            # Create content layout for the overlay
            layout = QVBoxLayout()
            layout.setSpacing(15)
            
            # Add title manually since overlay doesn't have a title bar
            title_label = QLabel(self.t("Tax Invoice"))
            title_label.setObjectName("paymentTitle")
            title_label.setAlignment(Qt.AlignCenter)
            title_label.setStyleSheet("font-size: 24px; font-weight: bold; margin-bottom: 10px;")
            layout.addWidget(title_label)

            receipt_text = QTextEdit()
            receipt_text.setReadOnly(True)
            receipt_text.setMinimumWidth(450)
            receipt_text.setMinimumHeight(500)

            # --- Data Preparation ---
            store_name = self.settings.get('store_name', 'Smart Store')
            store_address = self.settings.get('store_address', 'N/A')
            store_gstin = self.settings.get('store_gstin', 'N/A')

            now_str = datetime.now().strftime('%d-%b-%Y %I:%M %p')
            payment_id_str = payment.get('id', 'N/A')

            # --- GST Calculation ---
            gst_breakup = defaultdict(lambda: {'taxable_amount': 0, 'cgst': 0, 'sgst': 0})
            total_taxable_value = 0
            total_cgst = 0
            total_sgst = 0

            for item in self.cart:
                gst_rate = item['gst_percent']
                taxable_value_per_unit = item['price'] / (1 + (gst_rate / 100.0))
                total_taxable_for_item = taxable_value_per_unit * item['qty']
                total_gst_for_item = (item['price'] * item['qty']) - total_taxable_for_item
                cgst = total_gst_for_item / 2.0
                sgst = total_gst_for_item / 2.0
                gst_breakup[gst_rate]['taxable_amount'] += total_taxable_for_item
                gst_breakup[gst_rate]['cgst'] += cgst
                gst_breakup[gst_rate]['sgst'] += sgst
                total_taxable_value += total_taxable_for_item
                total_cgst += cgst
                total_sgst += sgst
            grand_total = self.total

            # --- Build Receipt HTML (uses self.t() which is currently English passthrough) ---
            receipt_html = f"""
            <html>
            <head>
                <style>
                    body {{ font-family: 'Courier New', Courier, monospace; font-size: 22px; line-height: 1.4; }}
                    .center {{ text-align: center; }}
                    .right {{ text-align: right; }}
                    .left {{ text-align: left; }}
                    .bold {{ font-weight: bold; }}
                    table {{ width: 100%; border-collapse: collapse; }}
                    .header-table td {{ padding: 3px; }}
                    .items-table th, .items-table td {{ padding: 5px; border-bottom: 1px dashed #555; }}
                    .totals-table td {{ padding: 4px; }}
                    .line {{ border-top: 2px dashed #555; margin: 6px 0; }}
                    h3 {{ font-size: 26px; }}
                    h4 {{ font-size: 24px; }}
                </style>
            </head>
            <body>
                <div class="center">
                    <h3 style="margin:0;">{store_name}</h3>
                    <p style="margin:3px 0;">{store_address}</p>
                    <p style="margin:3px 0;"><b>GSTIN: {store_gstin}</b></p>
                    <h4 style="margin:6px 0;">{self.t("Tax Invoice")}</h4>
                </div>
                <div class="line"></div>
                <table class="header-table">
                    <tr>
                        <td class="left">{self.t("Bill No")}: {payment_id_str[-8:]}</td>
                        <td class="right">{self.t("Date")}: {now_str}</td>
                    </tr>
                    <tr>
                        <td class="left" colspan="2">{self.t("Payment ID")}: {payment_id_str}</td>
                    </tr>
                </table>
                <div class="line"></div>
                <table class="items-table">
                    <thead>
                        <tr>
                            <th class="left">{self.t("HSN")}</th>
                            <th class="left">{self.t("PARTICULARS")}</th>
                            <th class="right">{self.t("QTY")}</th>
                            <th class="right">{self.t("RATE")}</th>
                            <th class="right">{self.t("VALUE")}</th>
                        </tr>
                    </thead>
                    <tbody>
            """

            for item in self.cart:
                taxable_rate = item['price'] / (1 + (item['gst_percent'] / 100.0))
                line_total_value = taxable_rate * item['qty']
                receipt_html += f"""
                    <tr>
                        <td class="left">{item['hsn_code']}</td>
                        <td class="left">{item['name']}</td>
                        <td class="right">{item['qty']}</td>
                        <td class="right">{taxable_rate:.2f}</td>
                        <td class="right">{line_total_value:.2f}</td>
                    </tr>
                """

            receipt_html += f"""
                    </tbody>
                </table>
                <div class="line"></div>
                <table class="totals-table">
                    <tr>
                        <td class="left bold">{self.t("SUB TOTAL")}</td>
                        <td class="right bold">{total_taxable_value:.2f}</td>
                    </tr>
                    <tr>
                        <td class="left">{self.t("CGST")}</td>
                        <td class="right">{total_cgst:.2f}</td>
                    </tr>
                    <tr>
                        <td class="left">{self.t("SGST")}</td>
                        <td class="right">{total_sgst:.2f}</td>
                    </tr>
                </table>
                <div class="line" style="border-style: solid; border-width: 2px;"></div>
                <table class="totals-table">
                    <tr>
                        <td class="left bold" style="font-size: 24px;">{self.t("GRAND TOTAL")}</td>
                        <td class="right bold" style="font-size: 24px;">₹{grand_total:.2f}</td>
                    </tr>
                </table>
                <div class="line" style="border-style: solid; border-width: 2px;"></div>

                <div class="center bold" style="margin-top: 10px;">{self.t("GST Breakup Details")}</div>
                <table class="items-table">
                    <thead>
                        <tr>
                            <th class="right">{self.t("GST%")}</th>
                            <th class="right">{self.t("Taxable Amt")}</th>
                            <th class="right">{self.t("CGST")}</th>
                            <th class="right">{self.t("SGST")}</th>
                            <th class="right">{self.t("Total Tax")}</th>
                        </tr>
                    </thead>
                    <tbody>
            """

            sorted_gst_rates = sorted(gst_breakup.keys())
            for rate in sorted_gst_rates:
                data = gst_breakup[rate]
                total_tax_for_rate = data['cgst'] + data['sgst']
                receipt_html += f"""
                    <tr>
                        <td class="right">{rate:.2f}%</td>
                        <td class="right">{data['taxable_amount']:.2f}</td>
                        <td class="right">{data['cgst']:.2f}</td>
                        <td class="right">{data['sgst']:.2f}</td>
                        <td class="right">{total_tax_for_rate:.2f}</td>
                    </tr>
                """

            receipt_html += f"""
                    </tbody>
                </table>
                <div class="line"></div>
                <div class="center" style="margin-top:10px;">
                    <p style="margin:2px 0;">{self.t("Thank You! Visit Again!")}</p>
                </div>
            </body>
            </html>
            """

            receipt_text.setHtml(receipt_html)
            layout.addWidget(receipt_text)

            # Track if user chose a receipt option
            self.receipt_option_selected = False
            
            # Helper to enable finish button
            def mark_receipt_selected():
                self.receipt_option_selected = True
                close_btn.setStyleSheet("""
                    QPushButton { background-color: #3b82f6; color: white; font-weight: bold; border-radius: 8px; }
                    QPushButton:hover { background-color: #2563eb; }
                """)

            button_layout = QHBoxLayout()
            print_btn = QPushButton(self.t("Print"))
            
            # Connect print button with tracking to prevent duplicates
            def handle_print():
                mark_receipt_selected()
                if not getattr(self, 'receipt_printed', False):
                    self.print_thermal_receipt(payment, receipt_html)
                    self.receipt_printed = True
                    print_btn.setEnabled(False)
                    print_btn.setText(self.t("Printed"))
            
            print_btn.clicked.connect(handle_print)
            button_layout.addWidget(print_btn)

            email_btn = QPushButton(self.t("Email"))
            def handle_email():
                mark_receipt_selected()
                self.prompt_and_email_receipt(receipt_html)
            email_btn.clicked.connect(handle_email)
            button_layout.addWidget(email_btn)

            telegram_btn = QPushButton(self.t("Telegram"))
            def handle_telegram():
                mark_receipt_selected()
                self.prompt_and_telegram_receipt(payment)
            telegram_btn.clicked.connect(handle_telegram)
            button_layout.addWidget(telegram_btn)

            close_btn = QPushButton(self.t("Finish & Clear Trolley"))
            close_btn.setStyleSheet("""
                QPushButton { background-color: #94a3b8; color: white; border-radius: 8px; }
                QPushButton:hover { background-color: #64748b; }
            """)
            
            def handle_finish():
                if not getattr(self, 'receipt_option_selected', False):
                    self.show_message(self.t("Action Required"), self.t("Please send or print a receipt first, or select a receipt option to continue."), "warning")
                    return
                    
                # Ask user to clear trolley
                if getattr(self, 'scale_worker', None):
                    self._clearing_trolley_active = True
                    try:
                        clear_dlg = ClearTrolleyVerificationOverlay(self, self.scale_worker)
                        if clear_dlg.exec_() == QDialog.Accepted:
                            dlg.accept()
                    finally:
                        self._clearing_trolley_active = False
                else:
                    dlg.accept()

            close_btn.clicked.connect(handle_finish)
            button_layout.addWidget(close_btn)

            layout.addLayout(button_layout)
            
            # Add layout to overlay dialog
            dlg.add_layout(layout)
            
            dlg.exec_()

        finally:
            # Restore original translator
            self.t = original_t

            # Fully refresh UI so the dropdown / labels / cart are correct and responsive.
            # This makes sure all widgets reflect the current self.language and re-renders the table contents.
            try:
                self.refresh_texts()
            except Exception:
                pass
            try:
                self.refresh_cart_display()
            except Exception:
                pass

            # Re-sync combo index with current language (safe - does not change self.language)
            try:
                lang_map = {'en': 0, 'hi': 1, 'gu': 2}
                self.lang_combo.blockSignals(True)
                self.lang_combo.setCurrentIndex(lang_map.get(self.language, 0))
                self.lang_combo.blockSignals(False)
            except Exception:
                pass



    def open_transactions(self):
        self.record_activity()
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            rows = cur.execute("SELECT date, amount, status, razorpay_id FROM transactions ORDER BY id DESC LIMIT 100").fetchall()
        
        # Use custom OverlayDialog instead of native QDialog
        dlg = OverlayDialog(self)
        
        layout = QVBoxLayout()
        
        # Add title manually
        title_label = QLabel("Transaction History")
        title_label.setObjectName("paymentTitle")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 24px; font-weight: bold; margin-bottom: 15px;")
        layout.addWidget(title_label)
        
        table = QTableWidget(len(rows), 4)
        table.setHorizontalHeaderLabels(["Date", "Amount", "Status", "Order ID"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setMinimumWidth(600)
        table.setMinimumHeight(400)
        
        for i, row in enumerate(rows):
            table.setItem(i, 0, QTableWidgetItem(str(row[0])))
            table.setItem(i, 1, QTableWidgetItem(f"₹{row[1]}"))
            table.setItem(i, 2, QTableWidgetItem(str(row[2])))
            table.setItem(i, 3, QTableWidgetItem(str(row[3])))
            
        layout.addWidget(table)
        
        close_btn = QPushButton("Close")
        close_btn.setObjectName("primaryCta")
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn)
        
        # Add layout to overlay dialog
        dlg.add_layout(layout)
        
        dlg.exec_()
    
    def prompt_and_telegram_receipt(self, payment):
        """Show QR code for customer to scan and receive receipt on Telegram."""
        if not TELEGRAM_BOT_TOKEN:
            self.show_message(self.t("Telegram"), "Telegram Bot Token is not configured.", "warning")
            return
        
        if not config.TELEGRAM_BOT_USERNAME:
            self.show_message(self.t("Telegram"), "Telegram bot is not running. Please check bot configuration.", "warning")
            return

        try:
            # Generate unique transaction ID
            transaction_id = str(uuid.uuid4())[:8]
            
            # Store receipt data
            PENDING_RECEIPTS[transaction_id] = {
                'payment': payment,
                'cart': self.cart.copy(),
                'total': self.total,
                'store_name': self.settings.get('store_name', STORE_NAME),
                'timestamp': datetime.now().isoformat()
            }
            
            # Generate Telegram deep link
            deep_link = f"https://t.me/{config.TELEGRAM_BOT_USERNAME}?start=receipt_{transaction_id}"
            
            # Use custom OverlayDialog instead of native QDialog
            dlg = OverlayDialog(self)
            
            layout = QVBoxLayout()
            layout.setSpacing(20)
            
            # Add title manually
            title_label = QLabel(self.t("Telegram Receipt"))
            title_label.setObjectName("paymentTitle")
            title_label.setAlignment(Qt.AlignCenter)
            title_label.setStyleSheet("font-size: 24px; font-weight: bold; margin-bottom: 10px;")
            layout.addWidget(title_label)
            
            # Instructions
            instructions = QLabel(self.t("Scan this QR code with Telegram to receive your receipt:"))
            instructions.setWordWrap(True)
            instructions.setAlignment(Qt.AlignCenter)
            instructions.setStyleSheet("font-size: 16px; color: #333;")
            layout.addWidget(instructions)
            
            # Generate and display QR code
            qr_pixmap = self.generate_qr_code(deep_link)
            qr_label = QLabel()
            qr_label.setPixmap(qr_pixmap)
            qr_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(qr_label)
            
            # Bot username hint
            bot_hint = QLabel(f"Or search for @{config.TELEGRAM_BOT_USERNAME} on Telegram")
            bot_hint.setAlignment(Qt.AlignCenter)
            bot_hint.setStyleSheet("color: #666; font-size: 14px; font-weight: bold;")
            layout.addWidget(bot_hint)
            
            # Close button
            close_btn = QPushButton(self.t("Close"))
            close_btn.setObjectName("primaryCta")
            close_btn.clicked.connect(dlg.accept)
            layout.addWidget(close_btn)
            
            # Add layout to overlay dialog
            dlg.add_layout(layout)
            
            dlg.exec_()
            
        except Exception as e:
            print(f"Error generating Telegram QR: {e}")
            self.show_message(self.t("Telegram"), f"Error generating QR code: {e}", "error")

    def show_message(self, title, message, icon_type="info"):
        """Show a custom overlay message box to replace native QMessageBox."""
        dlg = OverlayDialog(self)
        
        layout = QVBoxLayout()
        layout.setSpacing(20)
        
        # Title
        title_label = QLabel(title)
        title_label.setObjectName("paymentTitle")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 22px; font-weight: bold; margin-bottom: 5px;")
        layout.addWidget(title_label)
        
        # Message
        msg_label = QLabel(message)
        msg_label.setWordWrap(True)
        msg_label.setAlignment(Qt.AlignCenter)
        msg_label.setStyleSheet("font-size: 16px; color: #333;")
        layout.addWidget(msg_label)
        
        # Button
        btn = QPushButton("OK")
        btn.setObjectName("primaryCta")
        btn.setMinimumHeight(50)
        btn.clicked.connect(dlg.accept)
        layout.addWidget(btn)
        
        dlg.add_layout(layout)
        dlg.exec_()

    def generate_qr_code(self, data, size=300):
        """Generate QR code and return as QPixmap."""
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(data)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convert PIL image to QPixmap
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        
        pixmap = QPixmap()
        pixmap.loadFromData(buffer.read())
        return pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    
    def prompt_and_email_receipt(self, html):
        # Use touch-friendly dialog with on-screen keyboard
        dialog = TouchInputDialog(
            self, 
            self.t("Email Receipt"), 
            self.t("Enter recipient email address:"), 
            keyboard_type="email",
            placeholder="customer@example.com"
        )
        
        if dialog.exec_() == QDialog.Accepted:
            email = dialog.get_text().strip()
            if email:
                try:
                    self.send_email(email, f"{STORE_NAME} Receipt", html)
                    self.show_message(self.t("Email"), self.t("Receipt emailed successfully."), "info")
                except Exception as e:
                    self.show_message(self.t("Email"), f"{self.t('Failed to send email')}: {e}", "error")

    def send_email(self, to_email, subject, html_body):
        if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD:
            raise RuntimeError("SMTP not configured. Set SMTP_HOST, SMTP_USER, SMTP_PASSWORD env variables.")
        msg = MIMEMultipart('alternative')
        msg['From'] = SMTP_USER
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(html_body, 'html'))
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        if SMTP_USE_TLS:
            server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, [to_email], msg.as_string())
        server.quit()

    def open_settings(self):
        self.record_activity()
        # Use custom OverlayDialog instead of native QDialog
        dlg = OverlayDialog(self)
        
        layout = QVBoxLayout()
        
        # Add title manually
        title_label = QLabel(self.t("Settings"))
        title_label.setObjectName("paymentTitle")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 24px; font-weight: bold; margin-bottom: 15px;")
        layout.addWidget(title_label)
        
        form_layout = QGridLayout()
        
        form_layout.addWidget(QLabel(self.t("Store Name:")), 0, 0)
        store_name_edit = QLineEdit(self.settings.get('store_name', STORE_NAME))
        form_layout.addWidget(store_name_edit, 0, 1)
        
        form_layout.addWidget(QLabel(self.t("Store Address:")), 1, 0)
        store_address_edit = QLineEdit(self.settings.get('store_address', ''))
        form_layout.addWidget(store_address_edit, 1, 1)

        form_layout.addWidget(QLabel(self.t("Store GSTIN:")), 2, 0)
        store_gstin_edit = QLineEdit(self.settings.get('store_gstin', ''))
        form_layout.addWidget(store_gstin_edit, 2, 1)

        form_layout.addWidget(QLabel(self.t("UPI ID:")), 3, 0)
        upi_id_edit = QLineEdit(self.settings.get('upi_id', STORE_UPI_ID))
        form_layout.addWidget(upi_id_edit, 3, 1)
        
        form_layout.addWidget(QLabel(self.t("Razorpay Enabled:")), 4, 0)
        razorpay_check = QComboBox()
        razorpay_check.addItems(
            ["हाँ", "नहीं"] if self.language == 'hi' else
            ["હા", "ના"] if self.language == 'gu' else
            ["Yes", "No"]
        )
        razorpay_check.setCurrentIndex(0 if self.settings.get('razorpay_enabled', 'true') == 'true' else 1)
        form_layout.addWidget(razorpay_check, 4, 1)
        
        form_layout.addWidget(QLabel(self.t("Logo Transparency Threshold:")), 5, 0)
        threshold_spin = QSpinBox()
        threshold_spin.setRange(200, 255)
        threshold_spin.setValue(self.logo_threshold)
        form_layout.addWidget(threshold_spin, 5, 1)
        
        layout.addLayout(form_layout)
        
        button_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.setObjectName("primaryCta")
        
        def save_settings():
            self.save_setting('store_name', store_name_edit.text())
            self.save_setting('store_address', store_address_edit.text())
            self.save_setting('store_gstin', store_gstin_edit.text())
            self.save_setting('upi_id', upi_id_edit.text())
            self.save_setting('razorpay_enabled', 'true' if razorpay_check.currentIndex() == 0 else 'false')
            self.logo_threshold = int(threshold_spin.value())
            self.save_setting('logo_transparency_threshold', str(self.logo_threshold))
            
            global STORE_NAME, STORE_UPI_ID
            STORE_NAME = store_name_edit.text()
            STORE_UPI_ID = upi_id_edit.text()
            self.store_label.setText(STORE_NAME)
            # Also reflect store name next to the hero logo if present
            if hasattr(self, 'hero_name') and self.hero_name is not None:
                self.hero_name.setText(STORE_NAME)
            self.refresh_logos()
            
            dlg.accept()
        
        save_btn.clicked.connect(save_settings)
        button_layout.addWidget(save_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dlg.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
        
        # Add layout to overlay dialog
        dlg.add_layout(layout)
        
        dlg.exec_()

    def admin_exit(self):
        # Touch-friendly password prompt using on-screen keyboard
        dialog = TouchInputDialog(
            self,
            self.t("Admin Exit"),
            self.t("Enter admin password:"),
            keyboard_type="default",
            placeholder="******",
            is_password=True
        )
        if dialog.exec_() == QDialog.Accepted:
            password = dialog.get_text()
            if password == ADMIN_PASSWORD:
                self.close()
            else:
                self.show_message(self.t("Invalid Credentials"), self.t("Incorrect username or password."), "warning")

    def record_activity(self):
        self.last_activity = time.time()
        if self.stacked_widget.currentWidget() is self.idle_screen:
            self.stacked_widget.setCurrentWidget(self.cart_screen)

    def check_idle(self):
        # Never go to idle when cart has items
        if self.payment_in_progress:
            return
        if len(self.cart) > 0:
            return
        # Never go to idle when in admin panel
        if hasattr(self, 'admin_screen') and self.stacked_widget.currentWidget() == self.admin_screen:
            return
        if time.time() - self.last_activity > IDLE_TIMEOUT:
            # Do not clear cart by default on idle; keep items when the screen sleeps and wakes up.
            # If the environment variable CLEAR_CART_ON_IDLE is set to true, clear as before.
            try:
                if CLEAR_CART_ON_IDLE:
                    self.clear_cart()
            except Exception:
                # If for some reason the flag is not in scope, fail safe and preserve cart
                pass
            self.stacked_widget.setCurrentWidget(self.idle_screen)
            
    def serial_scanner_thread(self):
        try:
            ser = serial.Serial(SERIAL_PORT, SERIAL_BAUDRATE, timeout=1)
            print("Serial scanner listening on", SERIAL_PORT)
            buf = ""
            while True:
                ch = ser.read().decode(errors='ignore')
                if not ch:
                    continue
                if ch in ("\n", "\r"):
                    barcode = buf.strip()
                    buf = ""
                    if barcode:
                        QApplication.postEvent(self, BarcodeEvent(barcode))
                else:
                    buf += ch
        except Exception as e:
            print("Serial scanner error:", e)
    
    def closeEvent(self, event):
        print("Application closing. Exiting.")
        if hasattr(self, 'scale_worker') and self.scale_worker:
            self.scale_worker.stop()
        # Disconnect thermal printer
        if hasattr(self, 'thermal_printer') and self.thermal_printer:
            self.thermal_printer.disconnect()
        event.accept()
    
    def _connect_thermal_printer(self):
        """Attempt to connect to thermal printer on startup."""
        if not ESCPOS_AVAILABLE:
            print("[Thermal Printer] python-escpos not installed. Thermal printing disabled.")
            return
        
        try:
            # Try Windows printer first (official Hoin drivers - RECOMMENDED)
            if self.thermal_printer.connect_windows_printer():
                print("[Thermal Printer] Successfully connected via Windows printer driver")
                return
            
            # Fallback: Try raw USB connection (requires WinUSB driver)
            print("[Thermal Printer] Windows printer not found, trying raw USB...")
            if self.thermal_printer.connect_usb():
                print("[Thermal Printer] Successfully connected via raw USB")
                return
            
            print("[Thermal Printer] No printer found. Install official Hoin drivers or configure manually.")
        except Exception as e:
            print(f"[Thermal Printer] Connection error: {e}")
    
    def print_thermal_receipt(self, payment, receipt_html):
        """Print receipt on thermal printer."""
        if not ESCPOS_AVAILABLE:
            self.show_message(
                self.t("Print Error"),
                "Thermal printer library not installed. Please install python-escpos.",
                "error"
            )
            return
        
        if not self.thermal_printer.connected:
            # Try to reconnect (Windows printer first, then USB)
            self.show_message(
                self.t("Print"),
                "Connecting to printer...",
                "info"
            )
            if not (self.thermal_printer.connect_windows_printer() or self.thermal_printer.connect_usb()):
                self.show_message(
                    self.t("Print Error"),
                    "Printer not connected. Please check connection and try again.",
                    "error"
                )
                return
        
        try:
            # Print the receipt
            self.thermal_printer.print_receipt(
                payment_data=payment,
                cart_items=self.cart,
                total=self.total,
                store_settings=self.settings
            )
            
            # CRITICAL: Disconnect to flush Windows print queue
            # This ensures the job prints immediately instead of staying in queue
            self.thermal_printer.disconnect()
            
            self.show_message(
                self.t("Print"),
                self.t("Receipt printed successfully!"),
                "info"
            )
        except Exception as e:
            print(f"[Thermal Printer] Print error: {e}")
            self.show_message(
                self.t("Print Error"),
                f"Failed to print receipt: {str(e)}",
                "error"
            )

    def open_admin_panel(self):
        """Prompt for admin credentials and navigate to admin screen on success."""
        self.record_activity()
        
        # Get username with touch keyboard
        username_dialog = TouchInputDialog(
            self,
            self.t("Admin Login"),
            self.t("Enter admin username:"),
            keyboard_type="default",
            placeholder="admin"
        )
        
        if username_dialog.exec_() != QDialog.Accepted:
            return
            
        username = username_dialog.get_text().strip()
        
        # Get password with touch keyboard
        password_dialog = TouchInputDialog(
            self,
            self.t("Admin Login"),
            self.t("Enter admin password:"),
            keyboard_type="default",
            placeholder="password",
            is_password=True
        )
        
        if password_dialog.exec_() != QDialog.Accepted:
            return
            
        password = password_dialog.get_text()
        
        # Verify credentials
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            self.admin_verified = True
            # Reset to Dashboard tab and refresh data
            self.admin_tabs.setCurrentIndex(0)
            self.refresh_admin_dashboard()
            self._load_admin_settings()
            self.stacked_widget.setCurrentWidget(self.admin_screen)
        else:
            self.show_message(self.t("Invalid Credentials"), self.t("Incorrect username or password."), "warning")

    def t(self, s):
        hi = {
            "Welcome to {store}\nScan your first item to begin": "{store} में आपका स्वागत है\nशुरू करने के लिए पहला आइटम स्कैन करें",
            "Clear Cart": "कार्ट साफ करें",
            "Checkout": "चेकआउट",
            "Payment Successful!": "भुगतान सफल!",
            "Payment Failed": "भुगतान असफल",
            "Empty cart": "खाली कार्ट",
            "Add items before proceeding to payment.": "भुगतान से पहले आइटम जोड़ें।",
            "Add items before payment.": "भुगतान से पहले आइटम जोड़ें।",
            "Product not found": "उत्पाद नहीं मिला",
            "No product for barcode: {code}": "बारकोड के लिए कोई उत्पाद नहीं: {code}",
            "Transactions": "लेन-देन", "Settings": "सेटिंग्स", "Exit": "बंद करें",
            "Admin Login": "एडमिन लॉगिन",
            "Username": "उपयोगकर्ता नाम", "Password": "पासवर्ड", "Login": "लॉगिन",
            "Cancel": "रद्द करें", "Invalid Credentials": "अमान्य प्रमाण-पत्र",
            "Incorrect username or password.": "गलत उपयोगकर्ता नाम या पासवर्ड।",
            "Store Name:": "दुकान का नाम:", "UPI ID:": "यूपीआई आईडी:",
            "Store Address:": "दुकान का पता:", "Store GSTIN:": "स्टोर GSTIN:",
            "Razorpay Enabled:": "रेज़रपे सक्षम:", "Save": "सहेजें", "Close": "बंद करें",
            "Email": "ईमेल", "Print": "प्रिंट", "Payment Receipt": "भुगतान रसीद",
            "Enter recipient email": "प्राप्तकर्ता ईमेल दर्ज करें",
            "Receipt emailed successfully.": "रसीद ईमेल कर दी गई।",
            "Failed to send email": "ईमेल भेजने में विफल",
            # New Receipt Keys for Translation
            "Tax Invoice": "टैक्स चालान", "Bill No": "बिल नंबर", "Date": "दिनांक",
            "Payment ID": "पेमेंट आईडी", "HSN": "HSN", "PARTICULARS": "विवरण",
            "QTY": "मात्रा", "RATE": "दर", "VALUE": "मूल्य", "SUB TOTAL": "उप-total",
            "CGST": "CGST", "SGST": "SGST", "GRAND TOTAL": "कुल योग",
            "GST Breakup Details": "GST विवरण", "GST%": "GST%",
            "Taxable Amt": "कर योग्य राशि", "Total Tax": "कुल कर",
            "Thank You! Visit Again!": "धन्यवाद! फिर से पधारें!",
            "Email Receipt": "ईमेल रसीद", "Enter recipient email address:": "प्राप्तकर्ता ईमेल पता दर्ज करें:",
            "Telegram": "टेलीग्राम", "Telegram Receipt": "टेलीग्राम रसीद",
            "Enter Telegram Chat ID:": "टेलीग्राम चैट आईडी दर्ज करें:",
            "Receipt sent to Telegram successfully.": "रसीद टेलीग्राम पर सफलतापूर्वक भेज दी गई।",
            "Failed to send Telegram message": "टेलीग्राम संदेश भेजने में विफल",
            "Scan this QR code with Telegram to receive your receipt:": "अपनी रसीद प्राप्त करने के लिए टेलीग्राम से इस QR कोड को स्कैन करें:",
            "Enter admin username:": "एडमिन उपयोगकर्ता नाम दर्ज करें:", "Enter admin password:": "एडमिन पासवर्ड दर्ज करें:",
            "Admin Exit": "एडमिन बाहर निकलें", "Invalid Password": "अमान्य पासवर्ड", "Incorrect password.": "गलत पासवर्ड।",
            # Checkout dialog
            "Confirm Checkout": "चेकआउट की पुष्टि करें",
            "Are you sure you want to proceed to payment?": "क्या आप भुगतान के लिए आगे बढ़ना चाहते हैं?",
            "Yes, Proceed": "हाँ, आगे बढ़ें",
            "Logo Transparency Threshold:": "लोगो पारदर्शिता सीमा:",
            "Printed": "प्रिंट हो गया",
            "Print Error": "प्रिंट त्रुटि",
            "Receipt printed successfully!": "रसीद सफलतापूर्वक प्रिंट हो गई!",
        }
        gu = {
            "Welcome to {store}\nScan your first item to begin": "{store} માં આપનું સ્વાગત છે\nશરૂ કરવા માટે પ્રથમ આઇટમ સ્કેન કરો",
            "Clear Cart": "કાર્ટ સાફ કરો",
            "Checkout": "ચેકઆઉટ",
            "Payment Successful!": "ચુકવણી સફળ!",
            "Payment Failed": "ચુકવણી નિષ્ફળ",
            "Empty cart": "ખાલી કાર્ટ",
            "Add items before proceeding to payment.": "ચુકવણી કરતાં પહેલાં આઇટમ્સ ઉમેરો.",
            "Add items before payment.": "ચુકવણી કરતાં પહેલાં આઇટમ્સ ઉમેરો.",
            "Product not found": "ઉત્પાદન મળ્યું નથી",
            "No product for barcode: {code}": "બારકોડ માટે કોઈ ઉત્પાદન નથી: {code}",
            "Transactions": "વ્યવહારો", "Settings": "સેટિંગ્સ", "Exit": "બહાર નીકળો",
            "Admin Login": "એડમિન લોગિન",
            "Username": "વપરાશકર્તા નામ", "Password": "પાસવર્ડ", "Login": "લોગિન",
            "Cancel": "રદ કરો", "Invalid Credentials": "અમાન્ય ઓળખપત્રો",
            "Incorrect username or password.": "ખોટું વપરાશકર્તા નામ અથવા પાસવર્ડ.",
            "Store Name:": "સ્ટોરનું નામ:", "UPI ID:": "UPI ID:",
            "Store Address:": "સ્ટોરનું સરનામું:", "Store GSTIN:": "સ્ટોર GSTIN:",
            "Razorpay Enabled:": "રેઝરપે સક્ષમ:", "Save": "સાચવો", "Close": "બંધ કરો",
            "Email": "ઈમેલ", "Print": "પ્રિન્ટ", "Payment Receipt": "ચુકવણીની રસીદ",
            "Enter recipient email": "પ્રાપ્તકર્તાનો ઇમેઇલ દાખલ કરો",
            "Receipt emailed successfully.": "રસીદ સફળતાપૂર્વક ઇમેઇલ કરવામાં આવી.",
            "Failed to send email": "ઇમેઇલ મોકલવામાં નિષ્ફળ",
            # New Receipt Keys for Translation
            "Tax Invoice": "ટેક્સ ઇન્વોઇસ", "Bill No": "બિલ નંબર", "Date": "તારીખ",
            "Payment ID": "પેમેન્ટ ID", "HSN": "HSN", "PARTICULARS": "વિગતો",
            "QTY": "જથ્થો", "RATE": "દર", "VALUE": "કિંમત", "SUB TOTAL": "પેટા-ટોટલ",
            "CGST": "CGST", "SGST": "SGST", "GRAND TOTAL": "કુલ સરવાળો",
            "GST Breakup Details": "GST વિગતો", "GST%": "GST%",
            "Taxable Amt": "કરપાત્ર રકમ", "Total Tax": "કુલ કર",
            "Thank You! Visit Again!": "આભાર! ફરી મુલાકાત લેજો!",
            "Email Receipt": "ઇમેઇલ રસીદ", "Enter recipient email address:": "પ્રાપ્તકર્તાનો ઇમેઇલ સરનામું દાખલ કરો:",
            "Telegram": "ટેલિગ્રામ", "Telegram Receipt": "ટેલિગ્રામ રસીદ",
            "Enter Telegram Chat ID:": "ટેલિગ્રામ ચેટ આઈડી દાખલ કરો:",
            "Receipt sent to Telegram successfully.": "રસીદ ટેલિગ્રામ પર સફળતાપૂર્વક મોકલવામાં આવી.",
            "Failed to send Telegram message": "ટેલિગ્રામ સંદેશ મોકલવામાં નિષ્ફળ",
            "Scan this QR code with Telegram to receive your receipt:": "તમારી રસીદ મેળવવા માટે ટેલિગ્રામ સાથે આ QR કોડ સ્કેન કરો:",
            "Enter admin username:": "એડમિન વપરાશકર્તા નામ દાખલ કરો:", "Enter admin password:": "એડમિન પાસવર્ડ દાખલ કરો:",
            "Admin Exit": "એડમિન બહાર નીકળો", "Invalid Password": "અમાન્ય પાસવર્ડ", "Incorrect password.": "ખોટું પાસવર્ડ.",
            # Checkout dialog
            "Confirm Checkout": "ચેકઆઉટની પુષ્ટિ કરો",
            "Are you sure you want to proceed to payment?": "શું તમે ચુકવણી માટે આગળ વધવા માંગો છો?",
            "Yes, Proceed": "હા, આગળ વધો",
            "Logo Transparency Threshold:": "લોગો પારદર્શકતા સીમા:",
            "Printed": "પ્રિન્ટ થઈ ગયું",
            "Print Error": "પ્રિન્ટ ત્રુટિ",
            "Receipt printed successfully!": "રસીદ સફળતાપૂર્વક પ્રિન્ટ થઈ ગઈ!",
        }

        if self.language == 'hi' and s in hi:
            return hi[s]
        if self.language == 'gu' and s in gu:
            return gu[s]
        return s

    def refresh_texts(self):
        # Update static texts based on language
        self.store_label.setText(STORE_NAME)
        self.clear_btn.setText("\ud83d\uddd1 " + self.t("Clear Cart"))
        self.pay_btn.setText(self.t("Checkout"))
        if hasattr(self, 'back_btn') and self.back_btn is not None:
            self.back_btn.setText(self.t("\u2190 Back to Cart"))
        self.admin_panel_btn.setText("\u2699")
        
        # Dynamically set table headers based on language
        headers = {
            'en': ["Product", "Price", "Qty", "Total", ""],
            'hi': ["उत्पाद", "कीमत", "संख्या", "कुल", ""],
            'gu': ["ઉત્પાદન", "કિંમત", "જથ્થો", "કુલ", ""]
        }
        self.cart_table.setHorizontalHeaderLabels(headers.get(self.language, headers['en']))

        # Idle label
        idle_label = self.findChild(QLabel, "idleLabel")
        if idle_label:
            idle_text = self.t("Welcome to {store}\nScan your first item to begin").format(store=STORE_NAME)
            idle_label.setText(idle_text)
        # Update total label format on language change
        self.total_label.setText(self.total_label_text())

    def to_devanagari_digits(self, s: str) -> str:
        mapping = str.maketrans('0123456789', '०१२३४५६७८९')
        return s.translate(mapping)
    
    def to_gujarati_digits(self, s: str) -> str:
        mapping = str.maketrans('0123456789', '૦૧૨૩૪૫૬૭૮૯')
        return s.translate(mapping)

    def fmt_int(self, n: int) -> str:
        s = f"{n}"
        if self.language == 'hi':
            return self.to_devanagari_digits(s)
        if self.language == 'gu':
            return self.to_gujarati_digits(s)
        return s

    def fmt_amount(self, amount_inr: float) -> str:
        text = f"₹{amount_inr:.2f}"
        if self.language == 'hi':
            return self.to_devanagari_digits(text)
        if self.language == 'gu':
            return self.to_gujarati_digits(text)
        return text

    def total_label_text(self) -> str:
        if self.language == 'hi':
            return f"कुल: {self.fmt_amount(self.total)}"
        if self.language == 'gu':
            return f"કુલ: {self.fmt_amount(self.total)}"
        return f"Total: {self.fmt_amount(self.total)}"

# ---- Dead duplicate code removed ----
# format_amount_server(), run_telegram_bot(), and generate_receipt_text()
# were duplicated from utils.py and telegram_bot.py — removed.
