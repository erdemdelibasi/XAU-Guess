"""Gold's macro drivers as a standalone directional component.

This is the component XRP-Guess could not have. Crypto has no agreed
fundamental anchor, so that project mined price for patterns and honestly
reported finding nothing tradeable. Gold does have an anchor: it is a dollar
price for an asset that yields nothing, so the dollar and the return on
holding cash instead are mechanically tied to it.

WHICH DRIVERS, AND WHY ONLY THESE
---------------------------------
research/drivers.py tested 16 candidate series two ways: against gold's
return the SAME day (explains, cannot be traded -- by the time today's dollar
close is known, today's gold close is known too) and against gold's return
the NEXT day (leads, can be traded). Only three survived a Bonferroni
threshold on the held-out half with a sign consistent across both halves:

    tip   TIP ETF (inflation-protected Treasuries)   test t = +6.79
    ief   IEF ETF (7-10y nominal Treasuries)         test t = +3.92
    vix   equity volatility index                    test t = -3.56

research/lags.py then confirmed these are genuine leads and not a calendar
misalignment, which was the obvious way to be fooled here. The control
series settle it: silver correlates 0.783 with gold the same day and
-0.016 the next -- an enormous contemporaneous relationship producing
exactly zero next-day tail. So TIP's +0.088 next-day tail is not spillover
from its +0.206 same-day figure; it is real.

The VIX sign is the interesting one and it is the opposite of the story most
people would tell. A VIX spike is BEARISH for gold the next day (no same-day
relation at all, r=-0.008). The standard reading is forced liquidation: in a
genuine scare, gold is among the few liquid things still worth something, so
it gets sold to meet margin calls first and bid as a haven only later.

WHAT THIS COMPONENT IS WORTH
----------------------------
Not much on its own, and the code should not pretend otherwise. In
backtest.py's 19.5-year replay the `macro` portfolio reached Calmar 0.24
against buy-and-hold's 0.23 at ETF costs -- but it traded 970 times to get
there, and at retail (40 bp) or bank (150 bp) costs it falls well behind.
It is a real signal that is expensive to act on.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Relative weights follow the measured |t| statistics from research/drivers.py
# rather than being fitted. Fitting them on the same history that scores them
# would be circular, and there is no separate window left to fit them on that
# would not cost the study its out-of-sample half.
DRIVER_WEIGHTS = {"tip": 0.40, "ief": 0.30, "vix": 0.30}

# Scaling constants turn a raw daily change into a -1..1 score. They are set
# so a typical daily move lands mid-scale rather than pinned at the clip:
# TIP/IEF move ~0.3% on an active day (x150 -> ~0.45), VIX ~1.5 points
# (/3 -> 0.5). Not tuned against returns.
BOND_SCALE = 150.0
VIX_SCALE = 3.0

# Abstain rather than guess from a single series. Silver only has TWO measured
# leads (tip, vix) against gold's three, so requiring 2 means silver abstains
# whenever either is missing -- deliberate: a one-driver "signal" on an asset
# with a thinner evidence base is exactly what should stay quiet.
MIN_DRIVERS = 2


def _bond_score(change: float) -> float:
    """Bond ETF up = yields down = the opportunity cost of holding gold falls."""
    if change is None or pd.isna(change):
        return None
    return float(np.clip(change * BOND_SCALE, -1, 1))


def _vix_score(change: float) -> float:
    """Negative by construction -- see the module docstring on liquidation."""
    if change is None or pd.isna(change):
        return None
    return float(np.clip(-change / VIX_SCALE, -1, 1))


def macro_signal(features: pd.DataFrame, drivers: tuple[str, ...] = ("tip", "ief", "vix")) -> dict:
    """Latest row of a feature frame -> a directional call.

    Abstains (confidence 0.0) when fewer than MIN_DRIVERS series are
    available. Abstention is a normal outcome, not a failure: a macro series
    can be missing because a market was closed, and a component that
    fabricates a view from one input is worse than one that says nothing.
    retrain.py excludes zero-confidence rows from a component's accuracy for
    exactly this reason.
    """
    last = features.iloc[-1]

    # Only this asset's OWN measured leads contribute. research/compare.py
    # found `ief` clears the out-of-sample bar for gold (t=+3.92) and misses
    # it for silver (t=+2.56); including it for silver would put a weighted
    # term of noise into a three-term average.
    scorer = {"tip": _bond_score, "ief": _bond_score, "vix": _vix_score}
    scores: dict[str, float] = {}
    for name in drivers:
        value = scorer[name](last.get(f"{name}_chg"))
        if value is not None:
            scores[name] = value

    if len(scores) < MIN_DRIVERS:
        return {"direction": "UP", "confidence": 0.0, "score": 0.0, "components": scores}

    # Renormalise across whatever actually arrived, so a missing series
    # weakens the signal's coverage but never silently shrinks its scale.
    total_weight = sum(DRIVER_WEIGHTS[k] for k in scores)
    combined = sum(scores[k] * DRIVER_WEIGHTS[k] for k in scores) / total_weight
    combined = float(np.clip(combined, -1, 1))

    return {
        "direction": "UP" if combined >= 0 else "DOWN",
        "confidence": min(abs(combined), 1.0),
        "score": combined,
        "components": scores,
    }


def describe_context(features: pd.DataFrame) -> dict:
    """Human-readable macro state, for the UI and for claude_signal's prompt.

    Deliberately separate from the signal: these are levels a person wants to
    see (where is the dollar, where are real yields) and they are NOT what the
    component trades on -- it trades on daily CHANGES in three specific
    series. Mixing the two in one function is how a display value ends up
    quietly driving a decision.

    BOTH metals are listed, and exactly one of them is present in any given
    panel -- assets.macro_symbols_for() swaps an asset's own series out for
    its counterpart, so gold's panel carries `silver` and silver's carries
    `gold`. Asking only for "silver" (the original list) therefore handed the
    SILVER prompt a context with no counterpart price in it at all: the one
    number that puts the gold/silver ratio beside it, missing precisely on
    the metal whose panel is built around that counterpart.
    """
    last = features.iloc[-1]
    out: dict[str, float | None] = {}
    for key in ("dxy", "us10y", "vix", "silver", "gold", "spx"):
        value = last.get(key)
        out[key] = float(value) if pd.notna(value) else None
    gs = last.get("gs_ratio")
    out["gold_silver_ratio"] = float(gs) if pd.notna(gs) else None
    z = last.get("gs_ratio_z")
    out["gold_silver_z"] = float(z) if pd.notna(z) else None
    return out
