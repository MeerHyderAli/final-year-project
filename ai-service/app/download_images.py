"""
Build the labelled image dataset.

    python -m app.download_images --per-class 40 --out data/images

Source: Openverse (https://api.openverse.org) — aggregates CC-licensed images from
Flickr, Wikimedia, museums and stock sites. No API key needed for low-volume use.

Two properties that make this dataset defensible in a viva:

  * Provenance is recorded. `data/images/manifest.json` keeps the source URL, licence
    and creator for every file, so the report can state exactly where data came from.
  * De-duplication is built in. Near-identical images inflate accuracy; the
    perceptual hash below drops them, which is the mitigation promised in
    docs/DATASET-AND-MODEL.md.

If the network is unavailable, `--synthetic` generates a small procedural dataset so
the pipeline (train -> evaluate -> serve) can still be demonstrated end to end.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import io
import json
import random
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.append(str(Path(__file__).resolve().parent.parent))
from app.taxonomy import CLASS_KEYS, SEARCH_QUERIES  # noqa: E402

API = "https://api.openverse.org/v1/images/"
UA = "AutoPartsAI/0.1 (final-year academic project; contact: student@example.edu)"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def perceptual_hash(img: Image.Image, size: int = 8) -> str:
    """Average-hash (aHash): cheap, robust, and enough to kill near-duplicates."""
    small = img.convert("L").resize((size, size), Image.BILINEAR)
    px = list(small.getdata())
    avg = sum(px) / len(px)
    bits = "".join("1" if p > avg else "0" for p in px)
    return f"{int(bits, 2):0{size * size // 4}x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def search(query: str, page: int, page_size: int, timeout: int = 20) -> dict:
    params = urllib.parse.urlencode(
        {
            "q": query,
            "page": page,
            "page_size": page_size,
            "license_type": "all-cc",
            "mature": "false",
        }
    )
    req = urllib.request.Request(f"{API}?{params}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def download(url: str, timeout: int = 20, max_bytes: int = 6_000_000) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(max_bytes + 1)
        return raw if len(raw) <= max_bytes else None
    except Exception:
        return None


def valid_image(raw: bytes) -> Image.Image | None:
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
        if min(im.size) < 200:  # too small to learn anything from
            return None
        return im.convert("RGB")
    except Exception:
        return None


def collect(session_hashes: list[str], img: Image.Image, threshold: int = 6) -> bool:
    """True if this image is sufficiently different from everything seen so far."""
    h = perceptual_hash(img)
    for other in session_hashes:
        if hamming(h, other) <= threshold:
            return False
    session_hashes.append(h)
    return True


def fetch_class(class_key: str, out_dir: Path, per_class: int, manifest: list[dict], hashes: list[str], delay: float) -> int:
    queries = SEARCH_QUERIES[class_key]
    saved = 0
    per_query = max(1, per_class // len(queries))

    for query in queries:
        if saved >= per_class:
            break
        for page in (1, 2):
            if saved >= per_class:
                break
            try:
                payload = search(query, page, page_size=per_query)
            except Exception as exc:
                print(f"  ! search failed for '{query}' p{page}: {exc}")
                break

            for item in payload.get("results", []):
                if saved >= per_class:
                    break
                url = item.get("url")
                if not url:
                    continue
                raw = download(url)
                if not raw:
                    continue
                img = valid_image(raw)
                if img is None:
                    continue
                if not collect(hashes, img):
                    continue

                digest = hashlib.sha1(url.encode()).hexdigest()[:10]
                path = out_dir / f"{class_key}_{saved:03d}_{digest}.jpg"
                img.save(path, "JPEG", quality=88)
                manifest.append(
                    {
                        "file": path.name,
                        "class": class_key,
                        "query": query,
                        "source_url": url,
                        "creator": item.get("creator"),
                        "license": item.get("license"),
                        "license_url": item.get("license_url"),
                        "foreign_landing_url": item.get("foreign_landing_url"),
                        "width": img.size[0],
                        "height": img.size[1],
                        "phash": perceptual_hash(img),
                        "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    }
                )
                saved += 1
                time.sleep(delay)

    return saved


def make_synthetic(out_dir: Path, per_class: int, manifest: list[dict]) -> int:
    """
    Procedural fallback so the pipeline (train -> evaluate -> serve) can be
    demonstrated without a network.

    IMPORTANT — what this dataset is and is not:
      Each class is rendered with the physical proportions of its real part family
      (a belt really is a long thin strip; a clutch plate really is a disc with a
      central hole; an air filter really is a bright pleated panel). That makes the
      task learnable, which is what you want for a pipeline smoke test.

      It is NOT a substitute for real photographs. Real parts bring glare, wear,
      dirt, packaging and cluttered backgrounds that these renders do not contain,
      so accuracy on this data overstates real-world performance. That gap is the
      single most important caveat for the report; see docs/DATASET-AND-MODEL.md.
    """
    rng = random.Random(1337)
    total = 0

    for class_key in CLASS_KEYS:
        for i in range(per_class):
            size = rng.randint(300, 420)
            # Vary the backdrop so the model cannot key on a single background.
            tint = rng.randint(-18, 18)
            base = rng.randint(150, 240)
            bg = tuple(int(min(255, max(0, base + tint + rng.randint(-12, 12)))) for _ in range(3))
            im = Image.new("RGB", (size, size), bg)
            d = ImageDraw.Draw(im)
            cx = size // 2 + rng.randint(-size // 12, size // 12)
            cy = size // 2 + rng.randint(-size // 12, size // 12)
            S = size  # shorthand

            if class_key == "oil_filter":
                # Vertical canister ~1.3:1, metallic, coloured paint, lighter top rim.
                w = rng.randint(S // 5, S // 3)
                h = int(w * rng.uniform(1.2, 1.5))
                body = rng.choice([(30, 60, 150), (25, 40, 90), (35, 90, 60), (110, 110, 120)])
                d.rounded_rectangle([cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2],
                                    radius=w // 8, fill=body, outline=(35, 35, 40), width=3)
                d.ellipse([cx - w // 3, cy - h // 2 - 7, cx + w // 3, cy - h // 2 + 11], fill=(150, 150, 155))
                d.line([cx - w // 3, cy + h // 2 - 8, cx + w // 3, cy + h // 2 - 8], fill=(60, 60, 65), width=3)

            elif class_key == "fuel_filter":
                # Narrower and taller than an oil filter; dark body, high contrast.
                w = rng.randint(S // 6, S // 4)
                h = int(w * rng.uniform(1.5, 1.9))
                body = rng.choice([(35, 35, 38), (48, 48, 52), (25, 30, 34)])
                d.rounded_rectangle([cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2],
                                    radius=w // 9, fill=body, outline=(20, 20, 20), width=3)
                d.rectangle([cx - w // 2, cy - h // 6, cx + w // 2, cy + h // 6], fill=(190, 190, 195))
                for k in range(6):
                    y = cy + h // 8 + k * (h // 22)
                    d.line([cx - w // 2 + 4, y, cx + w // 2 - 4, y], fill=(90, 90, 95), width=2)

            elif class_key == "hydraulic_filter":
                # Big, pale, low elongation — visibly the largest object in frame.
                w = rng.randint(S // 2 + 10, int(S * 0.62))
                h = int(w * rng.uniform(1.05, 1.35))
                d.rounded_rectangle([cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2],
                                    radius=w // 12, fill=(238, 236, 230), outline=(150, 148, 142), width=4)
                d.ellipse([cx - w // 3, cy - h // 2 - 10, cx + w // 3, cy - h // 2 + 14], fill=(205, 202, 196))
                d.line([cx - w // 2 + 10, cy + h // 4, cx + w // 2 - 10, cy + h // 4], fill=(180, 178, 172), width=4)

            elif class_key == "air_filter":
                # Bright pleated panel: the highest edge density of any class.
                w = rng.randint(int(S * 0.72), int(S * 0.9))
                h = rng.randint(int(S * 0.28), int(S * 0.42))
                d.rectangle([cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2],
                            fill=(242, 236, 206), outline=(150, 132, 78), width=4)
                for k in range(0, w, 7):  # tight pleats
                    x = cx - w // 2 + k
                    d.line([x, cy - h // 2 + 3, x, cy + h // 2 - 3], fill=(196, 186, 152), width=2)

            elif class_key == "brake_pad":
                # Two flat dark slabs with a bright backing plate. Low fill, dark.
                w = rng.randint(S // 3, S // 2)
                h = max(14, S // 14)
                for off in (-h - 12, h + 12):
                    y0 = cy + off
                    d.rounded_rectangle([cx - w // 2, y0 - h // 2, cx + w // 2, y0 + h // 2],
                                        radius=5, fill=(38, 36, 34), outline=(160, 160, 165), width=4)
                    d.rectangle([cx - w // 2, y0 + h // 3, cx + w // 2, y0 + h // 2], fill=(175, 175, 180))

            elif class_key == "belt":
                # Long thin near-black strip: elongation > 6, the strongest shape cue.
                w = rng.randint(int(S * 0.86), int(S * 0.96))
                h = rng.randint(S // 18, S // 11)
                y0 = cy + rng.randint(-S // 8, S // 8)
                d.rounded_rectangle([cx - w // 2, y0 - h // 2, cx + w // 2, y0 + h // 2],
                                    radius=h // 2, fill=(26, 26, 28))
                for k in range(0, w, 9):  # rib grooves
                    x = cx - w // 2 + k
                    d.line([x, y0 - h // 2 + 2, x, y0 + h // 2 - 2], fill=(58, 58, 62), width=2)

            elif class_key == "spark_plug":
                # Small, narrow, tall, bright ceramic + dark threaded metal.
                w = rng.randint(S // 13, S // 9)
                h = int(w * rng.uniform(3.0, 4.0))
                top = cy - h // 2
                d.rectangle([cx - w // 2, top, cx + w // 2, top + int(h * 0.42)],
                            fill=(238, 236, 230), outline=(180, 178, 172), width=2)
                d.rectangle([cx - w // 2, top + int(h * 0.42), cx + w // 2, top + int(h * 0.72)],
                            fill=(168, 168, 172))
                for k in range(7):
                    y = top + int(h * 0.42) + k * max(3, int(h * 0.30 / 7))
                    d.line([cx - w // 2, y, cx + w // 2, y], fill=(96, 96, 100), width=2)
                d.rectangle([cx - w // 2, top + int(h * 0.72), cx + w // 2, top + h], fill=(140, 140, 145))

            else:  # clutch_plate
                # Large grey disc with a central hole -> high hole ratio.
                r = rng.randint(S // 3, int(S * 0.44))
                d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(126, 124, 120), outline=(72, 72, 72), width=4)
                r2 = max(10, r // 3)
                d.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], fill=bg, outline=(72, 72, 72), width=4)
                for a in range(0, 360, 24):  # rivets / spring pockets
                    rad = math.radians(a)
                    x1 = cx + (r * 0.62) * math.cos(rad)
                    y1 = cy + (r * 0.62) * math.sin(rad)
                    d.ellipse([x1 - 7, y1 - 7, x1 + 7, y1 + 7], fill=(78, 76, 74))

            # Photographic degradations — blur, mild noise, brightness drift.
            im = im.filter(ImageFilter.GaussianBlur(rng.uniform(0.4, 1.3)))
            arr = np.asarray(im, dtype=np.int16)
            arr = np.clip(arr + rng.randint(-14, 14), 0, 255).astype(np.uint8)
            im = Image.fromarray(arr)

            path = out_dir / f"{class_key}_{i:03d}_syn.jpg"
            im.save(path, "JPEG", quality=88)
            manifest.append(
                {
                    "file": path.name,
                    "class": class_key,
                    "query": "synthetic",
                    "source_url": None,
                    "synthetic": True,
                    "phash": perceptual_hash(im),
                    "width": im.size[0],
                    "height": im.size[1],
                    "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
            )
            total += 1
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description="Download / generate the labelled spare-part dataset.")
    ap.add_argument("--out", default="data/images", help="output directory")
    ap.add_argument("--per-class", type=int, default=40)
    ap.add_argument("--delay", type=float, default=0.35, help="seconds between downloads (be polite)")
    ap.add_argument("--synthetic", action="store_true", help="skip the network, generate procedural images")
    args = ap.parse_args()

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    manifest: list[dict] = []
    hashes: list[str] = []
    counts: dict[str, int] = {}

    if args.synthetic:
        total = make_synthetic(out_dir, args.per_class, manifest)
        counts = {k: args.per_class for k in CLASS_KEYS}
        print(f"[dataset] generated {total} synthetic images in {out_dir}")
    else:
        for class_key in CLASS_KEYS:
            print(f"[dataset] {class_key} …")
            n = fetch_class(class_key, out_dir, args.per_class, manifest, hashes, args.delay)
            counts[class_key] = n
            print(f"  -> {n} images")

        if sum(counts.values()) < len(CLASS_KEYS) * 5:
            print("[dataset] network result too thin — topping up with synthetic images")
            extra = make_synthetic(out_dir, max(5, args.per_class // 4), manifest)
            for item in manifest[-extra:]:
                counts[item["class"]] = counts.get(item["class"], 0) + 1
            print(f"[dataset] added {extra} synthetic images")

    manifest_path.write_text(
        json.dumps(
            {
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "per_class": counts,
                "total": len(manifest),
                "synthetic_used": args.synthetic,
                "note": "Perceptual-hash de-duplicated. Provenance kept per file for the report.",
                "images": manifest,
            },
            indent=2,
        )
        + "\n"
    )

    print(f"[dataset] {len(manifest)} images -> {out_dir}")
    print(f"[dataset] manifest -> {manifest_path}")
    print("[dataset] per class:", counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
