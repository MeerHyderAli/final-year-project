import type { AiHealth } from '../lib/types';
import { Badge, Notice } from './ui';

/**
 * Tells the user which identification engine is actually answering.
 *
 * This exists because "the AI said so" is not a single thing: Gemini, a local
 * checkpoint and a rule-based guess are wildly different evidence, and 0.258-accurate
 * local model is not the same as a frontier vision model. Silently swapping between
 * them would be the most misleading thing this UI could do.
 */
export function ProviderStatus({ health }: { health: AiHealth | null }) {
  if (!health) return null;

  const cloud = health.engines?.cloud;
  const local = health.engines?.local;

  if (!health.reachable) {
    return (
      <Notice tone="warn" title="Identification service offline">
        Photo identification is unavailable. The part-number lookup and vehicle-fitment
        checks still work — use those.
      </Notice>
    );
  }

  if (cloud?.configured) {
    return (
      <div className="provider provider--good">
        <Badge tone="good">AI active</Badge>
        <span className="small">
          Identifying with <strong>{cloud.provider}</strong>
          {cloud.model ? ` · ${cloud.model}` : ''}. Category prediction only — fitment is
          still verified against the catalogue.
        </span>
      </div>
    );
  }

  return (
    <Notice tone="warn" title="No AI provider configured">
      <p>
        Set <code>VISION_PROVIDER=gemini</code> and <code>VISION_API_KEY</code> to enable
        proper image identification. Until then the service falls back to{' '}
        {local?.available ? 'a local model that measured 0.258 accuracy on real photographs' : 'rule-based guesses that cannot pass the confidence threshold'}.
      </p>
      <p className="small">
        The part-number and vehicle paths below are unaffected and give exact answers.
      </p>
    </Notice>
  );
}
