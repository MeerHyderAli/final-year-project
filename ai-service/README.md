# AutoParts AI — Identification Service

FastAPI service that turns a photo of a spare part (or a description of one) into a
**category suggestion and nothing more**. Fitment is decided by the Node API against
catalogue data, never here.

```
POST /predict   image        ->  ranked category predictions + part number/brand read from the part
POST /ocr       label image  ->  raw label text -> part-number candidates
POST /describe  text         ->  category suggestion from a written description
GET  /health    liveness, active engine, whether training/datasets are needed (they are not)
GET  /classes   taxonomy + engine list, for API/UI parity checks
```

## Quick start

```bash
cd ai-service
pip install -r requirements.txt          # no torch, no training, no dataset

export VISION_API_KEY=your-key           # free: https://aistudio.google.com/apikey
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

That is the whole setup. Check the key before you demo:

```bash
bash ../scripts/check-gemini.sh          # lists models, makes one real request, exits 0/1/2
```

`requirements.txt` deliberately contains **no heavy dependencies**. The optional
extras are separated out and documented in place:

| File | Adds | When you'd want it |
|---|---|---|
| `requirements.txt` | numpy, pillow, fastapi, uvicorn | always — this is the service |
| `requirements-local.txt` | torch | only for an offline demo with no key, or to re-run the study |
| `requirements-ocr.txt` | paddleocr / easyocr / pytesseract | only for OCR with no cloud provider at all |

## The engine ladder

`GET /health` reports which engine will actually answer, in this order:

| Engine | Available when | Real-photo quality | Confidence means |
|---|---|---|---|
| `cloud:gemini` / `cloud:openai` / `cloud:anthropic` | an API key is present | good | model self-report |
| `torch` | the optional checkpoint is installed | **0.258** — see below | calibrated probability |
| `heuristic` | always | poor, deliberately | **capped at 0.45**, below the API's 0.55 floor |

`requiresTraining: false` and `requiresDataset: false` are reported by `/health` and
asserted by the test suite. If no engine is configured, the service says so instead of
pretending — and the heuristic can never clear the API's confidence floor, so a guess is
structurally incapable of being presented as a finding.

## Why the cloud provider is the default

The committed local checkpoint is trained on **procedurally generated images**.
Measured performance:

| Split | Accuracy | Macro-F1 |
|---|---|---|
| In-domain (renders, held-out) | **0.969** | 0.967 |
| Cross-domain (31 real product photos) | **0.258** | — |
| **Domain gap** | **0.711** | |

The model is not merely less accurate on real photos — it is **confidently wrong**: it
labelled a real spark plug *"air filter"* at 0.99 confidence.

This is the single most important result in the project, and it validates the product's
design rule rather than undermining it: *AI suggests; catalogue and seller data verify.*
Three things follow, all implemented:

1. **The confidence floor.** `MIN_CONFIDENCE=0.55` in the Node API. A prediction below
   it is reported as uncertain and the user is asked for a part number or vehicle.
2. **Fitment is never inferred from an image.** Only a catalogue match asserts it. This
   holds for Gemini exactly as it holds for the local model.
3. **No cheap escape from the domain gap.** We tested whether a feature-space distance
   test could flag real photos as out-of-distribution:

   | Detector | Real photos flagged |
   |---|---|
   | Diagonal z-score distance | **0%** |
   | Mahalanobis distance | **35%** |

   So `app/ood.py` exists as an *advisory* only, and its own response payload says so.
   You cannot buy your way out of a domain gap with a novelty detector — you fix it
   with real labelled data, or you use a model that has already seen real data at scale.
   We do the latter.

## What the provider does and does not fix

**Fixes:** real-photo identification, label OCR (angled, glared and embossed text that
classical OCR engines struggle with), and text-description ingestion. One provider, three
capabilities, no system packages to install.

**Does not fix — and this is the point:** a vision model, however good, still returns a
**category**. It cannot tell you a part fits a 2019 Swift. Fitment still requires a
part-number match or a vehicle-catalogue match in the Express API. The safety
architecture is identical on both paths.

Further caveats that are enforced in code:

| | |
|---|---|
| **Confidence semantics change** | The local model's confidence is a temperature-calibrated softmax. A provider's is a self-report, so responses set `confidenceSource: "model_self_report"` and the API warns it is a coarse hint, not a probability. |
| **A read part number is evidence, not truth** | A number read off a photo arrives in the API as `visiblePartNumber` with a `part_number_read_from_photo` warning and a lower provenance rank than a number the user typed. If it matches nothing in the catalogue, the pipeline returns `needs_vehicle_info` — it never upgrades to `confirmed`. |
| **Privacy** | Every upload leaves the device for a third party. For a deployment handling customer photographs that is a disclosure you owe your users. |
| **Connectivity and cost** | Needs internet; roughly USD 0.001–0.01 per image. |

Any provider failure — no key, a 400, a 503, a timeout, an unparseable reply — falls
back down the ladder and logs why. `/predict` never fails because a provider did. That
path is tested: two suites, 91 checks, cover reply parsing, taxonomy validation, key
resolution, retry behaviour, the exact wire format, and every failure path.

## Tests

```bash
python tests/test_cloud_vision.py           # 44 checks: parsing, keys, taxonomy, failures
python tests/test_gemini_integration.py     # 47 checks: real Gemini wire format, via a local mock
```

The integration suite starts its own HTTP server that speaks the Gemini wire format and
points `VISION_BASE_URL` at it, so it verifies the request URL, the request body
(including that base64 image data round-trips), the response parsing, retry-on-503 and
no-retry-on-400 behaviour — without a key, a network, or a quota.

## Optional: the offline fallback model

```bash
pip install -r requirements-local.txt

# rebuild the dataset and the checkpoint from scratch, if you want to reproduce the study
python -m app.download_images --synthetic --per-class 60 --out ../data/images
python train/train.py --data data/images --epochs 80
python train/evaluate.py --model models/part_classifier.pt --data data/images
```

Install this only if you need an offline demo, or you are re-running the ablation study
in `docs/DATASET-AND-MODEL.md`. It is a fallback, not an answer.

### Why hand-crafted features instead of a CNN

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
  main.py             FastAPI app: /predict, /ocr, /describe, /health, /classes
  cloud_vision.py     Gemini / OpenAI / Anthropic clients (stdlib urllib), retries, parsing
  features.py         22-D hand-crafted extractor
  model.py            MLP classifier + temperature calibration
  ood.py              domain-shift advisory (with its own measured limitations)
  taxonomy.py         class order — must match backend/src/taxonomy.js
  download_images.py  dataset builder (Openverse, or --synthetic)
train/
  train.py            leak-aware split, training, calibration, checkpoint
  evaluate.py         in-domain + cross-domain evaluation
models/               committed checkpoint (< 100 KB, optional)
reports/              metrics.json, training-history.json, cross-domain.json
```

## Alignment guarantees

`app/taxonomy.py:CLASS_KEYS` order is the model's class order and must match
`backend/src/taxonomy.js:CATEGORIES` and `data/parts.json`. `GET /classes` exists so a
test can assert that the three agree rather than letting them drift. The cloud path
validates the provider's returned category against that same taxonomy and rejects
anything outside it, so a model that invents a plausible-sounding category cannot
introduce a phantom class into the catalogue.
