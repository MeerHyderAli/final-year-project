import { offersForPart } from '../store/index.js';
import config from '../config.js';

/**
 * Price engine.
 *
 * Transparency rules enforced here (deck slide 09):
 *   - every quote carries source, currency, last-updated timestamp and stock status
 *   - a quote older than STALE_AFTER_DAYS is flagged, never silently shown as current
 *   - "in stock" is only returned when the seller/inventory system confirmed it
 *   - nothing is invented: if there are no offers, the response says so
 */

const STALE_AFTER_DAYS = 30;
const FRESH_DAYS = 7;

const SOURCE_TRUST = {
  authorised_catalogue: 1.0,
  supplier_feed: 0.85,
  manual_verified: 0.75,
  shop_submitted: 0.6,
};

const CONDITION_MULTIPLIER = { genuine: 1.0, aftermarket: 0.85 };

export function ageInDays(iso) {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  return Math.floor((Date.now() - t) / 86_400_000);
}

export function freshnessOf(iso) {
  const days = ageInDays(iso);
  if (days == null) return 'unknown';
  if (days <= FRESH_DAYS) return 'fresh';
  if (days <= STALE_AFTER_DAYS) return 'recent';
  return 'stale';
}

/** Rank quotes so the most useful one is first — price alone is misleading. */
function usefulness(offer) {
  const trust = SOURCE_TRUST[offer.sourceType] ?? 0.5;
  const stock = { confirmed: 1.0, likely: 0.55, unconfirmed: 0.25, out_of_stock: 0.0 }[offer.stockStatus] ?? 0.2;
  const days = ageInDays(offer.updatedAt) ?? 999;
  const recency = Math.max(0, 1 - days / 60);
  return Number((trust * 0.45 + stock * 0.35 + recency * 0.2).toFixed(4));
}

export function quoteForPart(partId, { vehicleId, condition } = {}) {
  let offers = offersForPart(partId);
  const total = offers.length;
  if (condition) offers = offers.filter((o) => o.condition === condition);

  const quotes = offers
    .map((o) => {
      const freshness = freshnessOf(o.updatedAt);
      const ageDays = ageInDays(o.updatedAt);
      return {
        offerId: o.id,
        vendor: {
          id: o.vendor.id,
          name: o.vendor.name,
          area: o.vendor.area,
          city: o.vendor.city,
          phone: o.vendor.phone,
          openingHours: o.vendor.openingHours,
          lat: o.vendor.lat,
          lng: o.vendor.lng,
          verified: o.vendor.verified,
          rating: o.vendor.rating,
        },
        price: o.price,
        mrp: o.mrp,
        discountPct: o.mrp && o.mrp > o.price ? Math.round((1 - o.price / o.mrp) * 100) : 0,
        currency: o.currency || 'INR',
        condition: o.condition,
        genuineLabel: o.condition === 'genuine' ? 'Genuine / OEM' : 'Aftermarket',
        stockStatus: o.stockStatus,
        stockLabel: STOCK_LABEL[o.stockStatus] ?? o.stockStatus,
        // Only a seller/inventory confirmation may be described as "in stock".
        inStock: o.stockStatus === 'confirmed',
        source: { type: o.sourceType, name: o.sourceName },
        updatedAt: o.updatedAt,
        ageDays,
        freshness,
        warrantyMonths: o.warrantyMonths ?? 0,
        usefulness: usefulness(o),
        watchFor: watchFor(o, freshness),
      };
    })
    .sort((a, b) => b.usefulness - a.usefulness);

  const priced = quotes.filter((q) => q.stockStatus !== 'out_of_stock');
  const prices = priced.map((q) => q.price);
  const genuine = quotes.filter((q) => q.condition === 'genuine' && q.stockStatus !== 'out_of_stock');
  const aftermarket = quotes.filter((q) => q.condition === 'aftermarket' && q.stockStatus !== 'out_of_stock');

  const stats = prices.length
    ? {
        count: prices.length,
        min: Math.min(...prices),
        max: Math.max(...prices),
        median: median(prices),
        spreadPct: Math.round(((Math.max(...prices) - Math.min(...prices)) / Math.min(...prices)) * 100),
      }
    : { count: 0, min: null, max: null, median: null, spreadPct: null };

  const cheapest = priced.length ? priced.reduce((a, b) => (a.price <= b.price ? a : b)) : null;
  const bestEvidence = quotes.find((q) => q.stockStatus === 'confirmed') ?? quotes[0] ?? null;

  return {
    partId,
    currency: 'INR',
    offerCount: total,
    filteredCount: quotes.length,
    stats,
    // The honest headline: cheapest vs. best-evidenced are usually different shops.
    cheapest,
    mostVerified: bestEvidence,
    bestValue: pickBestValue(quotes),
    genuineLowest: genuine.length ? genuine.reduce((a, b) => (a.price <= b.price ? a : b)) : null,
    aftermarketLowest: aftermarket.length ? aftermarket.reduce((a, b) => (a.price <= b.price ? a : b)) : null,
    quotes,
    disclaimer:
      'Prices are indicator values from the sources shown, not live checkout rates. ' +
      'Availability is confirmed only where the seller or inventory system reported it. ' +
      'Always confirm the exact part number and price at the counter.',
    dataQuality: dataQuality(quotes, total),
  };
}

/**
 * Best value = good evidence AND good price, normalised so the two are comparable.
 * A cheap listing with no stock confirmation should not win.
 */
function pickBestValue(quotes) {
  const buyable = quotes.filter((q) => q.stockStatus !== 'out_of_stock');
  if (!buyable.length) return null;
  const min = Math.min(...buyable.map((q) => q.price));
  const max = Math.max(...buyable.map((q) => q.price));
  const span = max - min || 1;
  return buyable
    .map((q) => ({
      ...q,
      valueScore: Number((q.usefulness * 0.6 + (1 - (q.price - min) / span) * 0.4).toFixed(4)),
    }))
    .sort((a, b) => b.valueScore - a.valueScore)[0];
}

function dataQuality(quotes, total) {
  if (!total) {
    return {
      level: 'none',
      message: 'No seller or catalogue price is on record for this part. We will not estimate one.',
    };
  }
  const confirmed = quotes.filter((q) => q.stockStatus === 'confirmed').length;
  const stale = quotes.filter((q) => q.freshness === 'stale').length;
  if (confirmed >= 2 && stale === 0) {
    return { level: 'good', confirmed, stale, message: `${confirmed} listing(s) with seller-confirmed stock.` };
  }
  if (confirmed >= 1) {
    return { level: 'fair', confirmed, stale, message: `${confirmed} confirmed listing(s); ${stale} may be outdated.` };
  }
  return {
    level: 'weak',
    confirmed: 0,
    stale,
    message: 'No listing has seller-confirmed stock. Treat all prices as indicative and call ahead.',
  };
}

function watchFor(o, freshness) {
  const flags = [];
  if (o.stockStatus === 'unconfirmed') flags.push('Stock not confirmed by the seller');
  if (o.stockStatus === 'out_of_stock') flags.push('Seller reported out of stock');
  if (freshness === 'stale') flags.push('Price older than 30 days');
  if (o.sourceType === 'shop_submitted') flags.push('Self-reported listing, not independently verified');
  if (o.condition === 'aftermarket') flags.push('Aftermarket part — not OEM');
  return flags;
}

const STOCK_LABEL = {
  confirmed: 'In stock (seller confirmed)',
  likely: 'Likely available',
  unconfirmed: 'Availability unconfirmed',
  out_of_stock: 'Out of stock',
};

function median(xs) {
  const s = [...xs].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : Math.round((s[mid - 1] + s[mid]) / 2);
}

export const pricePolicy = { STALE_AFTER_DAYS, FRESH_DAYS, SOURCE_TRUST, CONDITION_MULTIPLIER, minConfidence: config.minConfidence };
