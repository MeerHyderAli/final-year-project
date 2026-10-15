import type { Freshness, StockStatus, Verdict } from './types';

export const inr = (n: number | null | undefined) =>
  n == null ? '—' : `₹${n.toLocaleString('en-IN')}`;

export const pct = (n: number) => `${Math.round(n * 100)}%`;

export function relativeTime(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return 'unknown';
  const days = Math.floor((Date.now() - t) / 86_400_000);
  if (days <= 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days < 30) return `${days} days ago`;
  const months = Math.floor(days / 30);
  return months === 1 ? '1 month ago' : `${months} months ago`;
}

/**
 * Verdict presentation. The UI must never render a bare "compatible" badge for a
 * safety-critical part or an uncertain match — the reason has to travel with it.
 */
export const VERDICT_META: Record<Verdict, { label: string; tone: 'good' | 'warn' | 'bad' | 'info'; blurb: string }> = {
  confirmed: {
    label: 'Verified by part number',
    tone: 'good',
    blurb: 'The part number matched a catalogue record and the vehicle is listed as compatible.',
  },
  compatible: {
    label: 'Compatible',
    tone: 'good',
    blurb: 'The catalogue lists this part for your vehicle.',
  },
  needs_part_number: {
    label: 'Verify the part number',
    tone: 'warn',
    blurb: 'Safety-critical component. Catalogue fitment is necessary but not sufficient.',
  },
  needs_vehicle_info: {
    label: 'Needs more information',
    tone: 'info',
    blurb: 'Add your vehicle details or the stamped part number to confirm fitment.',
  },
  unknown_part_number: {
    label: 'Part number not in catalogue',
    tone: 'warn',
    blurb: 'Check the stamped code — 0/O, 1/I and 8/B are commonly mis-read.',
  },
  incompatible: {
    label: 'Not listed for this vehicle',
    tone: 'bad',
    blurb: 'Do not purchase without a physical comparison.',
  },
};

export const STOCK_META: Record<StockStatus, { label: string; tone: 'good' | 'warn' | 'bad' | 'info' }> = {
  confirmed: { label: 'In stock — seller confirmed', tone: 'good' },
  likely: { label: 'Likely available', tone: 'info' },
  unconfirmed: { label: 'Availability unconfirmed', tone: 'warn' },
  out_of_stock: { label: 'Out of stock', tone: 'bad' },
};

export const FRESHNESS_META: Record<Freshness, { label: string; tone: 'good' | 'warn' | 'bad' | 'info' }> = {
  fresh: { label: 'Updated this week', tone: 'good' },
  recent: { label: 'Updated this month', tone: 'info' },
  stale: { label: 'Older than 30 days', tone: 'warn' },
  unknown: { label: 'Update date unknown', tone: 'warn' },
};

export const SOURCE_LABEL: Record<string, string> = {
  authorised_catalogue: 'Authorised catalogue',
  supplier_feed: 'Supplier feed',
  manual_verified: 'Field-verified',
  shop_submitted: 'Shop-submitted',
};
