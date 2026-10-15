# AutoParts AI

**Intelligent spare-part identification and price finder.**
From a photo to the right part, a fair price, and a nearby seller.

> Final-year engineering project · Data Science department
> AI-powered recognition · Price comparison · Nearby vendors

---

## The design principle

> ### AI suggests; catalogue and seller data verify.

An image can tell you a part *looks like* an oil filter. It cannot tell you the part
**fits your vehicle**. That distinction is enforced in code at three layers, and the
project's own measurements are what justify it — see [Honest results](#honest-results).

## What it does

1. **Upload** — take or upload a photo of the part, *or* type the stamped part number.
2. **Identify** — the vision model predicts a category and a confidence.
3. **Verify fit** — vehicle details or a part number produce one of six explicit verdicts.
4. **Compare** — vendor quotes, each with its source, timestamp and stock status.
5. **Locate** — sellers ranked by distance **and** stock evidence, not distance alone.

Supported vehicle classes: cars, SUVs, trucks/buses, tractors, JCB/heavy equipment.
Starting scope: filters, brake pads, belts, spark plugs, clutch and hydraulic parts.

## Honest results

The model scores **0.969** on held-out data from the dataset it was trained on — and
**0.258** on real photographs of real parts.

| Evaluation | Accuracy | Macro-F1 |
|---|---|---|
| In-domain (held-out rendered images) | 0.969 | 0.967 |
| Cross-domain (31 real product photos) | 0.258 | — |
| Domain gap | **0.711** | |

It is not just less accurate out-of-domain — it is **confidently wrong**: 48% of its
wrong answers carried ≥0.80 confidence, with a mean of 0.782 on errors. It called a
real spark plug an *"Air Filter"* at 0.99 confidence.

**We report this because it is the project's most useful finding.** It is the
empirical proof that fitment must never be inferred from image similarity — which is
exactly what the safety architecture already does:

- the vision model outputs a **category** and never sees fitment data;
- predictions below `MIN_CONFIDENCE = 0.55` are answered with *"tell us more"*, not a guess;
- safety-critical parts (brake pads, clutch plates) demand a part number even when the
  catalogue lists a fitment;
- every response carries the domain-gap advisory, and the UI shows it rather than
  hiding it in a tooltip.

We also tested whether a cheap out-of-distribution detector could rescue this. It
could not: a per-feature distance test flagged **0%** of real photos, and a full
Mahalanobis test only **35%**. That negative result is documented in
[`docs/DATASET-AND-MODEL.md`](docs/DATASET-AND-MODEL.md).

## Architecture

```
 React (Vite :5173) ──/api/*──▶ Express API (:4000) ──▶ FastAPI vision (:8000)
                                        │
                                        ▼
                              JSON catalogue → MongoDB
```

Three processes, two languages — the model is isolated so it cannot take the price
engine down with it. Full reasoning in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Repository layout

```
data/                    seed catalogue (JSON)
  parts.json             16 parts across 8 categories
  vehicles.json          12 vehicles across 5 classes
  vendors.json           8 sellers with coordinates and hours
  offers.json            43 price offers with source + timestamp + stock status
  images/                generated dataset (git-ignored, reproducible)

backend/                 Express API
  src/routes/            catalog · identify · ocr · fitment · price · nearby
  src/services/          fitmentService · priceService · nearbyService · geo · aiClient
  src/store/             JSON store with optional MongoDB mirror
  src/taxonomy.js        canonical category list

ai-service/              Python vision service
  app/features.py        22-D hand-crafted feature extractor
  app/model.py           MLP + temperature calibration
  app/ood.py             domain-shift advisory (with its measured limits)
  app/download_images.py dataset builder (Openverse, or --synthetic)
  train/train.py         leak-aware split, training, checkpoint
  train/evaluate.py      in-domain + cross-domain evaluation
  models/                committed checkpoint (65 KB)
  reports/               metrics.json · cross-domain.json

frontend/                React 18 + TypeScript + Vite
  src/components/        PhotoUpload · IdentifyPanel · FitmentPanel · PriceTable · NearbyList
  src/lib/               api client · types · formatting

docs/                    REQUIREMENTS · ARCHITECTURE · DATASET-AND-MODEL · DATA-CONTRACT
```

## Quick start

```bash
# ---- 0. dataset and model (once, ~10 seconds on a laptop CPU) ----
cd ai-service
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m app.download_images --synthetic --per-class 60 --out ../data/images
python train/train.py --data data/images --epochs 80

# ---- 1. vision service  ->  http://localhost:8000/docs ----
uvicorn app.main:app --host 0.0.0.0 --port 8000

# ---- 2. API  ->  http://localhost:4000/api ----
cd ../backend && npm install && npm start

# ---- 3. web app  ->  http://localhost:5173 ----
cd ../frontend && npm install && npm run dev
```

The web app works with **only** steps 2 and 3: if the vision service is down, uploads
return a clear 503 and the UI routes the user to the part-number path.

## API

Self-documenting at `GET /api`. The important ones:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/fitment/analyse` | Full pipeline: identify → fitment → price → nearby |
| `POST` | `/api/identify` | Image → category prediction + catalogue candidates |
| `POST` | `/api/ocr` | Label photo or raw text → part-number candidates → catalogue match |
| `GET` | `/api/price/compare?partId=` | Quotes, stats, same-category alternatives |
| `GET` | `/api/nearby?lat=&lng=&partId=` | Distance + evidence weighted vendor ranking |
| `GET` | `/api/catalog/parts/lookup?partNumber=` | Exact identifier match |
| `GET` | `/api/health` | Liveness, AI reachability, and the system's guarantees |

```bash
curl -X POST localhost:4000/api/fitment/analyse -H 'Content-Type: application/json' \
  -d '{"partNumber":"16510-61A31","vehicleId":"veh-maruti-swift-2018-k12m","lat":12.9716,"lng":77.5946}'
```

## Fitment verdicts

| Verdict | Asserted when |
|---|---|
| `confirmed` | part number matched a catalogue record **and** the vehicle is listed compatible |
| `compatible` | vehicle matched the catalogue fitment list (non-safety-critical) |
| `needs_part_number` | vehicle matched, but the part is safety-critical — a human must check |
| `needs_vehicle_info` | category known, nothing to verify fitment against |
| `unknown_part_number` | a part number was supplied but is absent from the catalogue |
| `incompatible` | vehicle supplied and provably not in the fitment list |

Every verdict ships with its `evidence[]`, and `requiresHumanCheck` is set for anything
below `compatible`. Verified behaviours:

```bash
# brake pad + correct vehicle -> needs_part_number (NOT a plain "compatible")
curl -s -X POST localhost:4000/api/fitment/analyse -H 'Content-Type: application/json' \
  -d '{"partId":"part-brake-pad-swift-08","vehicleId":"veh-maruti-swift-2018-k12m"}'

# Swift oil filter checked against a JCB -> incompatible, lists what it does fit
curl -s -X POST localhost:4000/api/fitment/analyse -H 'Content-Type: application/json' \
  -d '{"partId":"part-oil-filter-swift-01","vehicleId":"veh-jcb-3dx-2012"}'
```

## Configuration

| Variable | Default | Effect |
|---|---|---|
| `PORT` | `4000` | API port |
| `AI_SERVICE_URL` | `http://127.0.0.1:8000` | Vision service address |
| `MIN_CONFIDENCE` | `0.55` | Below this, the API asks for more information |
| `MONGODB_URI` | *(unset)* | Set to mirror the catalogue into MongoDB |
| `AI_TIMEOUT_MS` | `20000` | Vision service timeout |
| `UPLOAD_MAX_BYTES` | `8388608` | Upload limit (8 MB) |

## Status

**Working:** full three-service pipeline · six-state fitment engine with evidence trails ·
price engine with provenance and freshness · evidence-weighted nearby ranking ·
OCR ingestion with glyph-confusion resolution · React UI with the audit trail surfaced.

**Not built (deliberately out of scope):** accounts, ordering/payments, live inventory
sync, mobile apps, a retraining loop. See
[`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) §8.

**Known limits:** the model's domain gap (§[Honest results](#honest-results)); OOD
detection catches only ~35% of real-photo inputs; vendor data is static and not
refreshed by a scheduler; vendor identities in the seed data are illustrative
placeholders.

## Licence and third-party data

Project code: academic use. Seed catalogue data and generated images are original to
this repository. Real product photographs used for cross-domain evaluation are
third-party works and are **git-ignored** — see `docs/DATASET-AND-MODEL.md`.
