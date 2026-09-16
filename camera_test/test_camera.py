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

    # Auto-detect camera source
    print("Scanning for available camera sources (indices 0 to 10)...")
    working_index = None
    available_indices = []
    
    for i in range(11):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            ret, _ = cap.read()
            if ret:
                available_indices.append(i)
            cap.release()
            
    if not available_indices:
        print("Error: Could not detect any working video devices.")
        print("1. If using Raspberry Pi Camera Module, run using 'libcamerify python3 test_camera.py'")
        print("2. Check if the camera ribbon cable is firmly connected.")
        print("3. Ensure 'Legacy Camera' or 'V4L2' driver is enabled in raspi-config.")
        sys.exit(1)
        
    print(f"Detected working camera indices: {available_indices}")
    working_index = available_indices[0]
    print(f"Connecting to Camera Index: {working_index}")
    
    cap = cv2.VideoCapture(working_index)
    
    if not cap.isOpened():
        print("Error: Could not open the selected video device.")
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
