const EARTH_RADIUS_KM = 6371.0088;

const toRad = (deg) => (deg * Math.PI) / 180;

/** Great-circle distance in km. */
export function haversineKm(a, b) {
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const lat1 = toRad(a.lat);
  const lat2 = toRad(b.lat);
  const h =
    Math.sin(dLat / 2) ** 2 + Math.sin(dLng / 2) ** 2 * Math.cos(lat1) * Math.cos(lat2);
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.min(1, Math.sqrt(h)));
}

/**
 * Nearby ranking. Distance alone is the wrong answer — a shop 2 km away that has
 * never confirmed stock is less useful than a 6 km shop with a confirmed listing.
 *
 * Score = distance penalty + evidence penalty + trust adjustment (lower is better).
 */
export function rankVendor(vendor, origin, { offer, hasListing }) {
  const distanceKm = origin ? haversineKm(origin, vendor) : null;

  // ~1 score point per km, so a 4 km detour costs about as much as unconfirmed stock.
  const distancePenalty = distanceKm == null ? 0 : distanceKm;
  const stockPenalty = !offer ? 3.0 : { confirmed: 0, likely: 1.2, unconfirmed: 2.6, out_of_stock: 6 }[offer.stockStatus] ?? 2.0;
  const trustPenalty = (vendor.verified ? -0.4 : 0.4) + (5 - (vendor.rating ?? 4)) * 0.15;
  const listingPenalty = hasListing ? 0 : 1.0;

  return {
    score: Number((distancePenalty + stockPenalty + trustPenalty + listingPenalty).toFixed(3)),
    distanceKm: distanceKm == null ? null : Number(distanceKm.toFixed(2)),
    parts: { distancePenalty, stockPenalty: Number(stockPenalty.toFixed(2)), trustPenalty: Number(trustPenalty.toFixed(2)), listingPenalty },
  };
}

export function formatDistance(km) {
  if (km == null) return null;
  return km < 1 ? `${Math.round(km * 1000)} m` : `${km.toFixed(1)} km`;
}

export function isInsideBox(point, { lat, lng }, radiusKm) {
  const dLat = radiusKm / 111.32;
  const dLng = radiusKm / (111.32 * Math.cos(toRad(lat)) || 1);
  return (
    Math.abs(point.lat - lat) <= dLat && Math.abs(point.lng - lng) <= dLng
  );
}
