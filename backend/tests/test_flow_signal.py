"""Locks the boundaries the breakout rule was shipped inside.

research/flow.py measured this rule against a bar declared before the results
were seen and it did NOT clear it. What shipped is therefore a panel and not a
portfolio, and that distinction is the thing most likely to be lost by a
plausible, well-meant edit -- "the chart is already there, wire it to a book".

None of the tests below would raise on their own. They guard places where the
system would quietly claim something that was never measured, or would draw a
rule other than the one that was scored.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import assets as assets_module  # noqa: E402
import ensemble  # noqa: E402
import flow_signal  # noqa: E402
import ml_model  # noqa: E402
import trading  # noqa: E402


def synthetic(n: int = 400, seed: int = 7, trend: float = 0.0004) -> pd.DataFrame:
    """A daily OHLCV frame with real ranges and real volume.

    Deliberately NOT flat bars: the ETF series this rule reads has genuine
    intraday ranges, and a fixture made of settlement prints would exercise
    only the degenerate branch of every high/low computation here.
    """
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(trend, 0.011, n)))
    span = close * np.abs(rng.normal(0.008, 0.003, n))
    high = close + span * rng.uniform(0.2, 0.8, n)
    low = close - span * rng.uniform(0.2, 0.8, n)
    return pd.DataFrame({
        "time": pd.date_range("2020-01-01", periods=n, freq="B", tz="UTC"),
        "open": close, "high": high, "low": low, "close": close,
        "volume": rng.uniform(5e6, 2e7, n),
    })


# ---------------------------------------------------------------------------
# Boundary 1: it is a panel, never a portfolio and never a forecast component
# ---------------------------------------------------------------------------

def test_breakout_is_not_a_paper_portfolio():
    """The pre-registered bar was not cleared, so no book may run on it.

    On the buyable instrument at the $10,000 rung, out of sample: gold won on
    Calmar (0.566 vs 0.495) and finished 33.9% behind in money; silver lost on
    both. Adding "breakout" to STRATEGIES would create two $1,000 books that
    trade every entry and exit, and nothing in the system would object --
    schema.sql seeds portfolios from this list, and the dashboard renders
    whatever it finds.
    """
    assert "breakout" not in trading.STRATEGIES
    assert "breakout" not in trading.MECHANICAL


def test_breakout_is_not_an_ensemble_component():
    """`confidence` here counts agreeing oscillators, not a probability.

    ensemble.combine() pools each component's LIKELIHOOD RATIO against the
    asset's measured base rate. Feeding it a number that is "4 of 6 indicators
    agree" would be pooling an uncalibrated quantity as if it were evidence,
    and the result would look entirely normal.
    """
    assert "breakout" not in ensemble.COMPONENTS
    assert "flow" not in ensemble.COMPONENTS


def test_flow_columns_stay_out_of_the_model_feature_set():
    """The rule's columns are not five-day features and were never tested as such.

    research/flow.py measured every one of the nine instruments against the
    five-day forward return and not one reached |t| = 1, let alone the
    Bonferroni bar. Adding one to FEATURE_COLUMNS would also drop every row
    before the value area exists -- build_feature_frame drops NaN rows -- for
    a column measured to carry nothing.
    """
    forbidden = {"flow", "avwap", "vah", "val", "poc", "fib_pos", "cci20",
                 "mom10", "stoch_k"}
    assert forbidden.isdisjoint(set(ml_model.FEATURE_COLUMNS))


# ---------------------------------------------------------------------------
# Boundary 2: the two metals do not share a configuration
# ---------------------------------------------------------------------------

def test_breakout_params_are_per_asset_not_global():
    """Silver's training half chose a wider stop and gold's floor beat silver's.

    Copying gold's numbers onto silver raises nothing: the panel would simply
    draw a rule that was never scored, under a caption quoting the score of a
    different one. Same failure as
    test_trading.test_target_volatility_is_per_asset_not_global.
    """
    gold = assets_module.get("gold").breakout
    silver = assets_module.get("silver").breakout
    assert gold is not None and silver is not None
    assert gold.stop_sigmas != silver.stop_sigmas
    assert gold.flat_exposure != silver.flat_exposure
    assert gold.etf_symbol == "GLD" and silver.etf_symbol == "SLV"


def test_tracked_etfs_have_no_breakout_config():
    """GLD/SLV are the SIGNAL's series, not a second asset with its own panel.

    The metal's panel already reads the ETF. Giving the ETF book its own
    breakout config would put the identical rule on the page twice under two
    names, and a reader comparing them would find them agreeing perfectly and
    conclude something had been confirmed.
    """
    for asset in assets_module.TRACKED.values():
        assert asset.breakout is None


# ---------------------------------------------------------------------------
# Boundary 3: no lookahead
# ---------------------------------------------------------------------------

def test_value_area_describes_the_window_that_ENDED_yesterday():
    """A breakout must be measured against a level that predates it.

    Without the shift, a session that breaks out adds its own volume at its
    own price and helps build the level it is breaking. The rule would still
    trade, the backtest would still run, and the entries would be subtly
    easier than any live run could reproduce.
    """
    df = synthetic()
    shifted = flow_signal.volume_profile(df, window=60)
    unshifted = flow_signal.volume_profile(df, window=60).shift(-1)
    # Row t's value area equals the unshifted profile of the window ending t-1.
    assert shifted["vah"].iloc[80] == pytest.approx(unshifted["vah"].iloc[79])
    # And the first `window` rows carry nothing at all, rather than a partial
    # profile that would look like a real level.
    assert shifted["vah"].iloc[:60].isna().all()


def test_a_future_price_cannot_change_an_earlier_row():
    """Truncating the frame must not move any level that already existed.

    The sharpest lookahead test available without a clock: if row 200 is the
    same whether or not rows 201..399 exist, nothing downstream of 200 was
    read. The anchored VWAP is the one at real risk here -- its anchor is an
    argmin over a trailing window, and a window that reached forward would
    re-anchor the whole series the moment a new low printed.
    """
    df = synthetic()
    full = flow_signal.add_flow_columns(df)
    cut = flow_signal.add_flow_columns(df.iloc[:201].reset_index(drop=True))
    for column in ("avwap", "avwap_anchor", "vah", "val", "poc", "flow", "rsi14"):
        a = full[column].iloc[190:201].to_numpy(dtype=float)
        b = cut[column].iloc[190:201].to_numpy(dtype=float)
        assert np.allclose(a, b, equal_nan=True), column


# ---------------------------------------------------------------------------
# Boundary 4: the two vote implementations are one rule
# ---------------------------------------------------------------------------

def test_scalar_and_vectorised_votes_agree_on_every_row():
    """`confirmation_votes` is what the UI stores; `vote_totals` is what trades.

    They encode the same six thresholds twice, in two shapes, because the
    state machine needs a column and track_breakout.py needs a dict. That is
    the drift this project keeps finding -- so the two are scored on the same
    rows here rather than trusted to stay in step.
    """
    frame = flow_signal.add_flow_columns(synthetic())
    vectorised = flow_signal.vote_totals(frame)
    for i in range(0, len(frame), 17):
        row = frame.iloc[i]
        scalar = sum(flow_signal.confirmation_votes(row).values())
        assert scalar == vectorised.iloc[i], f"row {i}"


def test_missing_readings_abstain_rather_than_voting_down():
    """A NaN oscillator is "no opinion", not "bearish".

    The warm-up rows have no RSI and no MACD. Scoring those as -1 would make
    every series start with a six-vote bearish block and would push the first
    possible entry weeks later than the rule specifies -- silently, and in the
    direction that looks conservative.
    """
    row = pd.Series({c: float("nan") for c in flow_signal.VOTE_COLUMNS})
    assert set(flow_signal.confirmation_votes(row).values()) == {0}


# ---------------------------------------------------------------------------
# Boundary 5: the position machine holds, and the stop only ratchets
# ---------------------------------------------------------------------------

def test_the_stop_never_moves_down_within_a_position():
    """A stop that follows price down is not a stop.

    research/defense.py measured drawdown-STOP variants making maximum
    drawdown worse than holding (55.3% against 44.4%) by selling the low. A
    stop that could loosen is the same failure wearing a tighter name.
    """
    frame = flow_signal.add_flow_columns(synthetic(n=900, seed=3))
    path = flow_signal.breakout_path(frame)
    entries = np.flatnonzero(path["state"].diff().to_numpy() == 1)
    assert len(entries) > 0, "fixture never entered -- the test proves nothing"
    state = path["state"].to_numpy()
    stop = path["stop"].to_numpy(dtype=float)
    for start in entries:
        end = start
        while end + 1 < len(state) and state[end + 1]:
            end += 1
        within = stop[start:end + 1]
        assert np.all(np.diff(within) >= -1e-9), f"stop loosened in the run at {start}"


def test_a_position_outlives_the_session_that_opened_it():
    """The claim of a breakout rule is that it HOLDS. A one-day mean is not it.

    If the average holding period collapsed to a session or two, this would
    have quietly become a daily signal wearing a regime rule's name -- which
    is precisely the difference research/flow.py measured it as, and the
    reason it is not scored by hit rate.
    """
    frame = flow_signal.add_flow_columns(synthetic(n=900, seed=3))
    path = flow_signal.breakout_path(frame)
    entries = int((path["state"].diff() == 1).sum())
    assert entries > 0
    assert path["state"].sum() / entries > 3.0


def test_cooldown_blocks_an_immediate_re_entry():
    """Without it, a stop sells and buys back days later at a worse price.

    XRP-Guess measured 235 of 236 stop-losses re-triggering within ten hours
    with no cooldown. The daily-cadence version of that failure is invisible
    in a Calmar column and expensive in a fee column.
    """
    frame = flow_signal.add_flow_columns(synthetic(n=900, seed=3))
    path = flow_signal.breakout_path(frame, cooldown_days=flow_signal.COOLDOWN_DAYS)
    state = path["state"].to_numpy()
    exits = np.flatnonzero(np.diff(state) == -1)
    for i in exits:
        after = state[i + 1: i + 1 + flow_signal.COOLDOWN_DAYS]
        assert not after.any(), f"re-entered within the cooldown at {i}"


# ---------------------------------------------------------------------------
# Boundary 6: the live dict carries what the panel promises
# ---------------------------------------------------------------------------

def test_live_signal_reports_the_levels_that_end_the_position():
    """A panel showing a position but not its stop is showing half a decision."""
    frame = flow_signal.add_flow_columns(synthetic(n=900, seed=3))
    result = flow_signal.flow_signal(frame, assets_module.get("gold").breakout)
    assert set(result["votes"]) == set(flow_signal.VOTE_COLUMNS)
    for key in ("close", "vah", "val", "poc", "avwap", "flow"):
        assert key in result["levels"]
    if result["state"]:
        assert result["levels"]["stop"] is not None
        assert result["levels"]["entry_price"] is not None


def test_live_signal_uses_the_asset_configuration_it_is_given():
    """Gold's and silver's stops differ, so their paths must be allowed to.

    A `flow_signal(df)` that ignored `params` would return gold's answer for
    silver on silver's own series -- correct-looking, and not the rule the
    card's caption quotes.
    """
    frame = flow_signal.add_flow_columns(synthetic(n=900, seed=11))
    tight = flow_signal.breakout_path(frame, stop_sigmas=1.0)
    loose = flow_signal.breakout_path(frame, stop_sigmas=5.0)
    assert tight["state"].sum() != loose["state"].sum()


def test_empty_frame_abstains_instead_of_raising():
    """A dead Yahoo series must blank the card, not break the run."""
    result = flow_signal.flow_signal(pd.DataFrame())
    assert result["state"] == 0
    assert result["confidence"] == 0.0
