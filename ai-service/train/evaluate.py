"""
Evaluate a trained checkpoint, including the number that actually matters.

    python train/evaluate.py --model models/part_classifier.pt --data data/images
    python train/evaluate.py --model models/part_classifier.pt --external-dir path/to/real_photos

The second form runs a **cross-domain check**: images of real parts that the model
has never seen, from a completely different source (product photography rather than
our renders). This is the honest headline number.

Why it matters: a model trained on procedurally generated images will score ~97% on
procedurally generated images and far worse on real photographs. Reporting only the
first number would be misleading — the gap between them IS the finding.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import torch
from PIL import Image

sys.path.append(str(Path(__file__).resolve().parent.parent))
from app import features as feat  # noqa: E402
from app.model import PartClassifier  # noqa: E402
from app.taxonomy import CLASS_KEYS  # noqa: E402


def confusion(y_true, y_pred, k=len(CLASS_KEYS)):
    cm = np.zeros((k, k), dtype=int)
    for t, p in zip(y_true, y_pred):
        cm[t, p] += 1
    return cm


def report_block(y_true, y_pred) -> dict:
    if not len(y_true):
        return {"n": 0}
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    cm = confusion(y_true, y_pred)
    acc = float((y_true == y_pred).mean())

    per_class = {}
    for i, key in enumerate(CLASS_KEYS):
        tp = int(cm[i, i])
        fp = int(cm[:, i].sum() - tp)
        fn = int(cm[i, :].sum() - tp)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        if cm[i, :].sum():
            per_class[key] = {
                "precision": round(prec, 4),
                "recall": round(rec, 4),
                "f1": round(f1, 4),
                "support": int(cm[i, :].sum()),
            }
    return {
        "n": int(len(y_true)),
        "accuracy": round(acc, 4),
        "macro_f1": round(float(np.mean([v["f1"] for v in per_class.values()])) if per_class else 0.0, 4),
        "per_class": per_class,
        "confusion_matrix": cm.tolist(),
        "labels": CLASS_KEYS,
    }


def predict_dir(model: PartClassifier, directory: Path, mapping: dict[str, str] | None):
    """Returns (y_true, y_pred, rows). `mapping` maps filename prefix -> class key."""
    rows, y_true, y_pred = [], [], []
    files = [p for p in sorted(directory.glob("*")) if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}]
    for path in files:
        try:
            with Image.open(path) as im:
                vec = feat.extract(im)
        except Exception as exc:
            print(f"  ! skip {path.name}: {exc}")
            continue
        probs = model.predict_proba(torch.from_numpy(vec).unsqueeze(0))[0].numpy()
        order = probs.argsort()[::-1]
        top = CLASS_KEYS[order[0]]

        true_key = None
        if mapping:
            for prefix, key in mapping.items():
                if path.name.startswith(prefix):
                    true_key = key
                    break
        else:
            for key in CLASS_KEYS:
                if path.name.startswith(key):
                    true_key = key
                    break

        rows.append(
            {
                "file": path.name,
                "true": true_key,
                "predicted": top,
                "confidence": round(float(probs[order[0]]), 4),
                "correct": None if true_key is None else (top == true_key),
                "runnerUp": {"category": CLASS_KEYS[order[1]], "confidence": round(float(probs[order[1]]), 4)},
            }
        )
        if true_key:
            y_true.append(CLASS_KEYS.index(true_key))
            y_pred.append(int(order[0]))
    return y_true, y_pred, rows


def _load_train_module():
    """Import train.py by file path, so cwd and -m vs script invocation don't matter."""
    import importlib.util

    path = Path(__file__).resolve().parent / "train.py"
    spec = importlib.util.spec_from_file_location("_autoparts_train", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_manifest, module.make_splits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="models/part_classifier.pt")
    ap.add_argument("--data", default="data/images", help="in-domain test split")
    ap.add_argument("--external-dir", default=None, help="directory of real photos for a cross-domain check")
    ap.add_argument("--out", default=None, help="write a JSON report here")
    args = ap.parse_args()

    service_root = Path(__file__).resolve().parent.parent
    repo_root = service_root.parent
    model_path = Path(args.model)
    if not model_path.is_absolute():
        model_path = service_root / model_path
    if not model_path.exists():
        print(f"[eval] no checkpoint at {model_path} — run train/train.py first")
        return 2

    model = PartClassifier.load(model_path)
    print(f"[eval] loaded {model_path.name} (temperature={float(model.temperature):.3f})")

    out: dict = {"model": model_path.name}

    # ---- in-domain ------------------------------------------------------
    data_dir = Path(args.data)
    if not data_dir.is_absolute():
        data_dir = repo_root / data_dir
    if data_dir.exists():
        # Reuse the same split logic so the test set here matches training exactly.
        # Loaded by file path rather than `import train.train` so this works whether
        # the script is run as `python train/evaluate.py` or `python -m train.evaluate`.
        load_manifest, make_splits = _load_train_module()

        items = load_manifest(data_dir)
        splits = make_splits(items)
        print(f"[eval] in-domain test split: {len(splits['test'])} images")
        y_true, y_pred = [], []
        wrong = []
        for item in splits["test"]:
            try:
                with Image.open(data_dir / item["file"]) as im:
                    vec = feat.extract(im)
            except Exception:
                continue
            probs = model.predict_proba(torch.from_numpy(vec).unsqueeze(0))[0].numpy()
            p = int(probs.argmax())
            t = CLASS_KEYS.index(item["class"])
            y_true.append(t)
            y_pred.append(p)
            if p != t:
                wrong.append({"file": item["file"], "true": item["class"], "predicted": CLASS_KEYS[p]})
        out["in_domain"] = report_block(y_true, y_pred)
        out["in_domain"]["misclassified"] = wrong
        print(f"[eval] in-domain accuracy: {out['in_domain'].get('accuracy')}")

    # ---- cross-domain ---------------------------------------------------
    if args.external_dir:
        ext = Path(args.external_dir)
        if not ext.is_absolute():
            ext = repo_root / ext
        mapping_path = ext / "labels.json"
        mapping = json.loads(mapping_path.read_text()) if mapping_path.exists() else None
        if ext.exists():
            print(f"[eval] cross-domain: {ext}")
            y_true, y_pred, rows = predict_dir(model, ext, mapping)
            out["cross_domain"] = report_block(y_true, y_pred)
            out["cross_domain"]["directory"] = str(ext)
            out["cross_domain"]["predictions"] = rows
            for r in rows:
                mark = "OK " if r["correct"] else ("-- " if r["correct"] is None else "XX ")
                print(f"  {mark}{r['file'][:52]:54s} true={str(r['true']):17s} pred={r['predicted']:17s} {r['confidence']:.2f}")
            print(f"[eval] cross-domain accuracy: {out['cross_domain'].get('accuracy')} (n={out['cross_domain'].get('n')})")

            if out.get("in_domain", {}).get("accuracy") is not None and out["cross_domain"].get("accuracy") is not None:
                gap = out["in_domain"]["accuracy"] - out["cross_domain"]["accuracy"]
                out["domain_gap"] = round(gap, 4)
                print(
                    f"\n[eval] DOMAIN GAP = {gap:+.4f}. "
                    "This is the honest measure of how much the synthetic training set "
                    "fails to represent real parts. Report it, do not hide it."
                )

    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2) + "\n")
        print(f"[eval] report -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
