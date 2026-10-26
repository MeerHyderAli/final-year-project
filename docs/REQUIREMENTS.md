# Requirements — what you need to build and run this

Everything below is what the project actually uses. The **Minimum** column is what it
takes to get the three services running locally; **Recommended** is what you want for
the final demonstration and report.

## 1. Software you must install

| Component | Minimum | Recommended | Why |
|---|---|---|---|
| Node.js | 20 LTS | 22 LTS | Express API + React build tooling |
| npm | 10 | 10+ | ships with Node |
| Python | 3.10 | 3.11 | FastAPI identification service |
| pip / venv | any | any | dependency isolation |
| Git | 2.30 | 2.40+ | version control |
| Browser | any modern | Chrome/Edge | camera capture for the upload step |

Optional but useful: MongoDB 6+ (only if you want the API to serve from a database
rather than the JSON catalogue — see §4), Docker (to containerise), and a code editor.

**Hardware.** Any laptop. **No GPU is required and none is used** — there is no
training step in the project. Verified end to end on 2 vCPU / 4 GB RAM; identification
is a network round trip to the provider (sub-second), and the price/fitment engine runs
in milliseconds.

## 2. Language and framework choices

| Layer | Choice | Why this, not the alternative |
|---|---|---|
| Web app | **React 18 + TypeScript + Vite** | Vite's dev proxy keeps every request same-origin, so the app works behind any preview domain. TS matters here because the fitment verdict has six states and a typo in one string would silently mis-report compatibility. |
| API | **Node.js + Express** | The deck specifies it; it is also the right shape for this workload — I/O-bound catalogue lookups, no CPU-heavy work. |
| Identification | **Python + FastAPI** | FastAPI generates its OpenAPI schema from the same type hints the code already has. Kept as a *separate process* so a provider outage cannot take the catalogue API down. |
| AI | **Gemini API** (Google AI Studio), with OpenAI and Anthropic implemented as drop-in alternatives | No training, no image dataset, no GPU, and it reads real photographs properly. The provider is reached with the standard library (`urllib`) — no vendor SDK, so the dependency list stays honest. See §5. |
| Offline fallback | **NumPy + Pillow + PyTorch** (optional, *not installed by default*) | Keeps a no-internet demo possible. Its measured accuracy on real photographs is 0.258, which is exactly why it is not the default — see `docs/DATASET-AND-MODEL.md`. |
| Data store | **JSON demo → MongoDB source of truth** | Start with zero infrastructure; configure MongoDB for persistence and import validated supplier/seller records. A configured database is never silently replaced by demo JSON. See `docs/DEPLOYMENT.md`. |
| Local OCR (optional) | **PaddleOCR → EasyOCR → Tesseract** | Only for a fully offline deployment. Tried in that order; each is optional and `/ocr` returns 503 with install instructions if none is present. Never invents text. |
| Maps / location | **Haversine + your own vendor records** | A Maps API tells you a shop exists, not that it stocks a specific part number. Ranking uses distance *plus* stock evidence *plus* vendor trust. |

## 3. Python packages

```
numpy, pillow, fastapi, uvicorn[standard], python-multipart
```

`ai-service/requirements.txt` is exactly that list — no torch. Two optional extras are
kept separate and documented in the file headers themselves:

```
ai-service/requirements-local.txt    # torch — the offline fallback model + the study
ai-service/requirements-ocr.txt      # paddleocr | easyocr | pytesseract — offline OCR
```

Install an optional extra only if you need that particular capability; the service runs
without either, and `GET /health` reports which engine is therefore answering.

## 4. Data you must supply

| Data | Where | Status in this repo |
|---|---|---|
| Part catalogue (name, number, brand, specs) | `data/parts.json` | ✅ 18 illustrative records across 8 categories; replace/import verified data for deployment |
| Vehicle master (make, model, years, engine) | `data/vehicles.json` | ✅ 12 records, 5 vehicle classes |
| Sellers / vendors | `data/vendors.json` | ✅ 8 vendors with coordinates and hours |
| Seller price offers | `data/offers.json` | ✅ 43 offers with source + timestamp + stock status |
| API key for the AI provider | environment variable | ⚠️ **you must supply this** — see §5 |
| Labelled part images | — | ❌ **not needed any more.** The AI provider handles real photographs; there is no dataset to collect or curate |
| Real photographs for a local model | — | ❌ only if you choose to re-run the optional study in `docs/DATASET-AND-MODEL.md` |

**This is the honest bottleneck.** The AI is the easy half. Reliable price and
availability data is the hard half, exactly as the deck says. For a real deployment
you need either supplier feeds, shop-submitted listings, or manual field verification —
and every one of those needs a named source and a timestamp, which is why
`data/offers.json` has `sourceType`, `sourceName` and `updatedAt` on every row.

## 5. Accounts, keys and network access

**One thing only: a free Google AI Studio API key.**

```bash
export VISION_PROVIDER=gemini
export VISION_API_KEY=your-key     # https://aistudio.google.com/apikey
bash scripts/check-gemini.sh       # lists models and makes one real request: exit 0/1/2
```

That is the entire requirement. `VISION_PROVIDER` also accepts `openai` or `anthropic`
if you prefer; the provider-native environment variables (`GEMINI_API_KEY`,
`GOOGLE_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) are picked up automatically, so
an existing key needs no renaming.

Free-tier quotas are generous enough for a demonstration and a report. Cost, if you
exceed them, is roughly USD 0.001–0.01 per image.

**Optional, for extensions:** a Maps API key (shop discovery), supplier FTP/API
credentials (price feeds), cloud storage (image uploads). None are required, and each is
designed to degrade gracefully: the app is fully usable with the identification service
down, and `/api/health` reports reachability rather than failing.

**No key at all is also a supported state.** The service starts, the UI shows
"no AI provider configured", and the part-number and vehicle-fitment paths — the
safety-critical ones — work exactly as they do with a key.

## 6. Build and run

```bash
# 0. once
bash scripts/dev.sh --setup        # npm deps (backend, frontend) + pip deps
export VISION_API_KEY=your-key     # optional, from https://aistudio.google.com/apikey

# 1. everything, one command
bash scripts/dev.sh                # identification :8000 · API :4000 · web app :5173
```

Or the three services by hand:

```bash
cd ai-service && uvicorn app.main:app --host 0.0.0.0 --port 8000
cd backend    && npm install && npm start
cd frontend   && npm install && npm run dev
```

There is no dataset-building step and no training step. The web app is fully usable with
**only** the API and web app running: the identification service being down produces a
clear 503 and the UI routes the user to the part-number path.

## 7. Definition of done — acceptance checklist

Use this as the demo script. Every line is a behaviour you can show.

**Data layer**
- [ ] `GET /api/health` reports collection counts and AI-service reachability.
- [ ] Every offer carries a source name, a timestamp and a stock status.

**Identification**
- [ ] A photo returns a ranked category list with confidences, and nothing is claimed about fitment.
- [ ] A part number printed on the part is read off the photo and offered as a candidate.
- [ ] A low-confidence result is reported as `ask_for_more_info`, not as an answer.
- [ ] With no API key, the UI says *no AI provider configured* — it does not pretend to identify.
- [ ] With the identification service stopped, `/api/identify` returns 503 and the UI offers the part-number path instead of guessing.

**Fitment — the safety core**
- [ ] Exact part number + matching vehicle → `confirmed`.
- [ ] Correct vehicle, no part number, **brake pad** → `needs_part_number` with a human-check notice. *(Image similarity is never enough for a safety-critical part.)*
- [ ] A part number read from a photo is marked as such, and an unmatched one returns `needs_vehicle_info` rather than `confirmed`.
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
- [ ] `/api/health` and `/health` state plainly that no training and no dataset are required.
- [ ] The cloud provider's confidence is labelled a self-report, not a probability.
- [ ] The optional local model's cross-domain number (0.258) is reported wherever that
      engine's results are shown, and the UI shows the warning rather than hiding it.
- [ ] The reported accuracy of any model states which dataset it came from.

## 8. What is deliberately out of scope for the prototype

User accounts and authentication · payments or ordering · real-time inventory sync ·
mobile apps · multi-language UI · image storage and a retraining loop · a Maps API
integration (Haversine over your own vendor table is enough to demonstrate ranking).

These are the natural "future work" section of the report, and each one is a
data/operational problem rather than a modelling problem — which is the correct
conclusion to draw from this project.
