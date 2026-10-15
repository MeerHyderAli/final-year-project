import type { PriceBlock } from '../lib/types';
import { FRESHNESS_META, inr, relativeTime, SOURCE_LABEL, STOCK_META } from '../lib/format';
import { Badge, Card, Empty, Metric, Notice } from './ui';

/**
 * Step 4. Every row carries its own provenance: who said it, when, and how firm the
 * availability claim is. The summary line deliberately separates "cheapest" from
 * "best evidenced", because the cheapest listing is usually the least verified.
 */
export function PriceTable({ price }: { price: PriceBlock | null }) {
  if (!price) {
    return (
      <Card step="Step 4" title="Price comparison">
        <Empty>No catalogue part was resolved, so there is nothing to price. Identify the part first.</Empty>
      </Card>
    );
  }

  const q = price.dataQuality;
  const qualityTone = q.level === 'good' ? 'good' : q.level === 'fair' ? 'info' : q.level === 'none' ? 'bad' : 'warn';

  return (
    <Card
      step="Step 4"
      title="Price comparison"
      right={<Badge tone={qualityTone}>{price.stats.count} priced offer{price.stats.count === 1 ? '' : 's'}</Badge>}
    >
      <Notice tone={qualityTone as 'good' | 'warn' | 'bad' | 'info'} title="Data quality">
        {q.message}
      </Notice>

      {price.stats.count > 0 ? (
        <div className="metrics">
          <Metric label="Lowest" value={inr(price.stats.min)} sub={price.cheapest?.vendor.name} />
          <Metric label="Median" value={inr(price.stats.median)} />
          <Metric label="Highest" value={inr(price.stats.max)} />
          <Metric
            label="Spread"
            value={price.stats.spreadPct != null ? `${price.stats.spreadPct}%` : '—'}
            sub="across listed sellers"
          />
        </div>
      ) : (
        <Empty>
          No seller or catalogue price is on record for this part. We have deliberately not estimated one.
        </Empty>
      )}

      {price.bestValue && price.cheapest && price.bestValue.offerId !== price.cheapest.offerId && (
        <Notice tone="info" title="Cheapest is not the same as best-evidenced">
          The lowest price is {inr(price.cheapest.price)} at {price.cheapest.vendor.name} (
          {price.cheapest.stockLabel.toLowerCase()}). Weighting price against source trust and stock evidence,
          the best overall value is {inr(price.bestValue.price)} at {price.bestValue.vendor.name}.
        </Notice>
      )}

      {price.quotes.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Seller</th>
                <th>Type</th>
                <th className="num">Price</th>
                <th>Availability</th>
                <th>Source &amp; updated</th>
              </tr>
            </thead>
            <tbody>
              {price.quotes.map((quote) => {
                const stock = STOCK_META[quote.stockStatus];
                const fresh = FRESHNESS_META[quote.freshness];
                return (
                  <tr key={quote.offerId} className={quote.stockStatus === 'out_of_stock' ? 'row--muted' : ''}>
                    <td>
                      <div className="seller">
                        <strong>{quote.vendor.name}</strong>
                        {quote.vendor.verified && <Badge tone="good">verified</Badge>}
                      </div>
                      <span className="muted small">
                        {quote.vendor.area}, {quote.vendor.city} · {quote.vendor.phone}
                      </span>
                      <span className="muted small">{quote.vendor.openingHours}</span>
                    </td>
                    <td>
                      <Badge tone={quote.condition === 'genuine' ? 'good' : 'neutral'}>{quote.genuineLabel}</Badge>
                      {quote.warrantyMonths > 0 && <span className="muted small">{quote.warrantyMonths} mo warranty</span>}
                    </td>
                    <td className="num">
                      <strong>{inr(quote.price)}</strong>
                      {quote.discountPct > 0 && <span className="muted small">{quote.discountPct}% below MRP</span>}
                    </td>
                    <td>
                      <Badge tone={stock.tone}>{stock.label}</Badge>
                      <Badge tone={fresh.tone}>{relativeTime(quote.updatedAt)}</Badge>
                      {quote.watchFor.length > 0 && (
                        <ul className="watch">
                          {quote.watchFor.map((w) => (
                            <li key={w}>{w}</li>
                          ))}
                        </ul>
                      )}
                    </td>
                    <td>
                      <span className="muted small">{SOURCE_LABEL[quote.source.type] ?? quote.source.type}</span>
                      <span className="muted small">{quote.source.name}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="disclaimer">{price.disclaimer}</p>
    </Card>
  );
}
