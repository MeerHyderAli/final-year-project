import { useState } from 'react';
import { api, ApiError } from '../lib/api';
import type { DescribeResponse } from '../lib/types';
import { Badge, Notice } from './ui';

/**
 * "Describe it instead" — the no-photograph path.
 *
 * Genuinely useful when a picture is not possible: a part still bolted into a dark
 * engine bay, or someone describing a tractor part over the phone.
 *
 * It is presented as WEAKER evidence than a photo or a part number, and the copy says
 * so. A description narrows the search; it does not identify the part.
 */
export function DescribeInput({
  onResult,
  disabled,
}: {
  onResult: (result: DescribeResponse) => void;
  disabled?: boolean;
}) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  const submit = async () => {
    if (!text.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.describe(text.trim());
      onResult(result);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.status === 503
            ? 'The description path needs an AI provider. Configure VISION_PROVIDER and VISION_API_KEY, or use the part-number box.'
            : err.message
          : 'Could not reach the API.',
      );
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <button type="button" className="btn btn--ghost btn--sm" onClick={() => setOpen(true)} disabled={disabled}>
        Can&apos;t photograph it? Describe it instead
      </button>
    );
  }

  return (
    <div className="describe">
      <div className="describe__head">
        <strong>Describe the part</strong>
        <button type="button" className="btn btn--ghost btn--sm" onClick={() => setOpen(false)}>
          Close
        </button>
      </div>

      <textarea
        className="input describe__input"
        rows={3}
        maxLength={600}
        placeholder="e.g. round black metal canister, about 8 cm tall, screws onto the engine, has a rubber ring at the top"
        value={text}
        onChange={(e) => setText(e.target.value)}
        aria-label="Describe the spare part"
      />

      <div className="describe__foot">
        <button type="button" className="btn btn--primary btn--sm" onClick={submit} disabled={busy || !text.trim()}>
          {busy ? 'Thinking…' : 'Find candidates'}
        </button>
        <Badge tone="warn">weaker than a photo</Badge>
      </div>

      {error && <Notice tone="bad">{error}</Notice>}

      <p className="muted small">
        Say what it looks like, where it sits, what it is made of, and anything printed on
        it. A description narrows the search — it does not confirm the part.
      </p>
    </div>
  );
}
