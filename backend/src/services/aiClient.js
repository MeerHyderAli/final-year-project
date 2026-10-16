import config from '../config.js';

/**
 * Thin client for the Python vision service.
 *
 * Design rule: the API never fabricates a prediction. If the AI service is
 * unreachable or slow we return a structured `ai_unavailable` error and the UI
 * degrades to "search by part number / vehicle" instead of guessing.
 */

export class AiUnavailableError extends Error {
  constructor(message, cause) {
    super(message);
    this.name = 'AiUnavailableError';
    this.cause = cause;
  }
}

export async function predictImage({ buffer, filename, mimetype }) {
  const form = new FormData();
  form.append('file', new Blob([buffer], { type: mimetype || 'application/octet-stream' }), filename || 'upload.jpg');

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), config.aiTimeoutMs);

  try {
    const res = await fetch(`${config.aiServiceUrl}/predict`, {
      method: 'POST',
      body: form,
      signal: controller.signal,
    });

    if (!res.ok) {
      const detail = await res.text().catch(() => '');
      throw new AiUnavailableError(
        `vision service responded ${res.status}${detail ? `: ${detail.slice(0, 200)}` : ''}`,
      );
    }
    return await res.json();
  } catch (err) {
    if (err instanceof AiUnavailableError) throw err;
    throw new AiUnavailableError(
      err.name === 'AbortError'
        ? `vision service timed out after ${config.aiTimeoutMs} ms`
        : `vision service unreachable at ${config.aiServiceUrl}`,
      err,
    );
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Text description -> category. Same contract as predictImage, different endpoint.
 * Used when the user cannot supply a usable photograph.
 */
export async function describePart(description) {
  const form = new FormData();
  form.append('description', description);

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), config.aiTimeoutMs);

  try {
    const res = await fetch(`${config.aiServiceUrl}/describe`, {
      method: 'POST',
      body: form,
      signal: controller.signal,
    });
    if (!res.ok) {
      const detail = await res.text().catch(() => '');
      throw new AiUnavailableError(
        `identification service responded ${res.status}${detail ? `: ${detail.slice(0, 200)}` : ''}`,
      );
    }
    return await res.json();
  } catch (err) {
    if (err instanceof AiUnavailableError) throw err;
    throw new AiUnavailableError(
      err.name === 'AbortError'
        ? `identification service timed out after ${config.aiTimeoutMs} ms`
        : `identification service unreachable at ${config.aiServiceUrl}`,
      err,
    );
  } finally {
    clearTimeout(timer);
  }
}

export async function aiHealth() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 2500);
  try {
    const res = await fetch(`${config.aiServiceUrl}/health`, { signal: controller.signal });
    if (!res.ok) return { reachable: true, ok: false, status: res.status };
    return { reachable: true, ok: true, ...(await res.json()) };
  } catch (err) {
    return { reachable: false, ok: false, error: err.message };
  } finally {
    clearTimeout(timer);
  }
}
