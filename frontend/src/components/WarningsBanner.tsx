import type { AnalysisResponse } from '../lib/types';
import { Notice } from './ui';

/** Aggregated guard-rail messages produced by the API across all four stages. */
export function WarningsBanner({ warnings }: { warnings: AnalysisResponse['warnings'] }) {
  if (warnings.length === 0) return null;

  return (
    <div className="warnings">
      {warnings.map((w) => (
        <Notice
          key={w.code}
          tone={w.severity === 'high' ? 'bad' : w.code === 'safety_critical_category' ? 'bad' : 'warn'}
          title={w.code.replace(/_/g, ' ')}
        >
          {w.message}
        </Notice>
      ))}
    </div>
  );
}
