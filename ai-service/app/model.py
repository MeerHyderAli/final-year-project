"""
Part classifier.

`PartClassifier` maps the 39-D hand-crafted vector to a category logit vector.
It is intentionally small (≈6k parameters): with a few hundred images per class a
larger head overfits, and a small model is honest about the dataset size in the
report. Dropout + feature-standardisation do the regularisation work.

The classifier also carries a `temperature` for calibration. Raw softmax on a small
dataset is systematically overconfident, and this project's whole safety argument
rests on knowing when the model does NOT know.
"""

from __future__ import annotations

import json
from pathlib import Path

import torch
import torch.nn as nn


class PartClassifier(nn.Module):
    def __init__(self, in_dim: int = 39, num_classes: int = 8, hidden=(128, 64), dropout=0.35):
        super().__init__()
        layers: list[nn.Module] = []
        prev = in_dim
        for h in hidden:
            layers += [
                nn.Linear(prev, h),
                nn.BatchNorm1d(h),
                nn.ReLU(inplace=True),
                nn.Dropout(dropout),
            ]
            prev = h
        layers.append(nn.Linear(prev, num_classes))
        self.net = nn.Sequential(*layers)
        self.in_dim = in_dim
        self.num_classes = num_classes
        self.register_buffer("feature_mean", torch.zeros(in_dim))
        self.register_buffer("feature_std", torch.ones(in_dim))
        self.register_buffer("temperature", torch.tensor(1.0))

    def set_normalisation(self, mean, std, std_floor: float = 0.05):
        """
        Store feature standardisation statistics.

        `std_floor` is not cosmetic. A feature that is constant across the dataset
        has std 0; clamping it to a tiny epsilon (e.g. 1e-6) makes every downstream
        perturbation — augmentation noise, float jitter — blow up by ~1e6. That turns
        a harmless constant into a noise amplifier that silently stops training.
        Flooring the std keeps such features in a sane numeric range.
        """
        self.feature_mean.copy_(torch.as_tensor(mean, dtype=torch.float32))
        self.feature_std.copy_(
            torch.as_tensor(std, dtype=torch.float32).clamp_min(std_floor)
        )

    def forward(self, x):
        x = (x - self.feature_mean) / self.feature_std
        return self.net(x)

    @torch.no_grad()
    def predict_proba(self, x: torch.Tensor) -> torch.Tensor:
        self.eval()
        logits = self.forward(x)
        # Temperature-scaled softmax: lower confidence when the model is uncalibrated.
        return torch.softmax(logits / self.temperature.clamp_min(1e-3), dim=-1)

    def save(self, path: str | Path, meta: dict | None = None):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "state_dict": self.state_dict(),
                "in_dim": self.in_dim,
                "num_classes": self.num_classes,
                "meta": meta or {},
            },
            path,
        )
        if meta:
            path.with_suffix(".json").write_text(json.dumps(meta, indent=2) + "\n")

    @classmethod
    def load(cls, path: str | Path) -> "PartClassifier":
        blob = torch.load(Path(path), map_location="cpu", weights_only=False)
        model = cls(in_dim=blob["in_dim"], num_classes=blob["num_classes"])
        model.load_state_dict(blob["state_dict"])
        model.eval()
        return model


def calibrate_temperature(model: PartClassifier, features: torch.Tensor, labels: torch.Tensor) -> float:
    """
    Fit a single temperature on the validation split by minimising NLL.
    A model that reports "82% confident" should be right about 82% of the time.
    """
    model.eval()
    with torch.no_grad():
        logits = model(features)

    best_t, best_loss = 1.0, float("inf")
    for t in [0.5 + 0.05 * i for i in range(60)]:  # 0.5 .. 3.45
        loss = nn.functional.cross_entropy(logits / t, labels).item()
        if loss < best_loss:
            best_t, best_loss = round(t, 3), loss
    model.temperature.fill_(best_t)
    return best_t
