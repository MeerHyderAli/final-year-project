"""
Train the spare-part category classifier.

    python train/train.py --data data/images --epochs 60 --out models/part_classifier.pt

Split policy (see docs/DATASET-AND-MODEL.md):
  * split BY SOURCE-GROUP, not by random file. Images harvested from one web page
    are near-duplicates; putting some in train and some in test is the classic
    leakage that makes a project report look 97% accurate and useless in reality.
  * a held-out validation split drives early stopping and temperature calibration.
  * the test split is touched once, at the end, for the reported metrics.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from PIL import Image

sys.path.append(str(Path(__file__).resolve().parent.parent))
from app import features as feat  # noqa: E402
from app.model import PartClassifier, calibrate_temperature  # noqa: E402
from app.ood import OODDetector  # noqa: E402
from app.taxonomy import CLASS_KEYS, NUM_CLASSES  # noqa: E402


def set_seeds(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def load_manifest(data_dir: Path) -> list[dict]:
    mpath = data_dir / "manifest.json"
    if mpath.exists():
        blob = json.loads(mpath.read_text())
        items = blob.get("images", [])
        if items:
            return [i for i in items if (data_dir / i["file"]).exists()]
    # No manifest: infer the class from the filename prefix.
    items = []
    for p in sorted(data_dir.glob("*")):
        if p.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        for key in CLASS_KEYS:
            if p.name.startswith(key):
                items.append({"file": p.name, "class": key, "query": key, "synthetic": "syn" in p.name})
                break
    return items


def group_key(item: dict, items: list[dict], threshold: int = 6) -> str:
    """
    Cluster near-duplicates using the stored perceptual hashes, then use the cluster
    id as the split group. Falls back to (class, query) when no hash is present.
    """
    h = item.get("phash")
    if not h:
        return f"{item['class']}|{item.get('query', 'na')}"
    for other in items:
        oh = other.get("phash")
        if not oh or other is item:
            continue
        try:
            if bin(int(h, 16) ^ int(oh, 16)).count("1") <= threshold:
                return f"near-dup|{min(h, oh)}"
        except ValueError:
            continue
    return f"hash|{h}"


def make_splits(items: list[dict], val_frac=0.15, test_frac=0.15, seed=42) -> dict[str, list[dict]]:
    """
    STRATIFIED BY CLASS, GROUPED BY NEAR-DUPLICATE.

    Two failure modes this has to avoid simultaneously:
      1. Class starvation — splitting globally by group can dump an entire class
         into one split, so the model never trains on it (or never gets tested on
         it) and the reported accuracy is meaningless.
      2. Leakage — near-duplicates of one image landing on both sides of the split.

    So: cluster by perceptual hash first, then walk each class independently and
    deal its clusters into train/val/test at the target ratios.
    """
    rng = random.Random(seed)

    by_class: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for item in items:
        by_class[item["class"]][group_key(item, items)].append(item)

    splits: dict[str, list[dict]] = {"train": [], "val": [], "test": []}

    for cls in sorted(by_class):
        clusters = list(by_class[cls].values())
        rng.shuffle(clusters)
        # Largest clusters first so a 1-image class still lands somewhere sane.
        clusters.sort(key=len, reverse=True)

        n = sum(len(c) for c in clusters)
        want_test = max(1, int(round(n * test_frac)))
        want_val = max(1, int(round(n * val_frac))) if n >= 10 else 0

        counts = {"train": 0, "val": 0, "test": 0}
        for cluster in clusters:
            size = len(cluster)
            # Fill test, then val, then everything else goes to train — but never
            # let train be emptied out.
            if counts["test"] < want_test and counts["train"] >= size:
                bucket = "test"
            elif counts["val"] < want_val and counts["train"] >= size:
                bucket = "val"
            else:
                bucket = "train"
            splits[bucket].extend(cluster)
            counts[bucket] += size

    return splits


def extract_features(items: list[dict], data_dir: Path, cache: Path) -> tuple[np.ndarray, np.ndarray, list[str]]:
    cache_data = {}
    if cache.exists():
        try:
            cache_data = np.load(cache, allow_pickle=True).item()
        except Exception:
            cache_data = {}

    xs, ys, names = [], [], []
    for item in items:
        path = data_dir / item["file"]
        key = item["file"]
        vec = cache_data.get(key)
        if vec is None:
            try:
                with Image.open(path) as im:
                    vec = feat.extract(im)
            except Exception as exc:
                print(f"  ! skip {key}: {exc}")
                continue
            cache_data[key] = vec
        xs.append(vec)
        ys.append(CLASS_KEYS.index(item["class"]))
        names.append(key)

    cache.parent.mkdir(parents=True, exist_ok=True)
    np.save(cache, cache_data)
    return np.asarray(xs, dtype=np.float32), np.asarray(ys, dtype=np.int64), names


def augment(x: np.ndarray, noise: float = 0.02) -> np.ndarray:
    """Feature-space augmentation: small jitter + occasional feature dropout."""
    out = x + np.random.normal(0, noise, size=x.shape).astype(np.float32)
    mask = (np.random.rand(*x.shape) > 0.9).astype(np.float32)
    return out * (1 - mask * 0.5)


def evaluate(model, x, y) -> dict:
    if len(x) == 0:
        return {"accuracy": None, "n": 0}
    with torch.no_grad():
        probs = model.predict_proba(torch.from_numpy(x))
        pred = probs.argmax(1).numpy()
    acc = float((pred == y).mean())
    cm = np.zeros((NUM_CLASSES, NUM_CLASSES), dtype=int)
    for t, p in zip(y, pred):
        cm[t, p] += 1

    per_class = {}
    for i, key in enumerate(CLASS_KEYS):
        tp = int(cm[i, i])
        fp = int(cm[:, i].sum() - tp)
        fn = int(cm[i, :].sum() - tp)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        per_class[key] = {
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
            "support": int(cm[i, :].sum()),
        }
    macro_f1 = float(np.mean([v["f1"] for v in per_class.values()]))
    top2 = None
    if NUM_CLASSES > 1:
        with torch.no_grad():
            p2 = model.predict_proba(torch.from_numpy(x)).topk(2, dim=1).indices.numpy()
        top2 = float(np.mean([y[i] in p2[i] for i in range(len(y))]))

    return {
        "n": int(len(y)),
        "accuracy": round(acc, 4),
        "macro_f1": round(macro_f1, 4),
        "top2_accuracy": None if top2 is None else round(top2, 4),
        "per_class": per_class,
        "confusion_matrix": cm.tolist(),
        "labels": CLASS_KEYS,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/images")
    ap.add_argument("--out", default="models/part_classifier.pt")
    ap.add_argument("--epochs", type=int, default=80)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--patience", type=int, default=15)
    args = ap.parse_args()

    set_seeds(args.seed)
    repo_root = Path(__file__).resolve().parent.parent.parent
    service_root = Path(__file__).resolve().parent.parent
    data_dir = (repo_root / args.data).resolve() if not Path(args.data).is_absolute() else Path(args.data)
    out_path = (service_root / args.out).resolve() if not Path(args.out).is_absolute() else Path(args.out)

    items = load_manifest(data_dir)
    if len(items) < NUM_CLASSES * 3:
        print(f"[train] only {len(items)} usable images found in {data_dir}")
        print("[train] run:  python -m app.download_images --per-class 40 --out data/images")
        print("[train] or:   python -m app.download_images --synthetic --per-class 40 --out data/images")
        return 2

    print(f"[train] {len(items)} images across {len({i['class'] for i in items})} classes")
    splits = make_splits(items, seed=args.seed)
    for name, rows in splits.items():
        print(f"[train] {name}: {len(rows)} images  {dict(Counter(r['class'] for r in rows))}")

    cache = data_dir / ".feature_cache.npy"
    Xtr, ytr, _ = extract_features(splits["train"], data_dir, cache)
    Xva, yva, _ = extract_features(splits["val"], data_dir, cache)
    Xte, yte, _ = extract_features(splits["test"], data_dir, cache)
    if len(Xtr) < NUM_CLASSES:
        print("[train] not enough training images after extraction")
        return 2

    # feat.normalisation floors the std. Do NOT use Xtr.std(0) directly — a constant
    # feature would then be divided by ~1e-6 and amplified into pure noise.
    mean, std = feat.normalisation(Xtr)
    constant_features = np.where(Xtr.std(0) == 0)[0].tolist()
    if constant_features:
        print(
            f"[train] note: features {constant_features} are constant in the training split; "
            f"their std has been floored to {feat.STD_FLOOR} so they stay inert."
        )
    model = PartClassifier(in_dim=feat.FEATURE_DIM, num_classes=NUM_CLASSES)
    model.set_normalisation(mean, std, std_floor=feat.STD_FLOOR)

    # Light class balancing so rare categories are not ignored.
    counts = np.bincount(ytr, minlength=NUM_CLASSES).astype(np.float32)
    weights = torch.tensor((counts.sum() / np.maximum(counts, 1)) ** 0.5, dtype=torch.float32)

    optimiser = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=args.epochs)
    criterion = nn.CrossEntropyLoss(weight=weights, label_smoothing=0.08)

    Xtr_t = torch.from_numpy(Xtr)
    ytr_t = torch.from_numpy(ytr)
    Xva_t = torch.from_numpy(Xva) if len(Xva) else None

    best_f1, best_state, since_improved = -1.0, None, 0
    history = []

    for epoch in range(1, args.epochs + 1):
        model.train()
        perm = torch.randperm(len(Xtr_t))
        epoch_loss = 0.0
        for i in range(0, len(perm), args.batch):
            idx = perm[i : i + args.batch]
            xb = torch.from_numpy(augment(Xtr_t[idx].numpy()))
            yb = ytr_t[idx]
            optimiser.zero_grad()
            loss = criterion(model(xb), yb)
            loss.backward()
            optimiser.step()
            epoch_loss += loss.item() * len(idx)
        scheduler.step()

        train_loss = epoch_loss / max(len(perm), 1)
        if Xva_t is not None and len(Xva_t):
            vm = evaluate(model, Xva_t.numpy(), yva)
            score = vm["macro_f1"] or 0.0
            history.append({"epoch": epoch, "loss": round(train_loss, 4), "val_macro_f1": score, "val_acc": vm["accuracy"]})
            if score > best_f1 + 1e-4:
                best_f1, best_state, since_improved = score, {k: v.clone() for k, v in model.state_dict().items()}, 0
            else:
                since_improved += 1
            if epoch % 5 == 0 or epoch == 1:
                print(f"[train] epoch {epoch:3d}  loss={train_loss:.4f}  val_f1={score:.4f}  val_acc={vm['accuracy']:.4f}")
            if since_improved >= args.patience:
                print(f"[train] early stop at epoch {epoch} (no val improvement for {args.patience})")
                break
        else:
            print(f"[train] epoch {epoch:3d}  loss={train_loss:.4f}")

    if best_state and len(history) and best_f1 > 0:
        model.load_state_dict(best_state)
        print(f"[train] restored best checkpoint (val macro-F1 = {best_f1:.4f})")
    else:
        # Validation was unusable (too few val samples, or it never beat chance).
        # Keep the final epoch rather than a worse earlier one, and say so loudly.
        print(
            "[train] WARNING: validation macro-F1 never rose above 0 — keeping the FINAL epoch. "
            "Metrics below are not trustworthy; collect more labelled data per class."
        )

    # Calibration must use a split the model hasn't been early-stopped against too hard.
    temp = calibrate_temperature(model, Xva_t if Xva_t is not None and len(Xva_t) else Xtr_t,
                                 torch.from_numpy(yva if Xva_t is not None and len(Xva_t) else ytr))

    metrics = {
        "train": evaluate(model, Xtr, ytr),
        "val": evaluate(model, Xva, yva),
        "test": evaluate(model, Xte, yte),
    }

    # Domain-shift diagnostic. See app/ood.py — advisory only, ~35% detection rate.
    ood = OODDetector.fit(Xtr, mean, std)

    meta = {
        "modelVersion": "handcrafted-v1+mlp",
        "featureExtractor": feat.describe(),
        "trainedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "epochsRun": len(history),
        "temperature": temp,
        "val_accuracy": metrics["val"]["accuracy"] or metrics["train"]["accuracy"],
        "test_accuracy": metrics["test"]["accuracy"],
        "metrics": metrics,
        "dataset": {
            "root": str(data_dir.relative_to(repo_root)) if data_dir.is_relative_to(repo_root) else str(data_dir),
            "total": len(items),
            "splits": {k: len(v) for k, v in splits.items()},
        },
        "ood": ood.to_dict(),
        "caveat": (
            "Metrics are only meaningful for the collected dataset. Any image in the test split that is a "
            "near-duplicate of a training image would inflate accuracy; the group-wise split above mitigates this."
        ),
    }

    model.save(out_path, meta)

    report_dir = repo_root / "ai-service" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "metrics.json").write_text(json.dumps(meta, indent=2) + "\n")
    (report_dir / "training-history.json").write_text(json.dumps(history, indent=2) + "\n")

    print("\n=== RESULTS ===")
    print(f"  train acc      : {metrics['train']['accuracy']}")
    print(f"  val   acc      : {metrics['val']['accuracy']}   macro-F1 {metrics['val']['macro_f1']}")
    print(f"  test  acc      : {metrics['test']['accuracy']}   macro-F1 {metrics['test']['macro_f1']}")
    print(f"  temperature    : {temp}")
    print(f"  artefact       : {out_path}")
    print(f"  metrics        : {report_dir / 'metrics.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
