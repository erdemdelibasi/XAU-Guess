"""Breakout-regime signal: order flow, anchored VWAP and volume profile.

WHAT THIS IS, AND WHAT IT DELIBERATELY IS NOT
---------------------------------------------
Every other signal in this repo answers "which way over the next 5 sessions".
This one answers a different question: **am I in a position right now, and
what takes me out of it.** It enters on a breakout out of an established
value area and holds -- across weeks, through noise -- until the trend
genuinely breaks or a volatility-scaled stop is hit. There is no daily
re-aiming, because the whole claim of a breakout rule is that the position
outlives the day it was opened.

That makes it structurally unlike `trading.compute_target_exposure`'s
continuous allocator, and the difference is on purpose: a rule that trims 3%
of its holding every morning is not "holding through the trend", whatever its
label says.

THE VOLUME PROBLEM, MEASURED FIRST
----------------------------------
Order flow and volume profile are volume instruments, and the first thing
measured here was whether this project HAS a volume series. It does not have
one on the futures, and the two series fail in two DIFFERENT ways -- which is
why research/flow.py's part 0 runs three tests rather than the one obvious
test, and prints the one that clears both of them:

    GC=F -- not stable across sessions. The same 250 dates, the cached panel
    snapshot against a fetch days later: **3.6% of the values match**,
    correlation **-0.10**, medians 622 against 170,868 contracts. The same
    fault shows on the depth axis: a 2-year request returns ~181,000, a
    25-year request returns 219 for the same series.

    SI=F -- stable, and implausible at every depth. Median 124 contracts at
    2 years, 40 at 25, with 627 zero-volume sessions. COMEX silver trades
    ~60,000 contracts a day; this is not a noisy measurement of that.

A value area built on either would be rebuilt differently on different days,
or built on a quantity that is not participation at all, with nothing raising.

The ETFs pass all three. GLD and SLV return identical volume across fetches,
plausible levels at every depth (~8M and ~14M shares) and zero zero-volume
sessions in 16 years, because they are single listed instruments rather than
a stitched front-month.

So **every volume-derived quantity in this module reads the ETF series**
(GLD for gold, SLV for silver) while the metal itself is what gets traded.
This is the one place in the repo where a signal's inputs and its instrument
differ on purpose, and research/flow.py measures the rule on BOTH books
because of it.

"ORDER FLOW" IS A PROXY HERE AND THE NAME MUST NOT DRIFT
--------------------------------------------------------
Real order flow is the tape: bid/ask lifts, resting size, delta per print.
This project has no intraday tape and no source for one. What a daily bar
supports is the close-location proxy -- where in the session's range the
close landed, weighted by that session's volume, summed over a window. That
is Chaikin Money Flow, and it is what `flow` means in this file. It is a
genuine measure of whether buyers or sellers finished the day in control; it
is not the order book, and calling it "order flow" in the UI without that
sentence would be overstating what was measured.

NO-LOOKAHEAD
------------
The value area is computed on the window ending at t-1, so "today broke out
of the value area" compares today's close against a level that was already
established before today printed. Every other column uses data through t
only. research/flow.py re-checks this by construction: the entry test at row
t reads `vah` at row t, which `volume_profile` shifted.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from ta.momentum import ROCIndicator, RSIIndicator, StochasticOscillator
from ta.trend import CCIIndicator, MACD


@dataclass(frozen=True)
class BreakoutParams:
    """The per-asset configuration research/flow.py scored out of sample.

    Lives on assets.Asset for the reason that module's docstring gives: a
    constant that can differ per asset must be looked up, never hardcoded.
    The two metals genuinely chose different values on the training half
    (gold 2.0 sigmas with a 0.35 floor, silver 3.0 with none), and running
    gold's on silver would put a rule on screen that was never the rule
    scored -- the backtest/live divergence this repo exists to prevent.

    `flat_exposure` is recorded even though no portfolio ships: it was part
    of the configuration that produced the out-of-sample number the panel
    quotes, and dropping it would leave that number describing a rule nobody
    can reconstruct.
    """
    etf_symbol: str
    min_confirmations: int
    stop_sigmas: float
    flat_exposure: float


# ---------------------------------------------------------------------------
# Parameters. The three that were SWEPT were chosen on the FIRST HALF of the
# window by research/flow.py and then run once, unchanged, on the second half.
# Changing one without re-running that script turns a measured rule back into
# a guess.
# ---------------------------------------------------------------------------

# Volume profile window, in sessions. ~3 months of participation is the span
# over which a value area is a real shelf rather than last week's noise.
PROFILE_WINDOW = 60
# Price bins across the window's range. 50 puts a gold bin at roughly $8 on a
# $400 range -- fine enough to place a breakout, coarse enough that one
# session cannot own a bin.
PROFILE_BINS = 50
# Fraction of the window's volume inside the value area. 70% is the
# convention (one standard deviation of a normal), kept rather than tuned:
# sweeping it would be fitting the definition of "value" to the outcome.
VALUE_AREA_PCT = 0.70

# Anchored VWAP anchor: the lowest close of the trailing N sessions. The
# anchor moves only when a new low is set, so the VWAP is genuinely anchored
# to a swing rather than being a rolling average wearing a different name.
AVWAP_ANCHOR_LOOKBACK = 252

# Chaikin money-flow window (the order-flow proxy).
FLOW_WINDOW = 20

# Oscillator windows. Standard settings, NOT swept: six confirmations swept
# jointly is a grid large enough to find something in pure noise, and the
# bench's rule is that a parameter chosen by looking at the outcome is not a
# parameter, it is a result.
RSI_WINDOW = 14
CCI_WINDOW = 20
MOM_WINDOW = 10
STOCH_WINDOW = 14
STOCH_SMOOTH = 3
# Swing window for the Fibonacci retracement frame.
FIB_WINDOW = 120

# --- the three swept parameters ---
# How many of the six confirmations must agree for an entry.
MIN_CONFIRMATIONS = 3
# Stop distance, in daily standard deviations, below the highest close since
# entry. Close-to-close rather than ATR, for the reason indicators.py states:
# on this project's futures series ~11% of bars have a fabricated high/low.
STOP_SIGMAS = 3.0
# Exposure retained while the rule is OUT of position. Not assumed to be
# zero: trading.TREND_OFF_EXPOSURE is 0.35 rather than 0 precisely because
# research/defense.py's hard stops sold the low and bought back higher.
FLAT_EXPOSURE = 0.0

# Consecutive closes below the anchored VWAP that count as a trend break.
TREND_BREAK_DAYS = 2
# Sessions after an exit before a new entry may be taken. XRP-Guess measured
# 235 of 236 stop-losses re-triggering within 10 hours with no cooldown; the
# same shape at a daily cadence is a stop that sells and buys back three days
# later at a worse price.
COOLDOWN_DAYS = 5

VOTE_COLUMNS = ("rsi14", "macd_hist", "cci20", "mom10", "stoch_k", "fib_pos")


# ---------------------------------------------------------------------------
# Columns
# ---------------------------------------------------------------------------

def money_flow(df: pd.DataFrame, window: int = FLOW_WINDOW) -> pd.Series:
    """Chaikin money flow -- the order-flow proxy. See the module docstring.

    Where high == low (a flat bar, or a genuinely untraded session) the close
    location is undefined, not zero-and-therefore-neutral; the bar
    contributes its volume to the denominator and nothing to the numerator,
    which is what "we cannot tell who was in control" should do to an
    average.
    """
    span = (df["high"] - df["low"]).replace(0, np.nan)
    clv = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / span
    numer = (clv.fillna(0.0) * df["volume"]).rolling(window).sum()
    denom = df["volume"].rolling(window).sum().replace(0, np.nan)
    return numer / denom


def anchored_vwap(df: pd.DataFrame,
                  lookback: int = AVWAP_ANCHOR_LOOKBACK) -> tuple[pd.Series, pd.Series]:
    """VWAP measured from the trailing `lookback`-session low, and the anchor.

    Returns (avwap, anchor_price). The anchor is the lowest close in the
    trailing window, so it only moves when the market makes a new low --
    which is exactly when a trader would re-anchor.
    """
    close = df["close"].to_numpy(dtype=float)
    typical = ((df["high"] + df["low"] + df["close"]) / 3.0).to_numpy(dtype=float)
    volume = df["volume"].to_numpy(dtype=float)
    n = len(df)

    pv = np.cumsum(typical * volume)
    vv = np.cumsum(volume)

    out = np.full(n, np.nan)
    anchor_px = np.full(n, np.nan)
    for i in range(n):
        start = max(0, i - lookback + 1)
        a = start + int(np.argmin(close[start:i + 1]))
        num = pv[i] - (pv[a - 1] if a > 0 else 0.0)
        den = vv[i] - (vv[a - 1] if a > 0 else 0.0)
        out[i] = num / den if den > 0 else np.nan
        anchor_px[i] = close[a]
    return pd.Series(out, index=df.index), pd.Series(anchor_px, index=df.index)


def _one_profile(highs: np.ndarray, lows: np.ndarray, vols: np.ndarray,
                 bins: int, value_area: float) -> tuple[float, float, float]:
    """(poc, vah, val) for one window. Volume spread across each bar's range.

    The value area grows OUTWARD from the point of control, taking whichever
    neighbouring bin holds more volume, until `value_area` of the window's
    volume is inside. That is the real definition; the shortcut of sorting
    bins by volume and taking the top 70% returns a disconnected set of
    shelves, which cannot be read as "the range price accepted".
    """
    lo, hi = float(np.min(lows)), float(np.max(highs))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return (float("nan"),) * 3

    edges = np.linspace(lo, hi, bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2.0
    inside = (centers[None, :] >= lows[:, None]) & (centers[None, :] <= highs[:, None])
    counts = inside.sum(axis=1)

    # A bar narrower than one bin covers no center. Its volume is real and
    # must land somewhere: the bin its midpoint falls in. Dropping it would
    # quietly delete every flat bar from the profile.
    narrow = counts == 0
    if narrow.any():
        idx = np.clip(np.digitize((highs[narrow] + lows[narrow]) / 2.0, edges) - 1, 0, bins - 1)
        inside[np.where(narrow)[0], idx] = True
        counts = inside.sum(axis=1)

    weights = inside / np.maximum(counts, 1)[:, None]
    hist = (vols[:, None] * weights).sum(axis=0)
    total = hist.sum()
    if total <= 0:
        return (float("nan"),) * 3

    poc = int(np.argmax(hist))
    lo_i = hi_i = poc
    acc = hist[poc]
    target = total * value_area
    while acc < target and (lo_i > 0 or hi_i < bins - 1):
        below = hist[lo_i - 1] if lo_i > 0 else -1.0
        above = hist[hi_i + 1] if hi_i < bins - 1 else -1.0
        if above >= below:
            hi_i += 1
            acc += hist[hi_i]
        else:
            lo_i -= 1
            acc += hist[lo_i]
    return float(centers[poc]), float(centers[hi_i]), float(centers[lo_i])


def volume_profile(df: pd.DataFrame, window: int = PROFILE_WINDOW,
                   bins: int = PROFILE_BINS,
                   value_area: float = VALUE_AREA_PCT) -> pd.DataFrame:
    """Rolling (poc, vah, val), SHIFTED so row t describes the window to t-1.

    The shift is the no-lookahead guarantee and also the definition: "price
    broke out of the value area" has to compare today against a level that
    existed before today traded. Without it a breakout session adds its own
    volume at its own price and partly builds the level it is breaking.
    """
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    vols = df["volume"].to_numpy(dtype=float)
    n = len(df)
    out = np.full((n, 3), np.nan)
    for i in range(window, n + 1):
        out[i - 1] = _one_profile(highs[i - window:i], lows[i - window:i],
                                  vols[i - window:i], bins, value_area)
    frame = pd.DataFrame(out, columns=["poc", "vah", "val"], index=df.index)
    return frame.shift(1)


def add_flow_columns(df: pd.DataFrame, profile_window: int = PROFILE_WINDOW,
                     flow_window: int = FLOW_WINDOW,
                     avwap_lookback: int = AVWAP_ANCHOR_LOOKBACK) -> pd.DataFrame:
    """Every column this module's rule reads. Pure; expects daily OHLCV."""
    out = df.copy()
    out["flow"] = money_flow(out, flow_window)
    avwap, anchor = anchored_vwap(out, avwap_lookback)
    out["avwap"] = avwap
    out["avwap_anchor"] = anchor
    out[["poc", "vah", "val"]] = volume_profile(out, profile_window)

    close = out["close"]
    out["rsi14"] = RSIIndicator(close, window=RSI_WINDOW).rsi()
    out["macd_hist"] = MACD(close, window_slow=26, window_fast=12, window_sign=9).macd_diff()
    out["cci20"] = CCIIndicator(out["high"], out["low"], close, window=CCI_WINDOW).cci()
    out["mom10"] = ROCIndicator(close, window=MOM_WINDOW).roc()
    stoch = StochasticOscillator(out["high"], out["low"], close,
                                 window=STOCH_WINDOW, smooth_window=STOCH_SMOOTH)
    out["stoch_k"] = stoch.stoch()
    out["stoch_d"] = stoch.stoch_signal()

    # Fibonacci frame: the trailing swing, and where price sits inside it.
    swing_hi = close.rolling(FIB_WINDOW).max()
    swing_lo = close.rolling(FIB_WINDOW).min()
    out["fib_high"] = swing_hi
    out["fib_low"] = swing_lo
    out["fib_pos"] = (close - swing_lo) / (swing_hi - swing_lo).replace(0, np.nan)

    out["sigma"] = close.pct_change().rolling(20).std()
    return out


# ---------------------------------------------------------------------------
# Confirmations
# ---------------------------------------------------------------------------

def confirmation_votes(row) -> dict[str, int]:
    """Six oscillators, each +1 / 0 / -1. Deliberately coarse.

    These are CONFIRMATIONS, not the signal: the entry is decided by the
    three volume-and-structure instruments and these only say whether the
    rest of the tape agrees. Scoring them on a continuous scale would let a
    strongly-positive RSI outvote the value-area break itself, which inverts
    what the rule claims to be.

    Each threshold is the instrument's own conventional neutral point, not a
    fitted number: RSI 50, MACD histogram zero, CCI +/-100, momentum zero,
    stochastic 50, and the 0.382 Fibonacci retracement (price holding above
    the 61.8% retracement of its trailing swing).
    """
    def val(name):
        v = row.get(name)
        return float(v) if v is not None and pd.notna(v) else None

    votes: dict[str, int] = {}
    rsi = val("rsi14")
    votes["rsi14"] = 0 if rsi is None else (1 if rsi > 50 else -1)
    macd = val("macd_hist")
    votes["macd_hist"] = 0 if macd is None else (1 if macd > 0 else -1)
    cci = val("cci20")
    votes["cci20"] = 0 if cci is None else (1 if cci > 100 else (-1 if cci < -100 else 0))
    mom = val("mom10")
    votes["mom10"] = 0 if mom is None else (1 if mom > 0 else -1)
    stoch = val("stoch_k")
    votes["stoch_k"] = 0 if stoch is None else (1 if stoch > 50 else -1)
    fib = val("fib_pos")
    votes["fib_pos"] = 0 if fib is None else (1 if fib > 0.382 else -1)
    return votes


def vote_totals(df: pd.DataFrame) -> pd.Series:
    """Sum of the six votes, vectorised. Same thresholds as confirmation_votes.

    The scalar version above is what the live path and the UI read, so the
    two must agree; tests/test_flow_signal.py scores both on the same rows.
    """
    total = pd.Series(0.0, index=df.index, dtype=float)
    total += np.where(df["rsi14"].notna(), np.where(df["rsi14"] > 50, 1, -1), 0)
    total += np.where(df["macd_hist"].notna(), np.where(df["macd_hist"] > 0, 1, -1), 0)
    total += np.where(df["cci20"].notna(),
                      np.where(df["cci20"] > 100, 1, np.where(df["cci20"] < -100, -1, 0)), 0)
    total += np.where(df["mom10"].notna(), np.where(df["mom10"] > 0, 1, -1), 0)
    total += np.where(df["stoch_k"].notna(), np.where(df["stoch_k"] > 50, 1, -1), 0)
    total += np.where(df["fib_pos"].notna(), np.where(df["fib_pos"] > 0.382, 1, -1), 0)
    return total


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------

def breakout_path(df: pd.DataFrame, min_confirmations: int = MIN_CONFIRMATIONS,
                  stop_sigmas: float = STOP_SIGMAS,
                  trend_break_days: int = TREND_BREAK_DAYS,
                  cooldown_days: int = COOLDOWN_DAYS) -> pd.DataFrame:
    """Walk the frame once and record the position state for every session.

    Stateful by necessity -- "hold until it breaks" cannot be expressed as a
    per-row score, which is the whole reason this rule exists alongside the
    continuous allocator. Returns one row per input row with:

        state        1 while in position, 0 while flat
        stop         the level that would take the position out
        entry_price  fill price of the open position (nan while flat)
        entry_index  positional index of that entry
        exit_reason  what closed the last position ("stop" / "trend")

    The stop only ratchets upward within a position. A stop that could fall
    is not a stop, it is a level that follows price down and exits at the
    bottom -- the failure research/defense.py measured when drawdown-stops
    made maximum drawdown WORSE than holding.
    """
    close = df["close"].to_numpy(dtype=float)
    vah = df["vah"].to_numpy(dtype=float)
    val = df["val"].to_numpy(dtype=float)
    avwap = df["avwap"].to_numpy(dtype=float)
    flow = df["flow"].to_numpy(dtype=float)
    sigma = df["sigma"].to_numpy(dtype=float)
    votes = vote_totals(df).to_numpy(dtype=float)

    n = len(df)
    state = np.zeros(n, dtype=float)
    stop_out = np.full(n, np.nan)
    entry_out = np.full(n, np.nan)
    entry_idx = np.full(n, np.nan)
    reason_out: list[str] = [""] * n

    in_pos = False
    stop = np.nan
    entry_price = np.nan
    entry_i = -1
    peak = np.nan
    below_avwap = 0
    cooldown = 0
    last_reason = ""

    for i in range(n):
        px = close[i]
        if not np.isfinite(px):
            state[i] = 1.0 if in_pos else 0.0
            continue

        below_avwap = below_avwap + 1 if (np.isfinite(avwap[i]) and px < avwap[i]) else 0

        if in_pos:
            peak = px if not np.isfinite(peak) else max(peak, px)
            if np.isfinite(sigma[i]) and np.isfinite(peak):
                stop = max(stop, peak * (1.0 - stop_sigmas * sigma[i]))
            if px < stop:
                in_pos, last_reason = False, "stop"
                cooldown = cooldown_days
            elif below_avwap >= trend_break_days:
                in_pos, last_reason = False, "trend"
                cooldown = cooldown_days
        else:
            if cooldown > 0:
                cooldown -= 1
            elif (np.isfinite(vah[i]) and np.isfinite(avwap[i]) and np.isfinite(flow[i])
                  and np.isfinite(sigma[i])
                  and px > vah[i] and px > avwap[i] and flow[i] >= 0.0
                  and votes[i] >= min_confirmations):
                in_pos = True
                entry_price = px
                entry_i = i
                peak = px
                # Opening stop: the low edge of the value area it just left,
                # or the volatility stop, whichever is HIGHER. A breakout that
                # falls back inside the area it broke out of has failed, and
                # waiting for a wide volatility stop to catch that is paying
                # for information already in hand.
                stop = max(val[i] if np.isfinite(val[i]) else -np.inf,
                           px * (1.0 - stop_sigmas * sigma[i]))
                last_reason = ""

        state[i] = 1.0 if in_pos else 0.0
        stop_out[i] = stop if in_pos else np.nan
        entry_out[i] = entry_price if in_pos else np.nan
        entry_idx[i] = entry_i if in_pos else np.nan
        reason_out[i] = "" if in_pos else last_reason

    return pd.DataFrame({
        "state": state, "stop": stop_out, "entry_price": entry_out,
        "entry_index": entry_idx, "exit_reason": reason_out,
    }, index=df.index)


def exposure_path(path: pd.DataFrame, flat_exposure: float = FLAT_EXPOSURE,
                  max_exposure: float = 1.0) -> pd.Series:
    """State -> target exposure, so the repo's Portfolio can step it.

    `flat_exposure` is a parameter and not a constant because this project
    has already measured that a hard exit is not obviously right:
    trading.TREND_OFF_EXPOSURE is 0.35 rather than 0 precisely because
    research/defense.py's hard stops sold the low and bought back higher.
    research/flow.py chooses between the two on the training half.
    """
    return path["state"] * max_exposure + (1.0 - path["state"]) * flat_exposure


# ---------------------------------------------------------------------------
# Live path
# ---------------------------------------------------------------------------

def flow_signal(df: pd.DataFrame, params: BreakoutParams | None = None) -> dict:
    """The current breakout state for a prepared frame. Pure, no DB.

    `df` must be the ETF frame with add_flow_columns already applied, oldest
    first. `params` is the asset's own BreakoutParams; omitting it falls back
    to the module defaults, which is right for a test and wrong for a live
    asset -- see BreakoutParams for why the two metals differ.

    Returns a dict the UI and the daily mail can both print without
    recomputing anything, including the levels -- a breakout panel that shows
    a position but not the stop that ends it is showing half a decision.
    """
    if df.empty:
        return {"state": 0, "direction": "DOWN", "confidence": 0.0,
                "levels": {}, "votes": {}, "reason": "veri yok"}

    path = (breakout_path(df) if params is None else
            breakout_path(df, min_confirmations=params.min_confirmations,
                          stop_sigmas=params.stop_sigmas))
    row = df.iloc[-1]
    last = path.iloc[-1]
    votes = confirmation_votes(row)
    agree = sum(1 for v in votes.values() if v > 0)

    in_position = bool(last["state"])
    entry_price = float(last["entry_price"]) if pd.notna(last["entry_price"]) else None
    entry_index = int(last["entry_index"]) if pd.notna(last["entry_index"]) else None
    close = float(row["close"])

    def num(name):
        v = row.get(name)
        return float(v) if v is not None and pd.notna(v) else None

    levels = {
        "close": close,
        "vah": num("vah"), "val": num("val"), "poc": num("poc"),
        "avwap": num("avwap"), "avwap_anchor": num("avwap_anchor"),
        "flow": num("flow"),
        "stop": float(last["stop"]) if pd.notna(last["stop"]) else None,
        "entry_price": entry_price,
        "fib_high": num("fib_high"), "fib_low": num("fib_low"),
        "fib_pos": num("fib_pos"),
    }
    # Fibonacci extension of the trailing swing -- the level the rule would be
    # aiming at if it aimed at anything. It does NOT trigger an exit: the exit
    # is the stop and the trend break, and a profit target that closes a
    # winning trend is the opposite of "hold until it breaks". Display only,
    # exactly like gs_ratio.
    if levels["fib_high"] and levels["fib_low"]:
        span = levels["fib_high"] - levels["fib_low"]
        levels["fib_target"] = levels["fib_high"] + 0.618 * span
        levels["fib_support"] = levels["fib_low"] + 0.382 * span

    if in_position:
        held = (len(df) - 1 - entry_index) if entry_index is not None else 0
        gain = (close / entry_price - 1.0) if entry_price else 0.0
        headroom = (close / levels["stop"] - 1.0) if levels.get("stop") else None
        reason = (f"{held} seanstir pozisyonda; stop %{100 * headroom:.1f} asagida"
                  if headroom is not None else f"{held} seanstir pozisyonda")
        return {"state": 1, "direction": "UP",
                # Confidence is how many confirmations agree, not a
                # probability. It is NOT fed to ensemble.combine and must not
                # be: that function pools likelihood ratios against a measured
                # base rate, and this number has no such calibration.
                "confidence": agree / len(votes),
                "held_sessions": held, "gain": gain,
                "levels": levels, "votes": votes, "reason": reason}

    reason_map = {"stop": "stop seviyesi kirildi", "trend": "trend kirildi (AVWAP alti)"}
    return {"state": 0, "direction": "DOWN", "confidence": 0.0,
            "held_sessions": 0, "gain": 0.0,
            "levels": levels, "votes": votes,
            "exit_reason": str(last["exit_reason"] or ""),
            "reason": reason_map.get(str(last["exit_reason"]), "kirilim bekleniyor")}
