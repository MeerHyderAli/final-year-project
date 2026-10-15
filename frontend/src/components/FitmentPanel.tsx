import type { AnalysisResponse } from '../lib/types';
import { VERDICT_META, pct } from '../lib/format';
import { Badge, Card, Notice } from './ui';

/**
 * Step 3. The fitment verdict is the safety-critical output of the whole product,
 * so it is rendered with its evidence attached and never as a bare badge.
 */
export function FitmentPanel({ data }: { data: AnalysisResponse }) {
  const f = data.stage2_fitment;
  const meta = VERDICT_META[f.verdict];

  return (
    <Card
      step="Step 3"
      title="Does it fit?"
      right={
        <div className="badges">
          <Badge tone={meta.tone}>{meta.label}</Badge>
          {f.safetyCritical && <Badge tone="bad" title="Braking or drivetrain safety">Safety-critical</Badge>}
        </div>
      }
    >
      <p className="verdict-blurb">{meta.blurb}</p>
      <p className="verdict-summary">{f.summary}</p>

      {f.requiresHumanCheck && (
        <Notice tone={f.verdict === 'incompatible' ? 'bad' : 'warn'} title="Human check required">
          {f.verdict === 'incompatible'
            ? 'This combination is recorded as incompatible in the catalogue. Confirm physically before buying.'
            : 'Confirm the stamped part number on the old component, or ask a qualified mechanic, before fitting.'}
          {f.confidence < 0.55 && <> Automated confidence is only {pct(f.confidence)}.</>}
        </Notice>
      )}

      {f.verifications.map((v) => (
        <Notice key={v.reason} tone="warn">
          {v.message}
        </Notice>
      ))}

      <dl className="kv">
        <div>
          <dt>Candidate part</dt>
          <dd>{f.part ? `${f.part.name} · ${f.part.brand} · ${f.part.partNumber}` : 'Not resolved to a catalogue part'}</dd>
        </div>
        <div>
          <dt>Vehicle</dt>
          <dd>
            {f.vehicle
              ? `${f.vehicle.make} ${f.vehicle.model} (${f.vehicle.yearFrom}–${f.vehicle.yearTo}) · ${f.vehicle.engine}`
              : 'Not supplied'}
          </dd>
        </div>
      </dl>

      <details className="evidence" open>
        <summary>Why this verdict ({f.evidence.length} pieces of evidence)</summary>
        <ul className="evidence__list">
          {f.evidence.map((e, i) => (
            <li key={i} className={`evidence__item evidence__item--${e.strength}`}>
              <Badge tone={e.strength === 'strong' ? 'good' : e.strength === 'negative' ? 'bad' : 'info'}>
                {e.source.replace(/_/g, ' ')}
              </Badge>
              <span>{e.detail}</span>
            </li>
          ))}
        </ul>
      </details>

      {f.alternatives && f.alternatives.length > 0 && (
        <div className="subsection">
          <h3>What this part does fit</h3>
          <ul className="chips">
            {f.alternatives.map((a) => (
              <li key={a} className="chip">
                {a}
              </li>
            ))}
          </ul>
        </div>
      )}

      {f.listedFitments && f.listedFitments.length > 0 && (
        <div className="subsection">
          <h3>Catalogue fitments for this part number</h3>
          <ul className="chips">
            {f.listedFitments.map((a) => (
              <li key={a} className="chip">
                {a}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}
