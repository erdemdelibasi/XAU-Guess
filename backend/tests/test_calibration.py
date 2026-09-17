"""The calibrator has to measure each call against the bar that call faces.

These lock a bug that had not fired yet and would have fired silently. The
module subtracted `base_rate` from every call, UP or DOWN, so a DOWN call was
asked to be right 55.7% of the time before it counted as skilful at all --
while always-DOWN is right 44.3% of the time. Everything that ran against the
drift was rescaled to a negative number and clipped to zero, and trading.py
sizes positions from that number.

It was invisible because calibration.MIN_RECORDS_TO_FIT is 180 resolved rows
and no calibrator file had ever been written. The same "caught before the
first fit" window the fitted-on-its-own-output bug was caught in.
"""
import numpy as np
import pytest

import calibration

BASE = 0.557          # gold, assets.GOLD.base_rate_up
DOWN_FLOOR = 1 - BASE  # 0.443 -- what always-DOWN scores


class _FlatCurve:
    """A fitted curve that returns one excess value whatever it is asked."""

    def __init__(self, excess):
        self.excess = excess

    def predict(self, xs):
        return np.asarray([self.excess for _ in xs])


def test_no_information_rate_is_not_the_same_on_both_sides():
    """The whole bug in one assertion. ensemble.directional_reliability has
    said this since it shipped; this module disagreed with it in silence."""
    assert calibration.no_information_rate("UP", BASE) == pytest.approx(BASE)
    assert calibration.no_information_rate("DOWN", BASE) == pytest.approx(DOWN_FLOOR)


def test_a_down_call_beating_its_own_floor_keeps_its_confidence():
    """A DOWN side right 50% of the time is skilful -- always-DOWN scores
    44.3% -- and must come back with POSITIVE confidence.

    Under the old rule this was (0.50 - 0.557) / 0.443 = -0.13, clipped to
    0.0: the component was silenced on exactly the days it was adding
    something. The excess here is 0.50 - 0.443 = 0.057.
    """
    signal = {"direction": "DOWN", "confidence": 0.4, "score": -0.4}
    out = calibration.apply(_FlatCurve(0.50 - DOWN_FLOOR), signal, BASE)

    assert out["confidence"] > 0.0
    assert out["confidence"] == pytest.approx((0.50 - DOWN_FLOOR) / (1 - DOWN_FLOOR))
    assert out["score"] < 0.0, "calibration must never flip a direction"


def test_an_up_call_at_the_base_rate_is_still_silenced():
    """The correction must not loosen the UP side: a component that just
    tracks the drift has to land on exactly zero, which is the reason this
    module refuses to calibrate against 0.5 in the first place."""
    signal = {"direction": "UP", "confidence": 0.9, "score": 0.9}
    out = calibration.apply(_FlatCurve(0.0), signal, BASE)

    assert out["confidence"] == 0.0
    assert out["score"] == 0.0


def test_the_same_excess_is_worth_more_where_perfection_is_further_away():
    """An UP call has 0.443 of room above its floor and a DOWN call 0.557, so
    an identical measured excess is a larger fraction of what was available on
    the UP side. Dividing both by one shared span would misreport one of
    them."""
    excess = 0.05
    up = calibration.apply(_FlatCurve(excess),
                           {"direction": "UP", "confidence": 0.5, "score": 0.5}, BASE)
    down = calibration.apply(_FlatCurve(excess),
                             {"direction": "DOWN", "confidence": 0.5, "score": -0.5}, BASE)

    assert up["confidence"] > down["confidence"]
    assert up["confidence"] == pytest.approx(excess / (1 - BASE))
    assert down["confidence"] == pytest.approx(excess / (1 - DOWN_FLOOR))


def test_fit_learns_skill_that_lives_only_on_the_down_side():
    """End to end, on the sample that makes the bug arithmetic rather than
    rhetorical.

    The component calls DOWN at high confidence 200 times and is right 50% of
    them. That is skill: always-DOWN scores 44.3%. Its UP calls are pure
    drift, right at the base rate.

    Old rule, pooling both sides against 0.557: the high-confidence bin scores
    (200 x 0.50 + 50 x 0.557) / 250 = 0.511, which is BELOW the floor, so the
    curve was pinned at its minimum and the component fell silent.
    New rule, each call against its own floor: the same bin scores
    200 x (0.50 - 0.443) / 250 = +0.046 of excess, and the component speaks.

    Two confidence levels, because an isotonic curve needs at least two points
    to have a shape -- fit() returns None on one, which is correct and is why
    this test does not use a single level.
    """
    confidences, corrects, directions = [], [], []

    def add(n, confidence, direction, hits):
        for i in range(n):
            confidences.append(confidence)
            directions.append(direction)
            corrects.append(i < hits)

    add(200, 0.6, "DOWN", 100)   # right 50% against a 44.3% floor: skill
    add(100, 0.3, "DOWN", 44)    # right 44%: exactly the floor, no skill
    add(50, 0.6, "UP", 28)       # 56%: the drift, nothing more
    add(50, 0.3, "UP", 28)

    curve = calibration.fit(confidences, corrects, directions, BASE)
    assert curve is not None, "400 rows is well past MIN_RECORDS_TO_FIT"

    down = calibration.apply(curve, {"direction": "DOWN", "confidence": 0.6,
                                     "score": -0.6}, BASE)
    assert down["confidence"] > 0.0, "the skill was in the sample all along"

    quiet = calibration.apply(curve, {"direction": "DOWN", "confidence": 0.3,
                                      "score": -0.3}, BASE)
    assert quiet["confidence"] < down["confidence"], "and it is graded, not a vote"


def test_fit_refuses_a_thin_sample():
    """Unchanged: isotonic on a handful of rows is how a lucky tail becomes a
    maximum position. MIN_RECORDS_TO_FIT is the guard."""
    n = calibration.MIN_RECORDS_TO_FIT - 1
    assert calibration.fit([0.5] * n, [True] * n, ["UP"] * n, BASE) is None


def test_fit_will_not_guess_a_direction():
    """A confidence without its direction cannot be scored against anything.
    Raising beats defaulting to UP, which would silently rebuild the bug."""
    with pytest.raises(ValueError):
        calibration.fit([0.5] * 200, [True] * 200, ["UP"] * 199, BASE)


def test_the_file_name_carries_the_scale():
    """The curve's MEANING changed on 2026-09-17 while its shape did not, so a
    stale file would be read as the new quantity without raising. The version
    in the path is what makes an old file simply not found."""
    assert "_v2" in calibration.calibration_path("gold").name
    assert calibration.calibration_path("gold") != calibration.calibration_path("silver")
