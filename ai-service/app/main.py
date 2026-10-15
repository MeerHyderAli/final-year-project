"""
AutoParts AI — vision service (FastAPI).

Endpoints
    GET  /health   liveness + which model artefact is loaded
    GET  /classes  taxonomy + threshold, for API/UI parity checks
    POST /predict  image -> ranked category predictions (multipart field `file`)
    POST /ocr      label image -> raw text (multipart field `file`)

Contract with the Node API (backend/src/services/aiClient.js):
    {
      "modelVersion": "handcrafted-v1+mlp",
      "backend": "torch" | "heuristic",
      "latencyMs": 42,
      "predictions": [
        {"category": "oil_filter", "label": "Oil Filter",
         "confidence": 0.83, "safetyCritical": false, "classIndex": 0},
        ...
      ]
    }

Guard rail: if no trained checkpoint exists (or torch is missing) the service runs
in `heuristic` mode and caps confidence at 0.45, which is below the API's 0.55
threshold. Untrained predictions therefore *cannot* reach the user as an answer.
"""

from __future__ import annotations

import io
import os
import time
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, UnidentifiedImageError

from . import cloud_vision
from . import features as feat
from .ood import OODDetector
from .taxonomy import CATEGORIES, CLASS_KEYS, NUM_CLASSES, is_safety_critical, label_for

ARTIFACT = Path(os.environ.get("MODEL_PATH", Path(__file__).resolve().parent.parent / "models" / "part_classifier.pt"))
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 8 * 1024 * 1024))

# Anything below this is reported as "uncertain" by the Node API.
APP_CONFIDENCE_FLOOR = 0.55

app = FastAPI(title="AutoParts AI — Vision Service", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_MODEL = None
_MODEL_META: dict = {}
_BACKEND = "heuristic"
_OOD: OODDetector | None = None


def _load_model() -> None:
    global _MODEL, _MODEL_META, _BACKEND, _OOD
    if not ARTIFACT.exists():
        print(f"[vision] no checkpoint at {ARTIFACT} — running in heuristic mode")
        return
    try:
        import torch  # noqa: F401
        from .model import PartClassifier

        _MODEL = PartClassifier.load(ARTIFACT)
        _MODEL_META = {}
        meta_path = ARTIFACT.with_suffix(".json")
        if meta_path.exists():
            import json

            _MODEL_META = json.loads(meta_path.read_text())
        blob = _MODEL_META.get("ood")
        if blob:
            _OOD = OODDetector.from_dict(blob)
        _BACKEND = "torch"
        print(
            f"[vision] loaded {ARTIFACT.name} "
            f"(val_acc={_MODEL_META.get('val_accuracy', 'n/a')}, temp={_MODEL_META.get('temperature', 'n/a')})"
        )
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[vision] failed to load checkpoint: {exc}")


_load_model()


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "autoparts-ai-vision",
        "backend": _BACKEND,
        "cloudProvider": cloud_vision.status(),
        "modelPath": str(ARTIFACT),
        "modelVersion": _MODEL_META.get("modelVersion", "heuristic-v1"),
        "trained": _MODEL is not None,
        "classes": CLASS_KEYS,
        "numClasses": NUM_CLASSES,
        "confidenceFloor": APP_CONFIDENCE_FLOOR,
        "metrics": _MODEL_META.get("metrics", {}),
        "warning": None
        if _MODEL is not None
        else "No trained checkpoint. Predictions are capped below the API confidence threshold and will be treated as uncertain.",
    }


@app.get("/classes")
def classes():
    return {
        "categories": CATEGORIES,
        "confidenceFloor": APP_CONFIDENCE_FLOOR,
        "featureExtractor": feat.describe(),
    }


def _read_image(raw: bytes) -> Image.Image:
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"image exceeds {MAX_UPLOAD_BYTES} bytes")
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(415, f"not a readable image: {exc}") from exc
    return im.convert("RGB")


def _heuristic_predict(img: Image.Image) -> list[dict]:
    """
    Degraded mode. Uses the same physical features, but hand-written decision rules
    instead of learned weights, and hard-caps confidence below the API threshold so
    the UI always asks for more information.
    """
    arr = feat._to_array(img)
    grey = arr.mean(axis=2)
    mask = feat.foreground_mask(arr)
    geom = feat.geometry_features(mask)
    aspect_log, extent, solidity, hole_ratio, elongation, area_ratio = geom
    mean_rgb = arr[mask].mean(axis=0) if mask.any() else arr.mean(axis=(0, 1))
    edges = feat.edge_features(grey, mask)
    brightness = feat.brightness_features(arr, mask)
    sat = float((arr.max(axis=2) - arr.min(axis=2))[mask].mean()) if mask.any() else 0.0

    scores = {k: 0.2 for k in CLASS_KEYS}

    # Long, thin and dark => belt.
    if elongation > 2.2:
        scores["belt"] += 0.45
    # Compact and tall => small threaded item (spark plug).
    if elongation < 1.6 and area_ratio < 0.45 and edges[1] > 0.25:
        scores["spark_plug"] += 0.3
    # Round disc with a hole => clutch plate / brake pad family.
    if hole_ratio > 0.05:
        scores["clutch_plate"] += 0.3
    # Highly textured, roughly rectangular panel => air filter.
    if edges[0] > 0.16 and elongation < 2.0:
        scores["air_filter"] += 0.28
    # Bright and low-saturation => paper/pleated media (filters).
    if brightness[0] > 0.55 and sat < 0.25:
        scores["air_filter"] += 0.15
        scores["oil_filter"] += 0.1
    # Dark, saturated, near-black uniform => rubber/brake friction material.
    if brightness[0] < 0.35:
        scores["brake_pad"] += 0.22
        scores["belt"] += 0.1
    # Strong circular silhouette => cylindrical canister filters.
    if solidity > 0.75 and elongation < 1.5 and hole_ratio < 0.03:
        scores["oil_filter"] += 0.22
        scores["fuel_filter"] += 0.12
        scores["hydraulic_filter"] += 0.08
    if mean_rgb[2] > mean_rgb[0] + 0.05:  # blue-tinted canister
        scores["oil_filter"] += 0.12

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:3]
    total = sum(v for _, v in ranked) or 1.0
    out = []
    for key, raw in ranked:
        conf = min(0.45, (raw / total) * 0.6)  # hard cap: always below 0.55
        out.append(
            {
                "category": key,
                "label": label_for(key),
                "confidence": round(conf, 4),
                "safetyCritical": is_safety_critical(key),
                "classIndex": CLASS_KEYS.index(key),
            }
        )
    return out


@app.post("/predict")
async def predict(file: UploadFile = File(...)):
    started = time.perf_counter()
    raw = await file.read()
    img = _read_image(raw)

    # A cloud provider takes precedence when configured. Any failure degrades to the
    # local model rather than failing the request — see app/cloud_vision.py.
    if cloud_vision.enabled():
        try:
            cloud = cloud_vision.classify(raw, file.content_type or "image/jpeg")
            top = cloud["predictions"][0] if cloud["predictions"] else None
            return {
                "modelVersion": cloud["modelVersion"],
                "backend": cloud["backend"],
                "latencyMs": cloud["latencyMs"],
                "imageSize": list(img.size),
                "predictions": cloud["predictions"],
                "confidenceFloor": APP_CONFIDENCE_FLOOR,
                "uncertain": top is None or top["confidence"] < APP_CONFIDENCE_FLOOR,
                "outOfDistribution": None,
                "categoryOnly": True,
                "noPartDetected": cloud.get("noPartDetected", False),
                "confidenceSource": "model_self_report",
                "reasoning": cloud.get("reasoning", ""),
                "note": (
                    "Category prediction from a cloud vision model. Fitment is never "
                    "inferred from image similarity."
                ),
                "validity": {
                    "inDomainAccuracy": None,
                    "measuredCrossDomainAccuracy": None,
                    "confidenceCaveat": (
                        "This confidence is the model's own self-report, NOT a calibrated "
                        "probability. Treat it as a coarse hint."
                    ),
                    "statement": (
                        "A vision model identifies the CATEGORY only. It cannot confirm that a part "
                        "fits a vehicle — that needs a part number or a vehicle catalogue match."
                    ),
                },
            }
        except cloud_vision.CloudVisionError as exc:
            print(f"[vision] cloud provider failed, falling back to local model: {exc}")

    if _MODEL is None:
        preds = _heuristic_predict(img)
        backend = "heuristic"
        version = "heuristic-v1"
        ood = None
    else:
        import torch

        vec = feat.extract(img)
        # Advisory domain-shift score — see app/ood.py for why it must not be trusted
        # as a guarantee when it is silent.
        ood = _OOD.score(vec) if _OOD is not None else None
        x = torch.from_numpy(vec).unsqueeze(0)
        probs = _MODEL.predict_proba(x)[0].tolist()
        order = sorted(range(len(probs)), key=lambda i: probs[i], reverse=True)[:3]
        preds = [
            {
                "category": CLASS_KEYS[i],
                "label": label_for(CLASS_KEYS[i]),
                "confidence": round(float(probs[i]), 4),
                "safetyCritical": is_safety_critical(CLASS_KEYS[i]),
                "classIndex": i,
            }
            for i in order
        ]
        backend = "torch"
        version = _MODEL_META.get("modelVersion", "handcrafted-v1+mlp")

    top = preds[0]
    return {
        "modelVersion": version,
        "backend": backend,
        "latencyMs": round((time.perf_counter() - started) * 1000, 1),
        "imageSize": list(img.size),
        "predictions": preds,
        "confidenceFloor": APP_CONFIDENCE_FLOOR,
        "uncertain": top["confidence"] < APP_CONFIDENCE_FLOOR,
        "outOfDistribution": ood,
        "categoryOnly": True,
        "note": "Category prediction only. Fitment is never inferred from image similarity.",
        # The measured honesty statement. Replace these numbers if you retrain on a
        # different dataset — do not delete the sentence.
        "validity": {
            "inDomainAccuracy": _MODEL_META.get("test_accuracy"),
            "trainedOn": _MODEL_META.get("dataset", {}).get("root"),
            "syntheticTrainingData": True,
            "measuredCrossDomainAccuracy": 0.258,
            "statement": (
                "This checkpoint was trained on procedurally generated images. On a held-out set of "
                "real product photographs it scored 0.258 accuracy and was often confidently wrong. "
                "Do not present image predictions as a part identification until the model is retrained "
                "on real labelled photographs."
            ),
        },
    }


@app.post("/ocr")
async def ocr(file: UploadFile = File(...)):
    """
    Label/code OCR. Tries PaddleOCR -> EasyOCR -> pytesseract, in that order, and
    returns 503 if none is installed. It never invents text.
    """
    raw = await file.read()
    img = _read_image(raw)
    import numpy as np

    np_img = np.asarray(img)

    # 1. PaddleOCR
    try:
        from paddleocr import PaddleOCR  # type: ignore

        engine = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
        result = engine.ocr(np_img, cls=True)
        lines = [ln[1][0] for page in (result or []) for ln in (page or [])]
        return {"engine": "paddleocr", "text": "\n".join(lines), "lineCount": len(lines)}
    except Exception:
        pass

    # 2. EasyOCR
    try:
        import easyocr  # type: ignore

        reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        lines = [t for _, t, _ in reader.readtext(np_img)]
        return {"engine": "easyocr", "text": "\n".join(lines), "lineCount": len(lines)}
    except Exception:
        pass

    # 3. Tesseract
    try:
        import pytesseract  # type: ignore

        text = pytesseract.image_to_string(img, config="--psm 6")
        return {
            "engine": "tesseract",
            "text": text.strip(),
            "lineCount": len([l for l in text.splitlines() if l.strip()]),
        }
    except Exception:
        pass

    raise HTTPException(
        503,
        "No OCR engine installed. `pip install paddleocr` (best) / `easyocr` / `pytesseract`. "
        "The web client can also send form field `rawText` from on-device Tesseract.js.",
    )
