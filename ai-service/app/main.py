"""
AutoParts AI — identification service (FastAPI).

IDENTIFICATION ENGINES, in priority order
    1. cloud   (Gemini by default)  — needs VISION_API_KEY, no training, no dataset
    2. torch   (local checkpoint)   — offline fallback, if a checkpoint exists
    3. heuristic                    — last resort, confidence hard-capped at 0.45 so
                                      it can never pass the API's confidence floor

The service starts and serves in ANY of those states. Running with no key and no
checkpoint is a valid configuration: `/health` says so plainly and `/predict` returns
low-confidence results that the API turns into "tell us more", rather than failing.

Endpoints
    GET  /health      engine in use, provider status, measured metrics
    GET  /classes     taxonomy + IDs, for API/UI parity checks
    POST /predict     image -> category (+ any part number/brand visible in the photo)
    POST /ocr         image or text -> part-number candidates
    POST /describe    text  -> category, so the app works with no photograph at all

CONTRACT WITH THE NODE API (backend/src/services/aiClient.js)
    {
      "modelVersion": "cloud:gemini-2.0-flash",
      "backend": "gemini" | "torch" | "heuristic",
      "latencyMs": 812.4,
      "predictions": [{"category": "oil_filter", "label": "Oil Filter",
                       "confidence": 0.83, "safetyCritical": false, "classIndex": 0}],
      "visiblePartNumber": "16510-61A31",
      "confidenceSource": "model_self_report"
    }

REMEMBER: this service identifies CATEGORIES. It never asserts that a part fits a
vehicle. That decision belongs to the catalogue in the Express API.
"""

from __future__ import annotations

import io
import os
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, UnidentifiedImageError

from . import cloud_vision
from . import features as feat
from .ood import OODDetector
from .taxonomy import CATEGORIES, CLASS_KEYS, NUM_CLASSES, is_safety_critical, label_for

ARTIFACT = Path(
    os.environ.get("MODEL_PATH", Path(__file__).resolve().parent.parent / "models" / "part_classifier.pt")
)
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 8 * 1024 * 1024))

# Below this the Node API reports the result as uncertain and asks for more detail.
APP_CONFIDENCE_FLOOR = 0.55

app = FastAPI(title="AutoParts AI — Identification Service", version="0.2.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

_MODEL = None
_MODEL_META: dict = {}
_OOD: OODDetector | None = None
_LOCAL_BACKEND = "unavailable"  # "torch" once a checkpoint loads


def _load_local_model() -> None:
    """
    Load the optional local checkpoint.

    torch is NOT a hard dependency any more. When the cloud provider is configured
    the local model is only a fallback, so a 2 GB download to enable it is a bad
    trade — the import is guarded and its absence is reported, not fatal.
    """
    global _MODEL, _MODEL_META, _OOD, _LOCAL_BACKEND

    if not ARTIFACT.exists():
        print(f"[identify] no local checkpoint at {ARTIFACT} (cloud provider will serve)")
        return

    try:
        import torch  # noqa: F401
        from .model import PartClassifier
    except Exception as exc:  # noqa: BLE001
        print(f"[identify] torch unavailable, local fallback disabled: {exc}")
        print("[identify]   install it with:  pip install torch   (or pip install -r requirements-local.txt)")
        return

    try:
        _MODEL = PartClassifier.load(ARTIFACT)
        _LOCAL_BACKEND = "torch"
        meta_path = ARTIFACT.with_suffix(".json")
        if meta_path.exists():
            import json

            _MODEL_META = json.loads(meta_path.read_text())
        blob = _MODEL_META.get("ood")
        if blob:
            _OOD = OODDetector.from_dict(blob)
        print(
            f"[identify] local checkpoint loaded ({ARTIFACT.name}, "
            f"test_acc={_MODEL_META.get('test_accuracy', 'n/a')})"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[identify] local checkpoint failed to load: {exc}")


_load_local_model()


def _engine() -> str:
    """Which engine will actually serve a prediction right now."""
    if cloud_vision.enabled():
        return provider_label()
    if _MODEL is not None:
        return "torch"
    return "heuristic"


def provider_label() -> str:
    return f"cloud:{cloud_vision.provider_name()}"


@app.get("/health")
def health():
    engine = _engine()
    warnings: list[str] = []

    if not cloud_vision.enabled():
        if cloud_vision.provider_name() in cloud_vision.CLOUD_PROVIDERS:
            warnings.append(
                f"VISION_PROVIDER={cloud_vision.provider_name()} but no API key found. "
                f"Set VISION_API_KEY (or {cloud_vision.KEY_ENV_VARS[cloud_vision.provider_name()][1]}). "
                "Falling back to the local model."
            )
        else:
            warnings.append(
                "No cloud provider configured; using the local model, which scores 0.258 on real "
                "photographs. Set VISION_PROVIDER=gemini and VISION_API_KEY to fix that."
            )
    if _MODEL is None and not cloud_vision.enabled():
        warnings.append(
            "No cloud provider and no local checkpoint: serving capped heuristic guesses. "
            "Predictions cannot pass the API confidence floor."
        )

    return {
        "status": "ok",
        "service": "autoparts-ai-identify",
        "version": "0.2.0",
        "engine": engine,
        "engines": {
            "cloud": cloud_vision.status(),
            "local": {
                "available": _MODEL is not None,
                "backend": _LOCAL_BACKEND,
                "checkpoint": str(ARTIFACT) if ARTIFACT.exists() else None,
                "testAccuracy": _MODEL_META.get("test_accuracy"),
                "note": "Optional offline fallback. Not required when a cloud provider is configured.",
            },
            "heuristic": {
                "available": True,
                "confidenceCap": 0.45,
                "note": "Last resort. Capped below the API confidence floor so it can never be asserted as an answer.",
            },
        },
        "requiresTraining": False,
        "requiresDataset": False,
        "categoryOnly": True,
        "guarantee": (
            "This service returns a CATEGORY and nothing else. It never asserts that a "
            "part fits a vehicle — that comes from a part-number or vehicle-catalogue "
            "match in the Express API, never from image similarity."
        ),
        "classes": CLASS_KEYS,
        "numClasses": NUM_CLASSES,
        "confidenceFloor": APP_CONFIDENCE_FLOOR,
        "warnings": warnings,
    }


@app.get("/classes")
def classes():
    return {
        "categories": CATEGORIES,
        "confidenceFloor": APP_CONFIDENCE_FLOOR,
        "engine": _engine(),
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
    Degraded mode: hand-written rules over the same physical features. Used only when
    there is no cloud provider and no checkpoint. Confidence is hard-capped at 0.45,
    below the API's 0.55 floor, so a guess can never be presented as an answer.
    """
    arr = feat._to_array(img)
    grey = arr.mean(axis=2)
    mask = feat.foreground_mask(arr)
    geom = feat.geometry_features(mask)
    _aspect, _extent, solidity, hole_ratio, elongation, area_ratio = geom
    mean_rgb = arr[mask].mean(axis=0) if mask.any() else arr.mean(axis=(0, 1))
    edges = feat.edge_features(grey, mask)
    brightness = feat.brightness_features(arr, mask)
    sat = float((arr.max(axis=2) - arr.min(axis=2))[mask].mean()) if mask.any() else 0.0

    scores = {k: 0.2 for k in CLASS_KEYS}
    if elongation > 2.2:
        scores["belt"] += 0.45
    if elongation < 1.6 and area_ratio < 0.45 and edges[1] > 0.25:
        scores["spark_plug"] += 0.3
    if hole_ratio > 0.05:
        scores["clutch_plate"] += 0.3
    if edges[0] > 0.16 and elongation < 2.0:
        scores["air_filter"] += 0.28
    if brightness[0] > 0.55 and sat < 0.25:
        scores["air_filter"] += 0.15
        scores["oil_filter"] += 0.1
    if brightness[0] < 0.35:
        scores["brake_pad"] += 0.22
        scores["belt"] += 0.1
    if solidity > 0.75 and elongation < 1.5 and hole_ratio < 0.03:
        scores["oil_filter"] += 0.22
        scores["fuel_filter"] += 0.12
        scores["hydraulic_filter"] += 0.08
    if mean_rgb[2] > mean_rgb[0] + 0.05:
        scores["oil_filter"] += 0.12

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:3]
    total = sum(v for _, v in ranked) or 1.0
    return [
        {
            "category": key,
            "label": label_for(key),
            "confidence": round(min(0.45, (raw / total) * 0.6), 4),
            "safetyCritical": is_safety_critical(key),
            "classIndex": CLASS_KEYS.index(key),
        }
        for key, raw in ranked
    ]


def _local_predict(img: Image.Image) -> tuple[list[dict], dict | None]:
    """Run the local torch model, or the heuristic if no checkpoint is loaded."""
    if _MODEL is None:
        return _heuristic_predict(img), None

    import torch

    vec = feat.extract(img)
    ood = _OOD.score(vec) if _OOD is not None else None
    probs = _MODEL.predict_proba(torch.from_numpy(vec).unsqueeze(0))[0].tolist()
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
    return preds, ood


@app.post("/predict")
async def predict(file: UploadFile = File(...)):
    started = time.perf_counter()
    raw = await file.read()
    img = _read_image(raw)
    mime = file.content_type or "image/jpeg"

    # ---- 1. cloud provider -------------------------------------------------
    if cloud_vision.enabled():
        try:
            cloud = cloud_vision.classify(raw, mime)
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
                "noPartDetected": cloud["noPartDetected"],
                "confidenceSource": "model_self_report",
                "reasoning": cloud["reasoning"],
                # The highest-value field: if the photo shows a part number, the
                # caller can attempt an exact catalogue match -> `confirmed` verdict.
                "visiblePartNumber": cloud["visiblePartNumber"],
                "visibleBrand": cloud["visibleBrand"],
                "note": (
                    "Category prediction only. Fitment is never inferred from image similarity."
                ),
                "validity": {
                    "provider": cloud_vision.provider_name(),
                    "model": cloud_vision.model_name(),
                    "confidenceCaveat": (
                        "This confidence is the model's own self-report, NOT a calibrated "
                        "probability. Treat it as a coarse hint."
                    ),
                    "statement": (
                        "A vision model identifies the CATEGORY. It cannot confirm that a part fits "
                        "a vehicle — that requires a part-number or vehicle-catalogue match."
                    ),
                },
            }
        except cloud_vision.CloudVisionError as exc:
            # Degrade rather than fail. The user still gets an answer if we can give one.
            print(f"[identify] cloud provider failed, falling back to local: {exc}")
            fallback_reason = str(exc)
    else:
        fallback_reason = None

    # ---- 2 & 3. local model or heuristic ----------------------------------
    preds, ood = _local_predict(img)
    uncertain = (not preds) or preds[0]["confidence"] < APP_CONFIDENCE_FLOOR

    response = {
        "modelVersion": _MODEL_META.get("modelVersion", "heuristic-v1") if _MODEL else "heuristic-v1",
        "backend": "torch" if _MODEL else "heuristic",
        "latencyMs": round((time.perf_counter() - started) * 1000, 1),
        "imageSize": list(img.size),
        "predictions": preds,
        "confidenceFloor": APP_CONFIDENCE_FLOOR,
        "uncertain": uncertain,
        "outOfDistribution": ood,
        "categoryOnly": True,
        "noPartDetected": not preds,
        "confidenceSource": "calibrated_softmax" if _MODEL else "heuristic_rule",
        "reasoning": "",
        "visiblePartNumber": None,
        "visibleBrand": None,
        "note": "Category prediction only. Fitment is never inferred from image similarity.",
    }

    if fallback_reason:
        response["fallbackReason"] = fallback_reason
        response["validity"] = {
            "provider": "local",
            "statement": (
                "The cloud provider could not be reached, so the local model answered. It was trained "
                "on rendered images and measured 0.258 accuracy on real photographs — treat this "
                "category as weak evidence."
            ),
        }
    elif not cloud_vision.enabled():
        response["validity"] = {
            "provider": "local",
            "measuredCrossDomainAccuracy": 0.258,
            "statement": (
                "No cloud provider configured. The local model measured 0.258 on real photographs. "
                "Set VISION_PROVIDER=gemini and VISION_API_KEY for reliable identification."
            ),
        }

    return response


@app.post("/ocr")
async def ocr(file: UploadFile = File(default=None), rawText: str = Form(default=None)):  # noqa: B008
    """
    Label or stamped-code reading.

    Order: cloud provider -> PaddleOCR -> EasyOCR -> Tesseract. The cloud path needs
    no system packages and handles angled, glared and embossed text far better, which
    is how part numbers actually appear.
    """
    if file is None and not rawText:
        raise HTTPException(400, "send a file, or the form field `rawText`")

    # A client that already OCR'd on-device can post the text straight through.
    if not file and rawText:
        return {"engine": "client_supplied", "text": rawText, "lineCount": len(rawText.splitlines())}

    raw = await file.read()
    img = _read_image(raw)
    mime = file.content_type or "image/jpeg"

    if cloud_vision.enabled():
        try:
            out = cloud_vision.read_label(raw, mime)
            out["lineCount"] = len([ln for ln in out["text"].splitlines() if ln.strip()])
            return out
        except cloud_vision.CloudVisionError as exc:
            print(f"[identify] cloud OCR failed, trying local engines: {exc}")

    import numpy as np

    np_img = np.asarray(img)

    try:
        from paddleocr import PaddleOCR  # type: ignore

        engine = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
        result = engine.ocr(np_img, cls=True)
        lines = [ln[1][0] for page in (result or []) for ln in (page or [])]
        return {"engine": "paddleocr", "text": "\n".join(lines), "lineCount": len(lines)}
    except Exception:  # noqa: BLE001
        pass

    try:
        import easyocr  # type: ignore

        reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        lines = [t for _, t, _ in reader.readtext(np_img)]
        return {"engine": "easyocr", "text": "\n".join(lines), "lineCount": len(lines)}
    except Exception:  # noqa: BLE001
        pass

    try:
        import pytesseract  # type: ignore

        text = pytesseract.image_to_string(img, config="--psm 6")
        return {
            "engine": "tesseract",
            "text": text.strip(),
            "lineCount": len([ln for ln in text.splitlines() if ln.strip()]),
        }
    except Exception:  # noqa: BLE001
        pass

    raise HTTPException(
        503,
        "No OCR engine available. Either configure the cloud provider "
        "(VISION_PROVIDER=gemini + VISION_API_KEY), or install an OCR engine "
        "(`pip install paddleocr` is best), or run OCR in the browser and post `rawText`.",
    )


@app.post("/describe")
async def describe(description: str = Form(...)):  # noqa: B008
    """
    Text description -> category. Lets the whole product work with no photograph:
    a user who cannot picture the part can type "the round black filter under my
    Swift's engine" and get catalogue candidates to verify against.
    """
    if not cloud_vision.enabled():
        raise HTTPException(
            503,
            "The description path needs the cloud provider. Configure VISION_PROVIDER=gemini "
            "and VISION_API_KEY, or use the part-number search instead.",
        )
    try:
        result = cloud_vision.interpret_description(description)
    except cloud_vision.CloudVisionError as exc:
        raise HTTPException(502, f"provider error: {exc}") from exc

    top = result["predictions"][0] if result["predictions"] else None
    return {
        **result,
        "confidenceFloor": APP_CONFIDENCE_FLOOR,
        "uncertain": top is None or top["confidence"] < APP_CONFIDENCE_FLOOR,
        "categoryOnly": True,
        "note": (
            "Category inferred from a description. It is a starting point, not an identification — "
            "confirm with a part number or your vehicle details."
        ),
    }
