"""
Reusable UI components for Smart Checkout Kiosk
Uses Qt Virtual Keyboard for touch-friendly input
"""
import os
import csv
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


# Map YOLO class names to friendly product names, barcodes and weights
YOLO_PRODUCT_MAP = {
    "banana_wafer": {
        "name": "Balaji Banana Wafer Mast Mari",
        "barcode": "8906010500153",
        "weight": 27.0
    },
    "crunchem_simply_salted": {
        "name": "Balaji Crunchem Simply Salted",
        "barcode": "8906010500016",
        "weight": 32.0
    },
    "gippi_tornado": {
        "name": "Balaji Gippi Tornado",
        "barcode": "8906010504625",
        "weight": 20.0
    },
    "wheels": {
        "name": "Wheels Balaji",
        "barcode": "8906010500900",
        "weight": 22.0
    },
    "gopal_vatka": {
        "name": "Gopal Masala Cup",
        "barcode": "8908000861008",
        "weight": 22.0
    }
}


def resolve_product_info(identifier):
    """
    Resolves product name, barcode, weight, and YOLO class from any identifier
    (YOLO class key, full product name, or barcode).
    """
    if not identifier:
        return {"name": "Unknown Item", "barcode": None, "weight": 0.0, "yolo": None}
    
    # 1. Direct YOLO class match
    if str(identifier) in YOLO_PRODUCT_MAP:
        info = YOLO_PRODUCT_MAP[str(identifier)]
        return {
            "name": info["name"],
            "barcode": info["barcode"],
            "weight": info["weight"],
            "yolo": str(identifier)
        }
    
    # 2. Direct product name or barcode match in YOLO_PRODUCT_MAP
    for yolo_k, info in YOLO_PRODUCT_MAP.items():
        if (info["name"].strip().lower() == str(identifier).strip().lower() or 
            info["barcode"] == str(identifier).strip()):
            return {
                "name": info["name"],
                "barcode": info["barcode"],
                "weight": info["weight"],
                "yolo": yolo_k
            }
            
    # 3. Lookup in products.csv
    try:
        csv_path = os.path.join(os.path.dirname(__file__), "products.csv")
        if os.path.exists(csv_path):
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    r_name = row.get('name', '').strip()
                    r_barcode = row.get('barcode', '').strip()
                    if (r_name.lower() == str(identifier).strip().lower() or 
                        r_barcode == str(identifier).strip()):
                        return {
                            "name": r_name,
                            "barcode": r_barcode,
                            "weight": float(row.get('weight_grams') or 0.0),
                            "yolo": None
                        }
    except Exception as e:
        print(f"[ProductMeta] Error reading products.csv: {e}")
        
    return {"name": str(identifier), "barcode": None, "weight": 0.0, "yolo": None}


def load_product_pixmap(barcode, size=(100, 100)):
    """
    Loads product image from images/<barcode>.png (or .jpg), returning scaled QPixmap.
    """
    if barcode:
        base_dir = os.path.dirname(__file__)
        for ext in [".png", ".jpg", ".jpeg"]:
            p = os.path.join(base_dir, "images", f"{barcode}{ext}")
            if os.path.exists(p):
                pix = QPixmap(p)
                if not pix.isNull():
                    return pix.scaled(size[0], size[1], Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return None


class ItemWeightVerificationOverlay(OverlayDialog):
    """
    Active item-by-item verification dialog with dual weight and visual inspection.
    Enforces a strict 1-time 10s visual verification window.
    If a wrong item is placed, presents a side-by-side discrimination card showing
    both the expected product and the wrong detected product images, and permanently
    locks until the wrong item is physically removed from the trolley.
    """
    def __init__(self, parent, scale_worker, product_name, expected_weight, 
                 tolerance_pct=20.0, tolerance_g=8.0, camera_worker=None, 
                 expected_yolo_class=None, expected_barcode=None):
        super().__init__(parent)
        self.scale_worker = scale_worker
        self.camera_worker = camera_worker
        self.expected_yolo_class = expected_yolo_class
        self.expected_barcode = expected_barcode
        self.product_name = product_name
        self.expected_weight = float(expected_weight)
        self.tolerance_pct = tolerance_pct
        self.tolerance_g = tolerance_g
        self.measured_weight = self.expected_weight

        # Auto-resolve product info if barcode or yolo class was not supplied
        prod_info = resolve_product_info(self.product_name)
        if not self.expected_barcode:
            self.expected_barcode = prod_info.get("barcode")
        if not self.expected_yolo_class:
            self.expected_yolo_class = prod_info.get("yolo")

        # Compute acceptable bounds
        tol = max(self.tolerance_g, self.expected_weight * (self.tolerance_pct / 100.0))
        self.min_weight = max(1.0, self.expected_weight - tol)
        self.max_weight = self.expected_weight + tol

        # 1. Determine items already present in the cart & expected cart baseline weight
        self.already_in_cart_yolo = set()
        self.cart_baseline_weight = 0.0
        if self.parent_widget and hasattr(self.parent_widget, 'cart'):
            for it in self.parent_widget.cart:
                w = sum(it.get("actual_weights", [])) if it.get("actual_weights") else (it["qty"] * it.get("weight_grams", 0.0))
                self.cart_baseline_weight += w
                c_info = resolve_product_info(it.get("name"))
                if c_info and c_info.get("yolo"):
                    self.already_in_cart_yolo.add(c_info["yolo"])

        # 2. Determine competing YOLO items of related/similar weight
        # We only consider competing items whose weight is within +/- 5.5g of expected_weight,
        # and exclude items that are already in the cart (since they are already in the trolley!)
        self.competing_same_weight_yolo = set()
        for yolo_cls, p_info in YOLO_PRODUCT_MAP.items():
            if yolo_cls == self.expected_yolo_class:
                continue
            if yolo_cls in self.already_in_cart_yolo:
                continue
            if abs(p_info["weight"] - self.expected_weight) <= 4.0:
                self.competing_same_weight_yolo.add(yolo_cls)

        print(f"[VisualVerify] Scanned: '{self.product_name}' ({self.expected_weight}g, yolo={self.expected_yolo_class})")
        print(f"[VisualVerify] Items already in cart: {self.already_in_cart_yolo} (cart baseline={self.cart_baseline_weight:.1f}g)")
        print(f"[VisualVerify] Competing same-weight items to check: {self.competing_same_weight_yolo}")

        # 3. Protect initial baseline from negative/spurious drift:
        # Must be at least cart_baseline_weight and never negative
        live_scale = self.scale_worker.get_current_weight() if self.scale_worker else 0.0
        if live_scale >= (self.cart_baseline_weight - 5.0) and live_scale < (self.cart_baseline_weight + max(12.0, self.expected_weight * 0.7)):
            self.initial_weight = max(0.0, live_scale)
        else:
            self.initial_weight = max(0.0, self.cart_baseline_weight)

        self.verified = False
        self.weight_verified = False
        self.visual_verifying = False
        self.visual_failed = False
        self.match_count = 0
        self.wrong_item_counts = {}
        self.last_detected_items = []

        self.content_container.setFixedWidth(560)

        # 1. Title
        self.title_label = QLabel("📦 Place Item into Trolley")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet("font-size: 21px; font-weight: 800; color: #1e293b; margin-bottom: 2px;")
        self.content_layout.addWidget(self.title_label)

        # 2. Product Name & Expected Info Box (Normal State)
        self.prod_box = QFrame()
        self.prod_box.setStyleSheet("background-color: #f8fafc; border: 1.5px solid #e2e8f0; border-radius: 12px; padding: 10px;")
        pb_layout = QHBoxLayout(self.prod_box)
        pb_layout.setContentsMargins(12, 8, 12, 8)
        pb_layout.setSpacing(14)
        
        # Expected Thumbnail
        self.prod_thumb_label = QLabel()
        self.prod_thumb_label.setFixedSize(54, 54)
        self.prod_thumb_label.setAlignment(Qt.AlignCenter)
        self.prod_thumb_label.setStyleSheet("background-color: #ffffff; border: 1px solid #cbd5e1; border-radius: 8px;")
        exp_thumb = load_product_pixmap(self.expected_barcode, size=(50, 50))
        if exp_thumb:
            self.prod_thumb_label.setPixmap(exp_thumb)
        else:
            self.prod_thumb_label.setText("📦")
            self.prod_thumb_label.setStyleSheet("font-size: 22px; background-color: #ffffff; border: 1px solid #cbd5e1; border-radius: 8px;")
        pb_layout.addWidget(self.prod_thumb_label)

        prod_text_layout = QVBoxLayout()
        prod_text_layout.setSpacing(2)
        p_name = QLabel(self.product_name)
        p_name.setStyleSheet("font-size: 16px; font-weight: 700; color: #0f172a;")
        p_name.setWordWrap(True)
        prod_text_layout.addWidget(p_name)

        target_info = QLabel(f"Expected weight: ~{self.expected_weight:.0f}g (±{tol:.0f}g)")
        target_info.setStyleSheet("font-size: 13px; color: #64748b; font-weight: 500;")
        prod_text_layout.addWidget(target_info)
        pb_layout.addLayout(prod_text_layout, 1)

        self.content_layout.addWidget(self.prod_box)

        # 3. Live Reading & Status Box
        self.reading_box = QFrame()
        self.reading_box.setStyleSheet("background-color: #eff6ff; border: 2px solid #93c5fd; border-radius: 12px; padding: 10px;")
        rb_layout = QVBoxLayout(self.reading_box)
        rb_layout.setSpacing(6)
        
        self.live_diff_label = QLabel("Waiting for item...")
        self.live_diff_label.setAlignment(Qt.AlignCenter)
        self.live_diff_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #1d4ed8;")
        rb_layout.addWidget(self.live_diff_label)

        self.live_status_label = QLabel(f"Please place '{self.product_name}' into the trolley")
        self.live_status_label.setAlignment(Qt.AlignCenter)
        self.live_status_label.setStyleSheet("font-size: 13px; color: #3b82f6; font-weight: 500;")
        self.live_status_label.setWordWrap(True)
        rb_layout.addWidget(self.live_status_label)

        # Countdown Progress Bar (for visual check)
        self.countdown_bar = QProgressBar()
        self.countdown_bar.setRange(0, 100)
        self.countdown_bar.setValue(100)
        self.countdown_bar.setTextVisible(True)
        self.countdown_bar.setFixedHeight(20)
        self.countdown_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #93c5fd;
                border-radius: 10px;
                text-align: center;
                font-weight: 700;
                font-size: 11px;
                color: #1e3a8a;
                background-color: #dbeafe;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3b82f6, stop:1 #10b981);
                border-radius: 9px;
            }
        """)
        self.countdown_bar.setVisible(False)
        rb_layout.addWidget(self.countdown_bar)
        
        self.content_layout.addWidget(self.reading_box)

        # 4. Side-by-Side Comparison Container (Failure State)
        self.comparison_box = QFrame()
        self.comparison_box.setStyleSheet("background-color: #ffffff; border: 1.5px solid #fca5a5; border-radius: 14px; padding: 6px;")
        comp_layout = QHBoxLayout(self.comparison_box)
        comp_layout.setContentsMargins(10, 8, 10, 8)
        comp_layout.setSpacing(10)

        # --- Left Card: Expected Item ---
        self.expected_card = QFrame()
        self.expected_card.setStyleSheet("background-color: #f0fdf4; border: 2px solid #22c55e; border-radius: 10px; padding: 6px;")
        exp_layout = QVBoxLayout(self.expected_card)
        exp_layout.setContentsMargins(6, 6, 6, 6)
        exp_layout.setSpacing(4)
        exp_layout.setAlignment(Qt.AlignCenter)

        exp_badge = QLabel("🟢 EXPECTED")
        exp_badge.setAlignment(Qt.AlignCenter)
        exp_badge.setStyleSheet("font-size: 11px; font-weight: 800; color: #15803d; background: #dcfce7; border-radius: 5px; padding: 2px 6px;")
        exp_layout.addWidget(exp_badge)

        self.expected_img_label = QLabel()
        self.expected_img_label.setFixedSize(100, 100)
        self.expected_img_label.setAlignment(Qt.AlignCenter)
        self.expected_img_label.setStyleSheet("background: #ffffff; border: 1px solid #86efac; border-radius: 8px;")
        exp_layout.addWidget(self.expected_img_label)

        self.expected_name_label = QLabel(self.product_name)
        self.expected_name_label.setAlignment(Qt.AlignCenter)
        self.expected_name_label.setStyleSheet("font-size: 13px; font-weight: 700; color: #14532d;")
        self.expected_name_label.setWordWrap(True)
        exp_layout.addWidget(self.expected_name_label)

        self.expected_sub_label = QLabel(f"Expected: ~{self.expected_weight:.0f}g")
        self.expected_sub_label.setAlignment(Qt.AlignCenter)
        self.expected_sub_label.setStyleSheet("font-size: 11px; color: #16a34a; font-weight: 600;")
        exp_layout.addWidget(self.expected_sub_label)

        comp_layout.addWidget(self.expected_card, 1)

        # --- Middle Divider: VS / Mismatch Badge ---
        vs_layout = QVBoxLayout()
        vs_layout.setAlignment(Qt.AlignCenter)
        vs_layout.setSpacing(2)

        vs_badge = QLabel("≠")
        vs_badge.setAlignment(Qt.AlignCenter)
        vs_badge.setFixedSize(36, 36)
        vs_badge.setStyleSheet("""
            background-color: #fee2e2;
            color: #dc2626;
            font-size: 18px;
            font-weight: 900;
            border: 2px solid #f87171;
            border-radius: 18px;
        """)
        vs_layout.addWidget(vs_badge)

        vs_text = QLabel("WRONG")
        vs_text.setAlignment(Qt.AlignCenter)
        vs_text.setStyleSheet("font-size: 9px; font-weight: 900; color: #ef4444;")
        vs_layout.addWidget(vs_text)
        comp_layout.addLayout(vs_layout)

        # --- Right Card: Wrong Item Placed ---
        self.wrong_card = QFrame()
        self.wrong_card.setStyleSheet("background-color: #fef2f2; border: 2px solid #ef4444; border-radius: 10px; padding: 6px;")
        wrong_layout = QVBoxLayout(self.wrong_card)
        wrong_layout.setContentsMargins(6, 6, 6, 6)
        wrong_layout.setSpacing(4)
        wrong_layout.setAlignment(Qt.AlignCenter)

        wrong_badge = QLabel("❌ YOU PLACED")
        wrong_badge.setAlignment(Qt.AlignCenter)
        wrong_badge.setStyleSheet("font-size: 11px; font-weight: 800; color: #991b1b; background: #fee2e2; border-radius: 5px; padding: 2px 6px;")
        wrong_layout.addWidget(wrong_badge)

        self.wrong_img_label = QLabel()
        self.wrong_img_label.setFixedSize(100, 100)
        self.wrong_img_label.setAlignment(Qt.AlignCenter)
        self.wrong_img_label.setStyleSheet("background: #ffffff; border: 1px solid #fca5a5; border-radius: 8px;")
        wrong_layout.addWidget(self.wrong_img_label)

        self.wrong_name_label = QLabel("Wrong Item")
        self.wrong_name_label.setAlignment(Qt.AlignCenter)
        self.wrong_name_label.setStyleSheet("font-size: 13px; font-weight: 700; color: #991b1b;")
        self.wrong_name_label.setWordWrap(True)
        wrong_layout.addWidget(self.wrong_name_label)

        self.wrong_sub_label = QLabel("Detected by camera")
        self.wrong_sub_label.setAlignment(Qt.AlignCenter)
        self.wrong_sub_label.setStyleSheet("font-size: 11px; color: #dc2626; font-weight: 600;")
        wrong_layout.addWidget(self.wrong_sub_label)

        comp_layout.addWidget(self.wrong_card, 1)

        self.comparison_box.setVisible(False)
        self.content_layout.addWidget(self.comparison_box)

        # 5. Error Action Instruction Banner
        self.error_action_banner = QFrame()
        self.error_action_banner.setStyleSheet("background-color: #fff1f2; border: 1.5px solid #f43f5e; border-radius: 10px; padding: 8px;")
        eab_layout = QVBoxLayout(self.error_action_banner)
        eab_layout.setContentsMargins(8, 6, 8, 6)
        self.error_action_text = QLabel("👉 Please REMOVE the wrong item from the trolley to try again.")
        self.error_action_text.setAlignment(Qt.AlignCenter)
        self.error_action_text.setWordWrap(True)
        self.error_action_text.setStyleSheet("font-size: 14px; font-weight: 800; color: #be123c;")
        eab_layout.addWidget(self.error_action_text)
        self.error_action_banner.setVisible(False)
        self.content_layout.addWidget(self.error_action_banner)

        # 6. Action Buttons (Cancel)
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setMinimumHeight(44)
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
        if self.verified:
            return

        # If user lifted an item that was already resting on the trolley, adjust baseline
        # but NEVER let baseline drop below cart_baseline_weight or negative!
        if is_stable and current_weight < (self.initial_weight - 5.0):
            self.initial_weight = max(self.cart_baseline_weight, max(0.0, current_weight))

        # Safe baseline prevents negative initial_weight corruption from inflating diff
        safe_base = max(self.cart_baseline_weight, max(0.0, self.initial_weight))
        diff = max(0.0, current_weight - safe_base)

        # 1. Handling locked failed state (wrong item placed)
        if self.visual_failed:
            if diff <= 2.0:
                # User removed the wrong item from the trolley! Reset to clean state
                self.visual_failed = False
                self.weight_verified = False
                self.visual_verifying = False
                self.match_count = 0
                self.wrong_item_counts = {}
                self.last_detected_items = []
                if hasattr(self, 'visual_timer') and self.visual_timer:
                    self.visual_timer.stop()
                self._disconnect_camera()

                # Restore standard UI
                self.title_label.setText("📦 Place Item into Trolley")
                self.title_label.setStyleSheet("font-size: 21px; font-weight: 800; color: #1e293b; margin-bottom: 2px;")
                self.comparison_box.setVisible(False)
                self.error_action_banner.setVisible(False)
                self.prod_box.setVisible(True)
                self.countdown_bar.setVisible(False)
                self.reading_box.setStyleSheet("background-color: #eff6ff; border: 2px solid #93c5fd; border-radius: 12px; padding: 10px;")
                self.live_diff_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #1d4ed8;")
                self.live_diff_label.setText("Waiting for item...")
                self.live_status_label.setStyleSheet("font-size: 13px; color: #3b82f6; font-weight: 500;")
                self.live_status_label.setText(f"Please place '{self.product_name}' into the trolley")
            else:
                self.live_diff_label.setText(f"❌ Scale: +{diff:.1f} g (Remove item)")
            return

        # 2. Handling active visual verification countdown
        if self.visual_verifying:
            if diff <= 2.0:
                # User took the item back off during the 10s check
                self.visual_verifying = False
                self.weight_verified = False
                if hasattr(self, 'visual_timer') and self.visual_timer:
                    self.visual_timer.stop()
                self._disconnect_camera()
                self.countdown_bar.setVisible(False)
                self.live_diff_label.setText("Waiting for item...")
                self.live_status_label.setText(f"Please place '{self.product_name}' into the trolley")
                self.reading_box.setStyleSheet("background-color: #eff6ff; border: 2px solid #93c5fd; border-radius: 12px; padding: 10px;")
            else:
                self.live_diff_label.setText(f"+{diff:.1f} g")
            return

        # 3. Idle / waiting for item
        if diff <= 2.0:
            self.live_diff_label.setText("Waiting for item...")
            self.live_status_label.setText(f"Please place '{self.product_name}' into the trolley")
            self.reading_box.setStyleSheet("background-color: #eff6ff; border: 2px solid #93c5fd; border-radius: 12px; padding: 10px;")
            self.live_diff_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #1d4ed8;")
            self.live_status_label.setStyleSheet("font-size: 13px; color: #3b82f6;")
            return

        # 4. An item has been placed on the scale
        self.live_diff_label.setText(f"+{diff:.1f} g")

        if self.min_weight <= diff <= self.max_weight:
            if is_stable:
                self.measured_weight = round(diff, 1)
                self.weight_verified = True
                
                if self.camera_worker and self.expected_yolo_class:
                    self.start_visual_verification()
                else:
                    self.verified = True
                    self.live_diff_label.setText(f"✅ Verified: +{diff:.1f} g")
                    self.live_status_label.setText(f"Weight matched! Added '{self.product_name}' to cart...")
                    self.reading_box.setStyleSheet("background-color: #f0fdf4; border: 2px solid #4ade80; border-radius: 12px; padding: 10px;")
                    self.live_diff_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #15803d;")
                    self.live_status_label.setStyleSheet("font-size: 13px; color: #16a34a; font-weight: 600;")
                    QTimer.singleShot(700, self.accept)
            else:
                self.live_status_label.setText("Stabilizing reading...")
                self.reading_box.setStyleSheet("background-color: #fefce8; border: 2px solid #fde047; border-radius: 12px; padding: 10px;")
                self.live_diff_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #854d0e;")
                self.live_status_label.setStyleSheet("font-size: 13px; color: #ca8a04;")
        else:
            if is_stable:
                self.live_status_label.setText(f"⚠️ Weight mismatch: Expected ~{self.expected_weight:.0f}g, got {diff:.1f}g.")
                self.reading_box.setStyleSheet("background-color: #fef2f2; border: 2px solid #f87171; border-radius: 12px; padding: 10px;")
                self.live_diff_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #b91c1c;")
                self.live_status_label.setStyleSheet("font-size: 13px; color: #dc2626; font-weight: 600;")

    def start_visual_verification(self):
        """Initiate single 10s visual verification window."""
        self.match_count = 0
        self.wrong_item_counts = {}
        self.last_detected_items = []
        self.required_matches = 3
        self.total_duration_secs = 10.0
        self.start_time = time.time()
        self.visual_verifying = True
        self.visual_failed = False
        
        self.countdown_bar.setValue(100)
        self.countdown_bar.setFormat("Verifying with camera: 10.0s")
        self.countdown_bar.setVisible(True)
        
        self.reading_box.setStyleSheet("background-color: #f0fdf4; border: 2px solid #4ade80; border-radius: 12px; padding: 10px;")
        self.live_diff_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #15803d;")
        self.live_status_label.setStyleSheet("font-size: 13px; color: #15803d; font-weight: 600;")
        self.live_status_label.setText(f"Weight matched! Checking camera for '{self.product_name}'...")

        try:
            self.camera_worker.sig_detection_result.connect(self.on_camera_detection)
            self.camera_worker.sig_camera_error.connect(self.on_camera_error)
        except Exception:
            pass

        self.visual_timer = QTimer(self)
        self.visual_timer.timeout.connect(self._poll_camera)
        self.visual_timer.start(200)
        self._poll_camera()

    def _poll_camera(self):
        if self.verified or not self.visual_verifying or not self.camera_worker:
            if hasattr(self, 'visual_timer') and self.visual_timer:
                self.visual_timer.stop()
            return
            
        elapsed = time.time() - self.start_time
        remaining = max(0.0, self.total_duration_secs - elapsed)
        pct = int((remaining / self.total_duration_secs) * 100)
        self.countdown_bar.setValue(pct)
        self.countdown_bar.setFormat(f"Verifying with camera: {remaining:.1f}s")
        
        if remaining <= 0.0:
            # 10s expired without required 3 matches - Strict rejection, runs ONLY ONCE
            if hasattr(self, 'visual_timer') and self.visual_timer:
                self.visual_timer.stop()
            self._disconnect_camera()
            self.visual_verifying = False
            self.visual_failed = True
            
            wrong_item = None
            if self.wrong_item_counts:
                wrong_item = max(self.wrong_item_counts, key=self.wrong_item_counts.get)
            elif self.last_detected_items:
                for item in self.last_detected_items:
                    if item in self.competing_same_weight_yolo:
                        wrong_item = item
                        break
                        
            self.show_visual_failure(wrong_item_yolo=wrong_item)
            return

        self.camera_worker.request_analysis()

    def on_camera_detection(self, detected_items):
        if self.verified or not self.visual_verifying:
            return
            
        self.last_detected_items = detected_items
        elapsed = time.time() - self.start_time
        remaining = max(0.0, self.total_duration_secs - elapsed)

        print(f"[VisualVerify] Frame: detected={detected_items}, expected={self.expected_yolo_class}, competing={self.competing_same_weight_yolo}, matches={self.match_count}/{self.required_matches}")

        # 1. Check for competing same-weight items accumulating matches
        # Strictly ignores items already in cart or items with unrelated weights!
        for item in detected_items:
            if item in self.competing_same_weight_yolo:
                self.wrong_item_counts[item] = self.wrong_item_counts.get(item, 0) + 1
                if self.wrong_item_counts[item] >= self.required_matches:
                    # Immediate failure! (Confirmed wrong same-weight item placed)
                    if hasattr(self, 'visual_timer') and self.visual_timer:
                        self.visual_timer.stop()
                    self._disconnect_camera()
                    self.visual_verifying = False
                    self.visual_failed = True
                    self.show_visual_failure(wrong_item_yolo=item)
                    return

        # 2. Check for expected class matches
        if self.expected_yolo_class in detected_items:
            self.match_count += 1
            if self.match_count >= self.required_matches:
                # Successfully verified!
                self.verified = True
                self.visual_verifying = False
                if hasattr(self, 'visual_timer') and self.visual_timer:
                    self.visual_timer.stop()
                self._disconnect_camera()
                self.countdown_bar.setVisible(False)
                self.live_diff_label.setText(f"✅ Verified: +{self.measured_weight:.1f} g")
                self.live_status_label.setText(f"Visual & Weight verified! Adding '{self.product_name}' to cart...")
                self.live_status_label.setStyleSheet("font-size: 13px; color: #16a34a; font-weight: 700;")
                self.reading_box.setStyleSheet("background-color: #f0fdf4; border: 2px solid #4ade80; border-radius: 12px; padding: 10px;")
                QTimer.singleShot(700, self.accept)
                return
            else:
                self.live_status_label.setText(f"🔍 Confirmed {self.match_count}/{self.required_matches} visual matches ({remaining:.1f}s left)...")
        else:
            saw = f" (seeing {', '.join(detected_items)})" if detected_items else ""
            self.live_status_label.setText(f"Analyzing camera ({remaining:.1f}s left)... Matched {self.match_count}/{self.required_matches}{saw}")

    def _get_camera_pixmap(self, size=(94, 94)):
        if not hasattr(self, 'camera_worker') or not self.camera_worker or not hasattr(self.camera_worker, 'last_frame'):
            return None
        frame = self.camera_worker.last_frame
        if frame is None:
            return None
        try:
            import cv2
            from PySide6.QtGui import QImage, QPixmap
            from PySide6.QtCore import Qt
            rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_image.shape
            bytes_per_line = ch * w
            q_img = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)
            min_dim = min(w, h)
            start_x = (w - min_dim) // 2
            start_y = (h - min_dim) // 2
            cropped = q_img.copy(start_x, start_y, min_dim, min_dim)
            return QPixmap.fromImage(cropped).scaled(size[0], size[1], Qt.KeepAspectRatio, Qt.SmoothTransformation)
        except Exception as e:
            print(f"[VisualVerify] Error getting camera pixmap: {e}")
            return None

    def show_visual_failure(self, wrong_item_yolo=None):
        """Displays side-by-side discrimination UI and locks until item is removed."""
        self.visual_failed = True
        self.visual_verifying = False
        self.countdown_bar.setVisible(False)
        
        self.title_label.setText("⚠️ Item Verification Failed")
        self.title_label.setStyleSheet("font-size: 21px; font-weight: 800; color: #dc2626; margin-bottom: 2px;")
        
        # 1. Setup Expected Product card
        exp_meta = resolve_product_info(self.product_name)
        exp_name = exp_meta["name"]
        exp_barcode = self.expected_barcode or exp_meta.get("barcode")
        self.expected_name_label.setText(exp_name)
        self.expected_sub_label.setText(f"Expected: ~{self.expected_weight:.0f}g")
        exp_pix = load_product_pixmap(exp_barcode, size=(94, 94))
        if exp_pix:
            self.expected_img_label.setPixmap(exp_pix)
            self.expected_img_label.setText("")
            self.expected_img_label.setStyleSheet("background: #ffffff; border: 1px solid #86efac; border-radius: 8px;")
        else:
            self.expected_img_label.setText("📦")
            self.expected_img_label.setStyleSheet("font-size: 32px; background: #ffffff; border: 1px solid #86efac; border-radius: 8px;")

        # 2. Setup Detected Product card
        if wrong_item_yolo:
            wrong_meta = resolve_product_info(wrong_item_yolo)
            wrong_name = wrong_meta["name"]
            wrong_barcode = wrong_meta.get("barcode")
            self.wrong_name_label.setText(wrong_name)
            self.wrong_sub_label.setText("Detected by camera")
            wrong_pix = load_product_pixmap(wrong_barcode, size=(94, 94))
            
            if not wrong_pix:
                wrong_pix = self._get_camera_pixmap()
                
            if wrong_pix:
                self.wrong_img_label.setPixmap(wrong_pix)
                self.wrong_img_label.setText("")
                self.wrong_img_label.setStyleSheet("background: #ffffff; border: 1px solid #fca5a5; border-radius: 8px;")
            else:
                self.wrong_img_label.setText("📦")
                self.wrong_img_label.setStyleSheet("font-size: 32px; background: #ffffff; border: 1px solid #fca5a5; border-radius: 8px;")
            
            self.live_status_label.setText(f"❌ Wrong item detected: '{wrong_name}'. Please place '{exp_name}'.")
            self.error_action_text.setText(f"👉 Please REMOVE '{wrong_name}' from trolley to continue")
        else:
            self.wrong_name_label.setText("Unidentified Item")
            self.wrong_sub_label.setText("Not recognized by camera")
            
            cam_pix = self._get_camera_pixmap()
            if cam_pix:
                self.wrong_img_label.setPixmap(cam_pix)
                self.wrong_img_label.setText("")
                self.wrong_img_label.setStyleSheet("background: #ffffff; border: 1px solid #fca5a5; border-radius: 8px;")
            else:
                self.wrong_img_label.setText("📷")
                self.wrong_img_label.setStyleSheet("font-size: 32px; background: #ffffff; border: 1px solid #fca5a5; border-radius: 8px;")
                
            self.live_status_label.setText(f"❌ Camera could not verify '{exp_name}'. Please place item facing camera.")
            self.error_action_text.setText(f"👉 Please remove item, face label toward camera, and place again")

        # 3. Swap views
        self.prod_box.setVisible(False)
        self.comparison_box.setVisible(True)
        self.error_action_banner.setVisible(True)

        self.reading_box.setStyleSheet("background-color: #fef2f2; border: 2px solid #ef4444; border-radius: 12px; padding: 10px;")
        self.live_diff_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #b91c1c;")
        self.live_diff_label.setText(f"❌ Scale: +{self.measured_weight:.1f} g")
        self.live_status_label.setStyleSheet("font-size: 13px; color: #b91c1c; font-weight: 700;")

    def on_camera_error(self, err_msg):
        print(f"[VisualVerify] Camera error reported: {err_msg}")
        self._disconnect_camera()
        if hasattr(self, 'visual_timer') and self.visual_timer:
            self.visual_timer.stop()
        self.visual_verifying = False
        self.visual_failed = True
        self.countdown_bar.setVisible(False)
        self.show_visual_failure(wrong_item_yolo=None)
        self.live_status_label.setText(f"❌ Camera error: {err_msg}. Visual check is required.")

    def _disconnect_camera(self):
        try:
            if self.camera_worker:
                self.camera_worker.sig_detection_result.disconnect(self.on_camera_detection)
        except Exception:
            pass
        try:
            if self.camera_worker:
                self.camera_worker.sig_camera_error.disconnect(self.on_camera_error)
        except Exception:
            pass

    def reject(self):
        if hasattr(self, 'visual_timer') and self.visual_timer:
            self.visual_timer.stop()
        self._disconnect_camera()
        if self.scale_worker:
            try:
                self.scale_worker.sig_weight_updated.disconnect(self.on_weight_update)
            except Exception:
                pass
        super().reject()

    def accept(self):
        if hasattr(self, 'visual_timer') and self.visual_timer:
            self.visual_timer.stop()
        self._disconnect_camera()
        if self.scale_worker:
            try:
                self.scale_worker.sig_weight_updated.disconnect(self.on_weight_update)
            except Exception:
                pass
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

        self.countdown_bar = QProgressBar()
        self.countdown_bar.setFixedHeight(18)
        self.countdown_bar.setTextVisible(True)
        self.countdown_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #fca5a5;
                border-radius: 9px;
                background-color: #fee2e2;
                text-align: center;
                font-weight: bold;
                color: #991b1b;
            }
            QProgressBar::chunk {
                background-color: #ef4444;
                border-radius: 8px;
            }
        """)
        wb_layout.addWidget(self.countdown_bar)

        self.images_widget = QWidget()
        self.images_layout = QHBoxLayout(self.images_widget)
        self.images_layout.setAlignment(Qt.AlignCenter)
        wb_layout.addWidget(self.images_widget)

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

        # Determine cart yolo classes
        self.cart_yolo_classes = set()
        if hasattr(parent, 'cart'):
            for item in parent.cart:
                meta = resolve_product_info(item["product_name"])
                if meta.get("yolo"):
                    self.cart_yolo_classes.add(meta["yolo"])

        self.unscanned_items_found = set()
        self.total_duration_secs = 10.0
        self.start_time = time.time()
        self.visual_analyzing = True

        if self.camera_worker:
            self.camera_worker.sig_detection_result.connect(self.on_camera_detection)
            self.visual_timer = QTimer(self)
            self.visual_timer.timeout.connect(self._poll_camera)
            self.visual_timer.start(200)
            self._poll_camera()
        else:
            self.visual_analyzing = False
            self.countdown_bar.setVisible(False)
            self._update_images_ui()

        # Connect live scale signal
        if self.scale_worker:
            self.scale_worker.sig_weight_updated.connect(self.on_scale_update)

    def _get_camera_pixmap(self, size=(94, 94)):
        if not hasattr(self, 'camera_worker') or not self.camera_worker or not hasattr(self.camera_worker, 'last_frame'):
            return None
        frame = self.camera_worker.last_frame
        if frame is None:
            return None
        try:
            import cv2
            from PySide6.QtGui import QImage, QPixmap
            from PySide6.QtCore import Qt
            rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_image.shape
            bytes_per_line = ch * w
            q_img = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)
            min_dim = min(w, h)
            start_x = (w - min_dim) // 2
            start_y = (h - min_dim) // 2
            cropped = q_img.copy(start_x, start_y, min_dim, min_dim)
            return QPixmap.fromImage(cropped).scaled(size[0], size[1], Qt.KeepAspectRatio, Qt.SmoothTransformation)
        except Exception as e:
            print(f"[UnscannedItem] Error getting camera pixmap: {e}")
            return None

    def _poll_camera(self):
        if not self.visual_analyzing or not self.camera_worker:
            if hasattr(self, 'visual_timer') and self.visual_timer:
                self.visual_timer.stop()
            return
            
        elapsed = time.time() - self.start_time
        remaining = max(0.0, self.total_duration_secs - elapsed)
        pct = int((remaining / self.total_duration_secs) * 100)
        self.countdown_bar.setValue(pct)
        self.countdown_bar.setFormat(f"Analyzing trolley: {remaining:.1f}s")
        
        if remaining <= 0.0:
            self.visual_analyzing = False
            self.countdown_bar.setVisible(False)
            if hasattr(self, 'visual_timer') and self.visual_timer:
                self.visual_timer.stop()
            self._update_images_ui()
            return
            
        self.camera_worker.request_analysis()

    def on_camera_detection(self, detected_items):
        if not self.visual_analyzing:
            return
            
        added_new = False
        for item in detected_items:
            if item not in self.cart_yolo_classes:
                if item not in self.unscanned_items_found:
                    self.unscanned_items_found.add(item)
                    added_new = True
                    
        if added_new:
            self._update_images_ui()

    def _update_images_ui(self):
        # Clear existing layout
        while self.images_layout.count():
            item = self.images_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
                
        if not self.unscanned_items_found:
            if self.visual_analyzing:
                self.msg_label.setText("Analyzing item...")
                return
            else:
                self.msg_label.setText("Unidentified item placed without scanning!")
                vbox = QVBoxLayout()
                img_lbl = QLabel()
                cam_pix = self._get_camera_pixmap()
                if cam_pix:
                    img_lbl.setPixmap(cam_pix)
                else:
                    img_lbl.setText("📷")
                img_lbl.setAlignment(Qt.AlignCenter)
                img_lbl.setStyleSheet("background: #ffffff; border: 1px solid #fca5a5; border-radius: 8px; padding: 4px;")
                vbox.addWidget(img_lbl)
                
                name_lbl = QLabel("Unidentified Item")
                name_lbl.setAlignment(Qt.AlignCenter)
                name_lbl.setStyleSheet("font-size: 12px; font-weight: bold;")
                vbox.addWidget(name_lbl)
                
                wrapper = QWidget()
                wrapper.setLayout(vbox)
                self.images_layout.addWidget(wrapper)
        else:
            names = []
            for yolo_cls in self.unscanned_items_found:
                meta = resolve_product_info(yolo_cls)
                names.append(f"<b>{meta['name']}</b>")
                
                vbox = QVBoxLayout()
                img_lbl = QLabel()
                pix = load_product_pixmap(meta.get("barcode"), size=(80, 80))
                if not pix:
                    pix = self._get_camera_pixmap((80, 80))
                    
                if pix:
                    img_lbl.setPixmap(pix)
                else:
                    img_lbl.setText("📦")
                img_lbl.setAlignment(Qt.AlignCenter)
                img_lbl.setStyleSheet("background: #ffffff; border: 1px solid #fca5a5; border-radius: 8px; padding: 4px;")
                vbox.addWidget(img_lbl)
                
                name_lbl = QLabel(meta['name'])
                name_lbl.setAlignment(Qt.AlignCenter)
                name_lbl.setWordWrap(True)
                name_lbl.setStyleSheet("font-size: 11px; font-weight: bold; max-width: 90px;")
                vbox.addWidget(name_lbl)
                
                wrapper = QWidget()
                wrapper.setLayout(vbox)
                self.images_layout.addWidget(wrapper)
                
            self.msg_label.setText(f"You placed {', '.join(names)} without scanning!<br>Please scan or remove from trolley.")

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
            
            self.countdown_bar.setVisible(False)
            self._disconnect_scale()
            if hasattr(self, 'visual_timer') and self.visual_timer:
                self.visual_timer.stop()
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
