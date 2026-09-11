"""Per-asset configuration. One place, so what differs between metals is
visible rather than scattered.

Gold and silver are NOT the same instrument wearing different prices, and
treating them as one was the first thing measured when silver was added.
Every constant below that carries a number is measured, and the measurement
lives in `research/compare.py` (run it again if you add a third metal).

The rule this module enforces: a constant that could differ per asset must be
looked up here, never hardcoded in a signal or trading module. `BASE_RATE_UP`
is the sharp example -- ensemble.py measures every component's skill against
it, so a gold number applied to silver silently rebases silver's entire
component scoreboard.
"""
from __future__ import annotations

from dataclasses import dataclass

import fetch_data
from indicators import PriceScales


@dataclass(frozen=True)
class Asset:
    key: str                 # short id used in the DB `symbol`-adjacent columns
    symbol: str              # Yahoo ticker
    label: str               # Turkish display name (UI, logs)
    label_en: str            # English name, for prompts sent to the model
    model_filename: str
    # P(close higher over HORIZON_DAYS). ensemble.py pools every component's
    # evidence against this, so it must be the asset's own measured rate.
    base_rate_up: float
    # Annualised volatility budget for trading.vol_scale(). Set near the
    # asset's own long-run volatility so the rule spends most of its time
    # near fully invested and only cuts in genuinely turbulent markets.
    target_volatility: float
    # Round-trip cost assumed for this asset's paper portfolios, one-way.
    # Silver's bid/ask is a wider fraction of its price than gold's.
    fee_rate: float
    # The counterpart metal, joined into this asset's panel as a macro column.
    counterpart_key: str
    counterpart_symbol: str
    # Macro series measured to LEAD this asset out of sample. Not shared:
    # research/compare.py found `ief` clears the Bonferroni bar for gold
    # (t=+3.92) and misses it for silver (t=+2.56). Carrying a driver that
    # does not lead is not free -- it adds a weighted term that contributes
    # noise in place of evidence.
    leading_drivers: tuple[str, ...]
    # The three technical scale constants that depend on how volatile this
    # metal is (indicators.PriceScales). Measured as 1 / p90(|quantity|) on
    # this metal's own 25-year panel so a 90th-percentile move maps to a full
    # score -- see the block comment above indicators.BOND_SCALE for the table
    # and for what gold's numbers did to silver before this was split.
    price_scales: PriceScales
    # Per-trade commission in DOLLARS, on top of `fee_rate`. Defaults to 0.0,
    # so gold and silver -- and every number already in research/README.md --
    # are untouched.
    #
    # It exists because a proportional fee and a flat one are not the same
    # shape of cost, and research/README.md section 15 measured how far apart:
    # a percentage fee is blind to account size, a flat one depends on nothing
    # else, and on a $1000 book a $1.50 commission bankrupts the two
    # highest-turnover strategies outright. A tracker whose live book pays a
    # proportional fee while the person pays a flat one would flatter itself
    # every single day.
    flat_fee_usd: float = 0.0


GOLD = Asset(
    key="gold",
    symbol=fetch_data.GOLD_SYMBOL,
    label="Altın",
    label_en="gold",
    model_filename="xau_model.joblib",
    # P(gold closes higher over 5 trading days), 6272 sessions, 2001-2026.
    # Measured at 0.557 by research/compare.py. It was 0.552 here first --
    # read off the wrong row of research/wall.py's table -- which is a half
    # point of pure bias applied to every component's scoreboard, in the one
    # constant the whole ensemble is calibrated against.
    base_rate_up=0.557,
    # Gold's own long-run realised volatility is ~18%; 15% keeps the rule
    # mostly invested. research/defense.py's walk-forward selector picked
    # a 12-15% budget in 12 of 20 years.
    target_volatility=0.15,
    # 5 bp per side = 10 bp round trip, the "ETF / CFD" rung of
    # research/wall.py's ladder.
    fee_rate=0.0005,
    counterpart_key="silver",
    counterpart_symbol=fetch_data.SILVER_SYMBOL,
    leading_drivers=("tip", "ief", "vix"),
    # p90 over 6022 sessions: macd_hist/close 0.00581, ema9/ema21-1 0.01940,
    # close/sma200-1 0.15368. Saturation 10.6% / 4.7% / 4.7%.
    price_scales=PriceScales(macd=172.0, ema_cross=51.5, sma200=6.5),
)

SILVER = Asset(
    key="silver",
    symbol=fetch_data.SILVER_SYMBOL,
    label="Gümüş",
    label_en="silver",
    model_filename="xag_model.joblib",
    # Measured, not copied from gold -- see research/compare.py. Silver
    # rises less often than gold over the same horizon (0.539 vs 0.557).
    base_rate_up=0.539,
    # Measured 1.86x gold's realised volatility (33.7% against 18.1%) over
    # the same 25 years, for essentially the SAME return (11.7% vs 11.8%) and
    # a far worse drawdown (75.8% vs 44.4%). Gold's 15% budget applied here
    # would peg silver at a fraction of full exposure permanently -- that is
    # not volatility targeting, it is "hold less silver", and it has never
    # been tested. Scaled by the measured ratio to preserve the intent.
    target_volatility=0.28,
    # Silver's spread is a wider fraction of its price than gold's: the same
    # $0.01-0.02 tick is ~3 bp on a $67 metal against ~0.05 bp on a $4400 one,
    # and retail silver products carry visibly wider quotes.
    fee_rate=0.0010,
    counterpart_key="gold",
    counterpart_symbol=fetch_data.GOLD_SYMBOL,
    # `ief` deliberately absent: t=+2.56 out of sample, under the |t|>3.29
    # Bonferroni bar it clears for gold. See research/compare.py section 4.
    leading_drivers=("tip", "vix"),
    # Measured on SILVER's panel, not copied: p90 over 6024 sessions is
    # macd_hist/close 0.01071 (1.84x gold's), ema9/ema21-1 0.03416 (1.76x),
    # close/sma200-1 0.26876 (1.75x) -- silver's own 1.86x realised
    # volatility, showing up exactly where a price-derived scale should feel
    # it. Under gold's numbers silver's macd score saturated on 35.2% of
    # sessions with a median |score| of 0.715, i.e. it had stopped grading
    # and started voting. Nothing raised; the scoreboard just quietly moved.
    price_scales=PriceScales(macd=93.4, ema_cross=29.3, sma200=3.72),
)

ASSETS = {GOLD.key: GOLD, SILVER.key: SILVER}
DEFAULT = GOLD


# ---------------------------------------------------------------------------
# Tracked ETFs -- the instruments a person can actually buy
# ---------------------------------------------------------------------------
# Deliberately a SEPARATE registry from ASSETS, not a third entry in it.
# ASSETS is what predict.py iterates: full prediction pipeline, ML model,
# calibrator, Claude call, ensemble, a `predictions` row. None of that applies
# here and pretending otherwise would buy a daily LLM call and a third model
# file in exchange for nothing.
#
# WHY ONLY MECHANICAL STRATEGIES RUN ON THESE
# --------------------------------------------
# research/README.md section 17 re-ran the whole scoreboard on GLD/IAU/SLV in
# a common window with a flat commission. Of everything that beat buy-and-hold
# on the ETF at a $10,000 account, all but one (`ensemble`) is in
# trading.MECHANICAL -- and every MECHANICAL strategy needs price history and
# nothing else: no model, no macro panel, no Claude. The measured answer and
# the cheap implementation happen to be the same set, which is the only reason
# this is a small file rather than a third pipeline.
#
# And section 17's real finding is the one that has to stay attached to these
# books: on money rather than Calmar, NOTHING here beats buying and holding.
# `voltarget` finished $1,413 ahead of buy-and-hold over 16.1 years on a
# $10,000 GLD account -- noise -- while taking max drawdown from 45.6% to
# 39.2% and Sharpe from 0.48 to 0.59, on about 8 trades a year. That is what
# these portfolios are for: watching whether a measured RISK reduction holds
# up live, not waiting for it to make money.
GLD = Asset(
    key="gld",
    symbol="GLD",
    label="GLD (altın ETF)",
    label_en="SPDR Gold Shares",
    model_filename="",          # no model -- mechanical strategies only
    # Measured on GLD's own 20-year panel by research/instrument.py, not
    # inherited from gold: 0.553 against GC=F's 0.557.
    base_rate_up=0.553,
    # NOT re-measured, and that is deliberate. target_volatility is a risk
    # PREFERENCE rather than a property: gold realises 18.1% and targets 15%,
    # silver realises 33.7% and targets 28% -- both about 83% of realised.
    # GLD realises 18.3%, so gold's 15% budget is the same choice expressed on
    # the same volatility. Substituting GLD's own realised figure would make
    # `voltarget` here a different strategy from `voltarget` on gold, and the
    # comparison between the two columns would stop being about the instrument.
    target_volatility=0.15,
    # ASSUMPTION, not a measurement, and flagged as such: a liquid gold ETF's
    # bid/ask is roughly a basis point one-way. The commission below is the
    # term that actually matters.
    fee_rate=0.0001,
    counterpart_key="silver",
    counterpart_symbol="SLV",
    # Empty on purpose. No MECHANICAL strategy reads a macro driver, so the
    # tracker never builds a macro panel at all -- and listing gold's drivers
    # here would imply a measurement (research/drivers.py's Bonferroni bar on
    # GLD) that has not been made.
    leading_drivers=(),
    # Measured by research/instrument.py as 1/p90(|quantity|) on GLD's own
    # series: 171.9 / 50.8 / 6.25, against GC=F's 173.1 / 51.9 / 6.53. Nearly
    # identical because all three normalise RATIOS, so GLD's ~$403 and GC=F's
    # ~$4384 cannot matter by construction. Recorded rather than omitted even
    # though no MECHANICAL strategy reads them -- an empty field invites the
    # next person to copy gold's.
    price_scales=PriceScales(macd=171.9, ema_cross=50.8, sma200=6.25),
    # The user's actual broker charges this per trade regardless of size.
    flat_fee_usd=1.50,
)

TRACKED = {GLD.key: GLD}


def get(key: str) -> Asset:
    if key not in ASSETS:
        raise KeyError(f"Unknown asset {key!r}; known: {', '.join(ASSETS)}")
    return ASSETS[key]


def by_symbol(symbol: str) -> Asset:
    for asset in ASSETS.values():
        if asset.symbol == symbol:
            return asset
    raise KeyError(f"No asset configured for symbol {symbol!r}")


def macro_symbols_for(asset: Asset) -> dict[str, str]:
    """MACRO_SYMBOLS with the asset's own series swapped for its counterpart.

    Without this, silver's panel would carry a `silver` macro column that is
    just its own close -- a perfect, useless self-correlation that a tree model
    would happily split on, and which would make `gs_ratio` identically 1.0.
    """
    symbols = dict(fetch_data.MACRO_SYMBOLS)
    symbols.pop(asset.key, None)
    symbols[asset.counterpart_key] = asset.counterpart_symbol
    return symbols
