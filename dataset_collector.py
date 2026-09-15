"""
YOLO26 Indian Grocery Product - Automated Image Dataset Collector
Downloads product images using DuckDuckGo + Bing fallback.
Keeps original filenames. Specific front/back product queries.
Usage: python dataset_collector.py [--products parle_g] [--max-images 100] [--output ./dataset/raw]
"""

import os
import sys
import json
import time
import re
import hashlib
import argparse
import logging
from pathlib import Path
from io import BytesIO
from urllib.parse import urlparse, unquote

import httpx
from PIL import Image
import imagehash
from tqdm import tqdm

# ─── Logging ───
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("collector")

# ─── Load Product Config ───
CONFIG_PATH = Path(__file__).parent / "products_config.json"

def load_products() -> list[dict]:
    """Load product definitions from JSON config."""
    if not CONFIG_PATH.exists():
        log.error(f"Product config not found: {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        return json.load(f)

PRODUCTS = load_products()


# ─── Image Search Engines ───

def search_images_ddg(query: str, max_results: int = 50) -> list[str]:
    """Search DuckDuckGo for image URLs with retry logic."""
    for attempt in range(3):
        try:
            from ddgs import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.images(query, max_results=max_results))
                urls = [r["image"] for r in results if r.get("image")]
                log.info(f"  [DDG] Found {len(urls)} URLs for: {query}")
                return urls
        except Exception as e:
            wait = (attempt + 1) * 5
            log.warning(f"  DDG attempt {attempt+1}/3 failed: {e}")
            if attempt < 2:
                log.info(f"  Retrying in {wait}s...")
                time.sleep(wait)
    return search_images_bing_scrape(query, max_results)


def search_images_bing_scrape(query: str, max_results: int = 50) -> list[str]:
    """Fallback: scrape Bing Image Search (no API key needed)."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        url = f"https://www.bing.com/images/search?q={query.replace(' ', '+')}&first=1&count={max_results}"
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
            if resp.status_code != 200:
                return []
            urls = re.findall(r'murl&quot;:&quot;(https?://[^&]+?)&quot;', resp.text)
            urls = list(dict.fromkeys(urls))[:max_results]
            log.info(f"  [Bing fallback] Found {len(urls)} URLs for: {query}")
            return urls
    except Exception as e:
        log.warning(f"  Bing scrape failed: {e}")
        return []


# ─── Image Download & Validation ───

def get_original_filename(url: str) -> str:
    """Extract original filename from URL, clean it up."""
    parsed = urlparse(url)
    filename = unquote(Path(parsed.path).name)
    # Remove query params that got into filename
    filename = filename.split("?")[0]
    # If no extension or weird name, generate one
    if not filename or len(filename) < 3:
        filename = hashlib.md5(url.encode()).hexdigest()[:12] + ".jpg"
    # Ensure it has an image extension
    valid_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
    ext = Path(filename).suffix.lower()
    if ext not in valid_exts:
        filename = filename + ".jpg"
    return filename


def download_image(url: str, timeout: float = 15.0) -> bytes | None:
    """Download a single image, return bytes or None."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
            if resp.status_code == 200 and len(resp.content) > 5000:
                return resp.content
    except Exception:
        pass
    return None


def validate_image(data: bytes, min_size: int = 300) -> Image.Image | None:
    """Validate image: check format, minimum 300x300, reasonable aspect ratio."""
    try:
        img = Image.open(BytesIO(data))
        img.verify()
        img = Image.open(BytesIO(data))
        w, h = img.size

        # Minimum 300x300
        if w < min_size or h < min_size:
            return None

        # Aspect ratio filter: reject ultra-wide banners (likely ads)
        ratio = max(w, h) / min(w, h)
        if ratio > 3.0:
            return None

        # Convert to RGB
        if img.mode == "RGBA":
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        return img
    except Exception:
        return None


# ─── Deduplication ───

class ImageDeduplicator:
    """Track seen images via perceptual hash + MD5."""

    def __init__(self):
        self.md5_hashes: set[str] = set()
        self.perceptual_hashes: set[str] = set()

    def is_duplicate(self, data: bytes, img: Image.Image) -> bool:
        md5 = hashlib.md5(data).hexdigest()
        if md5 in self.md5_hashes:
            return True
        try:
            phash = str(imagehash.phash(img, hash_size=10))
            if phash in self.perceptual_hashes:
                return True
            self.perceptual_hashes.add(phash)
        except Exception:
            pass
        self.md5_hashes.add(md5)
        return False

    def load_existing(self, folder: Path):
        if not folder.exists():
            return
        for img_path in folder.iterdir():
            if img_path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                try:
                    data = img_path.read_bytes()
                    self.md5_hashes.add(hashlib.md5(data).hexdigest())
                    img = Image.open(img_path)
                    self.perceptual_hashes.add(str(imagehash.phash(img, hash_size=10)))
                except Exception:
                    continue


# ─── Main Collection Logic ───

def make_unique_path(folder: Path, filename: str) -> Path:
    """If filename exists, append _1, _2, etc."""
    path = folder / filename
    if not path.exists():
        return path
    stem = path.stem
    ext = path.suffix
    counter = 1
    while True:
        new_path = folder / f"{stem}_{counter}{ext}"
        if not new_path.exists():
            return new_path
        counter += 1


def count_images(folder: Path) -> int:
    if not folder.exists():
        return 0
    return sum(1 for f in folder.iterdir()
               if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})


def collect_for_product(product: dict, output_dir: Path, max_images: int = 100,
                        delay: float = 2.0) -> int:
    """Collect images for one product. Returns count of new images saved."""
    product_id = product["id"]
    product_dir = output_dir / product_id
    product_dir.mkdir(parents=True, exist_ok=True)

    existing = count_images(product_dir)
    if existing >= max_images:
        log.info(f"✓ {product['name']}: Already have {existing} images, skipping.")
        return 0

    log.info(f"━━━ Collecting: {product['name']} ({product_id}) ━━━")
    log.info(f"  Existing: {existing}, Target: {max_images}")

    dedup = ImageDeduplicator()
    dedup.load_existing(product_dir)

    # Collect URLs from all queries
    all_urls = []
    per_query = max(30, (max_images - existing) // len(product["queries"]) + 15)
    for query in product["queries"]:
        urls = search_images_ddg(query, max_results=per_query)
        all_urls.extend(urls)
        time.sleep(delay)

    all_urls = list(dict.fromkeys(all_urls))
    log.info(f"  Total unique URLs to try: {len(all_urls)}")

    saved = 0
    current_count = existing
    for url in tqdm(all_urls, desc=f"  {product_id}", leave=False):
        if current_count >= max_images:
            break

        data = download_image(url)
        if data is None:
            continue

        img = validate_image(data)
        if img is None:
            continue

        if dedup.is_duplicate(data, img):
            continue

        # Save with ORIGINAL filename
        orig_name = get_original_filename(url)
        save_path = make_unique_path(product_dir, orig_name)
        img.save(str(save_path), "JPEG", quality=92)
        saved += 1
        current_count += 1
        time.sleep(0.1)

    log.info(f"  ✓ Saved {saved} new images → total: {current_count}")
    return saved


def generate_summary(output_dir: Path):
    """Generate dataset summary."""
    summary = {"products": [], "total_images": 0}
    for product in PRODUCTS:
        cnt = count_images(output_dir / product["id"])
        summary["products"].append({
            "id": product["id"], "name": product["name"],
            "category": product["category"], "image_count": cnt
        })
        summary["total_images"] += cnt

    with open(output_dir / "dataset_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n{'─'*60}")
    print(f"{'Product':<35} {'Count':>6} {'Status':>10}")
    print(f"{'─'*60}")
    for p in summary["products"]:
        status = "✓ OK" if p["image_count"] >= 50 else "⚠ Low" if p["image_count"] > 0 else "✗ Empty"
        print(f"{p['name']:<35} {p['image_count']:>6} {status:>10}")
    print(f"{'─'*60}")
    print(f"{'TOTAL':<35} {summary['total_images']:>6}")


# ─── CLI ───

def main():
    parser = argparse.ArgumentParser(
        description="YOLO26 Indian Grocery Product Image Collector",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python dataset_collector.py                              # Collect all 50 products
  python dataset_collector.py --products parle_g           # Single product
  python dataset_collector.py --category snacks            # One category
  python dataset_collector.py --max-images 80              # 80 images per product
  python dataset_collector.py --list                       # List all product IDs
  python dataset_collector.py --summary                    # Show dataset summary
        """
    )
    parser.add_argument("--products", nargs="*", default=None,
                        help="Product IDs to collect (default: all)")
    parser.add_argument("--max-images", type=int, default=100,
                        help="Max images per product (default: 100)")
    parser.add_argument("--output", type=str, default="./dataset/raw",
                        help="Output directory (default: ./dataset/raw)")
    parser.add_argument("--delay", type=float, default=2.0,
                        help="Delay between queries in seconds (default: 2.0)")
    parser.add_argument("--list", action="store_true", help="List product IDs and exit")
    parser.add_argument("--summary", action="store_true", help="Show summary and exit")
    parser.add_argument("--category", type=str, default=None,
                        choices=["snacks","biscuits","beverages","chocolates",
                                 "noodles","personal_care","dairy","staples"],
                        help="Collect only this category")

    args = parser.parse_args()
    output_dir = Path(args.output)

    if args.list:
        print(f"\n{'ID':<30} {'Name':<40} {'Category':<15}")
        print("─" * 85)
        for p in PRODUCTS:
            print(f"{p['id']:<30} {p['name']:<40} {p['category']:<15}")
        print(f"\nTotal: {len(PRODUCTS)} products")
        return

    if args.summary:
        generate_summary(output_dir)
        return

    if args.products is not None:
        targets = [p for p in PRODUCTS if p["id"] in args.products]
        not_found = set(args.products) - {p["id"] for p in targets}
        if not_found:
            log.error(f"Unknown IDs: {not_found}. Use --list to see valid IDs.")
            sys.exit(1)
    elif args.category:
        targets = [p for p in PRODUCTS if p["category"] == args.category]
    else:
        targets = PRODUCTS

    log.info(f"🚀 Collecting images for {len(targets)} products")
    log.info(f"   Output: {output_dir.resolve()}")
    log.info(f"   Max per product: {args.max_images}")
    log.info(f"   Delay: {args.delay}s\n")

    output_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    for i, product in enumerate(targets, 1):
        log.info(f"\n[{i}/{len(targets)}]")
        total += collect_for_product(product, output_dir, args.max_images, args.delay)
        if i < len(targets):
            time.sleep(2.0)

    log.info(f"\n{'═'*50}")
    log.info(f"✅ Done! Total new images: {total}")
    generate_summary(output_dir)


if __name__ == "__main__":
    main()
