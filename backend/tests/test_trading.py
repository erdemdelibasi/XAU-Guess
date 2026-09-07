"""Tests for the pure decision functions in trading.py.

Only the DB-free logic is covered here. Signal-producing code (Yahoo,
Binance, Supabase, Anthropic) has no tests -- it is validated by backtest.py
and by watching live rows, exactly as in XRP-Guess.

Most of these lock in a behaviour the research measured, so that a future
edit cannot quietly undo a finding. Where that is the case the test says
which measurement it is protecting.
"""
import numpy as np
import pytest

import trading


# --------------------------------------------------------------------------
# vol_scale / trend_scale
# --------------------------------------------------------------------------

def test_vol_scale_caps_at_one_no_leverage():
    """Calm markets must not produce leverage. Simulating a levered gold
    position at spot cost would flatter every result in the project."""
    assert trading.vol_scale(0.05) == 1.0
    assert trading.vol_scale(0.0001) == 1.0


def test_vol_scale_cuts_in_turbulence():
    # Twice the target volatility should halve exposure.
    assert trading.vol_scale(2 * trading.TARGET_VOLATILITY) == pytest.approx(0.5)


def test_vol_scale_handles_missing_volatility():
    """NaN early in a series must default to invested, not to zero -- a
    warmup period is not a risk signal."""
    assert trading.vol_scale(float("nan")) == 1.0
    assert trading.vol_scale(0.0) == 1.0


def test_trend_scale_stays_partly_invested_when_trend_is_off():
    """A hard exit is what made research/defense.py's drawdown-stop variants
    WORSE than holding (55.3% max drawdown against 44.4%): they sold the low
    and bought back higher. Staying partly invested keeps the recovery."""
    off = trading.trend_scale(price=100.0, trend_average=120.0)
    assert off == trading.TREND_OFF_EXPOSURE
    assert 0.0 < off < 1.0, "a full exit re-introduces the sell-the-low failure"


def test_trend_scale_defaults_to_invested_without_history():
    assert trading.trend_scale(100.0, float("nan")) == 1.0


# --------------------------------------------------------------------------
# compute_target_exposure
# --------------------------------------------------------------------------

def test_buyhold_ignores_every_signal():
    """buyhold is the benchmark. If anything can move it, the comparison the
    whole project reports against stops being a benchmark."""
    for direction, confidence, vol in (("DOWN", 1.0, 0.9), ("UP", 0.0, 0.01)):
        assert trading.compute_target_exposure(
            "buyhold", 100.0, 200.0, vol, direction, confidence) == trading.MAX_EXPOSURE


def test_mechanical_strategies_ignore_the_direction_signal():
    """research/defense.py's result works BECAUSE these forecast nothing --
    they react to realised volatility, which is autocorrelated. Wiring a
    forecast in would silently convert them into something never measured."""
    for name in trading.MECHANICAL:
        up = trading.compute_target_exposure(name, 100.0, 90.0, 0.15, "UP", 1.0)
        down = trading.compute_target_exposure(name, 100.0, 90.0, 0.15, "DOWN", 1.0)
        assert up == down, f"{name} responded to the direction signal"


def test_signal_tilt_is_two_sided():
    """A bullish signal must be able to RAISE exposure, not merely fail to
    lower it. With base == MAX the tilt clips away and only ever cuts."""
    bullish = trading.compute_target_exposure("technical", 100.0, 90.0, 0.15, "UP", 1.0)
    neutral = trading.compute_target_exposure("technical", 100.0, 90.0, 0.15, "UP", 0.0)
    bearish = trading.compute_target_exposure("technical", 100.0, 90.0, 0.15, "DOWN", 1.0)
    assert bearish < neutral < bullish


def test_signal_tilt_is_bounded_by_max_signal_tilt():
    """research/tilt.py measured the direction signal's contribution to
    position sizing at approximately zero (+0.011 Calmar). It is allowed a
    small voice on purpose; widening this without new measurement would be
    acting on a result that does not exist."""
    neutral = trading.compute_target_exposure("technical", 100.0, 90.0, 0.15, "UP", 0.0)
    extreme = trading.compute_target_exposure("technical", 100.0, 90.0, 0.15, "UP", 1.0)
    assert extreme - neutral <= trading.MAX_SIGNAL_TILT + 1e-9


def test_exposure_never_leaves_zero_to_max():
    rng = np.random.default_rng(0)
    for _ in range(500):
        target = trading.compute_target_exposure(
            rng.choice(list(trading.STRATEGIES) + ["ensemble"]),
            price=float(rng.uniform(1, 5000)),
            trend_average=float(rng.uniform(1, 5000)),
            volatility=float(rng.uniform(0.01, 2.0)),
            direction=rng.choice(["UP", "DOWN"]),
            confidence=float(rng.uniform(0, 1)),
        )
        assert 0.0 <= target <= trading.MAX_EXPOSURE


# --------------------------------------------------------------------------
# compute_rebalance
# --------------------------------------------------------------------------

def test_rebalance_holds_inside_the_band():
    """Rebalancing to every wobble is pure cost. XRP-Guess measured a tight
    band causing severe fee erosion."""
    result = trading.compute_rebalance(cash=500.0, ounces=0.5, price=1000.0,
                                       target_exposure=0.50)
    assert result["action"] == "HOLD"


def test_rebalance_buys_when_under_target():
    result = trading.compute_rebalance(cash=1000.0, ounces=0.0, price=1000.0,
                                       target_exposure=0.80)
    assert result["action"] == "BUY"
    assert result["usd_amount"] == pytest.approx(800.0)


def test_rebalance_sells_when_over_target():
    result = trading.compute_rebalance(cash=0.0, ounces=1.0, price=1000.0,
                                       target_exposure=0.50)
    assert result["action"] == "SELL"
    assert result["ounce_amount"] == pytest.approx(0.5)


def test_rebalance_never_spends_more_cash_than_it_has():
    result = trading.compute_rebalance(cash=10.0, ounces=0.0, price=1000.0,
                                       target_exposure=1.0)
    assert result["usd_amount"] <= 10.0


def test_full_exit_leaves_no_dust():
    """ounces*price divided back by price does not round-trip exactly, and the
    leftover reads as an open position on the dashboard. XRP-Guess had a
    portfolio holding 5.7e-14 units display as LONG."""
    result = trading.compute_rebalance(cash=0.0, ounces=0.1234567890123,
                                       price=4431.7, target_exposure=0.0)
    assert result["action"] == "SELL"
    assert result["ounce_amount"] == 0.1234567890123


def test_rebalance_handles_worthless_portfolio():
    result = trading.compute_rebalance(cash=0.0, ounces=0.0, price=1000.0,
                                       target_exposure=0.8)
    assert result["action"] == "HOLD"


def test_rebalance_round_trip_costs_exactly_two_fees():
    """A BUY then an immediate SELL back to flat should lose the round-trip
    cost and nothing else -- the invariant backtest.Portfolio relies on.

    The second fee is charged on what survived the first, not on the original
    stake, so the total is 1-(1-f)^2 rather than 2f. At f=0.0005 that is
    0.09999% against a naive 0.1% -- a difference of 2.5 cents on $1000,
    which is exactly the size of error that hides comfortably inside a
    "close enough" tolerance and then compounds across 6000 backtest steps.
    """
    price, start = 4000.0, 1000.0
    decision = trading.compute_rebalance(start, 0.0, price, 1.0)
    gross = decision["usd_amount"]
    ounces = (gross - gross * trading.FEE_RATE) / price
    cash = start - gross

    back = trading.compute_rebalance(cash, ounces, price, 0.0)
    assert back["action"] == "SELL"
    proceeds = back["ounce_amount"] * price
    final = cash + proceeds - proceeds * trading.FEE_RATE

    expected = start * (1 - trading.FEE_RATE) ** 2
    assert final == pytest.approx(expected, rel=1e-12)
    # (1-f)^2 = 1 - 2f + f^2, so compounding leaves slightly MORE than the
    # naive 2f estimate would predict -- the f^2 term is the second fee not
    # being charged on money the first one already took.
    assert final > start * (1 - 2 * trading.FEE_RATE)


def test_strategies_list_is_the_complete_set_exactly_once():
    """predict.py iterates trading.STRATEGIES once and nothing else. It used
    to iterate ("ensemble", *STRATEGIES), running the ensemble twice a day.
    That never raised -- _state_table() routes the name to portfolio_state
    either way, so the second pass re-read the row it had just rebalanced and
    held -- which is precisely why it could have stayed there: a duplicate
    that costs a round trip and looks like nothing from the outside."""
    assert len(trading.STRATEGIES) == len(set(trading.STRATEGIES))
    assert "ensemble" in trading.STRATEGIES
    assert "buyhold" in trading.STRATEGIES, "the benchmark must always run"


def test_target_volatility_is_per_asset_not_global():
    """Silver realises 1.86x gold's volatility for the same return. Sizing it
    against gold's 15% budget would peg it near a third of full exposure
    forever -- "hold less silver", not volatility targeting, and never tested.
    This is the single easiest way for a second asset to be quietly wrong."""
    import assets

    calm = 0.15
    gold_exposure = trading.compute_target_exposure(
        "voltarget", 100.0, 90.0, calm, "UP", 0.0, assets.GOLD.target_volatility)
    silver_exposure = trading.compute_target_exposure(
        "voltarget", 100.0, 90.0, calm, "UP", 0.0, assets.SILVER.target_volatility)
    assert gold_exposure == pytest.approx(1.0)
    assert silver_exposure == pytest.approx(1.0)

    # At silver's own realised level, gold's budget would cut it to ~45%.
    turbulent = assets.SILVER.target_volatility
    with_own_budget = trading.compute_target_exposure(
        "voltarget", 100.0, 90.0, turbulent, "UP", 0.0, assets.SILVER.target_volatility)
    with_gold_budget = trading.compute_target_exposure(
        "voltarget", 100.0, 90.0, turbulent, "UP", 0.0, assets.GOLD.target_volatility)
    assert with_own_budget == pytest.approx(1.0)
    assert with_gold_budget < 0.6
