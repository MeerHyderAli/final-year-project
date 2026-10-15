/**
 * Error envelope: every failure is machine-readable and, where possible, tells the
 * caller what to do next. No stack traces leak to clients.
 */
export function notFound(req, res) {
  res.status(404).json({
    error: 'not_found',
    path: req.originalUrl,
    hint: 'See GET /api/health for the route index.',
  });
}

export function errorHandler(err, _req, res, _next) {
  const status = err.status || (err.message === 'unsupported_image_type' ? 415 : 500);
  if (status >= 500) console.error('[error]', err);
  res.status(status).json({
    error: err.code || 'internal_error',
    detail: err.message,
    ...(status === 415 ? { hint: 'Send a JPEG, PNG, WebP, BMP or GIF image.' } : {}),
  });
}
