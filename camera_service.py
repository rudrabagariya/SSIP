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
            # Check if ONNX or NCNN formats exist first (for speed), otherwise fallback to PyTorch
            model_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "YOLO_26"))
            ncnn_path = os.path.join(model_dir, "best_ncnn_model")
            onnx_path = os.path.join(model_dir, "best.onnx")
            pt_path = os.path.join(model_dir, "best.pt")
            
            if os.path.exists(ncnn_path):
                model_path = ncnn_path
                print(f"Loading optimized NCNN Model from {model_path}...")
            elif os.path.exists(onnx_path):
                model_path = onnx_path
                print(f"Loading optimized ONNX Model from {model_path}...")
            elif os.path.exists(pt_path):
                model_path = pt_path
                print(f"Loading standard PyTorch Model from {model_path}...")
            else:
                self.sig_camera_error.emit(f"Model not found in {model_dir}")
                return

            self.model = YOLO(model_path, task='detect')
        except Exception as e:
            self.sig_camera_error.emit(f"Failed to load YOLO model: {e}")
            return

        # Auto-detect camera source: Try Picamera2 first (Native libcamera on Bookworm)
        self.cap_picam = None
        self.cap_cv2 = None
        
        try:
            from picamera2 import Picamera2
            self.cap_picam = Picamera2()
            config = self.cap_picam.create_video_configuration(main={"format": "XRGB8888", "size": (640, 480)})
            self.cap_picam.configure(config)
            self.cap_picam.start()
        except Exception:
            self.cap_picam = None

        if self.cap_picam is None:
            self.cap_cv2 = cv2.VideoCapture(0)
            if not self.cap_cv2.isOpened():
                self.sig_camera_error.emit("Cannot open any camera device. Check libcamera or V4L2 drivers.")
                return

        history_len = 5
        history_buffer = deque(maxlen=history_len)

        while self._is_running and not self.isInterruptionRequested():
            if self.cap_picam:
                try:
                    frame_bgra = self.cap_picam.capture_array()
                    if frame_bgra is None:
                        continue
                    frame = cv2.cvtColor(frame_bgra, cv2.COLOR_BGRA2BGR)
                    ret = True
                except Exception:
                    time.sleep(0.1)
                    continue
            else:
                ret, frame = self.cap_cv2.read()
                if not ret:
                    time.sleep(0.1)
                    continue

            if self._analyze_requested:
                self._analyze_requested = False
                h, w, _ = frame.shape
                
                try:
                    # imgsz=640 for accuracy, conf=0.7 for reducing false positives
                    results = self.model.predict(source=frame, conf=0.70, imgsz=640, verbose=False)
                    
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

        if self.cap_picam:
            self.cap_picam.stop()
        if self.cap_cv2:
            self.cap_cv2.release()
