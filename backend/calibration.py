"""Maps a component's raw confidence onto the accuracy it actually delivers.

Direction is never touched -- only the magnitude of the confidence, and
therefore how much position size that component's own portfolio takes.

Ported from XRP-Guess's calibration.py, including the mistake it made first.
Isotonic regression is nonparametric and unregularised, so fitted directly on
individual samples a handful of lucky predictions in a thinly-populated
high-confidence tail can pin that segment at 1.0. That happened there: the
confidence>=0.35 bucket had so few samples that the raw fit reported "100%
accurate", which would have pushed position sizing to maximum on the least
trustworthy part of the curve. `fit()` therefore runs on binned,
count-weighted averages and drops any bin below MIN_BIN_COUNT.

WHAT IS DIFFERENT HERE
----------------------
The target is P(correct) measured against the BASE RATE, not against 0.5.
Gold rises 55.7% of the time over this horizon and silver 53.9%, so a
component whose calls are right 55% of the time has calibrated confidence of
ZERO on gold, not 0.10. The floor is the ASSET's own base rate, passed in --
the same correction ensemble.py applies for the same reason. Leaving it at
0.5 would quietly reintroduce the illusion that tracking the drift is skill;
sharing gold's rate with silver would do a smaller version of the same thing.

Sample size is also the binding constraint in a way it was not for XRP-Guess.
That system resolved 96 predictions a day and could refit meaningfully within
a week; this one resolves ONE per trading day, so MIN_RECORDS_TO_FIT
represents most of a trading year. Until then `apply()` is a no-op, which is
the correct behaviour: an uncalibrated confidence is better than one fitted
to thirty observations.
"""
from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
from sklearn.isotonic import IsotonicRegression

import ensemble


def calibration_path(asset_key: str = "gold") -> Path:
    """One file per asset. The curves map a component's raw confidence onto
    the accuracy it delivered ON THAT METAL, and the two differ enough
    (different base rates, different driver sets) that sharing one file would
    calibrate silver against gold's history."""
    return Path(__file__).parent / "models" / f"calibration_{asset_key}.joblib"


# ~9 months of trading days. High because this system produces one resolved
# row per day; see the module docstring.
MIN_RECORDS_TO_FIT = 180
BIN_WIDTH = 0.05
MIN_BIN_COUNT = 15


def fit(confidences: list[float], corrects: list[bool],
        base_rate: float = ensemble.BASE_RATE_UP) -> IsotonicRegression | None:
    """confidences: raw 0..1 confidence in the predicted direction.
    corrects: whether that predicted direction actually happened.

    Returns a fitted confidence -> P(correct) curve, or None when there is
    not enough evidence to fit one honestly.
    """
    if len(confidences) < MIN_RECORDS_TO_FIT:
        return None

    x = np.asarray(confidences, dtype=float)
    y = np.asarray([1.0 if c else 0.0 for c in corrects], dtype=float)

    edges = np.arange(0.0, float(x.max()) + BIN_WIDTH, BIN_WIDTH)
    if len(edges) < 2:
        return None
    index = np.clip(np.digitize(x, edges) - 1, 0, len(edges) - 2)

    bin_x, bin_y, bin_w = [], [], []
    for b in range(len(edges) - 1):
        mask = index == b
        count = int(mask.sum())
        if count < MIN_BIN_COUNT:
            continue
        bin_x.append(float(x[mask].mean()))
        bin_y.append(float(y[mask].mean()))
        bin_w.append(count)

    if len(bin_x) < 2:
        return None

    # y_min is THIS ASSET's base rate, not 0.5 -- see the module docstring.
    reg = IsotonicRegression(y_min=base_rate, y_max=1.0,
                            increasing=True, out_of_bounds="clip")
    reg.fit(bin_x, bin_y, sample_weight=bin_w)
    return reg


def save(calibrators: dict[str, IsotonicRegression], asset_key: str = "gold") -> None:
    path = calibration_path(asset_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(calibrators, path)


def load(asset_key: str = "gold") -> dict[str, IsotonicRegression]:
    path = calibration_path(asset_key)
    if not path.exists():
        return {}
    try:
        return joblib.load(path)
    except Exception as exc:  # noqa: BLE001 -- a corrupt file must not stop a run
        print(f"WARNING: calibration file unreadable ({exc}); running uncalibrated.")
        return {}


def apply(calibrator: IsotonicRegression | None, signal: dict,
          base_rate: float = ensemble.BASE_RATE_UP) -> dict:
    """`signal` with confidence (and score, kept consistent) recalibrated.

    No-op when this component has no fitted calibrator yet. The rescaled
    confidence is the EXCESS over the base rate, so a component delivering
    exactly the base rate lands on 0.0 and stops moving position size at all.
    """
    if calibrator is None:
        return signal
    p_correct = float(calibrator.predict([signal["confidence"]])[0])
    span = 1.0 - base_rate
    calibrated = max((p_correct - base_rate) / span, 0.0)
    sign = 1.0 if signal["direction"] == "UP" else -1.0
    return {**signal, "confidence": calibrated, "score": calibrated * sign}


def ceilings(calibrators: dict[str, IsotonicRegression],
             base_rate: float = ensemble.BASE_RATE_UP) -> dict[str, float]:
    """Highest calibrated confidence each component can currently produce.

    XRP-Guess learned to watch this the hard way: a calibrator's ceiling fell
    below the threshold needed to open a position, and a strategy silently
    stopped trading -- no error, no log line, just a portfolio that went
    quiet. retrain.py prints this every day so the same thing cannot happen
    unnoticed here.
    """
    out = {}
    for name, calibrator in calibrators.items():
        if calibrator is None:
            continue
        probe = np.linspace(0.0, 1.0, 101)
        p = calibrator.predict(probe)
        span = 1.0 - base_rate
        out[name] = float(max((p.max() - base_rate) / span, 0.0))
    return out
