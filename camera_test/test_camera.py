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

    # Auto-detect camera source: Try Picamera2 first (Native libcamera on Bookworm)
    cap_picam = None
    cap_cv2 = None
    
    try:
        from picamera2 import Picamera2
        print("Initializing Picamera2...")
        cap_picam = Picamera2()
        config = cap_picam.create_video_configuration(main={"format": "XRGB8888", "size": (640, 480)})
        cap_picam.configure(config)
        cap_picam.start()
        print("Connected using native Picamera2!")
    except Exception as e:
        print(f"Picamera2 failed or not installed: {e}")
        cap_picam = None

    if cap_picam is None:
        print("Falling back to standard OpenCV VideoCapture(0)...")
        cap_cv2 = cv2.VideoCapture(0)
        if not cap_cv2.isOpened():
            print("Error: Could not detect any working video devices.")
            sys.exit(1)
        print("Connected using standard VideoCapture!")

    print("Camera initialized! Press 'q' to quit.")
    
    fps_time = time.time()
    frames = 0
    fps_display = 0.0

    while True:
        if cap_picam:
            try:
                frame_bgra = cap_picam.capture_array()
                if frame_bgra is None:
                    continue
                frame = cv2.cvtColor(frame_bgra, cv2.COLOR_BGRA2BGR)
                ret = True
            except Exception as e:
                print(f"Failed to grab Picamera2 frame: {e}")
                time.sleep(0.5)
                continue
        else:
            ret, frame = cap_cv2.read()
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
    if cap_picam:
        cap_picam.stop()
    if cap_cv2:
        cap_cv2.release()
    cv2.destroyAllWindows()
    print("Camera closed.")

if __name__ == "__main__":
    main()
