import time
from collections import deque
import cv2
from PySide6.QtCore import QThread, Signal

class CameraWorker(QThread):
    """
    Background worker for YOLO 26 camera detection.
    It runs continuously to maintain camera feed but only runs YOLO inference
    when explicitly requested to save CPU resources.
    """
    sig_detection_result = Signal(str, float)  # Emits (class_name, confidence)
    sig_camera_error = Signal(str)

    def __init__(self, model_path="YOLO_26/best.pt", camera_index=0, conf_threshold=0.60):
        super().__init__()
        self.model_path = model_path
        self.camera_index = camera_index
        self.conf_threshold = conf_threshold
        
        self._analyze_requested = False
        self._is_running = True

    def request_analysis(self):
        """Set flag to analyze the next available frame."""
        self._analyze_requested = True

    def stop(self):
        self._is_running = False
        self.wait()

    def run(self):
        try:
            from ultralytics import YOLO
            model = YOLO(self.model_path)
        except Exception as e:
            self.sig_camera_error.emit(f"Failed to load YOLO model: {e}")
            return

        # Auto-detect camera source with advanced Raspberry Pi fallbacks
        cap = None
        
        # 1. Try modern libcamera GStreamer pipeline
        gstreamer_pipeline = "libcamerasrc ! video/x-raw, width=640, height=480, framerate=30 ! videoconvert ! appsink"
        cap = cv2.VideoCapture(gstreamer_pipeline, cv2.CAP_GSTREAMER)
        if cap.isOpened():
            ret, _ = cap.read()
            if not ret:
                cap.release()
                cap = None
        else:
            cap = None

        # 2. Try standard indices
        if cap is None or not cap.isOpened():
            for i in range(11):
                cap = cv2.VideoCapture(i)
                if cap.isOpened():
                    ret, _ = cap.read()
                    if ret:
                        break
                    cap.release()
                cap = None

        # 3. Try V4L2 specific backend
        if cap is None or not cap.isOpened():
            for i in range(11):
                cap = cv2.VideoCapture(i, cv2.CAP_V4L2)
                if cap.isOpened():
                    ret, _ = cap.read()
                    if ret:
                        break
                    cap.release()
                cap = None
                        
        if cap is None or not cap.isOpened():
            self.sig_camera_error.emit("Cannot open any camera device. Check libcamera or V4L2 drivers.")
            return

        history_len = 5
        history_buffer = deque(maxlen=history_len)

        while self._is_running and not self.isInterruptionRequested():
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.1)
                continue

            if self._analyze_requested:
                self._analyze_requested = False
                h, w, _ = frame.shape
                
                try:
                    # Run YOLO detection
                    results = model.predict(source=frame, conf=self.conf_threshold, imgsz=640, verbose=False)
                    
                    best_conf = 0.0
                    best_name = ""
                    
                    for box in results[0].boxes:
                        cls_id = int(box.cls[0])
                        conf = float(box.conf[0])
                        name = model.names[cls_id]

                        coords = box.xyxy[0].cpu().numpy()
                        bx1, by1, bx2, by2 = int(coords[0]), int(coords[1]), int(coords[2]), int(coords[3])

                        box_w = (bx2 - bx1) / float(w)
                        box_h = (by2 - by1) / float(h)
                        box_area = box_w * box_h

                        # Sanity filter: Ignore giant boxes (false positives on background)
                        if box_area > 0.30:
                            continue

                        if conf > best_conf:
                            best_conf = conf
                            best_name = name

                    if best_name:
                        self.sig_detection_result.emit(best_name, best_conf)
                    else:
                        self.sig_detection_result.emit("Unknown", 0.0)
                        
                except Exception as e:
                    self.sig_camera_error.emit(f"Inference error: {e}")

            # Sleep slightly to prevent maxing out a CPU core when idling
            time.sleep(0.03)

        cap.release()
