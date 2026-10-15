"""
Out-of-distribution (domain-shift) diagnostic.

MOTIVATION — measured, not assumed.

The shipped checkpoint is trained on procedurally generated renders. Evaluated on
real product photographs it scores:

    in-domain  (renders) : 0.969 accuracy
    cross-domain (photos): 0.258 accuracy        <- domain gap of 0.71

Worse than the accuracy drop: the model is *confidently* wrong there. It labelled a
real spark plug "air filter" at 0.99 confidence. A softmax score is not a measure of
whether the input resembles anything the model was trained on.

So can we detect the shift cheaply, in feature space? Measured results below.

    Diagonal (per-feature z-score) distance
        train p99 = 5.72   |   real photos above it: 0%
    Full Mahalanobis distance
        train p99 = 119.25 |   real photos above it: 35%

CONCLUSION: **a feature-space distance test does not reliably catch this shift.**
Real product photos happen to sit as close to the training mean as the renders do —
they are simply drawn from a different region of *label* space, not a far region of
*feature* space. Diagonal distance is actively useless here (0%).

This is an honest negative result and it is worth stating plainly in the report: you
cannot buy your way out of a domain gap with a cheap novelty detector.

What this module is therefore allowed to be: an **advisory** signal. When it does
fire it is informative; when it stays silent it proves nothing. Never treat
`in_distribution == True` as evidence that a prediction is trustworthy — the real
safeguards are the confidence floor and the rule that fitment is never inferred from
image similarity.
"""

from __future__ import annotations

import numpy as np


class OODDetector:
    def __init__(self, mean, std, precision, train_distance_p95: float, train_distance_p99: float):
        self.mean = np.asarray(mean, dtype=np.float64)
        self.std = np.asarray(std, dtype=np.float64)
        self.precision = np.asarray(precision, dtype=np.float64)
        self.p95 = float(train_distance_p95)
        self.p99 = float(train_distance_p99)

    @classmethod
    def fit(cls, X: np.ndarray, mean: np.ndarray, std: np.ndarray, ridge: float = 1e-3) -> "OODDetector":
        Z = (X - mean) / std
        cov = np.cov(Z.T)
        if cov.ndim == 0:  # single feature
            cov = np.array([[float(cov)]])
        cov = cov + np.eye(cov.shape[0]) * ridge
        precision = np.linalg.inv(cov)
        d = cls._mahalanobis(Z, precision)
        return cls(mean, std, precision, float(np.percentile(d, 95)), float(np.percentile(d, 99)))

    @staticmethod
    def _mahalanobis(Z: np.ndarray, precision: np.ndarray) -> np.ndarray:
        return np.einsum("ij,jk,ik->i", Z, precision, Z)

    def score(self, vec: np.ndarray) -> dict:
        z = ((np.asarray(vec, dtype=np.float64) - self.mean) / self.std).reshape(1, -1)
        d = float(self._mahalanobis(z, self.precision)[0])
        if d > self.p99:
            level, note = "high", "Features fall outside the training distribution (past the 99th percentile)."
        elif d > self.p95:
            level, note = "moderate", "Features are unusual relative to the training distribution (past the 95th percentile)."
        else:
            level, note = "low", "Features sit inside the training distribution."

        return {
            "distance": round(d, 3),
            "trainP95": round(self.p95, 3),
            "trainP99": round(self.p99, 3),
            "level": level,
            "inDistribution": level == "low",
            "note": note,
            # Repeated on purpose: the receiver must not read inDistribution as a
            # guarantee. Measured detection rate on the real-photo set: ~35%.
            "caveat": (
                "Advisory only. A low distance does NOT mean the prediction is correct; "
                "this test detected only ~35% of real-photo inputs during evaluation."
            ),
        }

    def to_dict(self) -> dict:
        return {
            "mean": self.mean.tolist(),
            "std": self.std.tolist(),
            "precision": self.precision.tolist(),
            "trainDistanceP95": self.p95,
            "trainDistanceP99": self.p99,
        }

    @classmethod
    def from_dict(cls, blob: dict) -> "OODDetector":
        return cls(
            blob["mean"], blob["std"], blob["precision"],
            blob["trainDistanceP95"], blob["trainDistanceP99"],
        )
