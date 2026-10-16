import type { IdentifyResponse } from '../lib/types';
import { pct } from '../lib/format';
import { Badge, Card, Notice } from './ui';

/**
 * Step 2. Shows the raw model output together with its validity statement.
 *
 * The domain-gap warning is not hidden behind a tooltip: the shipped checkpoint
 * scores 0.258 on real photographs, and a user looking at a confident-looking
 * percentage is entitled to know that.
 */
export function IdentifyPanel({
  identify,
  onSelectCandidate,
  selectedPartId,
}: {
  identify: IdentifyResponse;
  onSelectCandidate: (partId: string) => void;
  selectedPartId: string | null;
}) {
  const accepted = identify.decision === 'accept_category';
  const cross = identify.validity?.measuredCrossDomainAccuracy;
  const detected = identify.detected;

  return (
    <Card
      step="Step 2"
      title="What the model thinks this is"
      right={
        <div className="badges">
          <Badge tone={accepted ? 'info' : 'warn'}>{accepted ? 'Category accepted' : 'Uncertain'}</Badge>
          <Badge tone="neutral">{identify.backend ?? 'unknown'}</Badge>
          {identify.latencyMs != null && <Badge tone="neutral">{identify.latencyMs} ms</Badge>}
        </div>
      }
    >
      {/* The single best outcome from a photo: a part number printed on the part.
          That upgrades the request from "a guess" to an exact catalogue lookup. */}
      {detected?.partNumber && (
        <Notice
          tone={detected.catalogueMatch ? 'good' : 'warn'}
          title={detected.catalogueMatch ? 'Part number read from your photo' : 'Part number read, but not in the catalogue'}
        >
          Read <strong>{detected.partNumber}</strong>
          {detected.brand ? ` (${detected.brand})` : ''}
          {detected.catalogueMatch ? (
            <>
              {' '}— matched catalogue record{' '}
              <strong>
                {detected.catalogueMatch.partNumber} · {detected.catalogueMatch.name}
              </strong>
              . Confirm it against the physical label before ordering.
            </>
          ) : (
            <> — check it against the label. 0/O, 1/I and 8/B are commonly mis-read.</>
          )}
        </Notice>
      )}

      {identify.reasoning && (
        <p className="muted small">
          <strong>Model reasoning:</strong> {identify.reasoning}
        </p>
      )}

      {identify.confidenceSource === 'model_self_report' && (
        <p className="muted small">
          Confidence is the model&apos;s own self-report, not a calibrated probability.
        </p>
      )}

      {cross != null && cross < 0.6 && (
        <Notice tone="bad" title="Low trust in this image prediction">
          This checkpoint scores <strong>{pct(cross)}</strong> on real photographs — it was trained on rendered
          images. Treat the category below as a hint and confirm with a part number or vehicle details.
          {identify.validity?.statement}
        </Notice>
      )}

      {identify.outOfDistribution && identify.outOfDistribution.level !== 'low' && (
        <Notice tone="warn" title="Image looks unlike the training data">
          {identify.outOfDistribution.note} (distance {identify.outOfDistribution.distance} vs training 99th
          percentile {identify.outOfDistribution.trainP99}). {identify.outOfDistribution.caveat}
        </Notice>
      )}

      {identify.predictions.length === 0 ? (
        <p className="empty">No prediction returned.</p>
      ) : (
        <ul className="predictions">
          {identify.predictions.map((p, i) => (
            <li key={p.category} className={`prediction ${i === 0 ? 'prediction--top' : ''}`}>
              <div className="prediction__head">
                <strong>{p.label}</strong>
                <span className="muted small">
                  {pct(p.confidence)}
                  {p.safetyCritical && ' · safety-critical category'}
                </span>
              </div>
              <div className="bar" aria-hidden="true">
                <span className="bar__fill" style={{ width: `${Math.max(2, p.confidence * 100)}%` }} />
              </div>
              {i === 0 && (
                <>
                  <p className="muted small">
                    {identify.message}
                  </p>
                  {p.catalogueCandidates.length > 0 && (
                    <div className="candidates">
                      <span className="muted small">
                        Catalogue parts in this category — pick one to check fitment and price:
                      </span>
                      <div className="chips">
                        {p.catalogueCandidates.map((c) => (
                          <button
                            key={c.id}
                            type="button"
                            className={`chip chip--button ${selectedPartId === c.id ? 'chip--selected' : ''}`}
                            onClick={() => onSelectCandidate(c.id)}
                          >
                            {c.name} · {c.brand} · {c.partNumber}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
