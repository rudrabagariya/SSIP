"""
YOLO26 Training Helper for Indian Grocery Product Detection
Usage: python train_yolo.py --data dataset/annotated/data.yaml --model yolo26n.pt --epochs 100
"""

import argparse
import yaml
from pathlib import Path

# The 50 class names matching dataset_collector.py product IDs
CLASS_NAMES = [
    "balaji_classic_salted", "balaji_masala_masti", "lays_classic", "lays_magic_masala",
    "kurkure_masala_munch", "uncle_chipps", "bingo_mad_angles", "haldirams_bhujia",
    "too_yumm_multigrain", "pringles_original",
    "parle_g", "parle_monaco", "parle_hide_seek", "britannia_good_day",
    "britannia_marie_gold", "britannia_50_50", "oreo_original", "sunfeast_dark_fantasy",
    "coca_cola", "thums_up", "sprite", "pepsi", "frooti_mango", "maaza_mango",
    "real_juice", "paper_boat",
    "dairy_milk", "five_star", "kitkat", "munch", "gems", "mentos_mint",
    "maggi_noodles", "yippee_noodles", "top_ramen",
    "colgate", "dettol_soap", "lux_soap", "lifebuoy_soap", "head_shoulders",
    "vim_bar", "surf_excel",
    "amul_butter", "amul_taaza", "amul_dark_chocolate",
    "tata_salt", "tata_tea_gold", "nescafe_classic", "dabur_honey", "mtr_poha",
]


def generate_data_yaml(dataset_dir: Path):
    """Generate YOLO data.yaml for training."""
    data = {
        "train": str(dataset_dir / "images" / "train"),
        "val": str(dataset_dir / "images" / "val"),
        "nc": len(CLASS_NAMES),
        "names": CLASS_NAMES,
    }
    yaml_path = dataset_dir / "data.yaml"
    with open(yaml_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False)
    print(f"✓ Generated {yaml_path}")
    print(f"  Classes: {len(CLASS_NAMES)}")
    return yaml_path


def train(data_yaml: str, model: str = "yolo26n.pt", epochs: int = 100,
          imgsz: int = 640, batch: int = 16, device: str = "0"):
    """Train YOLO26 model."""
    try:
        from ultralytics import YOLO
    except ImportError:
        print("ERROR: ultralytics not installed. Run: pip install ultralytics")
        return

    print(f"\n🚀 Starting YOLO26 Training")
    print(f"   Model:   {model}")
    print(f"   Data:    {data_yaml}")
    print(f"   Epochs:  {epochs}")
    print(f"   ImgSize: {imgsz}")
    print(f"   Batch:   {batch}")
    print(f"   Device:  {device}\n")

    yolo = YOLO(model)
    results = yolo.train(
        data=data_yaml,
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        device=device,
        patience=20,
        augment=True,
        project="kiosk_detector",
        name="grocery_v1",
        exist_ok=True,
    )
    print(f"\n✅ Training complete! Results saved to kiosk_detector/grocery_v1/")
    return results


def main():
    parser = argparse.ArgumentParser(description="YOLO26 Indian Grocery Detector Training")
    sub = parser.add_subparsers(dest="command")

    # Generate data.yaml
    gen = sub.add_parser("generate-yaml", help="Generate data.yaml for YOLO training")
    gen.add_argument("--dataset", type=str, default="./dataset/annotated",
                     help="Path to annotated dataset directory")

    # Train
    tr = sub.add_parser("train", help="Train YOLO26 model")
    tr.add_argument("--data", type=str, required=True, help="Path to data.yaml")
    tr.add_argument("--model", type=str, default="yolo26n.pt",
                    help="Pretrained model (yolo26n.pt, yolo26s.pt, yolo26m.pt)")
    tr.add_argument("--epochs", type=int, default=100)
    tr.add_argument("--imgsz", type=int, default=640)
    tr.add_argument("--batch", type=int, default=16)
    tr.add_argument("--device", type=str, default="0", help="GPU device or 'cpu'")

    args = parser.parse_args()

    if args.command == "generate-yaml":
        generate_data_yaml(Path(args.dataset))
    elif args.command == "train":
        train(args.data, args.model, args.epochs, args.imgsz, args.batch, args.device)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
