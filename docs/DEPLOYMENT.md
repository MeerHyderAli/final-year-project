# Persistent catalogue and deployment path

The app has two explicit data modes. **A Gemini key is not a catalogue or an inventory
feed.** It only enables the identification service.

## Modes

| Mode | Configuration | Behaviour |
|---|---|---|
| JSON demo | No `MONGODB_URI` | Reads the illustrative files in `data/`; the UI labels this **Demo catalogue**. |
| Persistent catalogue | `MONGODB_URI` set | Reads vehicles, parts, vendors and offers from MongoDB. Startup fails if the database cannot be read; it never silently substitutes demo JSON. |

The current API loads the selected catalogue at startup. Restart the API after an
import. A live supplier-feed scheduler, admin UI, authentication and production
monitoring are still deployment work, not features to pretend exist.

## Run MongoDB locally

Docker is the easiest local option:

```bash
docker compose up -d mongo
```

Or use an existing MongoDB 6+ instance. Set the connection in `.env` (the development
runner loads it, and the file is gitignored):

```bash
MONGODB_URI=mongodb://127.0.0.1:27017
MONGODB_DB=autoparts_ai
SEED_DEMO_DATA=false
```

Do not set `SEED_DEMO_DATA=true` for a real supplier catalogue. That option is only
for intentionally putting the illustrative fixtures into an empty demo database.

## Validate and import real data

Prepare a directory containing `vehicles.json`, `parts.json`, `vendors.json` and
`offers.json`. The importer validates required fields, categories, vehicle links,
vendor links, price types, stock states, source names and timestamps before writing.

```bash
cd backend
npm install
npm run import:catalogue -- --check-only --dir /path/to/catalogue
MONGODB_URI=mongodb://127.0.0.1:27017 npm run import:catalogue -- --dir /path/to/catalogue
```

The importer upserts by stable document `id` and never deletes existing records. It
prints counts, not connection strings or credentials. To try the mechanism with the
repository's illustrative data, use `--dir ../data`; that is still demo data.

Then start the services from the repository root:

```bash
bash scripts/dev.sh
```

The web UI should show **Database catalogue**. The API health response also reports
`catalogue.driver`, `persistent`, `mongoReady` and collection counts.

## Data provenance requirements

Every offer must state what the source actually said:

- `sourceType`: `supplier_feed`, `shop_submitted`, `authorised_catalogue` or `manual_verified`
- `sourceName`: the feed, dealer catalogue or person/counter that supplied it
- `updatedAt`: the real source timestamp, not a fabricated current time
- `stockStatus`: `confirmed`, `likely`, `unconfirmed` or `out_of_stock`

If a source has no price or stock information, leave the offer out or mark it
unconfirmed. Do not ask Gemini to fill those fields. Fitment likewise needs an
authoritative part-number/vehicle catalogue record.

## Before calling this production-ready

The remaining operational work is deliberate and visible:

1. Connect an authorised supplier/seller feed or establish a manual verification process.
2. Add authenticated, authorised admin/import access and audit logging.
3. Add scheduled feed refreshes, conflict handling and failure alerts.
4. Configure HTTPS, a secrets manager, restricted CORS, rate limits and backups.
5. Run security review, load tests and a real-data acceptance test with each supplier.
6. Replace illustrative vendor identities and prices before any public demonstration.

Until those are done, describe the app honestly as a working full-stack prototype with
Gemini identification and an optional persistent catalogue—not as a live marketplace.
