/**
 * Distinguish an obvious natural-language part name from a stamped identifier.
 *
 * This is intentionally a narrow guard, not a part-number validator. Real
 * catalogue codes can contain letters, digits, spaces, dots, slashes or dashes;
 * only a phrase made solely of multiple alphabetic words is rejected. Everything
 * else still goes through the normal exact/suffix catalogue lookup.
 */
export function isObviousPartName(value) {
  const text = String(value ?? '').trim();
  return /^[A-Za-z]+(?:\s+[A-Za-z]+)+$/.test(text);
}

export function partNumberOrNull(value) {
  const text = String(value ?? '').trim();
  return text && !isObviousPartName(text) ? text : null;
}

export function partNameInputMessage(value) {
  return (
    `"${String(value ?? '').trim()}" looks like a part name, not a stamped part number. ` +
    'Use "Describe it instead" or upload a photo, or enter the printed alphanumeric code.'
  );
}
