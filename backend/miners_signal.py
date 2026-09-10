"""Gold miners as a standalone one-day directional component.

This is the only signal in this project that was adopted because it made
money in a backtest, and it is the newest, so read what it does and does not
claim before touching it.

WHAT WAS MEASURED (research/miners.py, research/README.md section 14)
---------------------------------------------------------------------
`GDX` (gold miners ETF) closes at 16:00 New York; COMEX gold settles at
17:00. So when the metal's bar prints, the miners' close is already an hour
old and genuinely knowable -- there is a decision here a person can actually
make, and the mechanically expected artefact runs the other way (gold leading
the miners), which research/lags.py measured to be absent.

The relationship survived seven attempts to kill it:

  1. lag scan          peak at lag 0, clean tail at +1, no weight at -1
  2. control series    silver's +0.783 same-day correlation produces NO lag+1
                       tail, so a large contemporaneous relation does not by
                       itself manufacture one
  3. own return        controlling gold's OWN same-day return STRENGTHENS it
                       (r=+0.151 -> partial +0.206), so it is not gold's
                       autocorrelation reflected back through a series that
                       is mostly made of gold
  4. flat bars         no difference on settlement-only prints
  5. constant exposure a constant position at this rule's own mean scores the
                       same as buy-and-hold, so the gain is NOT "hold less
                       gold" (the failure assets.py documents for silver's
                       target_volatility)
  6. stale signal      the same rule fed 5-day-old miner data -- same turnover,
                       same fees, zero information -- lands BELOW buy-and-hold
  7. own momentum      the same rule driven by the metal's own return_1d, a
                       free signal needing no new data, also lands below
                       buy-and-hold

THE HORIZON IS ONE DAY, AND THAT IS WHY THIS IS NOT AN ENSEMBLE COMPONENT
-------------------------------------------------------------------------
All of the information sits at t+1 and there is nothing from t+2 onward. In
edge.walk_forward's paired A/B this column added +0.079..+0.097 IC at a
one-day horizon on both metals (p=0.000 in all four cells; gold's IC went
+0.0447 -> +0.1416, the highest this bench has measured) and was
indistinguishable from noise at five days.

`ensemble.combine()` pools components into a FIVE-day forecast
(ml_model.HORIZON_DAYS). Putting a one-day vote into it would be answering a
different question with the same weight, so `miners` is deliberately absent
from `ensemble.COMPONENTS` -- the same exclusion, for the same kind of
reason, that kanal_finans.py carries. It reaches production as a STRATEGY
only: `trading.STRATEGIES` contains it, `ensemble.COMPONENTS` does not, and
`gdx_chg` is deliberately NOT in `ml_model.FEATURE_COLUMNS` (tests lock all
three).

WHERE IT STOPS BEING WORTH IT
-----------------------------
backtest.py, 19.5 years, both metals, Calmar against buy-and-hold:

                        gold                     silver
                miners  buyhold   diff    miners  buyhold   diff
    COMEX  2bp    0.38     0.23  +0.14      0.27     0.12  +0.15
    ETF   10bp    0.32     0.23  +0.09      0.24     0.12  +0.12
    retail 40bp   0.17     0.23  -0.06      0.15     0.12  +0.04
    bank  150bp  -0.05     0.23  -0.28     -0.02     0.12  -0.14

At gold's ETF rung it improves BOTH sides: CAGR 10.8% vs 10.3% and max
drawdown 33.2% vs 44.4%. It dies between 10bp and 40bp on gold and between
40bp and 150bp on silver.

**It trades about 165 times a year** (3225 trades in 19.5 years), and that
number is the whole reason the ladder collapses: at 150bp the fees come to
$2078 on a $1000 book. **On bank gram gold this signal loses money** --
exactly like the `macro` component in README section 7: a real signal that is
expensive to act on. The dashboard shows it next to `buyhold` for that
reason, and the adoption bar was declared in advance as "beats buy-and-hold
at 2bp AND 10bp on BOTH metals", never at the expensive rungs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Turns a daily miner return into a -1..1 score. Measured, not guessed: the
# 90th percentile of |gdx_chg| over the panel is 0.03973, so 1/0.03973 ~ 25
# puts a 90th-percentile day at full scale -- the same definition every scale
# constant in this project uses (see the block above indicators.BOND_SCALE).
#
# It is a MODULE constant rather than a per-asset one in assets.py, and that
# was checked rather than assumed: `gdx` is the same series read from both
# panels, and its p90 came out identical to five digits (0.03973) for gold
# and silver. That is the same test that kept BOND_SCALE/VIX_SCALE shared
# while the price-derived scales had to be split per metal.
#
# Both halves of the panel were checked too, because a scale that is only
# right on average is the `real_yield_chg` failure waiting to happen:
#
#            saturation   median |score|
#   full         9.9%         0.349
#   train       12.3%         0.402
#   test         7.4%         0.310
#
# All six numbers sit inside the ranges the other scorers occupy (saturation
# 5.7-13.7%, median 0.30-0.53). Saturation and median are checked TOGETHER
# on purpose: either one alone is misleading -- see the note in CLAUDE.md
# about the duration fix that left a weighted term with a median |score| of
# 0.009, doing nothing at all while still occupying a weight.
GDX_SCALE = 25.0

# The column this reads. `gdx` reaches the panel through
# indicators.SIGNAL_ONLY_SERIES, which exists so that adding a series for a
# standalone signal never quietly adds it to the model's feature vector.
SIGNAL_COLUMN = "gdx_chg"


def miners_signal(features: pd.DataFrame) -> dict:
    """Latest row of a feature frame -> a one-day directional call.

    Abstains (confidence 0.0) when the miner column is missing or NaN, which
    happens on any day Yahoo does not serve GDX and on every row before GDX
    started trading in 2006. Abstention is a normal outcome here, not a
    failure: `trading.compute_target_exposure` reads confidence 0.0 as "no
    tilt", so the portfolio simply holds SIGNAL_BASE_EXPOSURE, and
    retrain.py excludes zero-confidence rows from any track record.

    Deliberately NOT fail-hard on a missing column. `fetch_data.get_macro_daily`
    is fail-soft per series, so one dead symbol must leave a hole rather than
    stop the daily run for both metals.
    """
    if features is None or features.empty or SIGNAL_COLUMN not in features.columns:
        return {"direction": "UP", "confidence": 0.0, "score": 0.0}

    change = features.iloc[-1].get(SIGNAL_COLUMN)
    if change is None or pd.isna(change):
        return {"direction": "UP", "confidence": 0.0, "score": 0.0}

    score = float(np.clip(float(change) * GDX_SCALE, -1.0, 1.0))
    return {
        # Sign is POSITIVE: miners up today, metal up tomorrow. Unlike
        # macro_signal's vix term there is no counter-intuitive inversion
        # here, and the measured partial correlation (+0.206) is the reason
        # rather than the story.
        "direction": "UP" if score >= 0 else "DOWN",
        "confidence": min(abs(score), 1.0),
        "score": score,
    }
