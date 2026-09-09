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
