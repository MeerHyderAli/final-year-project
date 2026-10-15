# Architecture

## The one rule everything follows

> **AI suggests; catalogue and seller data verify.**

This is not a slogan — it is enforced in code at three separate layers.

| Layer | Enforcement |
|---|---|
| Vision service | Returns a **category** and a confidence. It has no access to fitment data, so it is structurally incapable of asserting compatibility. |
| Express API | Fitment verdicts come only from `fitmentService.checkFitment()`, whose inputs are a part number or a vehicle-catalogue record. A prediction below the confidence floor is downgraded to `ask_for_more_info`. |
| Web app | Renders the verdict with its evidence attached. There is no code path that displays "fits" without a supporting evidence list. |

## Services

```
 ┌──────────────┐   same-origin    ┌──────────────────┐   HTTP    ┌────────────────────┐
 │  React app   │  /api/*  ───────▶│  Express API     │ ────────▶ │  FastAPI vision    │
 │  Vite :5173  │   (proxied)      │  Node :4000      │           │  Python :8000      │
 └──────────────┘                  └────────┬─────────┘           └────────────────────┘
                                            │                      category + confidence
                                            │                      (+ OOD advisory)
                                            ▼
                                   ┌──────────────────┐
                                   │  Catalogue store │   JSON now → MongoDB later
                                   │  parts/vehicles/ │
                                   │  vendors/offers  │
                                   └──────────────────┘
```

Three processes, two languages. The split is not fashion: PyTorch does not belong in a
Node process, and a model that segfaults must not take the price engine down with it.

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

**JSON store, MongoDB-shaped.** `store/index.js` reads `data/*.json` into memory
(loads in milliseconds) and mirrors into MongoDB when `MONGODB_URI` is set. The
documents are already in Mongo's shape, so the migration is configuration, not a
rewrite. It also means the demo runs with zero infrastructure.

**Fail loudly, never invent.** When the vision service is unreachable `/api/identify`
returns **503** with a `fallback` object naming the deterministic route the UI should
offer. When a part has no offers, `/api/price/compare` says so instead of estimating.
Both are tested behaviours, not aspirations.

**Vite proxy, not CORS to localhost.** The browser calls same-origin `/api/*` and Vite
forwards to the API. This is required for hosted preview environments (where the
browser is not the machine running the server) and it removes CORS from the picture.

**Structured uncertainty.** The API models *six* fitment outcomes rather than a
boolean, because "we cannot tell" and "no" are different answers and conflating them
is how people buy the wrong brake pad.

## Layering rules

- `routes/` handle HTTP only — parse, validate, delegate, shape the response.
- `services/` hold the domain logic and are pure enough to unit-test without a server.
- `store/` is the only module that touches data files.
- `taxonomy.js` / `taxonomy.py` must agree; `GET /api/catalog/meta` and
  `GET /classes` exist so a test can assert that they do, rather than letting the
  three copies drift.

## Known limits

- **No distributed transactions.** Catalogue writes are not implemented in the
  prototype; the API is read-only over the seed data.
- **Domain gap.** The shipped model scores 0.969 in-domain and 0.258 on real
  photographs. That is a training-data problem, not an architecture problem, and the
  architecture is designed to stay safe while it is unsolved. Quantified in
  `docs/DATASET-AND-MODEL.md`.
- **Out-of-distribution detection is weak.** Measured at ~35% recall on real photos
  (0% for a diagonal distance). It is surfaced as an advisory and labelled as such.
- **Vendor data is static.** No scheduler refreshes offers; `updatedAt` is honest
  about that, and stale quotes (>30 days) are labelled instead of hidden.
