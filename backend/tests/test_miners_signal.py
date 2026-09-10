"""Locks the three boundaries the miners signal was adopted inside.

research/miners.py measured that GDX predicts the metal's NEXT DAY and is
indistinguishable from noise at the five-day horizon production trains on.
Every test here guards a place where that distinction could be lost by a
plausible, well-meant edit -- and none of them would raise an exception on
their own. They would just quietly make the system claim something that was
never measured.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ensemble  # noqa: E402
import indicators  # noqa: E402
import miners_signal  # noqa: E402
import ml_model  # noqa: E402
import trading  # noqa: E402


def _frame(**cols) -> pd.DataFrame:
    return pd.DataFrame({k: [v] for k, v in cols.items()})


# ---------------------------------------------------------------------------
# Boundary 1: it is a strategy, never a five-day forecast component
# ---------------------------------------------------------------------------

def test_miners_is_a_strategy_but_not_an_ensemble_component():
    """The horizon is one day; ensemble.combine() pools a FIVE-day forecast.

    Adding `miners` to COMPONENTS would give a one-day view a vote on a
    five-day question, at full weight, with no error anywhere -- and the
    paired A/B measured the five-day contribution as indistinguishable from
    noise (p=0.13 gold, p=0.99 silver). This is the same exclusion, for the
    same kind of reason, that kanal_finans.py carries.
    """
    assert "miners" in trading.STRATEGIES
    assert "miners" not in ensemble.COMPONENTS


def test_miners_is_not_mechanical():
    """It is a forecast, so it must not join the risk rules.

    trading.MECHANICAL exists so a future edit cannot wire a forecast into
    the one part of this system that was measured to work precisely because
    it does not forecast (research/defense.py, README section 5).
    """
    assert "miners" not in trading.MECHANICAL


# ---------------------------------------------------------------------------
# Boundary 2: gdx_chg must never become a model feature
# ---------------------------------------------------------------------------

def test_gdx_is_available_to_signals_but_not_to_the_model():
    """The column exists, and is deliberately outside FEATURE_COLUMNS.

    Putting it in would buy nothing measurable at the five-day horizon and
    cost 18.6% of the panel, because ml_model.build_feature_frame drops rows
    carrying a NaN feature and GDX only starts in 2006. The cost is silent:
    the model would still train, still score, and simply never see 2001-2006
    again.
    """
    assert "gdx" in indicators.SIGNAL_ONLY_SERIES
    assert "gdx_chg" not in ml_model.FEATURE_COLUMNS
    assert "gdx_chg5" not in ml_model.FEATURE_COLUMNS


def test_add_macro_columns_emits_gdx_without_touching_the_feature_count():
    """A panel carrying gdx produces gdx_chg AND the same feature list as one
    without it. This is the assertion that would fail the moment someone adds
    `gdx_chg` to FEATURE_COLUMNS in order to "use the data we already fetch"."""
    n = 40
    base = pd.DataFrame({
        "time": pd.date_range("2020-01-01", periods=n, tz="UTC"),
        "close": np.linspace(100.0, 120.0, n),
        "dxy": np.linspace(90.0, 95.0, n),
        "us10y": np.linspace(2.0, 3.0, n),
        "silver": np.linspace(20.0, 24.0, n),
        "spx": np.linspace(3000.0, 3500.0, n),
        "tip": np.linspace(110.0, 115.0, n),
        "ief": np.linspace(100.0, 104.0, n),
        "vix": np.linspace(15.0, 25.0, n),
    })
    without = indicators.add_macro_columns(base, drivers=("tip", "ief", "vix"))
    with_gdx = indicators.add_macro_columns(
        base.assign(gdx=np.linspace(30.0, 36.0, n)), drivers=("tip", "ief", "vix"))

    assert "gdx_chg" not in without.columns
    assert "gdx_chg" in with_gdx.columns
    assert ml_model.available_features(with_gdx) == ml_model.available_features(without)


# ---------------------------------------------------------------------------
# Boundary 3: the signal's own contract
# ---------------------------------------------------------------------------

def test_scale_puts_a_p90_day_at_full_scale():
    """GDX_SCALE is 1/p90 of |gdx_chg|, measured on both panels (0.03973).

    A scale is the one constant class this project has got wrong three times
    (see CLAUDE.md on real_yield_chg). If someone re-tunes it, this test says
    what the number is supposed to MEAN rather than merely what it is.
    """
    p90_move = 0.03973
    score = miners_signal.miners_signal(_frame(gdx_chg=p90_move))["score"]
    assert score == pytest.approx(1.0, abs=0.02)
    # And a typical day must land mid-scale, not pinned at the clip: a score
    # saturated half the time is a coin flip wearing a measurement's clothes.
    typical = miners_signal.miners_signal(_frame(gdx_chg=0.012))["score"]
    assert 0.15 < typical < 0.60


def test_sign_is_positive_miners_up_means_metal_up():
    """Measured partial correlation +0.206, not a story about safe havens.

    macro_signal's vix term is negative and counter-intuitive, so the risk of
    someone "fixing" this one's sign by analogy is real.
    """
    assert miners_signal.miners_signal(_frame(gdx_chg=0.02))["direction"] == "UP"
    assert miners_signal.miners_signal(_frame(gdx_chg=-0.02))["direction"] == "DOWN"


@pytest.mark.parametrize("frame", [
    pd.DataFrame(),                       # no rows at all
    pd.DataFrame({"close": [100.0]}),     # panel without the series
    pd.DataFrame({"gdx_chg": [np.nan]}),  # series present, value missing
])
def test_abstains_instead_of_guessing(frame):
    """Confidence 0.0, never an exception and never a fabricated direction.

    fetch_data.get_macro_daily is fail-soft per series, so a dead GDX must
    leave a hole rather than stop the daily run for both metals. And every
    row before 2006 is legitimately NaN. compute_target_exposure reads
    confidence 0.0 as "no tilt", so the portfolio holds its base exposure.
    """
    out = miners_signal.miners_signal(frame)
    assert out["confidence"] == 0.0
    assert out["score"] == 0.0


def test_abstention_leaves_the_portfolio_at_its_base_exposure():
    """The abstain path must be inert, not a hidden SELL.

    An abstaining signal returns direction "UP" with confidence 0.0. If a
    future edit made it return "DOWN" instead, the tilt would flip sign and
    every GDX outage would quietly become a sell order.
    """
    out = miners_signal.miners_signal(pd.DataFrame({"gdx_chg": [np.nan]}))
    target = trading.compute_target_exposure(
        "miners", price=100.0, trend_average=95.0, volatility=0.15,
        direction=out["direction"], confidence=out["confidence"])
    assert target == pytest.approx(trading.SIGNAL_BASE_EXPOSURE)


def test_extreme_move_clips_rather_than_running_away():
    """A 20% miner day is a real event and must not produce exposure > 1."""
    out = miners_signal.miners_signal(_frame(gdx_chg=0.20))
    assert out["score"] == 1.0
    target = trading.compute_target_exposure(
        "miners", price=100.0, trend_average=95.0, volatility=0.15,
        direction=out["direction"], confidence=out["confidence"])
    assert target <= trading.MAX_EXPOSURE
