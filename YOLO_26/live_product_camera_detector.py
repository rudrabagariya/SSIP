import cv2
import time
import os
import sys
from collections import deque, Counter

def main():
    weights_path = "best.pt"
    
    if not os.path.exists(weights_path):
        print(f"❌ '{weights_path}' not found in current directory.")
        sys.exit(1)

    try:
        from ultralytics import YOLO
    except ImportError:
        print("❌ Ultralytics is not installed.")
        sys.exit(1)

    print(f"Loading custom YOLO weights: {weights_path}...")
    model = YOLO(weights_path)
    print("Model loaded successfully!")

    # Video source
    video_source = 0
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        video_source = int(arg) if arg.isdigit() else arg

    if isinstance(video_source, str):
        print(f"\n📱 Connecting to Mobile Phone Camera at: {video_source} ...")
    else:
        print(f"\n💻 Connecting to Camera device index: {video_source} ...")

    cap = cv2.VideoCapture(video_source)
    if isinstance(video_source, int):
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    if not cap.isOpened():
        print(f"❌ Error: Could not open camera source: {video_source}")
        sys.exit(1)

    print("\n✅ Smart Live Stream Active (With Floor/Body False Alarm Filter)!")
    print("-------------------------------------------------------------")
    print("🎯 Filters out giant false boxes (floors/legs) & verifies real packets")
    print("⌨️  Controls:")
    print("   'r'       : Toggle Resolution (640 <-> 800)")
    print("   '+' / '-' : Adjust Confidence Threshold")
    print("   'q'       : Quit")
    print("-------------------------------------------------------------\n")

    prev_time = time.time()
    conf_threshold = 0.60
    img_sizes = [640, 800]
    img_size_idx = 0  # 640 is fast and stable

    # Rolling window for temporal verification
    history_len = 7
    history_buffer = deque(maxlen=history_len)

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Frame drop. Reconnecting...")
            time.sleep(0.1)
            continue

        h, w, _ = frame.shape

        # Calculate FPS
        curr_time = time.time()
        fps = 1.0 / (curr_time - prev_time) if (curr_time - prev_time) > 0 else 0
        prev_time = curr_time

        # Run YOLO detection
        current_imgsz = img_sizes[img_size_idx]
        results = model.predict(source=frame, conf=conf_threshold, imgsz=current_imgsz, verbose=False)

        detected_list = []
        annotated_frame = frame.copy()

        # Parse detected boxes with Sanity Filtering
        for box in results[0].boxes:
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            name = model.names[cls_id]

            coords = box.xyxy[0].cpu().numpy()
            bx1, by1, bx2, by2 = int(coords[0]), int(coords[1]), int(coords[2]), int(coords[3])

            box_w = (bx2 - bx1) / float(w)
            box_h = (by2 - by1) / float(h)
            box_area = box_w * box_h

            # SANITY FILTER: A snack packet at 30-40cm is NEVER as big as 30% of the entire screen!
            # Giant boxes covering half the screen (like floors, walls, legs) are discarded!
            if box_area > 0.30:
                continue

            detected_list.append((name, conf))

            # Draw clean bounding box
            cv2.rectangle(annotated_frame, (bx1, by1), (bx2, by2), (0, 255, 255), 3)
            label = f"{name} {conf*100:.0f}%"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)
            cv2.rectangle(annotated_frame, (bx1, by1 - th - 10), (bx1 + tw + 10, by1), (0, 200, 200), -1)
            cv2.putText(annotated_frame, label, (bx1 + 5, by1 - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 2)

        # Multi-object temporal verification (counts duplicates properly)
        current_frame_dets = Counter()
        for name, conf in detected_list:
            current_frame_dets[name] += 1

        history_buffer.append(current_frame_dets)

        # Average counts over the rolling window
        all_detected_names = set()
        for frame_dict in history_buffer:
            all_detected_names.update(frame_dict.keys())

        verified_products = {}
        for name in all_detected_names:
            counts = [frame_dict.get(name, 0) for frame_dict in history_buffer]
            # Must appear in at least 4 of the last 7 frames
            active_counts = [c for c in counts if c > 0]
            if len(active_counts) >= 4:
                avg_count = round(sum(active_counts) / len(active_counts))
                verified_products[name] = max(1, avg_count)

        # --- Top Status Banner ---
        h_ann, w_ann, _ = annotated_frame.shape
        cv2.rectangle(annotated_frame, (0, 0), (w_ann, 55), (20, 20, 20), -1)

        source_label = "Mobile Phone" if isinstance(video_source, str) else "Webcam"
        info_str = f"FPS: {fps:.1f} | Conf: {conf_threshold:.2f} | Res: {current_imgsz}px | Source: {source_label}"
        cv2.putText(annotated_frame, info_str, (15, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)

        if len(verified_products) > 0:
            total_items = sum(verified_products.values())
            summary_items = [f"{count}x {name}" if count > 1 else name for name, count in verified_products.items()]
            status_text = f"VERIFIED ({total_items}): " + ", ".join(summary_items)
            cv2.putText(annotated_frame, status_text[:95], (15, 46),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)
            cv2.circle(annotated_frame, (w_ann - 25, 28), 10, (0, 255, 0), -1)
        else:
            status_text = "STATUS: WAITING FOR PRODUCT..."
            cv2.putText(annotated_frame, status_text, (15, 46),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (140, 140, 255), 2)
            cv2.circle(annotated_frame, (w_ann - 25, 28), 10, (0, 0, 255), -1)

        cv2.imshow("Continuous Live Product Checker", annotated_frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('r'):
            img_size_idx = (img_size_idx + 1) % len(img_sizes)
            print(f"Inference resolution: {img_sizes[img_size_idx]}px")
        elif key == ord('+') or key == ord('='):
            conf_threshold = min(0.95, round(conf_threshold + 0.05, 2))
            print(f"Confidence threshold: {conf_threshold}")
        elif key == ord('-') or key == ord('_'):
            conf_threshold = max(0.15, round(conf_threshold - 0.05, 2))
            print(f"Confidence threshold: {conf_threshold}")

    cap.release()
    cv2.destroyAllWindows()
    print("Camera feed stopped.")

if __name__ == "__main__":
    main()
