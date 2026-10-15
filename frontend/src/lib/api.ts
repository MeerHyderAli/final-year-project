import type { AnalysisResponse, IdentifyResponse, Vehicle, PriceBlock } from './types';

/**
 * All requests are same-origin. Vite proxies /api to the Express server, which keeps
 * this working behind a preview domain where the browser cannot reach localhost.
 */
const BASE = '/api';

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly payload?: unknown) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!res.ok) {
    const detail =
      body && typeof body === 'object' && 'detail' in body
        ? String((body as { detail: unknown }).detail)
        : body && typeof body === 'object' && 'error' in body
          ? String((body as { error: unknown }).error)
          : `Request failed (${res.status})`;
    throw new ApiError(detail, res.status, body);
  }
  return body as T;
}

export const api = {
  health: () => request<Record<string, unknown>>('/health'),

  vehicles: () => request<{ count: number; makes: string[]; results: Vehicle[] }>('/catalog/vehicles'),

  identify: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return request<IdentifyResponse>('/identify', { method: 'POST', body: form });
  },

  lookupPartNumber: (partNumber: string) =>
    request<{ query: string; match: string; part: { id: string; name: string; brand: string; partNumber: string } }>(
      `/catalog/parts/lookup?partNumber=${encodeURIComponent(partNumber)}`,
    ),

  analyse: (payload: Record<string, unknown>) =>
    request<AnalysisResponse>('/fitment/analyse', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  compare: (partId: string) =>
    request<{ part: Record<string, unknown>; quote: PriceBlock; alternatives: Record<string, unknown>[] }>(
      `/price/compare?partId=${encodeURIComponent(partId)}`,
    ),

  nearby: (params: { lat?: number; lng?: number; partId?: string; radiusKm?: number }) => {
    const qs = new URLSearchParams();
    if (params.lat != null) qs.set('lat', String(params.lat));
    if (params.lng != null) qs.set('lng', String(params.lng));
    if (params.partId) qs.set('partId', params.partId);
    if (params.radiusKm) qs.set('radiusKm', String(params.radiusKm));
    return request<AnalysisResponse['stage4_nearby']>(`/nearby?${qs.toString()}`);
  },
};
