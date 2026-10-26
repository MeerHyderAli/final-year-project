# Architecture

## The one rule everything follows

> **AI suggests; catalogue and seller data verify.**

This is not a slogan — it is enforced in code at three separate layers.

| Layer | Enforcement |
|---|---|
| Identification service | Returns a **category** and a confidence. It has no access to fitment data, so it is structurally incapable of asserting compatibility. This holds identically for the cloud provider and for the optional local model. |
| Express API | Fitment verdicts come only from `fitmentService.checkFitment()`, whose inputs are a part number or a vehicle-catalogue record. A prediction below the confidence floor is downgraded to `ask_for_more_info`. |
| Web app | Renders the verdict with its evidence attached. There is no code path that displays "fits" without a supporting evidence list. |

## Services

```
 ┌──────────────┐  same-origin   ┌──────────────────┐   HTTP   ┌──────────────────────┐
 │  React app   │  /api/*  ────▶ │  Express API     │ ───────▶ │  FastAPI identify    │
 │  Vite :5173  │  (proxied)     │  Node :4000      │          │  Python :8000        │
 └──────────────┘                └────────┬─────────┘          └──────────┬───────────┘
                                          │                               │ engine ladder
                                          │                               ▼
                                          │                    ┌──────────────────────┐
                                          │                    │ Gemini / OpenAI /    │
                                          │                    │ Anthropic            │
                                          │                    │ (photo · label OCR · │
                                          │                    │  description)        │
                                          │                    └──────────────────────┘
                                          ▼                     or the optional local
                                 ┌──────────────────┐           checkpoint / heuristic
                                 │  Catalogue store │           when no key is present
                                 │  parts/vehicles/ │
                                 │  vendors/offers  │   JSON now → MongoDB later
                                 └──────────────────┘
```

Three processes, two languages. The split is not fashion: a third-party HTTP client and
a JSON parser do not belong in the catalogue API's process, and a provider that hangs or
returns nonsense must not take the price engine down with it. The identification service
is also the only component that ever needs an API key, so credential handling is confined
to one small, auditable file (`app/cloud_vision.py`) that uses the standard library
only.

## Request flow — `POST /api/fitment/analyse`

The single endpoint the product is built around. Each stage is independently
addressable, so a partial answer is still useful.

1. **Identify.** Accepts either a raw `prediction` (from `/api/identify`) or a
   `partId` / `partNumber`. If a prediction arrives, its confidence is compared with
   `MIN_CONFIDENCE` (0.55) and a low score raises a `low_confidence` warning.
2. **Fitment.** `checkFitment()` produces a verdict on this ladder:

   | Verdict | Asserted when |
   |---|---|
   | `confirmed` | part number matched a catalogue record **and** the vehicle is listed compatible |
   | `compatible` | vehicle matched the catalogue fitment list (non-safety-critical) |
   | `needs_part_number` | vehicle matched, but the part is safety-critical — a human must check the stamped number |
   | `needs_vehicle_info` | category known, nothing to verify fitment against |
   | `unknown_part_number` | a part number was supplied but is absent from the catalogue |
   | `incompatible` | vehicle supplied and provably not in the fitment list |

   Every verdict ships with an `evidence[]` array, and `requiresHumanCheck` is set for
   anything below `compatible`.
3. **Price.** `quoteForPart()` ranks offers by a usefulness score (source trust 45%,
   stock confidence 35%, recency 20%) and reports the lowest price, the
   best-evidenced price, and the best *value* separately — because they are usually
   different shops.
4. **Nearby.** `nearbyVendors()` scores each vendor as
   `distance + stockPenalty + trustAdjustment + listingPenalty`.
   One score point ≈ 1 km, so a shop 3 km away with unconfirmed stock ranks below a
   shop 5 km away with a confirmed listing. Distance alone is the wrong answer.

## Why these specific decisions

**JSON demo, MongoDB source of truth.** With no `MONGODB_URI`, `store/index.js`
reads the illustrative `data/*.json` fixtures and labels the mode `json-demo`. With a
URI, it reads MongoDB instead; the database is not a mirror and startup fails if it is
unavailable. `backend/scripts/import-catalogue.js` validates and upserts real supplier
or seller records. This keeps the zero-infrastructure demo while providing a persistent
deployment path — see `docs/DEPLOYMENT.md`.

**Fail loudly, never invent.** When the identification service is unreachable
`/api/identify` returns **503** with a `fallback` object naming the deterministic route
the UI should offer. When a part has no offers, `/api/price/compare` says so instead of
estimating. Both are tested behaviours, not aspirations.

**An engine ladder, not a dependency.** `/predict`, `/ocr` and `/describe` each try the
configured cloud provider first, then the optional local checkpoint, then a heuristic
whose confidence is hard-capped at 0.45 — structurally below the API's 0.55 floor, so a
guess can never be presented as a finding. `/health` reports which rung is live, and
`requiresTraining: false` / `requiresDataset: false` are asserted by the test suite. No
configuration is a failure state: "no provider configured" is a state the UI renders
honestly rather than a crash.

**Provenance on every input.** A part number a user typed, a part number the model read
off a photo, and a part number inferred from a category suggestion are three different
strengths of evidence. The pipeline labels which one it used (`resolution.path`) and warns
on the weaker ones, which is why a number read from a photo that matches nothing in the
catalogue returns `needs_vehicle_info` — never `confirmed`.

**Vite proxy, not CORS to localhost.** The browser calls same-origin `/api/*` and Vite
forwards to the API. This is required for hosted preview environments (where the
browser is not the machine running the server) and it removes CORS from the picture.

**Structured uncertainty.** The API models *six* fitment outcomes rather than a
boolean, because "we cannot tell" and "no" are different answers and conflating them
is how people buy the wrong brake pad.

## Layering rules

- `routes/` handle HTTP only — parse, validate, delegate, shape the response.
- `services/` hold the domain logic and are pure enough to unit-test without a server.
- `store/` is the only module that reads catalogue data, whether JSON or MongoDB.
- `taxonomy.js` / `taxonomy.py` must agree; `GET /api/catalog/meta` and
  `GET /classes` exist so a test can assert that they do, rather than letting the
  three copies drift.

## Known limits

- **No distributed transactions or admin writes.** The HTTP API is read-only; the
  separate CLI importer writes validated records. Authentication, scheduled refreshes
  and conflict resolution remain deployment work.
- **Provider confidence is a self-report.** The cloud model's confidence is not a
  calibrated probability, so responses tag it `confidenceSource: "model_self_report"` and
  the API warns that it is a coarse hint. Only the optional local model is calibrated.
- **Offline fallback domain gap.** The local checkpoint scores 0.969 in-domain and 0.258
  on real photographs. It is no longer the default path; it exists so an offline demo is
  possible. Quantified in `docs/DATASET-AND-MODEL.md`.
- **Out-of-distribution detection is weak.** Measured at ~35% recall on real photos
  (0% for a diagonal distance). It is surfaced as an advisory and labelled as such.
- **Vendor data is static.** No scheduler refreshes offers; `updatedAt` is honest
  about that, and stale quotes (>30 days) are labelled instead of hidden.
