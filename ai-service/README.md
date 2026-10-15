# AutoParts AI — Vision Service

FastAPI service that turns a photo of a spare part into a **category prediction and
nothing more**. Fitment is decided by the Node API against catalogue data, never here.

```
POST /predict   image  ->  ranked category predictions + domain-shift advisory
POST /ocr       label  ->  raw text (PaddleOCR / EasyOCR / Tesseract)
GET  /health    liveness, loaded artefact, measured metrics
GET  /classes   taxonomy + feature layout, for API/UI parity checks
```

## Quick start

```bash
cd ai-service
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. Build a dataset (procedural; no network needed)
python -m app.download_images --synthetic --per-class 60 --out ../data/images

# 2. Train
python train/train.py --data data/images --epochs 80

# 3. Evaluate (in-domain + the cross-domain check that actually matters)
python train/evaluate.py --model models/part_classifier.pt --data data/images

# 4. Serve
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

To use **real photographs** instead, drop the `--synthetic` flag. `download_images.py`
pulls CC-licensed images from Openverse and writes a `manifest.json` recording the
source URL, creator and licence of every file, so your report can state exactly where
the data came from. It de-duplicates with a perceptual hash as it goes.

## Read this before quoting an accuracy number

The committed checkpoint is trained on **procedurally generated images**. Measured
performance:

| Split | Accuracy | Macro-F1 |
|---|---|---|
| In-domain (renders, held-out) | **0.969** | 0.967 |
| Cross-domain (31 real product photos) | **0.258** | — |
| **Domain gap** | **0.711** | |

The model is not merely less accurate on real photos — it is **confidently wrong**:
it labelled a real spark plug *"air filter"* at 0.99 confidence.

This is the single most important result in the project, and it validates the
product's design rule rather than undermining it: *AI suggests; catalogue and seller
data verify.* Three things follow, all implemented:

1. **The confidence floor.** `MIN_CONFIDENCE=0.55` in the Node API. A prediction below
   it is reported as uncertain and the user is asked for a part number or vehicle.
2. **Fitment is never inferred from an image.** Only a catalogue match asserts it.
3. **No cheap escape from the domain gap.** We tested whether a feature-space distance
   test could flag real photos as out-of-distribution:

   | Detector | Real photos flagged |
   |---|---|
   | Diagonal z-score distance | **0%** |
   | Mahalanobis distance | **35%** |

   So `app/ood.py` exists as an *advisory* only, and its own response payload says so.
   You cannot buy your way out of a domain gap with a novelty detector — you fix it
   with real labelled data.

**Before claiming image recognition works, retrain on real labelled photographs.**

## Why hand-crafted features instead of a CNN

With a few hundred images per class, a frozen CNN backbone memorises; it does not
generalise, and the resulting accuracy figure describes the dataset rather than the
problem. `app/features.py` extracts 22 features that encode *physical* properties
which genuinely separate these parts:

| Block | Dims | What it captures |
|---|---|---|
| shape | 8 | aspect, elongation, extent, solidity, hole ratio, Hu moments |
| colour | 6 | mean RGB, saturation, warmth, value |
| hue | 4 | circular hue moments, saturation-weighted |
| texture | 4 | edge density, gradient magnitude, local roughness |

A belt really is a long thin strip; a clutch plate really is a disc with a central
hole; an air filter really is a bright, highly textured panel. These features make the
task learnable on a small dataset. `train/train.py --backbone mobilenet` is the
documented upgrade path for when the dataset grows.

## Optional: use a cloud vision model instead

The local model's weakness is real photographs (0.258). A frontier vision model has
seen millions of them and will do far better. Enable it with two variables:

```bash
export VISION_PROVIDER=openai          # or gemini | anthropic
export VISION_API_KEY=sk-...           # or OPENAI_API_KEY / GEMINI_API_KEY / ANTHROPIC_API_KEY
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

`GET /health` reports the active provider. `app/cloud_vision.py` implements all three;
requests use stdlib `urllib`, so there is no new dependency.

**What this fixes:** real-photo identification, which is the local model's weak point.

**What it does NOT fix — and this is the point:** a vision model, however good, still
returns a **category**. It cannot tell you a part fits a 2019 Swift. Fitment still
requires a part-number match or a vehicle-catalogue match in the Express API. The
safety architecture is unchanged, and the cloud path is *not* a shortcut around it.

Three further caveats:

| | |
|---|---|
| **Confidence semantics change** | The local model's confidence is a temperature-calibrated softmax. A cloud model's is a self-report, so responses set `confidenceSource: "model_self_report"` and the API warns it is a coarse hint, not a probability. |
| **Cost and connectivity** | Roughly USD 0.001–0.01 per image, and the offline demo stops working. Keep `local` as the default for demonstrations. |
| **Privacy** | Every upload leaves the device for a third party. For a deployment handling customer photographs that is a disclosure you owe your users. |

Any failure — no key, a 500, a timeout, an unparseable reply — falls back to the local
model and logs why. `/predict` never fails because a provider did. That path is tested:
`tests/test_cloud_vision.py` (44 checks) covers reply parsing, taxonomy validation,
key resolution, and the failure path.

## Two bugs worth reading about

Both were found by running the pipeline, and both are the kind that silently produce a
useless model that still reports plausible-looking numbers.

**1. Constant feature ÷ epsilon = noise amplifier.** `hole_ratio` is constant across
the dataset, so its std is 0. Standardising divides by std; clamping that to `1e-6`
made the augmentation noise (0.02) blow up to ±20 000. Training sat at chance
accuracy with the loss frozen at 2.14. Fix: floor the std (`app/features.py:STD_FLOOR`).

**2. Splitting by group, globally, starves classes.** The first splitter dealt
near-duplicate clusters into train/val/test globally, which dumped four *entire
classes* into train and two others into test. Validation macro-F1 was pinned at 0.000
and early stopping cheerfully selected the epoch-1 weights. Fix: cluster by perceptual
hash, then stratify **within each class**. See `make_splits` in `train/train.py`.

## Layout

```
app/
  main.py             FastAPI app: /predict, /ocr, /health, /classes
  features.py         22-D hand-crafted extractor
  model.py            MLP classifier + temperature calibration
  ood.py              domain-shift advisory (with its own measured limitations)
  taxonomy.py         class order — must match backend/src/taxonomy.js
  download_images.py  dataset builder (Openverse, or --synthetic)
train/
  train.py            leak-aware split, training, calibration, checkpoint
  evaluate.py         in-domain + cross-domain evaluation
models/               committed checkpoint (< 100 KB)
reports/              metrics.json, training-history.json, cross-domain.json
```

## Alignment guarantees

`app/taxonomy.py:CLASS_KEYS` order is the model's class order and must match
`backend/src/taxonomy.js:CATEGORIES` and `data/parts.json`. `GET /classes` exists so a
test can assert that the three agree rather than letting them drift.
