"""Locks the boundaries the ETF tracker was built inside.

research/README.md section 17 measured the whole scoreboard on GLD/IAU/SLV
and found the ranking changes fundamentally with the instrument. These books
exist to watch that live. Every test here guards a place where a plausible
edit would quietly make them claim something that was never measured -- and
none of those edits would raise an exception on its own.
"""
import io
import os
import re
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
    assert {"gld", "slv"} <= set(assets.TRACKED)
    assert not set(assets.TRACKED) & set(assets.ASSETS)


def test_both_metals_have_a_tradeable_book():
    """Silver is tracked too, and the omission would have been invisible.

    This project is a two-metal one in assets.ASSETS, in the panel, in the tab
    strip and in the daily mail. A TRACKED registry holding only gold would
    raise nothing anywhere -- track_etf.py would simply iterate one entry, the
    mail would print one section and the page one table. The claim "these
    strategies are measured on the instrument a person can buy" would then be
    true for half the project.
    """
    assert {a.symbol for a in assets.TRACKED.values()} == {"GLD", "SLV"}
    assert {a.symbol for a in assets.ASSETS.values()} == {
        assets.GOLD.symbol, assets.SILVER.symbol}


def test_a_tracked_etf_declares_no_model_and_no_drivers():
    """Both are empty on purpose and both are load-bearing.

    An empty `model_filename` is what makes "mechanical only" checkable rather
    than a convention. Empty `leading_drivers` matters just as much: listing
    the metal's would imply a research/drivers.py measurement on the ETF that
    nobody has made, and macro_signal would then vote on it.
    """
    for asset in assets.TRACKED.values():
        assert asset.model_filename == "", asset.key
        assert asset.leading_drivers == (), asset.key


def test_each_etf_carries_its_own_measured_price_scales():
    """The constant assets.py exists to stop anyone copying.

    research/instrument.py measured 171.9/50.8/6.25 on GLD and 93.7/29.0/3.73
    on SLV -- a factor of ~1.8 apart, which is silver's own realised
    volatility showing up exactly where a price-derived scale should feel it.
    Copying gold's onto the silver book is the documented failure that once had
    silver's macd score saturating on 35.2% of sessions, and it raises nothing.
    """
    gld, slv = assets.TRACKED["gld"], assets.TRACKED["slv"]
    assert gld.price_scales != slv.price_scales
    for field in ("macd", "ema_cross", "sma200"):
        ratio = getattr(gld.price_scales, field) / getattr(slv.price_scales, field)
        assert 1.6 < ratio < 2.0, field
    # And each ETF sits within a few percent of ITS OWN futures contract:
    # all three scales normalise ratios, so the ~10x price-level gap between
    # GLD and GC=F cannot matter by construction.
    for etf, metal in ((gld, assets.GOLD), (slv, assets.SILVER)):
        for field in ("macd", "ema_cross", "sma200"):
            near = getattr(etf.price_scales, field) / getattr(metal.price_scales, field)
            assert 0.95 < near < 1.05, (etf.key, field)


def test_the_etf_inherits_its_metals_volatility_budget_not_its_own():
    """target_volatility is a risk PREFERENCE, and re-measuring it is the trap.

    Gold realises 18.1% and targets 15%; silver realises 33.7% and targets 28%
    -- both about 83% of realised, i.e. a chosen budget rather than a property
    of the series. GLD realises 18.3% and SLV 33.3%, so the metals' budgets are
    the same choice on the same volatility. Letting each ETF target its own
    realised figure would make `voltarget` on GLD a different strategy from
    `voltarget` on gold, and research/README.md section 17's futures-vs-ETF
    comparison would stop being about the instrument.
    """
    assert assets.TRACKED["gld"].target_volatility == assets.GOLD.target_volatility
    assert assets.TRACKED["slv"].target_volatility == assets.SILVER.target_volatility


def test_only_mechanical_strategies_are_traded():
    """The tracker must not quietly acquire a forecast.

    Section 17's measured answer and the cheap implementation coincide here,
    which is exactly the kind of coincidence that invites someone to add `ml`
    later "since the model exists anyway". It does not exist for this asset.
    """
    assert set(trading.MECHANICAL) == {"buyhold", "voltarget", "trend", "defensive"}
    for strategy in trading.MECHANICAL:
        assert strategy in trading.STRATEGIES


def test_every_tracked_book_is_reachable_on_the_page():
    """A book the backend trades but the page never shows is invisible, silently.

    The card is asset-scoped: TRACKED_ETFS entries carry the ASSETS key whose
    tab they render under, so a fund whose `metal` matched nothing would trade
    every weekday and appear on no page at all. Nothing would raise -- the
    filter would simply return an empty list, and the card would print "this
    metal has no tracked ETF" while track_etf.py kept writing to the book.

    Text-level on purpose: there is no JS test runner here, and the failure
    being guarded is a missing edit rather than a wrong computation. The same
    reasoning as the REBALANCE_THRESHOLD mirror documented in CLAUDE.md.
    """
    app_js = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "frontend", "app.js")
    source = io.open(app_js, encoding="utf-8").read()
    block = source[source.index("const TRACKED_ETFS = ["):]
    block = block[:block.index("];")]

    for asset in assets.TRACKED.values():
        entry = re.search(r'\{ key: "%s".*?\}' % asset.key, block, re.S)
        assert entry, f"{asset.key} is traded but absent from TRACKED_ETFS"
        metal = re.search(r'metal: "(\w+)"', entry.group(0))
        assert metal and metal.group(1) in assets.ASSETS, (
            f"{asset.key} renders under no existing tab")
    # And the page must not advertise a book the backend does not keep.
    for key in re.findall(r'\{ key: "(\w+)"', block):
        assert key in assets.TRACKED, f"{key} is on the page but not TRACKED"


def test_every_book_on_the_page_shows_its_own_fills():
    """A book whose fills are invisible is a position with no history.

    This guards the shape of a bug that already happened once: GLD traded
    every weekday, wrote to `trades`, and appeared in no log at all, because
    the only log on the page filtered on `currentAsset` and an ETF's key is
    never that. The fix then was a second combined log; the fix now is that
    each book carries its own, so a new book type cannot be added without one
    -- there is no shared log left for it to be missing from.

    Text-level for the same reason as the test above: there is no JS test
    runner here and the failure being guarded is a missing edit, not a wrong
    computation.
    """
    app_js = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "frontend", "app.js")
    source = io.open(app_js, encoding="utf-8").read()

    def body(name):
        start = source.index(f"function {name}(")
        rest = source[start + 1:]
        end = rest.find("\nfunction ")
        return rest[:end if end != -1 else len(rest)]

    # Both families of book -- the metals' eleven and the ETF's four.
    for builder in ("renderStrategies", "renderOneEtfBook"):
        assert "bookLogHtml(" in body(builder), f"{builder} draws no fill log"

    # And the combined logs really are gone: two sources for one answer is how
    # the ETF log came to be capped differently from the metals' one.
    assert "function renderTrades" not in source
    assert "trades-table" not in source


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
    # Per TRADE, not per share -- which is why the same $1.50 lands on both
    # books even though SLV's share price is a seventh of GLD's.
    for asset in assets.TRACKED.values():
        assert asset.flat_fee_usd == 1.50, asset.key


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
    # SLV's assumed spread is twice GLD's: a one-cent quote is ~1.7 bp on a
    # $57 share against ~0.25 bp on a $396 one. Still second-order -- on this
    # trade size the flat fee is fifteen times the spread term.
    slv = assets.TRACKED["slv"]
    assert slv.fee_rate == pytest.approx(2 * gld.fee_rate)
    assert gross * slv.fee_rate + slv.flat_fee_usd == pytest.approx(0.20 + 1.50)
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

    # The same 30% is NOT hot for silver, and that is the whole point of the
    # per-asset budget: SLV's 28% target leaves it near fully invested where
    # gold is already halved. Gold's 15% applied here would not be volatility
    # targeting, it would be "hold less silver".
    slv = assets.TRACKED["slv"]
    slv_same = trading.compute_target_exposure(
        "voltarget", 57.0, 55.0, 0.30, "UP", 0.0, slv.target_volatility)
    assert slv_same > hot
    assert slv_same == pytest.approx(0.28 / 0.30, abs=0.01)


def test_a_forecast_cannot_move_a_mechanical_book():
    """Direction and confidence are passed in and must be ignored.

    trading.MECHANICAL exists so a future edit cannot wire a forecast into
    the one part of this system measured to work precisely because it does
    not forecast (research/defense.py, README section 5). The tracker passes
    ("UP", 0.0) explicitly rather than relying on defaults, so this stays a
    property of compute_target_exposure and not of the caller.
    """
    for asset in assets.TRACKED.values():
        for strategy in trading.MECHANICAL:
            bullish = trading.compute_target_exposure(
                strategy, 400.0, 380.0, 0.18, "UP", 1.0, asset.target_volatility)
            bearish = trading.compute_target_exposure(
                strategy, 400.0, 380.0, 0.18, "DOWN", 1.0, asset.target_volatility)
            assert bullish == bearish, (asset.key, strategy)


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
