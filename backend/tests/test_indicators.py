"""Tests for the technical scorers' scale calibration and for the macro
context handed to the model.

Both lock a MEASUREMENT rather than a preference, in the style of the rest of
this suite: the scale constants are documented as "the 90th percentile of the
underlying quantity maps to ~1.0", and that claim was true for gold and false
for silver for as long as the two shared one set of numbers.
"""
import numpy as np
import pandas as pd
import pytest

import assets
import indicators
import macro_signal


# --------------------------------------------------------------------------
# Per-asset price scales
# --------------------------------------------------------------------------

# p90 of |macd_hist / close| on each metal's own 25-year panel, measured by
# the same procedure that produced the constants (see indicators.py).
GOLD_P90_MACD = 0.00581
SILVER_P90_MACD = 0.01071


def test_price_scales_are_per_asset_not_shared():
    """The three price-derived scales must differ between the metals.

    Silver realises 1.86x gold's volatility, so a quantity like
    macd_hist/close is ~1.8x larger on silver at every percentile. Sharing
    gold's constants raises nothing -- it just clips silver's macd term to
    +-1 on 35.2% of sessions instead of 10.6%, which is the exact failure
    indicators.py's scale block was written to prevent, arriving through the
    side door of a second asset.
    """
    gold, silver = assets.GOLD.price_scales, assets.SILVER.price_scales
    assert gold != silver
    for attr in ("macd", "ema_cross", "sma200"):
        ratio = getattr(gold, attr) / getattr(silver, attr)
        assert 1.6 < ratio < 2.0, (
            f"{attr}: gold/silver scale ratio {ratio:.2f} no longer tracks "
            "silver's measured 1.86x volatility -- re-measure, don't nudge")


def test_each_scale_puts_that_assets_p90_at_full_score():
    """The property the constants are documented to have. If a future edit
    changes a window or a formula without re-measuring the divisor, this is
    what notices -- that is precisely how REAL_YIELD_SCALE went silent once."""
    for asset, p90 in ((assets.GOLD, GOLD_P90_MACD), (assets.SILVER, SILVER_P90_MACD)):
        price = 100.0
        score = indicators._score_macd(p90 * price, price, asset.price_scales.macd)
        assert abs(score) == pytest.approx(1.0, abs=0.05), asset.key


def test_gold_scales_saturate_a_typical_silver_move():
    """The bug itself, stated as a test. A move that is merely ordinary for
    silver must stay gradable under silver's scale and pins under gold's."""
    price = 100.0
    typical = SILVER_P90_MACD * price
    own = indicators._score_macd(typical, price, assets.SILVER.price_scales.macd)
    borrowed = indicators._score_macd(typical, price, assets.GOLD.price_scales.macd)
    assert abs(own) < 1.0 + 1e-9
    assert abs(borrowed) == 1.0, "gold's scale must be the one that clips here"

    # And at HALF that move -- an unremarkable silver session -- the borrowed
    # scale already reports nearly twice the conviction.
    half = typical / 2
    assert (indicators._score_macd(half, price, assets.GOLD.price_scales.macd)
            > 1.7 * indicators._score_macd(half, price, assets.SILVER.price_scales.macd))


def test_technical_signal_actually_reads_the_scales_it_is_given():
    """A signature that accepts `scales` and ignores them would pass every
    test above while shipping the original bug."""
    frame = pd.DataFrame([{
        "rsi14": 50.0, "macd_hist": 0.8, "close": 100.0,
        "ema9_21": 0.0, "px_sma200": 0.0, "bb_pct": 0.5,
        "vix_chg": 0.0, "real_yield_chg1": 0.0, "tip_chg": 0.0, "ief_chg": 0.0,
    }])
    gold = indicators.technical_signal(frame, assets.GOLD.price_scales)
    silver = indicators.technical_signal(frame, assets.SILVER.price_scales)
    assert gold["components"]["macd"] != silver["components"]["macd"]
    assert gold["score"] != silver["score"]


def test_scorers_stay_inside_minus_one_to_one():
    rng = np.random.default_rng(0)
    for _ in range(500):
        scales = rng.choice([assets.GOLD.price_scales, assets.SILVER.price_scales])
        assert -1.0 <= indicators._score_macd(
            float(rng.normal(0, 5)), float(rng.uniform(1, 5000)), scales.macd) <= 1.0
        assert -1.0 <= indicators._score_trend(
            float(rng.normal(0, 0.1)), float(rng.normal(0, 0.5)), scales) <= 1.0


# --------------------------------------------------------------------------
# describe_context
# --------------------------------------------------------------------------

def _panel_row(counterpart: str) -> pd.DataFrame:
    """One row shaped like a real panel. Only ONE metal column exists, because
    assets.macro_symbols_for swaps an asset's own series for its counterpart."""
    return pd.DataFrame([{
        "dxy": 99.16, "us10y": 4.78, "vix": 14.53, "spx": 7718.6,
        counterpart: 66.05 if counterpart == "silver" else 4429.8,
        "gs_ratio": 67.07, "gs_ratio_z": -0.08,
    }])


@pytest.mark.parametrize("counterpart", ["silver", "gold"])
def test_context_always_carries_the_counterpart_level(counterpart):
    """Gold's panel holds silver's close and silver's holds gold's. Asking
    only for "silver" -- the original list -- gave the SILVER prompt a context
    with no counterpart price in it at all, while still printing the
    gold/silver ratio: a ratio with neither leg on screen."""
    context = macro_signal.describe_context(_panel_row(counterpart))
    assert context[counterpart] is not None
    assert context["gold_silver_ratio"] is not None
    present = [k for k in ("gold", "silver") if context.get(k) is not None]
    assert present == [counterpart], (
        "exactly one metal is ever in a panel, and it must be the counterpart")


def test_context_reports_a_missing_series_as_none_not_a_crash():
    thin = pd.DataFrame([{"dxy": 99.0}])
    context = macro_signal.describe_context(thin)
    assert context["vix"] is None and context["gold_silver_ratio"] is None
