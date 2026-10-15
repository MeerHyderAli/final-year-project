# Requirements — what you need to build and run this

Everything below is what the project actually uses. The **Minimum** column is what it
takes to get the three services running locally; **Recommended** is what you want for
the final demonstration and report.

## 1. Software you must install

| Component | Minimum | Recommended | Why |
|---|---|---|---|
| Node.js | 20 LTS | 22 LTS | Express API + React build tooling |
| npm | 10 | 10+ | ships with Node |
| Python | 3.10 | 3.11 | FastAPI vision service + training |
| pip / venv | any | any | dependency isolation |
| Git | 2.30 | 2.40+ | version control |
| Browser | any modern | Chrome/Edge | camera capture for the upload step |

Optional but useful: MongoDB 6+ (only if you want the API to serve from a database
rather than the JSON catalogue — see §4), Docker (to containerise), and a code editor.

**Hardware.** CPU-only is fine. Verified end to end on 2 vCPU / 4 GB RAM: training the
committed checkpoint takes **~6 seconds** on 480 images; inference is **~35 ms** per
image. No GPU is required at this dataset size.

## 2. Language and framework choices

| Layer | Choice | Why this, not the alternative |
|---|---|---|
| Web app | **React 18 + TypeScript + Vite** | Vite's dev proxy keeps every request same-origin, so the app works behind any preview domain. TS matters here because the fitment verdict has six states and a typo in one string would silently mis-report compatibility. |
| API | **Node.js + Express** | The deck specifies it; it is also the right shape for this workload — I/O-bound catalogue lookups, no CPU-heavy work (that lives in Python). |
| Vision service | **Python + FastAPI + PyTorch** | PyTorch for training; FastAPI because it generates the OpenAPI schema from the same type hints the code already has. Kept as a *separate process* so a model crash cannot take down the catalogue API. |
| Features | **NumPy + Pillow** (hand-crafted) | At a few hundred images per class a CNN memorises; 22 physical features actually generalise. See `docs/DATASET-AND-MODEL.md`. |
| Data store | **JSON seed → MongoDB** | Start with zero infrastructure (JSON loads in milliseconds), migrate later without a rewrite — the documents are already in Mongo's shape. |
| OCR | **PaddleOCR → EasyOCR → Tesseract** | Tried in that order; each is optional and the endpoint returns 503 with install instructions if none is present. Never invents text. |
| Maps / location | **Haversine + your own vendor records** | A Maps API tells you a shop exists, not that it stocks a specific part number. Ranking uses distance *plus* stock evidence *plus* vendor trust. |

## 3. Python packages

```
numpy, pillow              # features
torch                      # training + inference
fastapi, uvicorn[standard], python-multipart   # service
# optional, pick at most one for OCR:
# paddleocr | easyocr | pytesseract
```
`ai-service/requirements.txt` pins these with notes.

## 4. Data you must supply

| Data | Where | Status in this repo |
|---|---|---|
| Part catalogue (name, number, brand, specs) | `data/parts.json` | ✅ 16 records across 8 categories |
| Vehicle master (make, model, years, engine) | `data/vehicles.json` | ✅ 12 records, 5 vehicle classes |
| Sellers / vendors | `data/vendors.json` | ✅ 8 vendors with coordinates and hours |
| Seller price offers | `data/offers.json` | ✅ 43 offers with source + timestamp + stock status |
| Labelled part images | `data/images/` | ⚠️ **generated**, not committed — one command rebuilds it |
| Real photographs | your own captures | ❌ **you must collect these** — see below |

**This is the honest bottleneck.** The AI is the easy half. Reliable price and
availability data is the hard half, exactly as the deck says. For a real deployment
you need either supplier feeds, shop-submitted listings, or manual field verification —
and every one of those needs a named source and a timestamp, which is why
`data/offers.json` has `sourceType`, `sourceName` and `updatedAt` on every row.

To collect real photographs, either capture them yourself (best: same phone, varied
angle, lighting, dirt and wear), or use the Openverse harvester which records the
licence and creator of every file:

```bash
cd ai-service
python -m app.download_images --per-class 40 --out ../data/images   # real CC images
```

## 5. Accounts, keys and network access

**None are required for the prototype.** That is deliberate — it means the demo works
on an exam laptop with no Wi-Fi.

If you extend it, you will need: a Maps API key (shop discovery), supplier FTP/API
credentials (price feeds), and cloud storage (image uploads). Design the code so each
one degrades gracefully: the app is fully usable with the vision service down, and the
`/api/health` endpoint reports reachability rather than failing.

## 6. Build and run — three terminals

```bash
# 0. dataset + model (once)
cd ai-service
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m app.download_images --synthetic --per-class 60 --out ../data/images
python train/train.py --data data/images --epochs 80          # ~6 s on 2 vCPU

# 1. vision service            -> http://localhost:8000/docs
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 2. API                       -> http://localhost:4000/api
cd backend && npm install && npm start

# 3. web app                   -> http://localhost:5173
cd frontend && npm install && npm run dev
```

The web app is fully usable with **only** steps 2 and 3 running: the vision service
being down produces a clear 503 and the UI routes the user to the part-number path.

## 7. Definition of done — acceptance checklist

Use this as the demo script. Every line is a behaviour you can show.

**Data layer**
- [ ] `GET /api/health` reports collection counts and AI-service reachability.
- [ ] Every offer carries a source name, a timestamp and a stock status.

**Identification**
- [ ] A photo returns a ranked category list with confidences.
- [ ] A low-confidence result is reported as `ask_for_more_info`, not as an answer.
- [ ] With the vision service stopped, `/api/identify` returns 503 and the UI offers the part-number path instead of guessing.

**Fitment — the safety core**
- [ ] Exact part number + matching vehicle → `confirmed`.
- [ ] Correct vehicle, no part number, **brake pad** → `needs_part_number` with a human-check notice. *(Image similarity is never enough for a safety-critical part.)*
- [ ] A Swift oil filter checked against a JCB → `incompatible`, listing what it *does* fit.
- [ ] Unknown part number → `unknown_part_number` with the OCR glyph-confusion hint.
- [ ] Year outside the catalogue range → the out-of-range evidence is shown explicitly.
- [ ] No vehicle supplied → `needs_vehicle_info`. **The API never infers fitment from an image.**

**Price**
- [ ] Each row shows seller, source type, timestamp and availability.
- [ ] "In stock" appears only where the seller confirmed it.
- [ ] A part with no offers says so rather than showing an estimate.
- [ ] The UI separates "cheapest" from "best evidenced" when they differ.

**Nearby**
- [ ] Results are ranked by distance *and* stock evidence, not distance alone.
- [ ] A vendor with no listing is labelled "handles this category, no listing for this exact part number".
- [ ] The Maps-listing caveat is visible in the UI.

**Honesty (this is graded)**
- [ ] The reported accuracy states which dataset it came from.
- [ ] The cross-domain number (0.258 on real photos) is reported alongside the in-domain one.
- [ ] The UI shows the domain-gap warning rather than hiding it behind a tooltip.

## 8. What is deliberately out of scope for the prototype

User accounts and authentication · payments or ordering · real-time inventory sync ·
mobile apps · multi-language UI · image storage and a retraining loop · a Maps API
integration (Haversine over your own vendor table is enough to demonstrate ranking).

These are the natural "future work" section of the report, and each one is a
data/operational problem rather than a modelling problem — which is the correct
conclusion to draw from this project.
