import config from '../config.js';

/**
 * Client for the OCR endpoint of the Python service (PaddleOCR / EasyOCR / Tesseract).
 * Fails loudly — the caller decides how to degrade. Never returns invented text.
 */
export async function fetchOcr({ buffer, filename, mimetype }) {
  const form = new FormData();
  form.append('file', new Blob([buffer], { type: mimetype || 'image/jpeg' }), filename || 'label.jpg');

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), config.aiTimeoutMs);

  try {
    const res = await fetch(`${config.aiServiceUrl}/ocr`, { method: 'POST', body: form, signal: controller.signal });
    if (!res.ok) {
      const detail = await res.text().catch(() => '');
      throw new Error(`ocr service responded ${res.status}${detail ? `: ${detail.slice(0, 200)}` : ''}`);
    }
    return await res.json();
  } catch (err) {
    if (err.name === 'AbortError') throw new Error(`ocr service timed out after ${config.aiTimeoutMs} ms`);
    throw err;
  } finally {
    clearTimeout(timer);
  }
}
