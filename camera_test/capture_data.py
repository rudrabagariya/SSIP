import cv2
import os
import sys

# The 5 product classes you specified
PRODUCTS = [
    "crunchem_simply_salted",
    "banana_wafer",
    "gopal_vatka",
    "wheels",
    "gippi_tornado"
]

def main():
    print("====================================")
    print("      DATA COLLECTION SCRIPT        ")
    print("====================================")
    print("Select a product to capture images for:")
    for i, prod in enumerate(PRODUCTS):
        print(f"  [{i}] : {prod}")
    
    try:
        choice = int(input("\nEnter product number: "))
        if choice < 0 or choice >= len(PRODUCTS):
            raise ValueError
        current_product = PRODUCTS[choice]
    except ValueError:
        print("Invalid choice. Exiting.")
        sys.exit(1)
        
    # Create the folder for this specific product
    base_dataset_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "dataset_raw"))
    save_dir = os.path.join(base_dataset_dir, current_product)
    os.makedirs(save_dir, exist_ok=True)
    
    # Initialize Camera
    cap_picam = None
    cap_cv2 = None
    try:
        from picamera2 import Picamera2
        print("Initializing Picamera2...")
        cap_picam = Picamera2()
        config = cap_picam.create_video_configuration(main={"format": "XRGB8888", "size": (1440, 1080)})
        cap_picam.configure(config)
        cap_picam.start()
        print("Connected using native Picamera2!")
    except Exception as e:
        print(f"Picamera2 not available, falling back to OpenCV VideoCapture... ({e})")
        cap_cv2 = cv2.VideoCapture(0)
        if not cap_cv2.isOpened():
            print("Error: Could not open any camera.")
            sys.exit(1)
            
    print(f"\nSaving videos to: {save_dir}")
    print("--> You will record two videos: Front View and Back View.")
    print("--> Press SPACE to start/stop recording.")
    print("--> Press 'q' to quit and return to terminal.")
    
    state = "IDLE_FRONT"
    recorder = None
    
    while True:
        # Grab frame
        if cap_picam:
            try:
                frame_bgra = cap_picam.capture_array()
                if frame_bgra is None:
                    continue
                frame = cv2.cvtColor(frame_bgra, cv2.COLOR_BGRA2BGR)
            except Exception:
                continue
        else:
            ret, frame = cap_cv2.read()
            if not ret:
                continue
                
        # Make a copy to draw text on (so we don't save the text into the dataset video)
        display_frame = frame.copy()
        
        # State machine logic
        if state == "IDLE_FRONT":
            cv2.putText(display_frame, f"Product: {current_product}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            cv2.putText(display_frame, "Ready for FRONT view", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
            cv2.putText(display_frame, "Press SPACE to Start Recording", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        elif state == "RECORDING_FRONT":
            if recorder:
                recorder.write(frame)
            cv2.putText(display_frame, "* RECORDING FRONT VIEW *", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            cv2.putText(display_frame, "Rotate product slowly...", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
            cv2.putText(display_frame, "Press SPACE to Stop", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        elif state == "IDLE_BACK":
            cv2.putText(display_frame, f"Product: {current_product}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            cv2.putText(display_frame, "Ready for BACK view", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
            cv2.putText(display_frame, "Press SPACE to Start Recording", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        elif state == "RECORDING_BACK":
            if recorder:
                recorder.write(frame)
            cv2.putText(display_frame, "* RECORDING BACK VIEW *", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            cv2.putText(display_frame, "Rotate product slowly...", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
            cv2.putText(display_frame, "Press SPACE to Stop", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        elif state == "DONE":
            cv2.putText(display_frame, "All done! Check your folders.", (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            cv2.putText(display_frame, "Press Q to quit.", (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            
        cv2.imshow("Video Capture (1440x1080)", display_frame)
        
        key = cv2.waitKey(1)
        if key == ord('q') or key == ord('Q'):
            break
        elif key == ord(' '):
            if state == "IDLE_FRONT":
                filepath = os.path.join(save_dir, "front.avi")
                # Use MJPG codec, 15 FPS
                recorder = cv2.VideoWriter(filepath, cv2.VideoWriter_fourcc(*'MJPG'), 15, (1440, 1080))
                state = "RECORDING_FRONT"
                print("Started recording front view...")
            elif state == "RECORDING_FRONT":
                if recorder:
                    recorder.release()
                    recorder = None
                state = "IDLE_BACK"
                print("Stopped recording front view.")
            elif state == "IDLE_BACK":
                filepath = os.path.join(save_dir, "back.avi")
                recorder = cv2.VideoWriter(filepath, cv2.VideoWriter_fourcc(*'MJPG'), 15, (1440, 1080))
                state = "RECORDING_BACK"
                print("Started recording back view...")
            elif state == "RECORDING_BACK":
                if recorder:
                    recorder.release()
                    recorder = None
                state = "DONE"
                print("Stopped recording back view.")
            
    # Cleanup
    if recorder:
        recorder.release()
    if cap_picam:
        cap_picam.stop()
    if cap_cv2:
        cap_cv2.release()
    cv2.destroyAllWindows()
    print("\nCamera closed.")

if __name__ == "__main__":
    main()
