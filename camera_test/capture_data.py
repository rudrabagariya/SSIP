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
        config = cap_picam.create_video_configuration(main={"format": "XRGB8888", "size": (640, 640)})
        cap_picam.configure(config)
        cap_picam.start()
        print("Connected using native Picamera2!")
    except Exception as e:
        print(f"Picamera2 not available, falling back to OpenCV VideoCapture... ({e})")
        cap_cv2 = cv2.VideoCapture(0)
        if not cap_cv2.isOpened():
            print("Error: Could not open any camera.")
            sys.exit(1)
            
    print(f"\nSaving images to: {save_dir}")
    print("--> Press SPACE to take a photo.")
    print("--> Press 'q' to quit and return to terminal.")
    
    # Get starting count based on existing files to prevent overwriting
    existing_files = os.listdir(save_dir)
    count = len([f for f in existing_files if f.endswith('.jpg')])
    
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
                
        # Make a copy to draw text on (so we don't save the text into the dataset image)
        display_frame = frame.copy()
        
        # Draw on-screen info
        cv2.putText(display_frame, f"Product: {current_product}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        cv2.putText(display_frame, f"Saved: {count} images", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        cv2.putText(display_frame, "SPACE to Capture | Q to Quit", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        
        cv2.imshow("Data Capture (Target: 640x640)", display_frame)
        
        key = cv2.waitKey(1)
        if key == ord(' '):
            # Save the clean frame (without text)
            filename = os.path.join(save_dir, f"{current_product}_{count}.jpg")
            cv2.imwrite(filename, frame)
            print(f"Saved: {filename}")
            count += 1
        elif key == ord('q') or key == ord('Q'):
            break
            
    # Cleanup
    if cap_picam:
        cap_picam.stop()
    if cap_cv2:
        cap_cv2.release()
    cv2.destroyAllWindows()
    print("\nCamera closed.")

if __name__ == "__main__":
    main()
