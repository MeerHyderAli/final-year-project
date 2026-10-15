# Data contract — price and availability

The deck is right that **reliable data is the hard part, not the AI model**. This
document is the contract that makes that data honest.

## The rule

> Every price and every availability claim must name its source and its age.
> A map listing is not evidence that a shop stocks a part.

## Offer schema (`data/offers.json`)

| Field | Type | Meaning |
|---|---|---|
| `id` | string | stable identifier |
| `partId` | string | → `parts.json` |
| `vendorId` | string | → `vendors.json` |
| `price` | number | in the currency below |
| `mrp` | number | list price, used only to compute a discount |
| `currency` | string | `INR` |
| `condition` | `genuine` \| `aftermarket` | drives the genuine-vs-aftermarket split |
| `stockStatus` | see below | **the availability claim, and how firm it is** |
| `sourceType` | see below | where the number came from |
| `sourceName` | string | the human-readable feed or counter |
| `updatedAt` | ISO-8601 | when the source last confirmed it |
| `warrantyMonths` | number | 0 when unknown |

### `stockStatus` — the important field

| Value | Shown as | Set when |
|---|---|---|
| `confirmed` | "In stock — seller confirmed" | the seller or their inventory system said so |
| `likely` | "Likely available" | the seller indicated it, without a stock count |
| `unconfirmed` | "Availability unconfirmed" | a listing exists but nobody verified it |
| `out_of_stock` | "Out of stock" | the seller reported it unavailable |

Only `confirmed` sets `inStock: true`. **"In stock" is never displayed on the strength
of a map listing.**

### `sourceType` and trust

| Value | Trust weight | Typical origin |
|---|---|---|
| `authorised_catalogue` | 1.00 | manufacturer/dealer B2B catalogue |
| `supplier_feed` | 0.85 | distributor price feed |
| `manual_verified` | 0.75 | field agent checked the counter |
| `shop_submitted` | 0.60 | the shop typed it in themselves |

The weight feeds the usefulness score (trust 45%, stock 35%, recency 20%) that orders
the price table. It is deliberately **not** the same as the price sort.

## Freshness

| Age | Classification | Behaviour |
|---|---|---|
| ≤ 7 days | `fresh` | shown plainly |
| 8–30 days | `recent` | shown plainly |
| > 30 days | `stale` | flagged "Older than 30 days" |

Stale offers are still shown — hiding them would be its own kind of dishonesty — but
they are labelled and they lower the part's `dataQuality` score.

## Data-quality score

Aggregated per part and surfaced in the UI:

- **good** — ≥2 seller-confirmed listings, none stale.
- **fair** — ≥1 confirmed listing, some stale.
- **weak** — no confirmed listing at all. *"Treat all prices as indicative and call ahead."*
- **none** — no offers on record. The API returns no estimate rather than inventing one.

## Vendor schema (`data/vendors.json`)

Beyond name and address: `lat`/`lng` (drives Haversine ranking), `phone`,
`openingHours`, `verified` (has a partner confirmed this vendor?), `rating`,
`categories[]` (which part families they handle), and `notes` for the caveats a
counter clerk would tell you — *"mixed genuine and aftermarket stock, confirm brand at
counter."*

`categories[]` is what allows honest degradation: a shop with no listing for a part
number can still be shown as *"handles this category, no listing for this exact part
number"* rather than as a match or as nothing.

## Nearby ranking

```
score = distanceKm + stockPenalty + trustAdjustment + listingPenalty
```

| Component | Value |
|---|---|
| `distanceKm` | Haversine great-circle distance |
| `stockPenalty` | confirmed 0 · likely 1.2 · unconfirmed 2.6 · out_of_stock 6.0 |
| `trustAdjustment` | verified −0.4 · unverified +0.4, plus (5 − rating) × 0.15 |
| `listingPenalty` | +1.0 when there is no listing for the part or category |

One score point ≈ one kilometre, so a 3 km shop with unconfirmed stock ranks below a
5 km shop with a confirmed listing. Lower is better; distance alone is the wrong answer.

## Ingestion — how to add real data

1. **Pick one source and one part family.** Do not attempt the whole catalogue.
2. Write offers with `sourceType`, `sourceName` and a real `updatedAt`. Never backfill
   a timestamp to make data look fresher.
3. Set `stockStatus` from what the source actually said. If it did not say, use
   `unconfirmed` — that is the honest default and the UI explains it.
4. Validate referential integrity. The seed loader is forgiving; a reality check is not.
   This snippet belongs in your test suite:

```python
import json, pathlib
parts   = {p["id"] for p in json.loads(pathlib.Path("data/parts.json").read_text())}
vendors = {v["id"] for v in json.loads(pathlib.Path("data/vendors.json").read_text())}
bad = [o for o in json.loads(pathlib.Path("data/offers.json").read_text())
       if o["partId"] not in parts or o["vendorId"] not in vendors]
assert not bad, f"dangling references: {bad}"
```

## Legal and ethical notes

- Vendor names, phone numbers and addresses in the seed data are **illustrative
  placeholders**, not real businesses. Replace them before any demonstration involving
  the public.
- Prices are **indicative catalogue values**, not live quotes. Every response repeats
  this; do not remove the disclaimer to make the demo look slicker.
- Do not scrape a retailer's live prices without checking their terms of service. Use
  supplier feeds, partner APIs, or manual verified entry.
