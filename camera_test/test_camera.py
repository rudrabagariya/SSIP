import cv2
import time
import os
import sys

# Try to import YOLO, exit gracefully if not installed
try:
    from ultralytics import YOLO
except ImportError:
    print("Error: ultralytics is not installed in the current environment.")
    print("Please activate your YOLO environment (e.g., dataset_venv) and run:")
    print("pip install ultralytics opencv-python")
    sys.exit(1)

def main():
    model_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "YOLO_26", "best.pt"))
    
    if not os.path.exists(model_path):
        print(f"Error: Model not found at {model_path}")
        print("Please ensure the YOLO_26 folder and best.pt exist.")
        sys.exit(1)
        
    print(f"Loading YOLO Model from {model_path}...")
    model = YOLO(model_path)
    print("Model loaded successfully!")

    # Auto-detect camera source with advanced Raspberry Pi fallbacks
    print("Scanning for available camera sources (including libcamera and V4L2)...")
    
    # 1. Try modern libcamera GStreamer pipeline
    gstreamer_pipeline = "libcamerasrc ! video/x-raw, width=640, height=480, framerate=30 ! videoconvert ! appsink"
    cap = cv2.VideoCapture(gstreamer_pipeline, cv2.CAP_GSTREAMER)
    if cap.isOpened():
        ret, _ = cap.read()
        if ret:
            print("Connected using native libcamera GStreamer pipeline!")
        else:
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
                    print(f"Connected using standard VideoCapture index {i}!")
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
                    print(f"Connected using V4L2 backend on index {i}!")
                    break
                cap.release()
            cap = None
            
    if cap is None or not cap.isOpened():
        print("Error: Could not detect any working video devices.")
        print("1. Did you run the script with: libcamerify python3 test_camera.py ?")
        print("2. Try running: sudo modprobe bcm2835-v4l2")
        print("3. Ensure camera permissions exist: sudo usermod -a -G video $USER")
        sys.exit(1)

    print("Camera initialized! Press 'q' to quit.")
    
    fps_time = time.time()
    frames = 0
    fps_display = 0.0

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to grab frame. Retrying...")
            time.sleep(0.5)
            continue

        # Run YOLO inference
        # imgsz=640 and verbose=False for performance
        results = model.predict(source=frame, conf=0.55, imgsz=640, verbose=False)

        # Plot bounding boxes on the frame
        annotated_frame = results[0].plot()

        # Calculate FPS
        frames += 1
        elapsed = time.time() - fps_time
        if elapsed > 1.0:
            fps_display = frames / elapsed
            frames = 0
            fps_time = time.time()

        # Draw FPS on screen
        cv2.putText(annotated_frame, f"FPS: {fps_display:.1f}", (10, 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        
        cv2.putText(annotated_frame, "Press 'q' to exit", (10, 70), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        # Display the resulting frame
        cv2.imshow('YOLO 26 - Camera Test', annotated_frame)

        # Press 'q' to exit
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # Clean up
    cap.release()
    cv2.destroyAllWindows()
    print("Camera closed.")

if __name__ == "__main__":
    main()
