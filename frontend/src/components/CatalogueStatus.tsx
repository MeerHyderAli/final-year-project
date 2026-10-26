import type { CatalogueHealth } from '../lib/types';
import { Badge } from './ui';

/** Makes the provenance of the data as visible as the AI provider status. */
export function CatalogueStatus({ catalogue }: { catalogue: CatalogueHealth | null }) {
  if (!catalogue) return null;

  const parts = catalogue.collections.parts ?? 0;
  const offers = catalogue.collections.offers ?? 0;
  const persistent = catalogue.persistent && catalogue.mongoReady;

  return (
    <div className={`provider ${persistent ? 'provider--good' : 'provider--warn'}`}>
      <Badge tone={persistent ? 'good' : 'warn'}>{persistent ? 'Database catalogue' : 'Demo catalogue'}</Badge>
      <span className="small">
        {persistent ? (
          <>MongoDB is the source of truth · {parts} parts · {offers} offers.</>
        ) : (
          <>JSON seed data · {parts} parts · {offers} offers. Not live inventory; configure MongoDB and import verified supplier/seller data for deployment.</>
        )}
      </span>
    </div>
  );
}
