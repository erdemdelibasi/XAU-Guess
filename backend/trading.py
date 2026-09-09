"""Virtual paper-trading for gold. No real money, no broker, no orders.

WHAT THE RESEARCH SAID, and why this engine is shaped the way it is
-------------------------------------------------------------------
XRP-Guess sized positions by signal confidence: a DOWN call meant 0% exposure,
an UP call meant up to 85%, and every 15 minutes the portfolio re-aimed at
that target. Copying that here would be building on a foundation this
project's own bench has already knocked down. Three measurements, in order:

  research/wall.py -- gold's break-even accuracy is 56.2% at a one-day
      horizon and ETF costs, against XRP's 95.7%. The game is playable. But
      the same table shows that from two days out, "always long" ALREADY
      clears the cost wall on its own, because gold rises 54.5% of the time
      and has drifted up 11.8%/yr for 25 years.

  research/edge.py -- the direction model beats chance and clears the wall at
      a 5-day horizon (53.26% against 52.70%, overlap-corrected z=+2.04), and
      still loses to always-long (55.2%). Its Brier skill score is negative
      at every horizon: the probabilities are worse than quoting the base rate.

  research/tilt.py -- given that, the obvious fallback is to let the model
      size a permanently-long position rather than pick sides. It does not
      work either. The ML grid chose TILT = 0.0 on the training half without
      being pushed, and out of sample the tilt was worth +0.011 Calmar.

So a confidence-driven allocator would be paying real costs to act on a
signal measured to be worse than doing nothing. The one thing that DID work
(research/defense.py, walk-forward, 19.9 years out of sample) was volatility
targeting plus a trend filter: Calmar 0.28 against buy-and-hold's 0.24,
Sharpe 0.64 against 0.58, maximum drawdown cut from 44.4% to 30.1%, at a cost
of 2.1 points of annual return.

That is a different machine and it is worth being precise about why it works
when the forecast does not: **it forecasts nothing.** Realised volatility is
strongly autocorrelated -- a turbulent week is followed by a turbulent week --
so scaling exposure to recent volatility is a reaction to something genuinely
persistent, not a prediction of direction. Never present defense.py's win as
evidence that the direction model is good.

Hence: exposure = TREND_FILTER x VOL_SCALE x (1 + small signal tilt), and the
tilt is capped hard because it was measured to be worth approximately nothing.

BUY-AND-HOLD IS A FIRST-CLASS COMPETITOR
----------------------------------------
`buyhold` is a real portfolio in this system, not a line in a report. On gold
it is a genuinely strong strategy and the honest thing is to let it beat the
clever ones in public where that is what happens. XRP-Guess kept buy-and-hold
in prose only, and every strategy losing to it was a fact the reader had to
assemble themselves.

compute_target_exposure() is pure -- no DB -- so backtest.py replays exactly
the code that runs live, the same discipline XRP-Guess used for
compute_rebalance().
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

# Default one-way cost, used where no asset is in hand (tests, the cost
# ladder's baseline). The REAL number for a live decision comes from
# assets.Asset.fee_rate, because silver's spread is a wider fraction of its
# price than gold's (20 bp round trip against 10). 5 bp per side is the
# "ETF / CFD" rung of research/wall.py's ladder, which every break-even
# figure in this project is quoted at; backtest.py re-runs everything across
# the full ladder rather than assuming it fits the reader.
FEE_RATE = 0.0005
STARTING_CASH = 1000.0

# Exposure never exceeds 1.0: no leverage. A leveraged gold position is a
# different product with financing costs and margin calls, and simulating it
# at spot cost would flatter every result here.
MAX_EXPOSURE = 1.0

# Default volatility budget. As with FEE_RATE, the live value comes from
# assets.Asset.target_volatility: silver realises 1.86x gold's volatility for
# essentially the same return, so gold's 15% budget applied to silver would
# peg it at a fraction of full exposure permanently -- that is "hold less
# silver", not volatility targeting, and it has never been tested. 15% sits
# just under gold's own long-run 18%, so the rule stays mostly invested and
# only cuts in genuinely turbulent markets; research/defense.py's
# walk-forward selector picked a 12-15% budget in 12 of 20 years.
TARGET_VOLATILITY = 0.15
VOL_LOOKBACK_DAYS = 60

# Trend filter. Long while price is above its 200-day average. In gold's
# 2011-2015 bear this cut maximum drawdown from 43.9% to 8.3%; in the
# 2019-2026 bull it cost 7.8 points of annual return. That asymmetry IS the
# trade -- it is insurance, and insurance has a premium.
TREND_WINDOW = 200
# Exposure retained when the trend filter is negative. Not zero: a hard exit
# is what made research/defense.py's drawdown-stop variants WORSE than
# holding (55.3% maximum drawdown against 44.4%), because they sold the low
# and bought back higher. Staying partly invested keeps the recovery.
TREND_OFF_EXPOSURE = 0.35

# How far the direction signal may move exposure. Deliberately small: this is
# the parameter research/tilt.py measured at approximately zero value, kept
# only so the signal-driven portfolios have something to express and so the
# comparison against buyhold stays honest rather than rigged.
MAX_SIGNAL_TILT = 0.15

# Where a signal-driven portfolio sits with a neutral signal. It must be
# MAX_EXPOSURE - MAX_SIGNAL_TILT, not MAX_EXPOSURE, or the tilt is ONE-SIDED:
# starting at the ceiling, a bullish call clips away to nothing while a
# bearish one still cuts, so every signal portfolio would be a pure
# short-the-signal machine that could never express agreement. The first
# version here did exactly that -- technical/ml/macro/claude all printed 100%
# exposure regardless of what they said.
SIGNAL_BASE_EXPOSURE = MAX_EXPOSURE - MAX_SIGNAL_TILT

# Don't trade unless the target has drifted this far from the current
# position. XRP-Guess measured 0.10 causing severe fee erosion and settled on
# 0.25 for a 15-minute cadence; a daily cadence trades ~96x less often, so a
# tighter band is affordable here. Still not zero -- volatility estimates
# wobble a little every day and rebalancing to every wobble is pure cost.
REBALANCE_THRESHOLD = 0.05

# Every portfolio that runs, INCLUDING "ensemble" -- it is one row in
# `portfolios` like any other, keyed by (asset, strategy). Callers iterate
# this list exactly once, per asset.
#
# predict.py originally iterated ("ensemble", *STRATEGIES), which ran the
# ensemble TWICE per day. Back then it did not even crash: the ensemble had
# its own singleton table and the second pass simply re-read the row it had
# just rebalanced, found no drift, and held. The cost was a wasted round trip
# and a rewritten updated_at -- which is exactly why it could have sat there
# indefinitely, since nothing about it looked wrong from the outside.
#
# If you add a portfolio, add it here AND to schema.sql's `portfolios` seed
# (once per asset) -- and keep iterating this list alone.
#
# "buyhold" is the benchmark and MUST stay in this list -- see the module
# docstring for why it is a real portfolio rather than a line in a report.
STRATEGIES = ("buyhold", "voltarget", "trend", "defensive", "ensemble",
              "technical", "ml", "macro", "claude")

# Which strategies ignore the direction signal entirely (they are mechanical
# risk rules, not forecasts). Keeping this explicit stops a future edit from
# quietly wiring a forecast into the one part of the system that was measured
# to work precisely because it does not forecast.
MECHANICAL = ("buyhold", "voltarget", "trend", "defensive")


def realised_volatility(returns: np.ndarray, lookback: int = VOL_LOOKBACK_DAYS) -> float:
    """Annualised standard deviation of the last `lookback` daily returns."""
    tail = np.asarray(returns, dtype=float)
    tail = tail[np.isfinite(tail)][-lookback:]
    if len(tail) < 20:
        return float("nan")
    return float(np.std(tail)) * np.sqrt(252.0)


def vol_scale(volatility: float, target: float = TARGET_VOLATILITY) -> float:
    """Exposure multiplier that brings realised volatility toward `target`.

    Capped at 1.0 on the way up (no leverage) but NOT floored on the way
    down -- cutting hard in a genuinely violent market is the entire point.
    """
    if not np.isfinite(volatility) or volatility <= 0:
        return 1.0
    return float(min(target / volatility, 1.0))


def trend_scale(price: float, trend_average: float) -> float:
    """1.0 in an uptrend, TREND_OFF_EXPOSURE below the long average."""
    if not np.isfinite(trend_average) or trend_average <= 0:
        return 1.0  # not enough history yet -- default to invested
    return 1.0 if price > trend_average else TREND_OFF_EXPOSURE


def compute_target_exposure(strategy: str, price: float, trend_average: float,
                            volatility: float, direction: str, confidence: float,
                            target_volatility: float = TARGET_VOLATILITY,
                            disagreement: float = 0.0, disagreement_tilt: float = 0.0) -> float:
    """Fraction of the portfolio that should be in the metal, in [0, MAX_EXPOSURE].

    Pure -- no DB, no clock, no network -- so backtest.py replays the live
    logic itself rather than a reimplementation of it. `target_volatility` is
    the ASSET's own budget (assets.Asset.target_volatility), never a global:
    see that field for why gold's number applied to silver is a different
    strategy wearing the same name.

    `disagreement` (0..1, how much of today's voting components point away
    from the pooled direction) and `disagreement_tilt` (how hard to react to
    it) both default to 0.0, which multiplies exposure by exactly 1.0 -- every
    existing caller is unaffected. They exist so research/ensemble_weights.py
    can score a candidate tilt through this exact function; see that script
    before ever passing a nonzero disagreement_tilt from anywhere else.
    """
    if strategy == "buyhold":
        return MAX_EXPOSURE

    base = MAX_EXPOSURE
    if strategy in ("voltarget", "defensive"):
        base *= vol_scale(volatility, target_volatility)
    if strategy in ("trend", "defensive"):
        base *= trend_scale(price, trend_average)

    if strategy in MECHANICAL:
        return float(np.clip(base, 0.0, MAX_EXPOSURE))

    # Signal-driven portfolios. The tilt is additive around a mostly-invested
    # base rather than multiplicative from zero, because the measured fact is
    # that being long is right and the signal is a weak modifier of how long.
    signed = confidence if direction == "UP" else -confidence
    tilt = MAX_SIGNAL_TILT * float(np.clip(signed, -1.0, 1.0))
    base = SIGNAL_BASE_EXPOSURE
    # `ensemble` additionally carries the risk rules; the single-signal
    # portfolios express their own signal alone so their contribution is
    # visible rather than buried under the volatility scaler.
    if strategy == "ensemble":
        base *= vol_scale(volatility, target_volatility) * trend_scale(price, trend_average)
        base *= 1.0 - disagreement_tilt * disagreement
    return float(np.clip(base + tilt, 0.0, MAX_EXPOSURE))


def compute_rebalance(cash: float, ounces: float, price: float, target_exposure: float) -> dict:
    """Turn a target exposure into a concrete BUY/SELL/HOLD. Pure.

    Returns {"action", "usd_amount", "ounce_amount", "reason"}; only the
    amount matching the action is meaningful.
    """
    value = cash + ounces * price
    if value <= 0 or price <= 0:
        return {"action": "HOLD", "usd_amount": 0.0, "ounce_amount": 0.0, "reason": ""}

    current_exposure = (ounces * price) / value
    drift = current_exposure - target_exposure

    if abs(drift) <= REBALANCE_THRESHOLD:
        return {"action": "HOLD", "usd_amount": 0.0, "ounce_amount": 0.0, "reason": ""}

    if drift > 0:
        ounces_to_sell = min(ounces, (drift * value) / price)
        # Float round-tripping through ounces*price and back leaves dust that
        # then reads as an open position on the dashboard. XRP-Guess hit this
        # exactly: a portfolio holding 5.7e-14 units displayed as "LONG".
        if ounces - ounces_to_sell < ounces * 1e-9:
            ounces_to_sell = ounces
        return {"action": "SELL", "usd_amount": 0.0, "ounce_amount": ounces_to_sell,
                "reason": f"Hedef pozisyona indir (%{100 * target_exposure:.0f})"}

    usd_to_spend = min(cash, -drift * value)
    if usd_to_spend <= 0:
        return {"action": "HOLD", "usd_amount": 0.0, "ounce_amount": 0.0, "reason": ""}
    return {"action": "BUY", "usd_amount": usd_to_spend, "ounce_amount": 0.0,
            "reason": f"Hedef pozisyona cikar (%{100 * target_exposure:.0f})"}


# --------------------------------------------------------------------------
# Live path (Supabase). Everything above this line is pure and testable.
# --------------------------------------------------------------------------
#
# ONE table keyed by (asset, strategy), not XRP-Guess's split of a singleton
# `portfolio_state` for the ensemble plus `strategy_portfolios` for everything
# else. That split existed there for a historical reason -- the ensemble
# portfolio already had real trade history before the project supported more
# than one strategy -- and it cost a permanent special case in every read,
# write and query. This project has no such legacy, and adding a second asset
# would have doubled the special case rather than the table.


def get_portfolio_state(db, asset_key: str, strategy: str) -> dict:
    return (db.table("portfolios").select("*")
            .eq("asset", asset_key).eq("strategy", strategy)
            .single().execute().data)


def _update_state(db, asset_key: str, strategy: str, fields: dict) -> None:
    (db.table("portfolios").update(fields)
     .eq("asset", asset_key).eq("strategy", strategy).execute())


def _record_trade(db, asset_key: str, strategy: str, side: str, price: float,
                  unit_amount: float, usd_amount: float, fee_usd: float,
                  cash_after: float, units_after: float, target_exposure: float,
                  prediction_id: int | None, reason: str) -> None:
    db.table("trades").insert({
        "asset": asset_key, "strategy": strategy, "side": side, "price": price,
        "ounce_amount": unit_amount, "usd_amount": usd_amount, "fee_usd": fee_usd,
        "cash_after": cash_after, "ounces_after": units_after,
        "target_exposure": target_exposure,
        "triggered_by_prediction_id": prediction_id, "reason": reason,
    }).execute()


def maybe_trade(db, asset, strategy: str, prediction_id: int | None, price: float,
                trend_average: float, volatility: float,
                direction: str, confidence: float) -> None:
    """Read this (asset, strategy) portfolio, decide, and apply the result.

    `asset` is an assets.Asset. Its fee_rate and target_volatility are what
    make this a silver decision rather than a gold decision run on silver
    prices -- passing the asset object rather than a key keeps it impossible
    to fetch one asset's state and size it with the other's constants.
    """
    state = get_portfolio_state(db, asset.key, strategy)
    cash = float(state["cash_usd"])
    units = float(state["ounces"])

    target = compute_target_exposure(strategy, price, trend_average, volatility,
                                     direction, confidence, asset.target_volatility)
    decision = compute_rebalance(cash, units, price, target)
    now_iso = datetime.now(timezone.utc).isoformat()

    if decision["action"] == "HOLD":
        _update_state(db, asset.key, strategy,
                      {"target_exposure": target, "updated_at": now_iso})
        return

    if decision["action"] == "BUY":
        gross = decision["usd_amount"]
        fee = gross * asset.fee_rate
        moved = (gross - fee) / price
        new_cash, new_units = cash - gross, units + moved
    else:
        moved = decision["ounce_amount"]
        gross = moved * price
        fee = gross * asset.fee_rate
        new_cash, new_units = cash + (gross - fee), units - moved

    _update_state(db, asset.key, strategy, {
        "cash_usd": new_cash, "ounces": new_units,
        "position": "LONG" if new_units > 0 else "CASH",
        "target_exposure": target, "updated_at": now_iso,
    })
    _record_trade(db, asset.key, strategy, decision["action"], price, moved, gross, fee,
                  new_cash, new_units, target, prediction_id, decision["reason"])
    print(f"TRADE [{asset.key}/{strategy}]: {decision['action']} {moved:.4f} oz "
          f"@ {price:,.2f} (fee ${fee:.2f}) -- {decision['reason']}")


def portfolio_value(state: dict, price: float) -> float:
    return float(state["cash_usd"]) + float(state["ounces"]) * price
