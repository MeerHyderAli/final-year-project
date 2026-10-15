import { byId, findParts, offersForPart, all } from '../store/index.js';
import { rankVendor, formatDistance } from './geo.js';

/**
 * Nearby vendor search (deck slide 05, module 5 + slide 09 location sources).
 *
 * Two hard rules:
 *   1. A maps listing is NOT proof of stock. Vendors whose catalogue categories
 *      don't include the part are labelled as such and pushed down the ranking.
 *   2. Every result states where the availability claim came from.
 */

export function nearbyVendors({ lat, lng, radiusKm = 15, category, partId, limit = 20 } = {}) {
  const origin = lat != null && lng != null ? { lat: Number(lat), lng: Number(lng) } : null;
  const part = partId ? byId('parts', partId) : null;
  const wantCategory = category || part?.category || null;

  const partOffers = part ? offersForPart(part.id) : [];
  const offerByVendor = new Map(partOffers.map((o) => [o.vendor.id, o]));

  // Category-only search: which vendors carry this class of part at all?
  const categoryParts = wantCategory ? findParts({ category: wantCategory }) : [];
  const vendorsWithCategory = new Set(
    categoryParts.flatMap((p) => offersForPart(p.id).map((o) => o.vendor.id)),
  );

  const results = [];

  for (const vendor of all('vendors')) {
    const ranked = rankVendor(vendor, origin, {
      offer: offerByVendor.get(vendor.id) ?? null,
      hasListing: part ? offerByVendor.has(vendor.id) : vendorsWithCategory.has(vendor.id),
    });

    if (origin && ranked.distanceKm != null && ranked.distanceKm > radiusKm) continue;

    const offer = offerByVendor.get(vendor.id) ?? null;
    const categoriesMatch = wantCategory ? vendor.categories.includes(wantCategory) : null;

    // Skip vendors that neither list the part nor carry the category at all.
    if (wantCategory && !part && categoriesMatch === false) continue;

    results.push({
      vendor: {
        id: vendor.id,
        name: vendor.name,
        area: vendor.area,
        city: vendor.city,
        pincode: vendor.pincode,
        lat: vendor.lat,
        lng: vendor.lng,
        phone: vendor.phone,
        openingHours: vendor.openingHours,
        verified: vendor.verified,
        rating: vendor.rating,
        notes: vendor.notes,
        categories: vendor.categories,
      },
      distanceKm: ranked.distanceKm,
      distanceLabel: formatDistance(ranked.distanceKm),
      ranking: ranked.parts,
      score: ranked.score,
      availability: availabilityFor({ part, offer, categoriesMatch }),
      offer: offer
        ? {
            offerId: offer.id,
            price: offer.price,
            currency: offer.currency,
            condition: offer.condition,
            stockStatus: offer.stockStatus,
            sourceType: offer.sourceType,
            sourceName: offer.sourceName,
            updatedAt: offer.updatedAt,
          }
        : null,
    });
  }

  results.sort((a, b) => a.score - b.score);

  return {
    origin,
    radiusKm,
    category: wantCategory,
    partId: part?.id ?? null,
    count: results.length,
    results: results.slice(0, limit),
    /** Slide 09 warning, surfaced in the UI verbatim. */
    caveat:
      'A shop appearing in a map search does not prove it stocks this part. ' +
      'Only listings marked "seller confirmed" carry an explicit availability claim.',
  };
}

function availabilityFor({ part, offer, categoriesMatch }) {
  if (!part) {
    return {
      claim: categoriesMatch
        ? 'Carries this part category'
        : 'No record of this category',
      strength: categoriesMatch ? 'category' : 'none',
      evidence: 'Vendor category profile from the catalogue',
    };
  }
  if (!offer) {
    if (categoriesMatch) {
      return {
        claim: 'Handles this category, no listing for this exact part number',
        strength: 'category',
        evidence: `Vendor declares the "${part.category}" category`,
      };
    }
    return { claim: 'No listing for this part', strength: 'none', evidence: 'No catalogue record' };
  }
  const claims = {
    confirmed: 'Seller confirmed stock for this part number',
    likely: 'Seller indicates the part is likely available',
    unconfirmed: 'Listing exists but availability is unconfirmed',
    out_of_stock: 'Seller reported out of stock',
  };
  return {
    claim: claims[offer.stockStatus] ?? 'Listing present',
    strength: offer.stockStatus === 'confirmed' ? 'confirmed' : 'listing',
    evidence: `${offer.sourceName} · ${offer.sourceType.replace(/_/g, ' ')}`,
  };
}
