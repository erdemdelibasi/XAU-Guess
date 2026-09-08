"""Feature construction for gold: price-derived technicals plus macro drivers.

Two deliberate departures from XRP-Guess's indicators.py, both forced by
measurement rather than taste.

1. **No period scaling.** That project ran on 15-minute candles and multiplied
   every classic indicator window by 4 so "RSI-14" still spanned 14 hours.
   Here the bar IS a day, so RSI-14 means 14 days -- the horizon the textbook
   values were designed for. Nothing to scale.

2. **Close-to-close, not high-low, wherever there is a choice.** ~11% of the
   GC=F daily history (and ~5% of the modern era) are "flat bars" where Yahoo
   has a settlement print but no intraday range, so open=high=low=close. The
   close is real -- it tracks GLD at r=0.737 -- but the range is fabricated.
   research/panel.py keeps those bars and flags them rather than dropping
   them, because deleting a session silently turns the next day's return into
   a two-day return. The cost of keeping them is that any high/low-based
   measure reads a zero range on those days. So volatility here is the
   standard deviation of close-to-close returns, not ATR, and the Donchian
   channel used for breakouts is built from CLOSES rather than highs -- a
   breakout defined on highs would be triggered by the flat bars' collapsed
   range at random.

The macro half has no equivalent in XRP-Guess at all. That project had no
fundamental anchor to reach for and said so. Gold does: it is a dollar price
for an asset that pays no yield, so the dollar and the cost of holding cash
are mechanically connected to it. research/drivers.py measured which of those
connections merely *explain* gold (contemporaneous, untradeable -- silver at
r=0.78, the dollar at r=-0.40) and which actually *lead* it. Only the leading
ones are built into features here; the rest would be lookahead dressed up as
insight.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD, SMAIndicator
from ta.volatility import BollingerBands

# Drivers that survived research/drivers.py's out-of-sample Bonferroni test
# (|t| > 3.29 on the held-out half, with a sign consistent between halves),
# confirmed by research/lags.py to be genuine leads rather than calendar
# misalignment. The lag structure is the evidence:
#
#   tip   lag 0 r=+0.206, lag+1 r=+0.088 (t=+6.6)  -- decaying tail, real
#   ief   lag 0 r=+0.164, lag+1 r=+0.066 (t=+5.2)  -- same shape
#   vix   lag 0 r=-0.008, lag+1 r=-0.068 (t=-5.4)  -- NO same-day relation
#                                                      at all, pure lead
#
# Silver is the control that proves the method: r=0.783 the same day and
# exactly nothing (r=-0.016) the next, i.e. a huge contemporaneous
# relationship does not by itself manufacture a lag+1 tail.
LEADING_DRIVERS = ("tip", "ief", "vix")

# Effective duration of both TIP and IEF, in years -- they are deliberately a
# matched-duration pair so their ratio isolates inflation expectations rather
# than a duration mismatch. Used to convert an ETF price move into the yield
# move it implies (see add_macro_columns).
BOND_ETF_DURATION_YEARS = 7.5

# Score scaling. Every one of these was measured on the 25-year panel and set
# so the 90th percentile of the underlying quantity maps to ~1.0 -- i.e. the
# score saturates on roughly the most extreme 10% of sessions and keeps its
# gradation everywhere else.
#
# This is not cosmetic. The first version guessed these, and two of them
# clipped constantly: macd saturated on 44.9% of sessions (median |score|
# 0.881) and real_yield on 49.1% (median 0.976). A score pinned at +-1 half
# the time is a coin, not a measurement -- it throws away exactly the
# gradation the ensemble is supposed to weigh.
MACD_SCALE = 175.0        # of macd_hist / close
EMA_CROSS_SCALE = 52.0    # of ema9 / ema21 - 1
SMA200_SCALE = 6.5        # of close / sma200 - 1
BOND_SCALE = 166.0        # of the tip/ief daily return
VIX_SCALE = 2.4           # divisor on the daily VIX point change
# Divisor on the ONE-DAY real-yield-proxy change, in percentage points. Its
# p90 is 0.078pp, so dividing by 0.078 puts a p90 move at a full score
# (saturation ~10%, median |score| ~0.36 -- in line with every other scorer
# here).
#
# TWO corrections are baked into this one number and both were measured.
# First the divisor was 6.0, a pre-duration-fix figure that left the term
# contributing a median |score| of 0.009 -- a weighted component silently
# doing nothing. Then it became 0.17, correct for a FIVE-day change.
# research/realrate.py measured that the five-day window is the wrong window:
# against the next day's return the one-day change clears the Bonferroni bar
# in both metals (gold t=-4.74, silver t=-3.65) and the five-day change
# clears it in neither (t=-2.06, t=-2.74). Every other measured lead in this
# project is a one-day change -- tip_chg, ief_chg, vix_chg (research/
# drivers.py) -- and this term was the only one built on five days.
#
# The scale had to move WITH the window: at 0.17 the one-day change would
# have saturated on 1.1% of sessions with a median |score| of 0.161, i.e.
# the same silent-term failure in a new place. Changing a window without
# re-measuring its divisor is how that bug happens.
#
# WHAT THE CHANGE COSTS, because it is not free and the backtest said so.
# Replaying both windows through backtest.py across the full cost ladder and
# both metals: Calmar moved by an average of -0.003 for `technical` and
# -0.002 for `ensemble`, i.e. nothing, in a band of +-0.02 -- but TURNOVER
# nearly doubled (gold `technical` 377 -> 659 trades, silver 379 -> 718),
# because a one-day change flips sign far more often than a five-day one.
# At the 150 bp bank rung that shows up as real damage: gold `technical`
# Calmar 0.20 -> 0.18.
#
# It is kept anyway, and the reasoning should be checkable rather than taken
# on trust: the five-day term was measured to carry NO next-day lead in
# either metal, so reverting would mean keeping a weighted term with no
# measured content purely because acting on it is quieter. The honest
# summary is the one this project keeps arriving at -- a real signal that is
# expensive to act on (compare macro_signal.py's own docstring).
REAL_YIELD_SCALE = 0.078

# Kept as features even though they don't lead on their own: they describe the
# regime a prediction is being made in, which a tree model can condition on
# even when their own directional correlation is ~0.
#
# Both metals appear here and whichever is the asset's own is simply absent
# from its panel, so the loop skips it (see assets.macro_symbols_for). The
# surviving one is ALSO copied to `counterpart_chg`, which is what
# ml_model.FEATURE_COLUMNS actually names -- that way gold's model and
# silver's model take the same-shaped feature vector instead of one carrying
# `silver_chg` and the other `gold_chg`, which would make the two models
# gratuitously incompatible and their feature-count guards asymmetric.
CONTEXT_DRIVERS = ("dxy", "us10y", "silver", "gold", "spx")


def add_indicator_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Append price-derived indicator columns to a daily OHLCV frame."""
    out = df.copy()
    close = out["close"]

    out["rsi14"] = RSIIndicator(close, window=14).rsi()

    macd = MACD(close, window_slow=26, window_fast=12, window_sign=9)
    out["macd"] = macd.macd()
    out["macd_signal"] = macd.macd_signal()
    out["macd_hist"] = macd.macd_diff()

    out["ema9"] = EMAIndicator(close, window=9).ema_indicator()
    out["ema21"] = EMAIndicator(close, window=21).ema_indicator()
    out["ema50"] = EMAIndicator(close, window=50).ema_indicator()
    out["sma200"] = SMAIndicator(close, window=200).sma_indicator()

    bb = BollingerBands(close, window=20, window_dev=2)
    out["bb_pct"] = bb.bollinger_pband()

    # Trend state as ratios rather than raw levels: gold went from $270 to
    # $4400 across this panel, so any feature carrying a price level would
    # let a tree split on "which decade is it" instead of on market state.
    out["ema9_21"] = out["ema9"] / out["ema21"] - 1.0
    out["px_sma200"] = close / out["sma200"] - 1.0
    out["px_ema50"] = close / out["ema50"] - 1.0

    out["return_1d"] = close.pct_change(1)
    out["return_5d"] = close.pct_change(5)
    out["return_20d"] = close.pct_change(20)
    out["return_60d"] = close.pct_change(60)

    # Close-to-close volatility, not ATR -- see module docstring on flat bars.
    daily_ret = close.pct_change()
    out["vol_20d"] = daily_ret.rolling(20).std()
    out["vol_60d"] = daily_ret.rolling(60).std()
    # Is the market unusually agitated relative to its own recent norm?
    out["vol_ratio"] = out["vol_20d"] / out["vol_60d"]

    # Donchian position from CLOSES (flat bars would corrupt a high/low one).
    roll_max = close.rolling(20).max()
    roll_min = close.rolling(20).min()
    span = (roll_max - roll_min).replace(0, np.nan)
    out["donchian_pct"] = (close - roll_min) / span

    return out


def add_macro_columns(df: pd.DataFrame, drivers: tuple[str, ...] = LEADING_DRIVERS) -> pd.DataFrame:
    """Append macro-driver features. Expects the panel's macro columns present.

    `drivers` is the asset's OWN measured leading set (assets.Asset.
    leading_drivers), not a shared constant: research/compare.py found `ief`
    clears the out-of-sample Bonferroni bar for gold (t=+3.92) and misses it
    for silver (t=+2.56). Feeding a non-leading series in as though it led
    adds a weighted term carrying noise where evidence should be.

    Every column produced here is a CHANGE observable at or before the close
    of the row it sits on, so a model consuming row t to predict t+1 sees
    nothing from the future. Missing macro series simply produce no columns
    (fail-soft, as in fetch_data.get_macro_daily).
    """
    out = df.copy()

    for name in tuple(drivers) + CONTEXT_DRIVERS:
        if name not in out.columns:
            continue
        if name in ("vix", "us10y"):
            # Already a level in percent/points -- a difference is the change.
            out[f"{name}_chg"] = out[name].diff()
            out[f"{name}_chg5"] = out[name].diff(5)
        else:
            out[f"{name}_chg"] = out[name].pct_change()
            out[f"{name}_chg5"] = out[name].pct_change(5)

    # The counterpart metal under one stable name, whichever asset this is.
    for candidate in ("silver", "gold"):
        if f"{candidate}_chg" in out.columns:
            out["counterpart_chg"] = out[f"{candidate}_chg"]
            out["counterpart_chg5"] = out[f"{candidate}_chg5"]
            break

    # Gold/silver ratio: a precious-metals regime marker. High and rising
    # historically marks fear-driven gold buying that silver isn't confirming.
    #
    # It must mean the SAME THING in both panels, so the numerator is always
    # gold. In the gold panel the counterpart column is `silver` and `close`
    # is gold; in the silver panel it is the other way round. Computing
    # close/counterpart blindly would give silver's panel the RECIPROCAL --
    # a series that moves the opposite way, feeding a feature named
    # `gs_ratio_z` whose sign is inverted relative to its name.
    if "silver" in out.columns:
        ratio = out["close"] / out["silver"]          # gold panel
    elif "gold" in out.columns:
        ratio = out["gold"] / out["close"]            # silver panel
    else:
        ratio = None
    if ratio is not None:
        out["gs_ratio"] = ratio
        out["gs_ratio_z"] = (ratio - ratio.rolling(250).mean()) / ratio.rolling(250).std()

    # Real-yield proxy. The true series (FRED DFII10) is the single best
    # fundamental driver of gold, but FRED is not reachable from every network
    # (see fetch_data.FRED_CSV), so this reconstructs the SHAPE from two ETFs
    # that are always available: TIP is inflation-protected, IEF is nominal of
    # similar duration, so TIP/IEF tracks breakeven inflation and nominal
    # minus breakeven is the real yield. A proxy for direction and change, not
    # for the level -- never present it as a real-yield quote.
    if {"tip", "ief"} <= set(out.columns):
        out["breakeven_proxy"] = out["tip"] / out["ief"]
        out["breakeven_chg"] = out["breakeven_proxy"].pct_change(5)
        if "us10y" in out.columns:
            # Both terms must be in PERCENTAGE POINTS of yield or the
            # subtraction is meaningless. us10y.diff(5) already is. The
            # TIP/IEF ratio is a PRICE change, and converting a bond price
            # move into a yield move means dividing by duration:
            #   yield change (pp) ~= -price change (%) / duration (years)
            # TIP and IEF both sit around 7.5 years, so a 1% relative move of
            # TIP against IEF is roughly 0.13pp of breakeven, not 1pp.
            #
            # Multiplying by a flat 100 (the first version here) inflated the
            # breakeven term 7.5x: measured on this panel its median magnitude
            # came out 0.321 against the yield term's 0.075, so "real yield
            # change" was in fact 4x an ETF-ratio change wearing a real
            # yield's name, and the resulting score saturated at +-1 on 49.1%
            # of all sessions.
            out["real_yield_chg"] = (
                out["us10y"].diff(5) - (100.0 / BOND_ETF_DURATION_YEARS) * out["breakeven_chg"]
            )
            # The one-day version, which is what the technical scorer reads.
            # Both windows are kept deliberately: research/realrate.py's
            # paired walk-forward found the ML model cannot tell them apart
            # (gold p=0.875, silver p=0.529 -- it already carries us10y_chg,
            # tip_chg and ief_chg and reconstructs the combination itself),
            # so `real_yield_chg` stays in FEATURE_COLUMNS untouched. Swapping
            # it would have changed a column's VALUES while keeping its NAME,
            # which is the one kind of feature change predict.py's guard
            # cannot see -- every saved model would have gone on scoring a
            # differently-distributed column with no error anywhere.
            out["real_yield_chg1"] = (
                out["us10y"].diff() - (100.0 / BOND_ETF_DURATION_YEARS)
                * out["breakeven_proxy"].pct_change()
            )

    return out


def build_features(df: pd.DataFrame, drivers: tuple[str, ...] = LEADING_DRIVERS) -> pd.DataFrame:
    """Full feature frame: technicals + macro, in the order the models expect."""
    return add_macro_columns(add_indicator_columns(df), drivers)


# --------------------------------------------------------------------------
# Rule-based technical signal
# --------------------------------------------------------------------------

def _score_rsi(rsi: float) -> float:
    """Mean-reversion read: oversold is bullish, overbought bearish."""
    if pd.isna(rsi):
        return 0.0
    if rsi <= 30:
        return 1.0
    if rsi >= 70:
        return -1.0
    return (50 - rsi) / 20.0


def _score_macd(macd_hist: float, price: float) -> float:
    """MACD histogram as a fraction of price, so the scale survives gold going
    from $270 to $4400 -- an absolute histogram threshold would mean something
    completely different at each end of this panel."""
    if pd.isna(macd_hist) or pd.isna(price) or price == 0:
        return 0.0
    return float(np.clip((macd_hist / price) * MACD_SCALE, -1, 1))


def _score_trend(ema9_21: float, px_sma200: float) -> float:
    """Trend agreement across two very different speeds. Gold trends hard --
    the 200-day is what separates its bull phases from its long dead zones --
    so a fast crossover that disagrees with the slow trend is discounted."""
    parts = []
    if pd.notna(ema9_21):
        parts.append(float(np.clip(ema9_21 * EMA_CROSS_SCALE, -1, 1)))
    if pd.notna(px_sma200):
        parts.append(float(np.clip(px_sma200 * SMA200_SCALE, -1, 1)))
    if not parts:
        return 0.0
    return float(np.mean(parts))


def _score_bollinger(bb_pct: float) -> float:
    if pd.isna(bb_pct):
        return 0.0
    return float(np.clip((0.5 - bb_pct) * 2, -1, 1))


def _score_vix(vix_chg: float) -> float:
    """A VIX spike is BEARISH for gold the next day, which is the opposite of
    the safe-haven story people expect. Measured, not assumed: lag+1 r=-0.068
    (t=-5.4) with no same-day relation at all (research/lags.py). The usual
    reading is forced liquidation -- in a real scare, gold is the liquid thing
    you can still sell to meet margin, so it gets sold first and bid later."""
    if pd.isna(vix_chg):
        return 0.0
    return float(np.clip(-vix_chg / VIX_SCALE, -1, 1))


def _score_real_yield(real_yield_chg: float) -> float:
    """Rising real yields raise the opportunity cost of holding a zero-yield
    asset, so gold should fall. Sign is negative by construction.

    Reads the ONE-day change (see REAL_YIELD_SCALE): the five-day change this
    used to take has no measured next-day lead in either metal, and the
    one-day change has one in both.
    """
    if pd.isna(real_yield_chg):
        return 0.0
    return float(np.clip(-real_yield_chg / REAL_YIELD_SCALE, -1, 1))


def _score_bonds(tip_chg: float, ief_chg: float) -> float:
    """Bond ETFs up = yields down = supportive for gold. These are the two
    strongest measured leads (t=+6.6 and +5.2) so they get their own term
    rather than being folded into the real-yield proxy."""
    parts = [v for v in (tip_chg, ief_chg) if pd.notna(v)]
    if not parts:
        return 0.0
    return float(np.clip(np.mean(parts) * BOND_SCALE, -1, 1))


WEIGHTS = {
    "rsi": 0.12,
    "macd": 0.14,
    "trend": 0.22,
    "bollinger": 0.08,
    "vix": 0.14,
    "real_yield": 0.12,
    "bonds": 0.18,
}


def technical_signal(features: pd.DataFrame) -> dict:
    """Latest row of `features` -> one directional call.

    Returns {"direction": "UP"/"DOWN", "confidence": 0..1, "score": -1..1,
    "components": {...}}. Weights are a starting allocation across terms with
    measured leads, NOT a fitted result -- research/edge.py is what says
    whether the whole thing clears the break-even wall, and nothing here
    should be read as tuned until it does.
    """
    last = features.iloc[-1]

    scores = {
        "rsi": _score_rsi(last.get("rsi14")),
        "macd": _score_macd(last.get("macd_hist"), last.get("close")),
        "trend": _score_trend(last.get("ema9_21"), last.get("px_sma200")),
        "bollinger": _score_bollinger(last.get("bb_pct")),
        "vix": _score_vix(last.get("vix_chg")),
        "real_yield": _score_real_yield(last.get("real_yield_chg1")),
        "bonds": _score_bonds(last.get("tip_chg"), last.get("ief_chg")),
    }
    combined = float(np.clip(sum(scores[k] * WEIGHTS[k] for k in WEIGHTS), -1, 1))

    return {
        "direction": "UP" if combined >= 0 else "DOWN",
        "confidence": min(abs(combined), 1.0),
        "score": combined,
        "components": scores,
    }


def recent_volatility(df: pd.DataFrame, window: int = 20) -> float:
    """Std-dev of daily close-to-close returns, as a fraction."""
    vol = df["close"].pct_change().rolling(window).std().iloc[-1]
    return float(vol) if pd.notna(vol) else 0.0


def estimate_pct_change(score: float, volatility: float) -> float:
    """A -1..1 directional score -> an expected percentage move, sized by how
    volatile gold has actually been lately rather than by a fixed constant."""
    return float(score) * volatility
