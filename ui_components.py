"""
Reusable UI components for Smart Checkout Kiosk
Uses Qt Virtual Keyboard for touch-friendly input
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QLineEdit, QDialog, QSizePolicy, QFrame, QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt, Signal, QEventLoop, QSize, QRect, QPoint
from PySide6.QtGui import QColor, QPalette, QBrush

class OverlayDialog(QWidget):
    """
    Base class for custom overlay dialogs that replace native QDialogs.
    Renders inside the application window to prevent OS window management (minimize/close).
    """
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_widget = parent
        # Cover the entire parent
        self.setGeometry(parent.rect())
        
        # Semi-transparent background
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setBrush(QPalette.Window, QBrush(QColor(0, 0, 0, 180)))
        self.setPalette(palette)
        
        # Main layout for the overlay (centers the content)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setAlignment(Qt.AlignCenter)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        
        # Content container (the actual "dialog" box)
        self.content_container = QFrame()
        self.content_container.setObjectName("overlayContent")
        self.content_container.setStyleSheet("""
            QFrame#overlayContent {
                background-color: white;
                border-radius: 16px;
                border: 1px solid #e0e0e0;
            }
        """)
        
        # Add shadow to content
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(30)
        shadow.setColor(QColor(0, 0, 0, 80))
        shadow.setOffset(0, 10)
        self.content_container.setGraphicsEffect(shadow)
        
        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(24, 24, 24, 24)
        self.content_layout.setSpacing(16)
        
        self.main_layout.addWidget(self.content_container)
        
        # Event loop for blocking behavior
        self._event_loop = None
        self._result = QDialog.Rejected
        
        # Hide by default
        self.setVisible(False)

    def setLayout(self, layout):
        # Redirect layout setting to content container
        # Note: This is a bit hacky, better to add widgets to content_layout directly
        pass

    def add_widget(self, widget):
        self.content_layout.addWidget(widget)

    def add_layout(self, layout):
        self.content_layout.addLayout(layout)
        
    def exec_(self):
        """Block until accepted or rejected, similar to QDialog.exec_()"""
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
        # Keep covering the parent when resized
        if self.parent_widget:
            self.setGeometry(self.parent_widget.rect())
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
