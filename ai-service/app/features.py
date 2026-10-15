"""
Hand-crafted feature extractor for spare-part images.

Why not fine-tune ResNet/EfficientNet on day one?
  The dataset plan starts at a few hundred images per class. A frozen
  transfer-learning CNN memorises 20 photos far better than it generalises, and the
  resulting accuracy number tells you about the dataset, not the problem. This
  extractor encodes *physical* properties that actually separate these parts —
  silhouette shape, elongation, metal-vs-paper colour, edge texture — so a small
  model on a small dataset still learns something true.

It remains the baseline; `train/train.py --backbone mobilenet` is the upgrade path
once the labelled set is large enough.

Two design rules learned the hard way and worth keeping:

  1. **Every feature is O(1).** Raw Hu moments span ~1e-6..1e0. If you feed those in
     and then standardise, a feature whose true std is 0.001 gets amplified ~1000x,
     and measurement noise drowns the signal. Features are scaled to comparable
     magnitudes here, and `model.set_normalisation` additionally floors std.
  2. **Compression must not destroy signal.** Log-scaling Hu moments aggressively
     pushed every shape to 5.1-7.3 — technically finite, practically constant. The
     shape statistics below are chosen to stay spread out.

Feature layout (FEATURE_DIM = 22):
  [0:8]   shape      log-aspect, elongation, extent, solidity, hole ratio,
                     area ratio, Hu#1, Hu#2
  [8:14]  colour     mean R, mean G, mean B, saturation, warmth (R-B), value
  [14:18] hue        circ-x, circ-y, sat>0.2 fraction, high-value hue count
  [18:22] texture    edge density (strict), edge density (loose), gradient mean,
                     roughness (local std)
"""

from __future__ import annotations

import numpy as np
from PIL import Image

FEATURE_DIM = 22
IMAGE_SIZE = 160

# Floor used when standardising. Features are O(1) by construction, so a std below
# this is measurement noise, not signal, and must not be divided out.
STD_FLOOR = 0.05


def _to_array(img: Image.Image) -> np.ndarray:
    img = img.convert("RGB").resize((IMAGE_SIZE, IMAGE_SIZE), Image.BILINEAR)
    return np.asarray(img, dtype=np.float32) / 255.0


def _otsu_threshold(values: np.ndarray) -> float:
    hist, edges = np.histogram(values, bins=64, range=(0.0, 1.0))
    hist = hist.astype(np.float64)
    total = hist.sum()
    if total == 0:
        return 0.5
    prob = hist / total
    centres = (edges[:-1] + edges[1:]) / 2.0
    omega = np.cumsum(prob)
    mu = np.cumsum(prob * centres)
    denom = np.clip(omega * (1.0 - omega), 1e-9, None)
    sigma_b = (mu[-1] * omega - mu) ** 2 / denom
    return float(centres[int(np.argmax(sigma_b))])


def _box_blur(m: np.ndarray) -> np.ndarray:
    pad = np.pad(m, 1, mode="edge")
    out = np.zeros_like(m, dtype=np.float32)
    for dy in range(3):
        for dx in range(3):
            out += pad[dy : dy + m.shape[0], dx : dx + m.shape[1]]
    return out / 9.0


def _erode(mask: np.ndarray) -> np.ndarray:
    """Shrink the mask by 1 px so boundary gradients don't pollute texture stats."""
    inner = mask[1:-1, 1:-1]
    out = np.zeros_like(mask)
    out[1:-1, 1:-1] = (
        inner & mask[:-2, 1:-1] & mask[2:, 1:-1] & mask[1:-1, :-2] & mask[1:-1, 2:]
    )
    return out


def foreground_mask(arr: np.ndarray) -> np.ndarray:
    """
    Separate the part from its background without assuming a studio backdrop.

    Two cues, because either alone fails:
      * colour distance from the estimated background (border ring median) — works
        when the part contrasts with the backdrop
      * local gradient magnitude — keeps textured regions that happen to match the
        background hue
    """
    h, w, _ = arr.shape
    border = np.concatenate([
        arr[0:4, :, :].reshape(-1, 3),
        arr[-4:, :, :].reshape(-1, 3),
        arr[:, 0:4, :].reshape(-1, 3),
        arr[:, -4:, :].reshape(-1, 3),
    ])
    bg = np.median(border, axis=0)

    dist = np.linalg.norm(arr - bg[None, None, :], axis=2)
    dist = dist / (dist.max() + 1e-6)

    grey = arr.mean(axis=2)
    gy = np.abs(np.diff(grey, axis=0, prepend=grey[:1, :]))
    gx = np.abs(np.diff(grey, axis=1, prepend=grey[:, :1]))
    grad = np.sqrt(gx**2 + gy**2)
    grad = grad / (grad.max() + 1e-6)

    combined = 0.75 * dist + 0.25 * grad
    mask = combined > max(_otsu_threshold(combined.ravel()), 0.12)
    mask = _box_blur(mask.astype(np.float32)) > 0.5

    if mask.sum() < 0.01 * h * w:
        mask = np.zeros((h, w), dtype=bool)
        mask[int(h * 0.3) : int(h * 0.7), int(w * 0.3) : int(w * 0.7)] = True
    return mask


def shape_features(mask: np.ndarray) -> np.ndarray:
    """8 silhouette descriptors, all O(1)."""
    ys, xs = np.nonzero(mask)
    if len(xs) < 8:
        return np.zeros(8, dtype=np.float32)

    h = ys.max() - ys.min() + 1
    w = xs.max() - xs.min() + 1
    area = float(mask.sum())
    aspect = w / max(h, 1)
    elongation = min(max(aspect, 1.0 / max(aspect, 1e-3)), 10.0)

    extent = area / float(h * w)

    row_span = np.zeros_like(mask)
    for r in np.unique(ys):
        cols = xs[ys == r]
        row_span[r, cols.min() : cols.max() + 1] = True
    solidity = area / max(float(row_span.sum()), 1.0)

    inner = mask[1:-1, 1:-1]
    holes = (~inner) & mask[:-2, 1:-1] & mask[2:, 1:-1] & mask[1:-1, :-2] & mask[1:-1, 2:]
    hole_ratio = float(holes.sum()) / max(area, 1.0)

    area_ratio = area / mask.size

    # Hu #1 and #2 only, and gently scaled — the higher invariants are ~0 for most
    # symmetric brake parts and contributed pure noise when they were included.
    x = xs.astype(np.float64)
    y = ys.astype(np.float64)
    cx, cy = x.mean(), y.mean()
    m00 = area
    n20 = float(np.sum((x - cx) ** 2)) / (m00**2)
    n02 = float(np.sum((y - cy) ** 2)) / (m00**2)
    n11 = float(np.sum((x - cx) * (y - cy))) / (m00**2)
    hu1 = n20 + n02
    hu2 = (n20 - n02) ** 2 + 4 * n11**2
    # sqrt keeps the useful dynamic range without flattening it.
    hu1 = float(np.sqrt(max(hu1, 0.0)))
    hu2 = float(np.sqrt(max(hu2, 0.0)) * 2.0)

    return np.array(
        [np.log(aspect + 1e-3), elongation / 10.0, extent, solidity,
         min(hole_ratio * 10.0, 2.0), area_ratio, hu1, hu2],
        dtype=np.float32,
    )


def colour_features(arr: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """6 colour descriptors + 4 circular hue descriptors."""
    mx = arr.max(axis=2)
    mn = arr.min(axis=2)
    delta = mx - mn
    sat = delta / (mx + 1e-6)

    sel = mask
    if not sel.any():
        return np.zeros(6, dtype=np.float32), np.zeros(4, dtype=np.float32)

    mean_rgb = arr[sel].mean(axis=0)
    sat_mean = float(sat[sel].mean())
    warmth = float(mean_rgb[0] - mean_rgb[2])
    value = float(mx[sel].mean())
    colour = np.array([mean_rgb[0], mean_rgb[1], mean_rgb[2], sat_mean, warmth, value], dtype=np.float32)

    # Hue as a circular quantity, weighted by saturation so grey pixels can't vote.
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    hue = np.zeros_like(mx)
    nz = delta > 1e-6
    i = nz & (mx == r)
    hue[i] = ((g - b)[i] / delta[i]) % 6.0
    i = nz & (mx == g)
    hue[i] = ((b - r)[i] / delta[i]) + 2.0
    i = nz & (mx == b)
    hue[i] = ((r - g)[i] / delta[i]) + 4.0
    hue = hue / 6.0
    theta = 2.0 * np.pi * hue

    wts = (sat**2)[sel]
    total = float(wts.sum()) + 1e-6
    hx = float((np.cos(theta)[sel] * wts).sum() / total)
    hy = float((np.sin(theta)[sel] * wts).sum() / total)
    colourful = float((sat[sel] > 0.2).mean())
    bright_colourful = float(((sat[sel] > 0.2) & (mx[sel] > 0.4)).mean())
    hue_feat = np.array([hx, hy, colourful, bright_colourful], dtype=np.float32)

    return colour, hue_feat


def texture_features(arr: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """4 texture descriptors: pleats, ribs and threads all raise these."""
    grey = arr.mean(axis=2)
    core = _erode(mask)
    if core.sum() < 16:
        core = mask
    if not core.any():
        return np.zeros(4, dtype=np.float32)

    gy = np.diff(grey, axis=0, prepend=grey[:1, :])
    gx = np.diff(grey, axis=1, prepend=grey[:, :1])
    mag = np.sqrt(gx**2 + gy**2)
    m = mag[core]
    density_strict = float((m > 0.08).mean())
    density_loose = float((m > 0.03).mean())
    grad_mean = float(m.mean() * 4.0)

    # Local roughness: deviation from a 3x3 box average, inside the silhouette.
    blurred = _box_blur(grey)
    rough = np.abs(grey - blurred)[core]
    roughness = float(rough.mean() * 8.0)

    return np.array([density_strict, density_loose, grad_mean, roughness], dtype=np.float32)


def spatial_features(mask: np.ndarray) -> np.ndarray:
    """2 descriptors: where the mass sits left-right and top-bottom."""
    h, w = mask.shape
    left = mask[:, : w // 2].sum()
    right = mask[:, w // 2 :].sum()
    top = mask[: h // 2, :].sum()
    bottom = mask[h // 2 :, :].sum()
    total = float(left + right) + 1e-6
    total_v = float(top + bottom) + 1e-6
    return np.array(
        [(left - right) / total, (top - bottom) / total_v], dtype=np.float32
    )


def extract(img: Image.Image) -> np.ndarray:
    """Return the FEATURE_DIM-length feature vector for a PIL image."""
    arr = _to_array(img)
    mask = foreground_mask(arr)

    colour, hue = colour_features(arr, mask)
    vec = np.concatenate([
        shape_features(mask),      # 8
        colour,                    # 6
        hue,                       # 4
        texture_features(arr, mask),  # 4
    ]).astype(np.float32)

    vec = np.nan_to_num(vec, nan=0.0, posinf=0.0, neginf=0.0)
    assert vec.shape[0] == FEATURE_DIM, f"expected {FEATURE_DIM} features, got {vec.shape[0]}"
    return vec


def extract_batch(images) -> np.ndarray:
    return np.stack([extract(im) for im in images]).astype(np.float32)


def normalisation(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Mean and *floored* std. Rule 1 in the module docstring: a feature that barely
    varies must not be amplified into full-scale noise.
    """
    mean = X.mean(0)
    std = np.maximum(X.std(0), STD_FLOOR)
    return mean.astype(np.float32), std.astype(np.float32)


def describe() -> dict:
    return {
        "name": "handcrafted-v2",
        "dim": FEATURE_DIM,
        "stdFloor": STD_FLOOR,
        "blocks": {
            "shape": [0, 8],
            "colour": [8, 14],
            "hue": [14, 18],
            "texture": [18, 22],
        },
    }
