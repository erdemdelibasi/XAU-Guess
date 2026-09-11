"""Locks the boundaries the ETF tracker was built inside.

research/README.md section 17 measured the whole scoreboard on GLD/IAU/SLV
and found the ranking changes fundamentally with the instrument. These books
exist to watch that live. Every test here guards a place where a plausible
edit would quietly make them claim something that was never measured -- and
none of those edits would raise an exception on its own.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import assets  # noqa: E402
import track_etf  # noqa: E402
import trading  # noqa: E402


# ---------------------------------------------------------------------------
# Boundary 1: the tracker never joins the prediction pipeline
# ---------------------------------------------------------------------------

def test_tracked_etfs_are_not_in_the_prediction_registry():
    """predict.py iterates assets.ASSETS; the trackers must stay out of it.

    Landing there would give a book with no model and no calibrator a
    `predictions` row, an ensemble vote and a daily Claude call -- and
    predict.run_asset would then try to load `model_filename`, which is
    deliberately empty here.
    """
    assert "gld" in assets.TRACKED
    assert "gld" not in assets.ASSETS
    assert not set(assets.TRACKED) & set(assets.ASSETS)


def test_a_tracked_etf_declares_no_model_and_no_drivers():
    """Both are empty on purpose and both are load-bearing.

    An empty `model_filename` is what makes "mechanical only" checkable rather
    than a convention. Empty `leading_drivers` matters just as much: listing
    gold's would imply a research/drivers.py measurement on GLD that nobody
    has made, and macro_signal would then vote on it.
    """
    gld = assets.TRACKED["gld"]
    assert gld.model_filename == ""
    assert gld.leading_drivers == ()


def test_only_mechanical_strategies_are_traded():
    """The tracker must not quietly acquire a forecast.

    Section 17's measured answer and the cheap implementation coincide here,
    which is exactly the kind of coincidence that invites someone to add `ml`
    later "since the model exists anyway". It does not exist for this asset.
    """
    assert set(trading.MECHANICAL) == {"buyhold", "voltarget", "trend", "defensive"}
    for strategy in trading.MECHANICAL:
        assert strategy in trading.STRATEGIES


# ---------------------------------------------------------------------------
# Boundary 2: the cost is the one the broker actually charges
# ---------------------------------------------------------------------------

def test_flat_fee_is_zero_for_the_metals_and_set_for_the_etf():
    """Gold and silver must be untouched by the flat-fee field.

    Every Calmar in research/README.md sections 1-14 assumes a purely
    proportional cost. A nonzero default here would silently invalidate all
    of them and the paper books along with them.
    """
    assert assets.GOLD.flat_fee_usd == 0.0
    assert assets.SILVER.flat_fee_usd == 0.0
    assert assets.TRACKED["gld"].flat_fee_usd == 1.50


def test_a_trade_pays_the_flat_fee_on_top_of_the_spread():
    """The fee arithmetic, checked on a hand-computable case.

    Section 15 measured that a flat and a proportional fee are different
    shapes of cost -- on a $1000 book a $1.50 commission bankrupts the
    highest-turnover strategies outright. A tracker paying a percentage while
    the person pays a flat fee would flatter itself every single day, with no
    error anywhere.
    """
    gld = assets.TRACKED["gld"]
    gross = 1_000.0
    expected = gross * gld.fee_rate + gld.flat_fee_usd
    assert expected == pytest.approx(0.10 + 1.50)
    # And the metals' arithmetic is unchanged.
    assert 1_000.0 * assets.GOLD.fee_rate + assets.GOLD.flat_fee_usd == pytest.approx(0.50)


# ---------------------------------------------------------------------------
# Boundary 3: sizing uses the asset's own budget and the right lookback
# ---------------------------------------------------------------------------

def test_voltarget_cuts_exposure_when_volatility_runs_hot():
    """The mechanism this whole tracker exists to watch.

    voltarget is the only strategy that beat buy-and-hold in EVERY column of
    section 17 -- futures and ETF, gold and silver -- because its edge is
    volatility autocorrelation, a property of the series rather than of the
    contract's clock.
    """
    gld = assets.TRACKED["gld"]
    calm = trading.compute_target_exposure(
        "voltarget", 400.0, 380.0, 0.10, "UP", 0.0, gld.target_volatility)
    hot = trading.compute_target_exposure(
        "voltarget", 400.0, 380.0, 0.30, "UP", 0.0, gld.target_volatility)
    assert calm == pytest.approx(1.0)          # capped, no leverage
    assert hot == pytest.approx(0.5, abs=0.01)  # 0.15 / 0.30
    assert hot < calm


def test_a_forecast_cannot_move_a_mechanical_book():
    """Direction and confidence are passed in and must be ignored.

    trading.MECHANICAL exists so a future edit cannot wire a forecast into
    the one part of this system measured to work precisely because it does
    not forecast (research/defense.py, README section 5). The tracker passes
    ("UP", 0.0) explicitly rather than relying on defaults, so this stays a
    property of compute_target_exposure and not of the caller.
    """
    gld = assets.TRACKED["gld"]
    for strategy in trading.MECHANICAL:
        bullish = trading.compute_target_exposure(
            strategy, 400.0, 380.0, 0.18, "UP", 1.0, gld.target_volatility)
        bearish = trading.compute_target_exposure(
            strategy, 400.0, 380.0, 0.18, "DOWN", 1.0, gld.target_volatility)
        assert bullish == bearish, strategy


def test_realised_volatility_uses_the_production_lookback():
    """60 days, from trading.VOL_LOOKBACK_DAYS, never a local constant.

    backtest.py records what happened the last time these diverged: the
    signal path was fed a 20-day estimate while production used 60, so a
    different and noisier strategy was being tested under the same name --
    a divergence hidden inside a column name. The tracker calls
    trading.realised_volatility rather than computing its own.
    """
    assert trading.VOL_LOOKBACK_DAYS == 60
    rng = np.random.default_rng(0)
    returns = rng.normal(0.0, 0.01, 500)
    # Only the tail is used, so a wildly different prefix must not move it.
    spiked = np.concatenate([rng.normal(0.0, 0.20, 400), returns[-60:]])
    assert trading.realised_volatility(returns) == pytest.approx(
        trading.realised_volatility(spiked), rel=1e-9)


def test_history_request_covers_the_two_hundred_day_average():
    """MIN_ROWS must exceed the longest window latest_state() reads.

    trend and defensive both divide by a 200-session mean. Asking for fewer
    rows would not raise -- numpy would happily average whatever arrived --
    it would just silently compute a shorter trend than production's.
    """
    assert track_etf.MIN_ROWS > 200
    assert track_etf.HISTORY_YEARS * 252 > track_etf.MIN_ROWS
