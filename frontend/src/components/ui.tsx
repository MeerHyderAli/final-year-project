import type { ReactNode } from 'react';

type Tone = 'good' | 'warn' | 'bad' | 'info' | 'neutral';

export function Badge({ tone = 'neutral', children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span className={`badge badge--${tone}`} title={title}>
      {children}
    </span>
  );
}

export function Card({
  title,
  step,
  right,
  children,
  className = '',
}: {
  title: string;
  step?: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      <header className="card__head">
        <div className="card__titlewrap">
          {step && <span className="card__step">{step}</span>}
          <h2 className="card__title">{title}</h2>
        </div>
        {right}
      </header>
      <div className="card__body">{children}</div>
    </section>
  );
}

export function Notice({
  tone = 'info',
  title,
  children,
}: {
  tone?: Tone;
  title?: string;
  children: ReactNode;
}) {
  return (
    <div className={`notice notice--${tone}`} role={tone === 'bad' ? 'alert' : undefined}>
      {title && <strong className="notice__title">{title}</strong>}
      <div className="notice__body">{children}</div>
    </div>
  );
}

export function Metric({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="metric">
      <span className="metric__label">{label}</span>
      <span className="metric__value">{value}</span>
      {sub && <span className="metric__sub">{sub}</span>}
    </div>
  );
}

export function Spinner({ label }: { label: string }) {
  return (
    <div className="spinner" role="status" aria-live="polite">
      <span className="spinner__dot" />
      <span>{label}</span>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}
