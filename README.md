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

1. **Upload** — take or upload a photo of the part, *or* type the stamped part number,
   *or* just describe it in words.
2. **Identify** — a vision model reads the photo (or the description) and returns a
   category, plus any part number and brand it can see printed on the part.
3. **Verify fit** — vehicle details or a part number produce one of six explicit verdicts.
4. **Compare** — vendor quotes, each with its source, timestamp and stock status.
5. **Locate** — sellers ranked by distance **and** stock evidence, not distance alone.

Supported vehicle classes: cars, SUVs, trucks/buses, tractors, JCB/heavy equipment.
Starting scope: filters, brake pads, belts, spark plugs, clutch and hydraulic parts.

## How the AI works — no training, no dataset

Identification runs on the **Gemini API** (Google AI Studio). There is no model to
train, no image dataset to collect, and no GPU involved. The AI service is a thin,
auditable wrapper around three questions:

| Endpoint | Question asked | Answer used for |
|---|---|---|
| `POST /predict` | "Which category is this part, and what number/brand is printed on it?" | Category suggestion + a candidate part number |
| `POST /ocr` | "Read all text in this photo." | Part-number candidates from a label photo |
| `POST /describe` | "Which category does this description describe?" | A category when the user has no photo |

**The only thing you need to supply is a free API key:**

```bash
export VISION_PROVIDER=gemini
export VISION_API_KEY=your-key      # free at https://aistudio.google.com/apikey
bash scripts/check-gemini.sh        # verifies the key and makes one real request
```

`VISION_PROVIDER` also accepts `openai` or `anthropic`; all three are implemented in
`ai-service/app/cloud_vision.py` using only the standard library. And without any key
the service still starts — it falls back to the optional local checkpoint, or to a
clearly-labelled heuristic answer that is capped below the API's confidence floor so a
guess can never be presented as a finding.

**An API key is not a shortcut around the safety rule.** The vision model returns a
*category*. Whether a part fits a 2019 Swift still comes from a part-number or
vehicle-catalogue match in the Express API. The AI never sees fitment data.

## Architecture

```
 React (Vite :5173) ──/api/*──▶ Express API (:4000) ──▶ FastAPI identify (:8000)
                                        │                        │
                                        │                        ▼
                                        │              Gemini / OpenAI / Anthropic
                                        │              (photo · label OCR · description)
                                        ▼
                              JSON catalogue → MongoDB
```

Three processes, two languages — the AI provider is isolated behind the Python service
so a provider outage cannot take the price engine down with it. Full reasoning in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Repository layout

```
data/                    seed catalogue (JSON)
  parts.json             16 parts across 8 categories
  vehicles.json          12 vehicles across 5 classes
  vendors.json           8 sellers with coordinates and hours
  offers.json            43 price offers with source + timestamp + stock status

backend/                 Express API
  src/routes/            catalog · identify · ocr · describe · fitment · price · nearby
  src/services/          fitmentService · priceService · nearbyService · geo · aiClient
  src/store/             JSON store with optional MongoDB mirror
  src/taxonomy.js        canonical category list

ai-service/              Python identification service
  app/cloud_vision.py    Gemini / OpenAI / Anthropic, stdlib urllib only
  app/main.py            engine ladder + /predict /ocr /describe /health /classes
  app/features.py        22-D feature extractor    ┐ optional offline fallback,
  app/model.py           MLP + calibration         │ see requirements-local.txt
  train/, models/, reports/  training pipeline + committed checkpoint and metrics
  tests/                 test_cloud_vision.py · test_gemini_integration.py

frontend/                React 18 + TypeScript + Vite
  src/components/        PhotoUpload · IdentifyPanel · DescribeInput · FitmentPanel
                         PriceTable · NearbyList · ProviderStatus

docs/                    REQUIREMENTS · ARCHITECTURE · DATASET-AND-MODEL · DATA-CONTRACT
```

## Quick start

```bash
# ---- 0. one-time setup (no training, no dataset) ----
bash scripts/dev.sh --setup      # npm deps for backend+frontend, pip deps for ai-service

# ---- 1. add an AI key (optional but recommended) ----
export VISION_API_KEY=your-key   # free: https://aistudio.google.com/apikey
bash scripts/check-gemini.sh     # confirms it works before you demo

# ---- 2. run everything ----
bash scripts/dev.sh              # identification :8000 · API :4000 · web app :5173
```

Open <http://localhost:5173>. `scripts/dev.sh` prints which engine will answer, waits
until all three services are up, and logs to `.logs/`.

**Windows / Git Bash:** the scripts auto-detect `python3`, `python`, and the `py`
launcher. If your installation is not on `PATH`, use `PYTHON=python bash scripts/dev.sh`
(or set `PYTHON` to the interpreter's full path). The same override works with
`scripts/check-gemini.sh` and `scripts/test.sh`. You do not need to install a second
copy of Python just because Windows does not provide a `python3` command.

If the key check lists models successfully but the identification call times out,
the key is working and the generation request is the part needing attention. Try the
current flash model with a longer read timeout:

```bash
VISION_MODEL=gemini-2.5-flash VISION_TIMEOUT=60 bash scripts/check-gemini.sh
```

Use the same two variables when starting `scripts/dev.sh`. A timeout is reported as a
provider error and triggers the documented fallback; it is never turned into a fake
identification.

Running the services by hand instead:

```bash
cd ai-service && uvicorn app.main:app --host 0.0.0.0 --port 8000   # identification
cd backend    && npm install && npm start                          # API       :4000
cd frontend   && npm install && npm run dev                        # web app   :5173
```

The web app works with **only** the API and web app running: if the identification
service is down, uploads return a clear 503 and the UI routes the user to the
part-number path instead of guessing.

## API

Self-documenting at `GET /api`. The important ones:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/fitment/analyse` | Full pipeline: identify → fitment → price → nearby |
| `POST` | `/api/identify` | Image → category suggestion + part number read from the photo + catalogue matches |
| `POST` | `/api/ocr` | Label photo or raw text → part-number candidates → catalogue match |
| `POST` | `/api/describe` | Text description → category suggestion (weaker evidence than a photo) |
| `GET` | `/api/identify/health` | Is the identification service reachable, and which engine is answering? |
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

Every verdict ships with its `evidence[]`, a `resolution` block naming *which* input
the answer came from, and `requiresHumanCheck` set for anything below `compatible`.
A part number read from a photo is treated as weaker than one the user typed, and says so.

Verified behaviours:

```bash
# brake pad + correct vehicle -> needs_part_number (NOT a plain "compatible")
curl -s -X POST localhost:4000/api/fitment/analyse -H 'Content-Type: application/json' \
  -d '{"partId":"part-brake-pad-swift-08","vehicleId":"veh-maruti-swift-2018-k12m"}'

# Swift oil filter checked against a JCB -> incompatible, lists what it does fit
curl -s -X POST localhost:4000/api/fitment/analyse -H 'Content-Type: application/json' \
  -d '{"partId":"part-oil-filter-swift-01","vehicleId":"veh-jcb-3dx-2012"}'

# a part number the model read off a photo is not trusted blindly
curl -s -X POST localhost:4000/api/fitment/analyse -H 'Content-Type: application/json' \
  -d '{"visiblePartNumber":"XX-9999-ZZ","category":"oil_filter"}'
#   -> needs_vehicle_info + warning part_number_not_matched (never "confirmed")
```

## Honest results

The optional local checkpoint scores **0.969** on held-out images from the dataset it
was trained on — and **0.258** on real photographs of real parts.

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
exactly what the safety architecture does:

- the vision model outputs a **category** and never sees fitment data;
- predictions below `MIN_CONFIDENCE = 0.55` are answered with *"tell us more"*, not a guess;
- safety-critical parts (brake pads, clutch plates) demand a part number even when the
  catalogue lists a fitment;
- the same rule applies to a frontier model: a category from Gemini is still only a
  category. Nothing downstream treats it as more than that.

It is also why the recommended configuration is the API rather than this model: for
real photographs, a model that has seen millions of them beats one trained on 480
renders. Our own negative results say so, so we act on them. See
[`docs/DATASET-AND-MODEL.md`](docs/DATASET-AND-MODEL.md) for the full study, including
why a cheap out-of-distribution detector could not rescue the local model (0% and 35%
of real photos flagged by two different methods).

## Running the checks

```bash
python ai-service/tests/test_cloud_vision.py      # 44 unit checks, no services needed
python ai-service/tests/test_gemini_integration.py # 47 checks incl. the wire format, via a local mock
bash scripts/check-gemini.sh                      # is your real key working?
bash scripts/verify.sh                            # 26 integration checks, needs services up
bash scripts/test.sh                              # both suites
```

## Configuration

| Variable | Default | Effect |
|---|---|---|
| `PORT` | `4000` | API port |
| `AI_SERVICE_URL` | `http://127.0.0.1:8000` | Identification service address |
| `MIN_CONFIDENCE` | `0.55` | Below this, the API asks for more information |
| `VISION_PROVIDER` | `gemini` | `gemini` \| `openai` \| `anthropic` \| `local` |
| `VISION_API_KEY` | *(unset)* | Provider key; provider-native names also work |
| `VISION_MODEL` | provider default | Model id override |
| `MONGODB_URI` | *(unset)* | Set to mirror the catalogue into MongoDB |
| `AI_TIMEOUT_MS` | `20000` | Identification service timeout |
| `UPLOAD_MAX_BYTES` | `8388608` | Upload limit (8 MB) |

Every setting is documented in [`.env.example`](.env.example).

## Status

**Working:** full three-service pipeline · photo, label-text and description ingestion ·
six-state fitment engine with evidence trails and provenance · price engine with
freshness rules · evidence-weighted nearby ranking · React UI that surfaces the audit
trail and the provider state.

**Not built (deliberately out of scope):** accounts, ordering/payments, live inventory
sync, mobile apps, a retraining loop. See
[`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) §8.

**Known limits:** vendor data is static and not refreshed by a scheduler; vendor
identities in the seed data are illustrative placeholders; the cloud provider's
"confidence" is a self-report rather than a calibrated probability, and the API labels
it as such; the offline fallback's domain gap is documented above and shown in the UI
whenever that engine answers.

## Licence and third-party data

Project code: academic use. Seed catalogue data and generated images are original to
this repository. Real product photographs used for the cross-domain evaluation are
third-party works and are **git-ignored** — see `docs/DATASET-AND-MODEL.md`.
