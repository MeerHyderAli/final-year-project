import type { NearbyBlock } from '../lib/types';
import { inr, relativeTime, SOURCE_LABEL, STOCK_META } from '../lib/format';
import { Badge, Card, Empty, Notice } from './ui';

/**
 * Step 5. Ranked by distance AND evidence: the API's score is distance + stock
 * confidence + vendor trust, so a nearby shop with no listing is pushed below a
 * slightly further shop that confirmed stock.
 */
export function NearbyList({ nearby }: { nearby: NearbyBlock }) {
  return (
    <Card
      step="Step 5"
      title="Nearby sellers"
      right={<Badge tone="info">{nearby.count} shop{nearby.count === 1 ? '' : 's'}</Badge>}
    >
      <Notice tone="warn" title="Maps presence ≠ stock">
        {nearby.caveat}
      </Notice>

      {nearby.originNote && <Notice tone="info">{nearby.originNote}</Notice>}

      {nearby.results.length === 0 ? (
        <Empty>No sellers within {nearby.radiusKm} km match this part or category.</Empty>
      ) : (
        <ol className="vendors">
          {nearby.results.map((r) => {
            const tone =
              r.availability.strength === 'confirmed'
                ? 'good'
                : r.availability.strength === 'listing'
                  ? 'info'
                  : r.availability.strength === 'category'
                    ? 'warn'
                    : 'bad';
            return (
              <li key={r.vendor.id} className="vendor">
                <div className="vendor__head">
                  <div>
                    <strong>{r.vendor.name}</strong>
                    <span className="muted small">
                      {r.vendor.area} · {r.vendor.city} {r.vendor.pincode}
                    </span>
                  </div>
                  <div className="vendor__right">
                    {r.distanceLabel && <Badge tone="neutral">{r.distanceLabel}</Badge>}
                    {r.vendor.verified ? <Badge tone="good">verified</Badge> : <Badge tone="warn">unverified</Badge>}
                    <Badge tone="neutral">★ {r.vendor.rating}</Badge>
                  </div>
                </div>

                <div className="vendor__avail">
                  <Badge tone={tone}>{r.availability.claim}</Badge>
                  <span className="muted small">Evidence: {r.availability.evidence}</span>
                </div>

                {r.offer ? (
                  <div className="vendor__offer">
                    <span className="price">{inr(r.offer.price)}</span>
                    <Badge tone={STOCK_META[r.offer.stockStatus].tone}>{STOCK_META[r.offer.stockStatus].label}</Badge>
                    <span className="muted small">
                      {SOURCE_LABEL[r.offer.sourceType] ?? r.offer.sourceType} · updated{' '}
                      {relativeTime(r.offer.updatedAt)}
                    </span>
                  </div>
                ) : (
                  <p className="muted small">No listing on record for this part number at this shop.</p>
                )}

                <div className="vendor__foot">
                  <span className="muted small">
                    {r.vendor.phone} · {r.vendor.openingHours}
                  </span>
                  <span className="muted small" title="distance + stock evidence + vendor trust">
                    rank score {r.score.toFixed(2)}
                  </span>
                </div>
                {r.vendor.notes && <p className="muted small vendor__notes">{r.vendor.notes}</p>}
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}
