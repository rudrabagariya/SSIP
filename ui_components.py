"""
Reusable UI components for Smart Checkout Kiosk
Uses Qt Virtual Keyboard for touch-friendly input
"""
import time
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QLineEdit, QDialog, QSizePolicy, QFrame, QGraphicsDropShadowEffect,
    QProgressBar
)
from PySide6.QtCore import Qt, Signal, QEventLoop, QSize, QRect, QPoint, QTimer, QEvent
from PySide6.QtGui import QColor, QPalette, QBrush, QPainter, QImage, QPixmap

class OverlayDialog(QWidget):
    """
    Base class for custom overlay dialogs that replace native QDialogs.
    Renders inside the application window to prevent OS window management (minimize/close).
    Automatically locks to parent window size and centers modal content.
    """
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_widget = parent
        
        # Cover parent window immediately
        self.update_geometry()
        if self.parent_widget:
            self.parent_widget.installEventFilter(self)
        
        # Semi-transparent background setup
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        
        # Main layout for the overlay (centers the content)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setAlignment(Qt.AlignCenter)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        
        # Content container (the actual "dialog" box)
        self.content_container = QFrame()
        self.content_container.setObjectName("overlayContent")
        self.content_container.setStyleSheet("""
            QFrame#overlayContent {
                background-color: #ffffff;
                border-radius: 18px;
                border: 1px solid #cbd5e1;
            }
            QFrame#overlayContent QLabel {
                background-color: transparent;
            }
        """)
        
        # Add shadow to content
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(30)
        shadow.setColor(QColor(0, 0, 0, 75))
        shadow.setOffset(0, 8)
        self.content_container.setGraphicsEffect(shadow)
        
        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(24, 24, 24, 24)
        self.content_layout.setSpacing(14)
        
        self.main_layout.addWidget(self.content_container)
        
        # Event loop for blocking behavior
        self._event_loop = None
        self._result = QDialog.Rejected
        
        # Hide by default
        self.setVisible(False)

    def paintEvent(self, event):
        painter = QPainter(self)
        # Draw smooth semi-transparent dark backdrop over the whole application
        painter.fillRect(self.rect(), QColor(15, 23, 42, 145))

    def eventFilter(self, obj, event):
        if obj == self.parent_widget and event.type() in (QEvent.Resize, QEvent.Show, QEvent.WindowStateChange):
            self.update_geometry()
        return super().eventFilter(obj, event)

    def update_geometry(self):
        if self.parent_widget:
            self.setGeometry(0, 0, self.parent_widget.width(), self.parent_widget.height())

    def showEvent(self, event):
        self.update_geometry()
        super().showEvent(event)

    def setLayout(self, layout):
        pass

    def add_widget(self, widget):
        self.content_layout.addWidget(widget)

    def add_layout(self, layout):
        self.content_layout.addLayout(layout)
        
    def exec_(self):
        """Block until accepted or rejected, similar to QDialog.exec_()"""
        self.update_geometry()
        self.setVisible(True)
        self.raise_()
        self.setFocus()
        
        self._event_loop = QEventLoop()
        self._event_loop.exec()
        
        self.setVisible(False)
        self.deleteLater()
        return self._result

    def accept(self):
        self._result = QDialog.Accepted
        if self._event_loop:
            self._event_loop.quit()

    def reject(self):
        self._result = QDialog.Rejected
        if self._event_loop:
            self._event_loop.quit()
            
    def resizeEvent(self, event):
        self.update_geometry()
        super().resizeEvent(event)

class TouchInputDialog(OverlayDialog):
    """Custom input dialog with Qt Virtual Keyboard support (Overlay version)"""
    
    def __init__(self, parent, title, label, keyboard_type="default", placeholder="", is_password=False):
        super().__init__(parent)
        
        # Set fixed width for the dialog box
        self.content_container.setFixedWidth(500)
        
        # Title
        title_label = QLabel(title)
        title_label.setObjectName("paymentTitle")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 22px; font-weight: bold; color: #333; margin-bottom: 10px;")
        self.content_layout.addWidget(title_label)
        
        # Input label
        input_label = QLabel(label)
        input_label.setAlignment(Qt.AlignCenter)
        input_label.setStyleSheet("font-size: 16px; color: #666;")
        self.content_layout.addWidget(input_label)
        
        # Input field
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText(placeholder)
        self.input_field.setMinimumHeight(50)
        self.input_field.setAlignment(Qt.AlignCenter)
        self.input_field.setStyleSheet("""
            QLineEdit {
                border: 2px solid #ddd;
                border-radius: 8px;
                padding: 10px;
                font-size: 18px;
            }
            QLineEdit:focus {
                border-color: #4a90e2;
            }
        """)
        
        if is_password:
            self.input_field.setEchoMode(QLineEdit.Password)
        
        self.content_layout.addWidget(self.input_field)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(15)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setMinimumHeight(50)
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.setStyleSheet("""
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
        self.cancel_btn.clicked.connect(self.reject)
        
        self.ok_btn = QPushButton("OK")
        self.ok_btn.setObjectName("primaryCta") # Inherit primary style if available
        self.ok_btn.setMinimumHeight(50)
        self.ok_btn.setCursor(Qt.PointingHandCursor)
        # Fallback style if ID styling doesn't apply in overlay context
        self.ok_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a90e2;
                border: none;
                border-radius: 8px;
                font-size: 16px;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #357abd;
            }
        """)
        self.ok_btn.clicked.connect(self.accept_input)
        
        button_layout.addWidget(self.cancel_btn)
        button_layout.addWidget(self.ok_btn)
        self.content_layout.addLayout(button_layout)
        
        # Handle Enter key
        self.input_field.returnPressed.connect(self.accept_input)
        
        # Set focus
        self.input_field.setFocus()
    
    def accept_input(self):
        """Accept the input and close dialog"""
        self.result_text = self.input_field.text()
        self.accept()
    
    def get_text(self):
        """Get the entered text"""
        return self.result_text


class ScaleTareOverlay(OverlayDialog):
    """
    Animated fullscreen/modal overlay shown on startup or manual tare.
    Displays tare progress, instructions to leave trolley empty, and offset confirmation.
    """
    def __init__(self, parent, scale_worker):
        super().__init__(parent)
        self.scale_worker = scale_worker
        self.content_container.setFixedWidth(460)

        # Brand Icon Badge
        icon_container = QWidget()
        icon_container.setStyleSheet("background: transparent;")
        icon_layout = QHBoxLayout(icon_container)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setAlignment(Qt.AlignCenter)

        icon_badge = QLabel()
        icon_badge.setAlignment(Qt.AlignCenter)
        icon_badge.setFixedSize(60, 60)
        icon_badge.setStyleSheet("""
            background-color: #eef2ff;
            border-radius: 30px;
            border: 1.5px solid #c7d2fe;
        """)

        cart_loaded = False
        try:
            import os
            base_dir = os.path.dirname(__file__)
            cart_path = os.path.join(base_dir, "cart.png")
            if os.path.exists(cart_path):
                img = QImage(cart_path).convertToFormat(QImage.Format_ARGB32)
                for y in range(img.height()):
                    for x in range(img.width()):
                        c = QColor(img.pixel(x, y))
                        if c.red() >= 240 and c.green() >= 240 and c.blue() >= 240:
                            c.setAlpha(0)
                            img.setPixelColor(x, y, c)
                pix = QPixmap.fromImage(img).scaled(34, 34, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                icon_badge.setPixmap(pix)
                cart_loaded = True
        except Exception:
            pass

        if not cart_loaded:
            icon_badge.setText("⚖️")
            icon_badge.setStyleSheet("font-size: 28px; background: #eef2ff; border-radius: 30px; border: 1.5px solid #c7d2fe;")

        icon_layout.addWidget(icon_badge)
        self.content_layout.addWidget(icon_container)

        title_label = QLabel("Zeroing Smart Trolley")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #0f172a; margin-top: 2px;")
        self.content_layout.addWidget(title_label)

        sub_label = QLabel("Please ensure the trolley is empty and untouched.")
        sub_label.setAlignment(Qt.AlignCenter)
        sub_label.setWordWrap(True)
        sub_label.setStyleSheet("font-size: 13px; color: #64748b; margin-bottom: 6px;")
        self.content_layout.addWidget(sub_label)

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1.5px solid #e2e8f0;
                border-radius: 10px;
                text-align: center;
                height: 28px;
                font-weight: 700;
                font-size: 12px;
                color: #0f172a;
                background-color: #f8fafc;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4f46e5, stop:1 #10b981);
                border-radius: 8px;
            }
        """)
        self.content_layout.addWidget(self.progress_bar)

        # Status message
        self.status_label = QLabel("Initializing sensor...")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 13px; color: #475569; font-weight: 600; margin-top: 4px;")
        self.content_layout.addWidget(self.status_label)

        # Connect scale worker signals
        if self.scale_worker:
            self.scale_worker.sig_tare_progress.connect(self.on_progress)
            self.scale_worker.sig_tare_completed.connect(self.on_completed)

    def on_progress(self, pct, status):
        self.progress_bar.setValue(pct)
        self.status_label.setText(status)

    def on_completed(self, success, msg, offset):
        self.progress_bar.setValue(100)
        if success:
            self.status_label.setText(f"✅ {msg}")
            self.status_label.setStyleSheet("font-size: 14px; color: #16a34a; font-weight: 700; margin-top: 10px;")
            QTimer.singleShot(1200, self.accept)
        else:
            self.status_label.setText(f"⚠️ {msg}")
            self.status_label.setStyleSheet("font-size: 14px; color: #dc2626; font-weight: 700; margin-top: 10px;")
            QTimer.singleShot(2000, self.reject)


class ItemWeightVerificationOverlay(OverlayDialog):
    """
    Active item-by-item verification dialog.
    Triggered when an item with weight_grams > 0 is scanned.
    Waits for the user to place the item into the trolley,
    tracks the weight delta, and validates against expected weight.
    """
    def __init__(self, parent, scale_worker, product_name, expected_weight, tolerance_pct=20.0, tolerance_g=8.0, camera_worker=None, expected_yolo_class=None):
        super().__init__(parent)
        self.scale_worker = scale_worker
        self.camera_worker = camera_worker
        self.expected_yolo_class = expected_yolo_class
        self.product_name = product_name
        self.expected_weight = float(expected_weight)
        self.tolerance_pct = tolerance_pct
        self.tolerance_g = tolerance_g
        self.measured_weight = self.expected_weight

        # Compute acceptable bounds
        tol = max(self.tolerance_g, self.expected_weight * (self.tolerance_pct / 100.0))
        self.min_weight = max(1.0, self.expected_weight - tol)
        self.max_weight = self.expected_weight + tol

        self.initial_weight = self.scale_worker.get_current_weight() if self.scale_worker else 0.0
        self.verified = False
        self.weight_verified = False
        self.content_container.setFixedWidth(540)

        # Title
        title_label = QLabel("📦 Place Item into Trolley")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 22px; font-weight: 800; color: #1e293b; margin-bottom: 4px;")
        self.content_layout.addWidget(title_label)

        # Product Name & Expected Weight Box
        prod_box = QFrame()
        prod_box.setStyleSheet("background-color: #f1f5f9; border-radius: 12px; padding: 12px;")
        pb_layout = QVBoxLayout(prod_box)
        pb_layout.setContentsMargins(12, 10, 12, 10)
        
        p_name = QLabel(self.product_name)
        p_name.setAlignment(Qt.AlignCenter)
        p_name.setStyleSheet("font-size: 18px; font-weight: 700; color: #0f172a;")
        p_name.setWordWrap(True)
        pb_layout.addWidget(p_name)

        target_info = QLabel("Please place the item into the trolley to verify")
        target_info.setAlignment(Qt.AlignCenter)
        target_info.setStyleSheet("font-size: 14px; color: #64748b; font-weight: 500; margin-top: 4px;")
        pb_layout.addWidget(target_info)
        self.content_layout.addWidget(prod_box)

        # Live Reading Box
        self.reading_box = QFrame()
        self.reading_box.setStyleSheet("background-color: #eff6ff; border: 2px solid #93c5fd; border-radius: 12px; padding: 12px;")
        rb_layout = QVBoxLayout(self.reading_box)
        
        self.live_diff_label = QLabel("Waiting for item...")
        self.live_diff_label.setAlignment(Qt.AlignCenter)
        self.live_diff_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #1d4ed8;")
        rb_layout.addWidget(self.live_diff_label)

        self.live_status_label = QLabel("Place the item into the trolley to verify")
        self.live_status_label.setAlignment(Qt.AlignCenter)
        self.live_status_label.setStyleSheet("font-size: 13px; color: #3b82f6;")
        rb_layout.addWidget(self.live_status_label)
        self.content_layout.addWidget(self.reading_box)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setMinimumHeight(46)
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #f1f5f9;
                color: #64748b;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                font-size: 15px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #e2e8f0; }
        """)
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        self.content_layout.addLayout(btn_layout)

        # Connect live scale signal
        if self.scale_worker:
            self.scale_worker.sig_weight_updated.connect(self.on_weight_update)

    def on_weight_update(self, current_weight, is_stable):
        if self.verified or self.weight_verified:
            return

        # If user lifted an item that was already resting on the trolley, adjust baseline
        if current_weight < (self.initial_weight - 5.0):
            self.initial_weight = current_weight

        diff = current_weight - self.initial_weight

        if diff <= 2.0:
            self.live_diff_label.setText("Waiting for item...")
            self.live_status_label.setText("Place the item into the trolley")
            self.reading_box.setStyleSheet("background-color: #eff6ff; border: 2px solid #93c5fd; border-radius: 12px;")
            return

        # An item has been placed
        self.live_diff_label.setText(f"+{diff:.1f} g")

        if self.min_weight <= diff <= self.max_weight:
            if is_stable:
                self.weight_verified = True
                self.measured_weight = round(diff, 1)
                
                if self.camera_worker and self.expected_yolo_class:
                    self.live_status_label.setText(f"Weight matched! Looking for {self.expected_yolo_class}...")
                    self.reading_box.setStyleSheet("background-color: #f0fdf4; border: 2px solid #4ade80; border-radius: 12px;")
                    self.live_diff_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #15803d;")
                    self.start_visual_verification()
                else:
                    self.verified = True
                    self.live_diff_label.setText(f"✅ Verified: +{diff:.1f} g")
                    self.live_status_label.setText("Weight matched! Adding to cart...")
                    self.reading_box.setStyleSheet("background-color: #f0fdf4; border: 2px solid #4ade80; border-radius: 12px;")
                    self.live_diff_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #15803d;")
                    self.live_status_label.setStyleSheet("font-size: 13px; color: #16a34a; font-weight: 600;")
                    QTimer.singleShot(800, self.accept)
            else:
                self.live_status_label.setText("Stabilizing reading...")
                self.reading_box.setStyleSheet("background-color: #fefce8; border: 2px solid #fde047; border-radius: 12px;")
                self.live_diff_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #854d0e;")
                self.live_status_label.setStyleSheet("font-size: 13px; color: #ca8a04;")
        else:
            if is_stable:
                self.live_status_label.setText("⚠️ Weight mismatch detected. Please place the correct item.")
                self.reading_box.setStyleSheet("background-color: #fef2f2; border: 2px solid #f87171; border-radius: 12px;")
                self.live_diff_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #b91c1c;")
                self.live_status_label.setStyleSheet("font-size: 13px; color: #dc2626; font-weight: 600;")

    def start_visual_verification(self):
        """Initiate strict multi-frame visual verification (10s window, 3 positive matches required)."""
        self.match_count = 0
        self.required_matches = 3
        self.total_duration_secs = 10.0
        self.start_time = time.time()
        
        try:
            self.camera_worker.sig_detection_result.connect(self.on_camera_detection)
            self.camera_worker.sig_camera_error.connect(self.on_camera_error)
        except Exception:
            pass

        # Poll camera every 250ms (up to ~40 frames in 10s)
        self.visual_timer = QTimer(self)
        self.visual_timer.timeout.connect(self._poll_camera)
        self.visual_timer.start(250)
        self._poll_camera()

    def _poll_camera(self):
        if self.verified or not self.camera_worker:
            if hasattr(self, 'visual_timer') and self.visual_timer:
                self.visual_timer.stop()
            return
            
        elapsed = time.time() - self.start_time
        remaining = max(0.0, self.total_duration_secs - elapsed)
        
        if remaining <= 0:
            # 10s expired without required 3 matches - Strict rejection, no bypass
            if hasattr(self, 'visual_timer') and self.visual_timer:
                self.visual_timer.stop()
            self._disconnect_camera()
            self.weight_verified = False # Reset so customer can reposition item
            self.live_status_label.setText(
                f"❌ Visual verification failed! Expected '{self.expected_yolo_class}' (only matched {self.match_count}/{self.required_matches}). Please face item to camera."
            )
            self.reading_box.setStyleSheet("background-color: #fef2f2; border: 2px solid #f87171; border-radius: 12px;")
            self.live_diff_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #b91c1c;")
            self.live_status_label.setStyleSheet("font-size: 13px; color: #dc2626; font-weight: 600;")
            return

        self.camera_worker.request_analysis()

    def on_camera_detection(self, detected_items):
        if self.verified:
            return

        elapsed = time.time() - self.start_time
        remaining = max(0.0, self.total_duration_secs - elapsed)

        print(f"[VisualVerify] Frame: detected={detected_items}, expected={self.expected_yolo_class}, matches={self.match_count}/{self.required_matches}")

        if self.expected_yolo_class in detected_items:
            self.match_count += 1
            if self.match_count >= self.required_matches:
                self.verified = True
                if hasattr(self, 'visual_timer') and self.visual_timer:
                    self.visual_timer.stop()
                self._disconnect_camera()
                self.live_diff_label.setText(f"✅ Verified: +{self.measured_weight:.1f} g")
                self.live_status_label.setText(f"Visual & Weight verified ({self.required_matches}/{self.required_matches} matches)! Adding to cart...")
                self.live_status_label.setStyleSheet("font-size: 13px; color: #16a34a; font-weight: 600;")
                self.reading_box.setStyleSheet("background-color: #f0fdf4; border: 2px solid #4ade80; border-radius: 12px;")
                QTimer.singleShot(700, self.accept)
                return
            else:
                self.live_status_label.setText(f"🔍 Confirmed {self.match_count}/{self.required_matches} visual matches ({remaining:.0f}s left)...")
                self.reading_box.setStyleSheet("background-color: #f0fdf4; border: 2px solid #4ade80; border-radius: 12px;")
                self.live_status_label.setStyleSheet("font-size: 13px; color: #15803d; font-weight: 600;")
        else:
            saw = f" (seeing {', '.join(detected_items)})" if detected_items else ""
            self.live_status_label.setText(f"Analyzing camera ({remaining:.0f}s left)... Matched {self.match_count}/{self.required_matches}{saw}")
            self.reading_box.setStyleSheet("background-color: #eff6ff; border: 2px solid #93c5fd; border-radius: 12px;")
            self.live_status_label.setStyleSheet("font-size: 13px; color: #2563eb; font-weight: 600;")

    def on_camera_error(self, err_msg):
        print(f"[VisualVerify] Camera error reported: {err_msg}")
        self._disconnect_camera()
        if hasattr(self, 'visual_timer') and self.visual_timer:
            self.visual_timer.stop()
        self.weight_verified = False
        self.live_status_label.setText(f"❌ Camera error: {err_msg}. Visual check is required.")
        self.reading_box.setStyleSheet("background-color: #fef2f2; border: 2px solid #f87171; border-radius: 12px;")
        self.live_diff_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #b91c1c;")
        self.live_status_label.setStyleSheet("font-size: 13px; color: #dc2626; font-weight: 600;")

    def _disconnect_camera(self):
        try:
            if self.camera_worker:
                self.camera_worker.sig_detection_result.disconnect(self.on_camera_detection)
                self.camera_worker.sig_camera_error.disconnect(self.on_camera_error)
        except Exception:
            pass

    def reject(self):
        if hasattr(self, 'visual_timer') and self.visual_timer:
            self.visual_timer.stop()
        self._disconnect_camera()
        super().reject()

    def accept(self):
        if hasattr(self, 'visual_timer') and self.visual_timer:
            self.visual_timer.stop()
        self._disconnect_camera()
        super().accept()


class ItemRemovalVerificationOverlay(OverlayDialog):
    """
    Active item-by-item removal verification dialog.
    Triggered when an item is removed from the cart via UI.
    Waits for the user to physically remove the item from the trolley,
    tracks the weight drop, and validates against expected weight.
    """
    def __init__(self, parent, scale_worker, product_name, expected_weight, expected_yolo_class, camera_worker=None, tolerance_pct=20.0, tolerance_g=8.0):
        super().__init__(parent)
        self.scale_worker = scale_worker
        self.product_name = product_name
        self.expected_weight = float(expected_weight)
        self.expected_yolo_class = expected_yolo_class
        self.camera_worker = camera_worker
        self.tolerance_pct = tolerance_pct
        self.tolerance_g = tolerance_g
        self.weight_verified = False

        # Compute acceptable bounds for weight DROP
        tol = max(self.tolerance_g, self.expected_weight * (self.tolerance_pct / 100.0))
        self.min_drop = max(1.0, self.expected_weight - tol)
        self.max_drop = self.expected_weight + tol

        self.initial_weight = self.scale_worker.get_current_weight() if self.scale_worker else 0.0
        self.verified = False
        self.content_container.setFixedWidth(540)

        # Title
        title_label = QLabel("📤 Remove Item from Trolley")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 22px; font-weight: 800; color: #1e293b; margin-bottom: 4px;")
        self.content_layout.addWidget(title_label)

        # Product Name Box
        prod_box = QFrame()
        prod_box.setStyleSheet("background-color: #fef2f2; border-radius: 12px; padding: 12px;")
        pb_layout = QVBoxLayout(prod_box)
        pb_layout.setContentsMargins(12, 10, 12, 10)
        
        p_name = QLabel(self.product_name)
        p_name.setAlignment(Qt.AlignCenter)
        p_name.setStyleSheet("font-size: 18px; font-weight: 700; color: #991b1b;")
        p_name.setWordWrap(True)
        pb_layout.addWidget(p_name)

        target_info = QLabel("Please remove the item from the trolley to continue")
        target_info.setAlignment(Qt.AlignCenter)
        target_info.setStyleSheet("font-size: 14px; color: #b91c1c; font-weight: 500; margin-top: 4px;")
        pb_layout.addWidget(target_info)
        self.content_layout.addWidget(prod_box)

        # Live Reading Box
        self.reading_box = QFrame()
        self.reading_box.setStyleSheet("background-color: #eff6ff; border: 2px solid #93c5fd; border-radius: 12px; padding: 12px;")
        rb_layout = QVBoxLayout(self.reading_box)
        
        self.live_diff_label = QLabel("Waiting for removal...")
        self.live_diff_label.setAlignment(Qt.AlignCenter)
        self.live_diff_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #1d4ed8;")
        rb_layout.addWidget(self.live_diff_label)

        self.live_status_label = QLabel("Take the item out of the trolley")
        self.live_status_label.setAlignment(Qt.AlignCenter)
        self.live_status_label.setStyleSheet("font-size: 13px; color: #3b82f6;")
        rb_layout.addWidget(self.live_status_label)
        self.content_layout.addWidget(self.reading_box)

        # Connect live scale signal
        if self.scale_worker:
            self.scale_worker.sig_weight_updated.connect(self.on_weight_update)

    def on_weight_update(self, current_weight, is_stable):
        if self.verified:
            return

        # If user added an item instead of removing, adjust baseline
        if current_weight > (self.initial_weight + 5.0):
            self.initial_weight = current_weight

        diff = self.initial_weight - current_weight

        if diff <= 2.0:
            self.live_diff_label.setText("Waiting for removal...")
            self.live_status_label.setText("Take the item out of the trolley")
            self.reading_box.setStyleSheet("background-color: #eff6ff; border: 2px solid #93c5fd; border-radius: 12px;")
            return

        # An item has been removed
        self.live_diff_label.setText(f"-{diff:.1f} g")

        if self.min_drop <= diff <= self.max_drop:
            if is_stable:
                if not getattr(self, 'weight_verified', False):
                    self.weight_verified = True
                    self.measured_weight = diff
                    self.live_status_label.setText("Weight verified! Verifying visual removal...")
                    self.live_status_label.setStyleSheet("font-size: 13px; color: #16a34a; font-weight: 600;")
                    
                    if self.camera_worker:
                        self.camera_worker.sig_detection_result.connect(self.on_camera_detection)
                        self.camera_worker.request_analysis()
                    else:
                        self.verified = True
                        self.live_diff_label.setText(f"✅ Verified: -{diff:.1f} g")
                        self.live_status_label.setText("Removal verified! Updating cart...")
                        self.reading_box.setStyleSheet("background-color: #f0fdf4; border: 2px solid #4ade80; border-radius: 12px;")
                        self.live_diff_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #15803d;")
                        QTimer.singleShot(800, self.accept)
            else:
                self.live_status_label.setText("Stabilizing reading...")
                self.reading_box.setStyleSheet("background-color: #fefce8; border: 2px solid #fde047; border-radius: 12px;")
                self.live_diff_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #854d0e;")
                self.live_status_label.setStyleSheet("font-size: 13px; color: #ca8a04;")
        else:
            if is_stable:
                self.live_status_label.setText("⚠️ Weight mismatch detected. Please remove the correct item.")
                self.reading_box.setStyleSheet("background-color: #fef2f2; border: 2px solid #f87171; border-radius: 12px;")
                self.live_diff_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #b91c1c;")
                self.live_status_label.setStyleSheet("font-size: 13px; color: #dc2626; font-weight: 600;")

    def on_camera_detection(self, detected_items):
        if self.verified:
            return
            
        try:
            self.camera_worker.sig_detection_result.disconnect(self.on_camera_detection)
        except Exception:
            pass
            
        if self.expected_yolo_class not in detected_items:
            self.verified = True
            self.live_diff_label.setText(f"✅ Verified: -{self.measured_weight:.1f} g")
            self.live_status_label.setText("Visual & Weight matched! Updating cart...")
            self.live_status_label.setStyleSheet("font-size: 13px; color: #16a34a; font-weight: 600;")
            self.reading_box.setStyleSheet("background-color: #f0fdf4; border: 2px solid #4ade80; border-radius: 12px;")
            self.live_diff_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #15803d;")
            QTimer.singleShot(800, self.accept)
        else:
            # Mismatch, item still there
            self.weight_verified = False # Reset so they can try again
            self.live_status_label.setText(f"⚠️ Visual mismatch! {self.expected_yolo_class} is still in the trolley.")
            self.reading_box.setStyleSheet("background-color: #fef2f2; border: 2px solid #f87171; border-radius: 12px;")
            self.live_diff_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #b91c1c;")
            self.live_status_label.setStyleSheet("font-size: 13px; color: #dc2626; font-weight: 600;")



class AutoRemovalVerificationOverlay(OverlayDialog):
    """
    Auto-verifies a removal without user interaction by checking YOLO.
    """
    def __init__(self, parent, lost_weight, cart, yolo_class_map, camera_worker):
        super().__init__(parent)
        self.parent_ui = parent
        self.lost_weight = lost_weight
        self.cart = cart
        self.yolo_class_map = yolo_class_map
        self.camera_worker = camera_worker
        self.removed_item_idx = None
        self.matched_actual_weight = None

        self.content_container.setFixedWidth(500)
        self.msg_label = QLabel("Verifying removal via camera...")
        self.msg_label.setAlignment(Qt.AlignCenter)
        self.msg_label.setStyleSheet("font-size: 18px; font-weight: 700; color: #1e293b;")
        self.content_layout.addWidget(self.msg_label)

        if self.camera_worker:
            self.camera_worker.sig_detection_result.connect(self.on_camera_detection)
            self.camera_worker.request_analysis()
        else:
            # Fallback if no camera
            self.on_camera_detection([])

    def on_camera_detection(self, detected_items):
        try:
            self.camera_worker.sig_detection_result.disconnect(self.on_camera_detection)
        except Exception:
            pass

        from config import SCALE_WEIGHT_TOLERANCE_GRAMS, SCALE_WEIGHT_TOLERANCE_PERCENT
        
        candidates = []
        for idx, item in enumerate(self.cart):
            actual_list = item.get("actual_weights", [])
            candidate_weights = actual_list if actual_list else [item.get("weight_grams", 0.0)]
            for cw in candidate_weights:
                if cw <= 0: continue
                diff = abs(cw - self.lost_weight)
                tol = max(SCALE_WEIGHT_TOLERANCE_GRAMS * 1.5, cw * (SCALE_WEIGHT_TOLERANCE_PERCENT / 100.0))
                if diff <= tol:
                    candidates.append((idx, item, cw))

        if not candidates:
            self.reject()
            return

        # If camera is active, filter candidates to those missing from the YOLO view
        if self.camera_worker:
            missing_candidates = []
            for idx, item, cw in candidates:
                expected_yolo_class = self.yolo_class_map.get(item["name"], item["name"])
                if expected_yolo_class not in detected_items:
                    missing_candidates.append((idx, item, cw))
            
            if len(missing_candidates) == 1:
                self.removed_item_idx, _, self.matched_actual_weight = missing_candidates[0]
                self.accept()
            elif len(missing_candidates) > 1:
                # Ambiguous, just reject
                self.reject()
            else:
                # None are missing? Reject
                self.reject()
        else:
            # No camera, fallback to first match
            self.removed_item_idx, _, self.matched_actual_weight = candidates[0]
            self.accept()


class ItemRemovedOverlay(OverlayDialog):
    """
    Auto-closing alert shown when an item is removed from the trolley.
    Dismisses automatically after 5 seconds or when OK is tapped.
    """
    def __init__(self, parent, product_name, weight_removed, auto_close_secs=5):
        super().__init__(parent)
        self.content_container.setFixedWidth(500)
        self.remaining_secs = auto_close_secs

        # Icon / Header
        icon_label = QLabel("📤")
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet("font-size: 44px; margin-bottom: 5px;")
        self.content_layout.addWidget(icon_label)

        title_label = QLabel("Item Removed from Trolley")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 22px; font-weight: 800; color: #dc2626;")
        self.content_layout.addWidget(title_label)

        # Removed item box
        box = QFrame()
        box.setStyleSheet("background-color: #fef2f2; border: 1px solid #fecaca; border-radius: 12px; padding: 12px;")
        b_layout = QVBoxLayout(box)
        b_layout.setContentsMargins(12, 10, 12, 10)

        name_label = QLabel(product_name)
        name_label.setAlignment(Qt.AlignCenter)
        name_label.setStyleSheet("font-size: 18px; font-weight: 700; color: #991b1b;")
        name_label.setWordWrap(True)
        b_layout.addWidget(name_label)

        weight_label = QLabel(f"Weight removed: -{weight_removed:.1f} g")
        weight_label.setAlignment(Qt.AlignCenter)
        weight_label.setStyleSheet("font-size: 14px; color: #b91c1c; font-weight: 600; margin-top: 4px;")
        b_layout.addWidget(weight_label)
        self.content_layout.addWidget(box)

        sub_label = QLabel("Item has been removed from your cart automatically.")
        sub_label.setAlignment(Qt.AlignCenter)
        sub_label.setWordWrap(True)
        sub_label.setStyleSheet("font-size: 14px; color: #475569; font-weight: 500; margin: 6px 0;")
        self.content_layout.addWidget(sub_label)

        # OK button with auto-close countdown
        self.ok_btn = QPushButton(f"OK ({self.remaining_secs}s)")
        self.ok_btn.setMinimumHeight(48)
        self.ok_btn.setCursor(Qt.PointingHandCursor)
        self.ok_btn.setStyleSheet("""
            QPushButton {
                background-color: #ef4444;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 16px;
                font-weight: 700;
            }
            QPushButton:hover { background-color: #dc2626; }
        """)
        self.ok_btn.clicked.connect(self.accept)
        self.content_layout.addWidget(self.ok_btn)

        # Countdown timer (ticks every 1 second)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_tick)
        self.timer.start(1000)

    def on_tick(self):
        self.remaining_secs -= 1
        if self.remaining_secs <= 0:
            self.timer.stop()
            self.accept()
        else:
            self.ok_btn.setText(f"OK ({self.remaining_secs}s)")


class UnscannedItemOverlay(OverlayDialog):
    """
    Warning popup shown when an unscanned/unknown item is placed into the trolley.
    DOES NOT dismiss automatically. It remains on screen blocking the UI until
    the user physically removes the unscanned item from the trolley.
    """
    def __init__(self, parent, scale_worker, added_weight, baseline_weight=0.0, camera_worker=None):
        super().__init__(parent)
        self.scale_worker = scale_worker
        self.camera_worker = camera_worker
        self.added_weight = added_weight
        self.baseline_weight = max(0.0, baseline_weight)
        self.initial_weight = self.scale_worker.get_current_weight() if self.scale_worker else (self.baseline_weight + added_weight)
        self.item_removed = False

        self.content_container.setFixedWidth(540)

        # Top Warning Icon
        self.icon_label = QLabel("🚨")
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setStyleSheet("font-size: 50px; margin-bottom: 2px;")
        self.content_layout.addWidget(self.icon_label)

        # Title
        self.title_label = QLabel("Unscanned Item Detected")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet("font-size: 23px; font-weight: 800; color: #dc2626;")
        self.content_layout.addWidget(self.title_label)

        # Warning Card Box
        self.warning_box = QFrame()
        self.warning_box.setStyleSheet("""
            QFrame {
                background-color: #fef2f2;
                border: 2px solid #f87171;
                border-radius: 14px;
                padding: 12px;
            }
        """)
        wb_layout = QVBoxLayout(self.warning_box)
        wb_layout.setContentsMargins(16, 12, 16, 12)
        wb_layout.setSpacing(6)

        self.msg_label = QLabel("Analyzing item...")
        self.msg_label.setAlignment(Qt.AlignCenter)
        self.msg_label.setWordWrap(True)
        self.msg_label.setStyleSheet("font-size: 16px; font-weight: 800; color: #991b1b;")
        wb_layout.addWidget(self.msg_label)

        if self.camera_worker:
            self.camera_worker.sig_detection_result.connect(self.on_camera_detection)
            self.camera_worker.request_analysis()
        else:
            self.msg_label.setText("Please first scan the item before putting onto the trolley.")

        self.action_instruction = QLabel("⚠️ Please REMOVE this item from the trolley to continue.")
        self.action_instruction.setAlignment(Qt.AlignCenter)
        self.action_instruction.setWordWrap(True)
        self.action_instruction.setStyleSheet("font-size: 14px; font-weight: 700; color: #b91c1c;")
        wb_layout.addWidget(self.action_instruction)

        self.weight_badge = QLabel(f"Unscanned Weight: +{added_weight:.1f} g")
        self.weight_badge.setAlignment(Qt.AlignCenter)
        self.weight_badge.setStyleSheet("""
            background-color: #fee2e2;
            color: #991b1b;
            font-size: 14px;
            font-weight: 700;
            border-radius: 6px;
            padding: 6px 12px;
            margin-top: 4px;
        """)
        wb_layout.addWidget(self.weight_badge)
        self.content_layout.addWidget(self.warning_box)

        # Live Reading / Status Box
        self.status_box = QFrame()
        self.status_box.setStyleSheet("""
            QFrame {
                background-color: #f8fafc;
                border: 1px solid #cbd5e1;
                border-radius: 12px;
                padding: 10px;
            }
        """)
        sb_layout = QVBoxLayout(self.status_box)
        sb_layout.setContentsMargins(12, 10, 12, 10)
        sb_layout.setSpacing(4)

        self.live_status_label = QLabel("⏳ Waiting for item to be removed...")
        self.live_status_label.setAlignment(Qt.AlignCenter)
        self.live_status_label.setStyleSheet("font-size: 15px; font-weight: 700; color: #475569;")
        sb_layout.addWidget(self.live_status_label)

        self.live_weight_label = QLabel(f"Current Trolley Weight: {max(0.0, self.initial_weight):.1f} g")
        self.live_weight_label.setAlignment(Qt.AlignCenter)
        self.live_weight_label.setStyleSheet("font-size: 13px; font-weight: 600; color: #64748b;")
        sb_layout.addWidget(self.live_weight_label)
        self.content_layout.addWidget(self.status_box)

        # Admin override button removed for security

        # Connect live scale signal
        if self.scale_worker:
            self.scale_worker.sig_weight_updated.connect(self.on_scale_update)

    def on_scale_update(self, current_weight, is_stable):
        if self.item_removed:
            return

        disp_w = max(0.0, current_weight)
        self.live_weight_label.setText(f"Current Trolley Weight: {disp_w:.1f} g")

        # Check removal criteria:
        # 1. Weight has returned close to baseline (before the unscanned item was put in)
        # 2. Or weight has dropped by at least ~70% of the added weight
        weight_dropped = self.initial_weight - current_weight
        min_drop_needed = max(4.0, self.added_weight * 0.70)
        returned_to_baseline = (current_weight <= (self.baseline_weight + 4.0))

        if returned_to_baseline or (weight_dropped >= min_drop_needed):
            self.item_removed = True
            
            # Update UI to success state
            self.icon_label.setText("✅")
            self.title_label.setText("Item Removed")
            self.title_label.setStyleSheet("font-size: 23px; font-weight: 800; color: #16a34a;")
            
            self.warning_box.setStyleSheet("""
                QFrame {
                    background-color: #f0fdf4;
                    border: 2px solid #4ade80;
                    border-radius: 14px;
                    padding: 12px;
                }
            """)
            self.msg_label.setText("Item removed from trolley.")
            self.msg_label.setStyleSheet("font-size: 16px; font-weight: 800; color: #15803d;")
            
            self.action_instruction.setText("Please scan the item barcode using the scanner first.")
            self.action_instruction.setStyleSheet("font-size: 14px; font-weight: 600; color: #16a34a;")
            
            self.status_box.setStyleSheet("""
                QFrame {
                    background-color: #f0fdf4;
                    border: 1px solid #86efac;
                    border-radius: 12px;
                    padding: 10px;
                }
            """)
            self.live_status_label.setText("✅ Resuming... Scan barcode first.")
            self.live_status_label.setStyleSheet("font-size: 15px; font-weight: 700; color: #15803d;")
            
            self._disconnect_scale()
            QTimer.singleShot(900, self.accept)
        else:
            self.live_status_label.setText("⏳ Waiting for item to be removed...")

    def _disconnect_scale(self):
        if not getattr(self, '_signals_connected', True):
            return
        self._signals_connected = False
        if self.scale_worker:
            try:
                self.scale_worker.sig_weight_updated.disconnect(self.on_scale_update)
            except Exception:
                pass
        if getattr(self, 'camera_worker', None):
            try:
                self.camera_worker.sig_detection_result.disconnect(self.on_camera_detection)
            except Exception:
                pass

    def on_camera_detection(self, detected_items):
        if detected_items:
            items_str = ", ".join(detected_items)
            self.msg_label.setText(f"You placed <b>{items_str}</b> without scanning!<br>Please scan its barcode or remove it from the trolley.")
        else:
            self.msg_label.setText("Please first scan the item before putting onto the trolley.")

    def accept(self):
        self._disconnect_scale()
        super().accept()

    def reject(self):
        self._disconnect_scale()
        super().reject()


class PaymentWeightWarningOverlay(OverlayDialog):
    """
    Warning popup shown when weight drops significantly during payment.
    Blocks the UI until the items are placed back into the trolley.
    """
    def __init__(self, parent, scale_worker, expected_total_weight):
        super().__init__(parent)
        self.scale_worker = scale_worker
        self.expected_total_weight = float(expected_total_weight)
        
        self.content_container.setFixedWidth(540)

        # Top Warning Icon
        self.icon_label = QLabel("🚨")
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setStyleSheet("font-size: 50px; margin-bottom: 2px;")
        self.content_layout.addWidget(self.icon_label)

        # Title
        self.title_label = QLabel("Cart Modified During Payment")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet("font-size: 23px; font-weight: 800; color: #dc2626;")
        self.content_layout.addWidget(self.title_label)

        # Warning Card Box
        self.warning_box = QFrame()
        self.warning_box.setStyleSheet("""
            QFrame {
                background-color: #fef2f2;
                border: 2px solid #f87171;
                border-radius: 14px;
                padding: 12px;
            }
        """)
        wb_layout = QVBoxLayout(self.warning_box)
        wb_layout.setContentsMargins(16, 12, 16, 12)
        wb_layout.setSpacing(6)

        self.msg_label = QLabel("Weight changed unexpectedly! You cannot add or remove items during checkout.")
        self.msg_label.setAlignment(Qt.AlignCenter)
        self.msg_label.setWordWrap(True)
        self.msg_label.setStyleSheet("font-size: 16px; font-weight: 800; color: #991b1b;")
        wb_layout.addWidget(self.msg_label)

        self.action_instruction = QLabel("⚠️ Please restore the trolley to its exact original state to continue payment.")
        self.action_instruction.setAlignment(Qt.AlignCenter)
        self.action_instruction.setWordWrap(True)
        self.action_instruction.setStyleSheet("font-size: 14px; font-weight: 700; color: #b91c1c;")
        wb_layout.addWidget(self.action_instruction)
        
        self.content_layout.addWidget(self.warning_box)

        # Live Reading / Status Box
        self.status_box = QFrame()
        self.status_box.setStyleSheet("""
            QFrame {
                background-color: #f8fafc;
                border: 1px solid #cbd5e1;
                border-radius: 12px;
                padding: 10px;
            }
        """)
        sb_layout = QVBoxLayout(self.status_box)
        sb_layout.setContentsMargins(12, 10, 12, 10)
        
        self.live_reading_label = QLabel("Current Weight: -- g")
        self.live_reading_label.setAlignment(Qt.AlignCenter)
        self.live_reading_label.setStyleSheet("font-size: 18px; font-weight: 800; color: #0f172a;")
        sb_layout.addWidget(self.live_reading_label)

        self.stability_label = QLabel("Status: Waiting for items...")
        self.stability_label.setAlignment(Qt.AlignCenter)
        self.stability_label.setStyleSheet("font-size: 14px; color: #64748b; font-weight: 600; margin-top: 4px;")
        sb_layout.addWidget(self.stability_label)
        
        self.content_layout.addWidget(self.status_box)

        if self.scale_worker:
            self.scale_worker.sig_weight_updated.connect(self.on_weight_update)

    def on_weight_update(self, current_weight, is_stable):
        diff = self.expected_total_weight - current_weight
        self.live_reading_label.setText(f"Current Weight: {current_weight:.1f} g")

        # If weight is back to expected (within 10g or 2% tolerance)
        tolerance = max(10.0, self.expected_total_weight * 0.02)
        
        if abs(diff) <= tolerance:
            if is_stable:
                self.stability_label.setText("Status: 🟢 Verified. Resuming payment...")
                self.status_box.setStyleSheet("background-color: #f0fdf4; border: 1px solid #4ade80;")
                self.live_reading_label.setStyleSheet("font-size: 18px; font-weight: 800; color: #16a34a;")
                QTimer.singleShot(1000, self.accept)
            else:
                self.stability_label.setText("Status: 🟡 Stabilizing...")
        else:
            if diff > 0:
                self.stability_label.setText(f"Missing roughly {diff:.1f} g")
            else:
                self.stability_label.setText(f"Extra roughly {abs(diff):.1f} g")
            self.status_box.setStyleSheet("background-color: #f8fafc; border: 1px solid #cbd5e1;")
            self.live_reading_label.setStyleSheet("font-size: 18px; font-weight: 800; color: #0f172a;")


class ClearTrolleyVerificationOverlay(OverlayDialog):
    """
    Overlay shown after checkout requiring the user to physically clear the trolley.
    Automatically closes when the weight hits near 0 (<= 3g).
    """
    def __init__(self, parent, scale_worker):
        super().__init__(parent)
        self.scale_worker = scale_worker
        
        self.content_container.setFixedWidth(540)

        # Icon
        self.icon_label = QLabel("🛒")
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setStyleSheet("font-size: 50px; margin-bottom: 2px;")
        self.content_layout.addWidget(self.icon_label)

        # Title
        self.title_label = QLabel("Please Clear the Trolley")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet("font-size: 24px; font-weight: 800; color: #2563eb;")
        self.content_layout.addWidget(self.title_label)

        self.instruction_label = QLabel("Remove all items from the trolley to complete your session.")
        self.instruction_label.setAlignment(Qt.AlignCenter)
        self.instruction_label.setWordWrap(True)
        self.instruction_label.setStyleSheet("font-size: 16px; color: #475569; margin: 10px 0;")
        self.content_layout.addWidget(self.instruction_label)

        # Live Reading / Status Box
        self.status_box = QFrame()
        self.status_box.setStyleSheet("""
            QFrame {
                background-color: #f8fafc;
                border: 2px solid #cbd5e1;
                border-radius: 12px;
                padding: 14px;
            }
        """)
        sb_layout = QVBoxLayout(self.status_box)
        sb_layout.setContentsMargins(12, 10, 12, 10)
        
        self.live_reading_label = QLabel("Current Weight: -- g")
        self.live_reading_label.setAlignment(Qt.AlignCenter)
        self.live_reading_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #0f172a;")
        sb_layout.addWidget(self.live_reading_label)

        self.stability_label = QLabel("Waiting for trolley to be emptied...")
        self.stability_label.setAlignment(Qt.AlignCenter)
        self.stability_label.setStyleSheet("font-size: 14px; color: #64748b; font-weight: 600; margin-top: 4px;")
        sb_layout.addWidget(self.stability_label)
        
        self.content_layout.addWidget(self.status_box)

        if self.scale_worker:
            self.scale_worker.sig_weight_updated.connect(self.on_weight_update)
            # Force an immediate check if weight is already 0
            current_w = getattr(self.scale_worker, 'current_weight', 999.0)
            if current_w <= 3.0:
                self.on_weight_update(current_w, True)

    def on_weight_update(self, current_weight, is_stable):
        self.live_reading_label.setText(f"Current Weight: {current_weight:.1f} g")

        # If weight is basically zero (<= 3g)
        if current_weight <= 3.0:
            if is_stable:
                self.stability_label.setText("🟢 Trolley clear! Thank you.")
                self.status_box.setStyleSheet("background-color: #f0fdf4; border: 2px solid #4ade80;")
                self.live_reading_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #16a34a;")
                QTimer.singleShot(1000, self.accept)
            else:
                self.stability_label.setText("🟡 Stabilizing near zero...")
        else:
            self.stability_label.setText("Waiting for trolley to be emptied...")
            self.status_box.setStyleSheet("background-color: #f8fafc; border: 2px solid #cbd5e1;")
            self.live_reading_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #0f172a;")
