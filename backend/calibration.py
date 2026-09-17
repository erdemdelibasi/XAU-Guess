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
The target is P(correct) measured against the no-information rate, not
against 0.5. Gold rises 55.7% of the time over this horizon and silver 53.9%,
so a component whose UP calls are right 55% of the time has calibrated
confidence of ZERO on gold, not 0.10. Leaving the floor at 0.5 would quietly
reintroduce the illusion that tracking the drift is skill; sharing gold's
rate with silver would do a smaller version of the same thing.

AND THAT FLOOR IS NOT THE SAME ON BOTH SIDES (fixed 2026-09-17)
---------------------------------------------------------------
This module used to subtract `base_rate` from every call, UP or DOWN. That is
the exact mistake ensemble.py carries four counters to avoid, and its own
docstring spells out why: a component that always says UP is right base_rate
of the time by construction, but one that always says DOWN is right only
1 - base_rate of the time. Measuring a DOWN call against 0.557 asks it to
clear a bar HARDER than the metal's own tendency, so a DOWN call right 50% of
the time -- genuinely skilful, since always-DOWN scores 44.3% -- was rescaled
to a negative number and clipped to zero. The calibrator was systematically
silencing whichever side the drift runs against, and trading.py sizes
positions from the result.

It had not fired yet: MIN_RECORDS_TO_FIT is 180 resolved rows and no
calibrator file has ever been written. Same shape as the "fitted on its own
output" bug recorded below, and caught at the same moment -- before the first
fit, which is the only cheap one.

THE FIX KEEPS ONE CURVE PER COMPONENT, NOT TWO
-----------------------------------------------
The curve is fitted on EXCESS over each sample's own no-information rate
(`correct - no_information_rate(that call's direction)`) instead of on raw
P(correct). Every sample is then measured against the bar that applies to it,
while both sides still share one curve and one sample.

Two curves was the obvious alternative and was rejected on sample size:
components lean heavily one way -- the ML model says UP on ~75% of days -- so
a per-side fit would need roughly three years of resolved rows before the
thin side earned a curve, and a component whose UP side is calibrated while
its DOWN side runs raw is sizing two directions on two different scales. What
is genuinely per-side is the FLOOR, which this fix makes per-side. The SHAPE
(more stated confidence -> more real skill) is assumed common to both sides,
and that assumption is written here rather than left implicit.

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
    the skill it delivered ON THAT METAL, and the two differ enough
    (different base rates, different driver sets) that sharing one file would
    calibrate silver against gold's history.

    The `_v2` is a guard, not decoration. On 2026-09-17 the curve stopped
    predicting P(correct) and started predicting EXCESS over the call's own
    no-information rate -- same file, same shape, different meaning, and a
    stale v1 file would be read as the new quantity without raising anything.
    A new name makes an old file simply not found, which falls back to
    running uncalibrated: the correct behaviour rather than a silent
    misreading. Bump it again if the quantity ever changes again."""
    return Path(__file__).parent / "models" / f"calibration_{asset_key}_v2.joblib"


# ~9 months of trading days. High because this system produces one resolved
# row per day; see the module docstring.
MIN_RECORDS_TO_FIT = 180
BIN_WIDTH = 0.05
MIN_BIN_COUNT = 15


def no_information_rate(direction: str, base_rate: float) -> float:
    """What a component with NO skill is right, on this side of the call.

    UP: the metal simply rises that often. DOWN: it falls that often. On gold
    those are 0.557 and 0.443, and treating them as one number is the bug in
    the module docstring. Same idea as ensemble.directional_reliability's
    `no_information_rate` argument -- one concept, and the two modules must
    not drift apart on it.
    """
    return base_rate if direction == "UP" else 1.0 - base_rate


def fit(confidences: list[float], corrects: list[bool],
        directions: list[str],
        base_rate: float = ensemble.BASE_RATE_UP) -> IsotonicRegression | None:
    """confidences: raw 0..1 confidence in the predicted direction.
    corrects: whether that predicted direction actually happened.
    directions: "UP"/"DOWN" for that same call. REQUIRED, because the bar a
    call has to clear depends on which way it pointed.

    Returns a fitted confidence -> EXCESS-over-no-information curve, or None
    when there is not enough evidence to fit one honestly. The output is no
    longer P(correct): it is how much better than an empty forecast the
    component is at that confidence, which is what `apply` needs and the only
    quantity that means the same thing on both sides.
    """
    if len(confidences) < MIN_RECORDS_TO_FIT:
        return None
    if len(directions) != len(confidences):
        raise ValueError("directions must line up with confidences")

    x = np.asarray(confidences, dtype=float)
    # Excess over THIS call's own bar, never over a shared one.
    y = np.asarray([(1.0 if c else 0.0) - no_information_rate(d, base_rate)
                    for c, d in zip(corrects, directions)], dtype=float)

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

    # The curve lives on the EXCESS scale, so its floor is 0.0 -- "adds
    # nothing over an empty forecast" -- rather than a probability. A negative
    # segment would mean anti-skill, which this project silences rather than
    # reads backwards (ensemble.ALLOW_INVERSION).
    reg = IsotonicRegression(y_min=0.0, y_max=1.0,
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

    No-op when this component has no fitted calibrator yet. The curve returns
    the EXCESS over the no-information rate for THIS call's direction, so a
    component delivering exactly that rate lands on 0.0 and stops moving
    position size at all.

    The excess is divided by the room that side actually has
    (1 - its own no-information rate) so the two sides come back on one 0..1
    scale. On gold that room is 0.443 for an UP call and 0.557 for a DOWN
    one: the same measured excess is worth slightly more confidence on the
    side where perfection is further away, which is why the division is not
    by a shared constant.
    """
    if calibrator is None:
        return signal
    excess = float(calibrator.predict([signal["confidence"]])[0])
    span = 1.0 - no_information_rate(signal["direction"], base_rate)
    calibrated = max(excess / span, 0.0)
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
        excess = float(calibrator.predict(probe).max())
        # The friendlier side, because the question this answers is "can this
        # component still open a trade at all". On a metal that drifts up the
        # UP side has less room to perfection, so it yields the higher
        # rescaled ceiling.
        best = max(excess / (1.0 - no_information_rate(d, base_rate))
                   for d in ("UP", "DOWN"))
        out[name] = float(max(best, 0.0))
    return out
