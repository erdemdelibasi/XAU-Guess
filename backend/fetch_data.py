"""Market data for gold and its macro drivers. No API key required.

Two independent sources, deliberately, because gold has a problem crypto
doesn't: **the market closes.** COMEX gold (GC=F) trades roughly 23h/day
Sunday evening to Friday afternoon New York time, so there is no such thing
as a Saturday gold price. Anything that needs a price *right now* on a
weekend has to come from somewhere else.

  Yahoo Finance chart API  -- primary. Keyless, ~25 years of daily history
      for GC=F and every macro series this project cares about (DXY, the
      Treasury curve, VIX, silver, copper, oil, FX). This is what the models
      train and backtest on.

  Binance PAXGUSDT         -- secondary. PAXG is a token redeemable for one
      troy ounce of LBMA gold, so it tracks spot closely but trades 24/7 on
      an endpoint this codebase already trusts (data-api.binance.vision,
      keyless, no cloud-IP blocks -- the same reasoning as XRP-Guess).
      Used for the live price when COMEX is shut, and as a sanity cross-check.

PAXG is NOT interchangeable with GC=F and must never be silently substituted
into a training set. Measured 2026-09-07: PAXG 4391.53 against GC=F 4476.60,
a 1.9% gap. That is not an error in either quote -- a futures contract with
months to expiry carries the cost of financing and storing the metal, so it
sits above spot, and PAXG carries its own small token premium/discount on top.
Mixing the two series would inject a phantom ~2% jump wherever the source
switched. `spot_reference_price()` is the only place they meet, and it
converts explicitly.
"""
from __future__ import annotations

import datetime as dt
import time
from zoneinfo import ZoneInfo

import pandas as pd
import requests

YAHOO_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
BINANCE_BASE = "https://data-api.binance.vision"

# Yahoo returns 403 to an unadorned python-requests User-Agent.
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

GOLD_SYMBOL = "GC=F"        # COMEX gold futures, front month, USD/troy oz
SILVER_SYMBOL = "SI=F"      # COMEX silver futures, front month, USD/troy oz
PAXG_SYMBOL = "PAXGUSDT"    # tokenized gold on Binance, 24/7

# Silver has no PAXG equivalent that this project trusts. Binance lists no
# LBMA-redeemable silver token with comparable liquidity, so silver simply has
# no weekend price here -- get_live_price falls back to the last COMEX close
# and labels it stale rather than substituting a thin proxy. An honest gap is
# better than a number whose provenance is different from the training data's.

# Macro series that actually drive gold, as opposed to series that merely
# correlate with it. Each is here for a stated reason; see macro.py for how
# they turn into a signal.
MACRO_SYMBOLS = {
    "dxy": "DX-Y.NYB",      # dollar index -- gold is priced in USD, so a stronger
                            # dollar mechanically lowers the gold price for
                            # non-USD buyers. The most reliable inverse relation.
    "us10y": "^TNX",        # 10Y nominal Treasury yield (in percent, e.g. 4.784)
    "us5y": "^FVX",         # 5Y nominal -- with us10y gives curve shape
    "us30y": "^TYX",        # 30Y nominal
    "vix": "^VIX",          # equity fear gauge -- gold's safe-haven bid
    "spx": "^GSPC",         # S&P 500 -- risk appetite
    "silver": "SI=F",       # silver futures -- the gold/silver ratio is a
                            # classic precious-metals regime indicator
    "copper": "HG=F",       # copper -- industrial demand; copper/gold is a
                            # widely-watched growth-vs-fear ratio
    "oil": "CL=F",          # WTI -- inflation impulse
    "eurusd": "EURUSD=X",
    "usdjpy": "USDJPY=X",
    "tip": "TIP",           # TIPS ETF -- with ief, a keyless proxy for real
    "ief": "IEF",           # yields (see macro.real_yield_proxy); FRED's own
                            # DFII10 series is the real thing but is not
                            # reachable from every network (see below).
    "gdx": "GDX",           # gold miners ETF. The ONE series here that feeds a
                            # standalone signal rather than the model -- see
                            # miners_signal.py. It graduated out of
                            # research/panel.CANDIDATE_SYMBOLS the only way a
                            # series may: research/drivers.py's Bonferroni bar,
                            # research/lags.py's alignment scan, and then
                            # research/miners.py's cost ladder. Do NOT add a
                            # series here that has not made that trip; this
                            # dict is fetched on every live run.
}

# FRED publishes the actual 10Y TIPS real yield (DFII10), the 10Y breakeven
# (T10YIE) and the Fed's own target rate as keyless CSV.
#
# REACHABILITY IS NOT SETTLED, AND THAT IS THE WHOLE DESIGN CONSTRAINT.
# fred.stlouisfed.org was completely unreachable from the development
# machine on 2026-09-07 (repeated 60s read timeouts, while every Yahoo call
# in the same process went through). On 2026-09-08 the same machine got
# every series in under 1.2s. Nothing in this repo changed in between, so
# the honest reading is that this host is intermittently blocked here, not
# that the block is gone.
#
# Everything downstream is therefore built to treat FRED as an ENRICHMENT
# that may vanish: get_fred_series returns None instead of raising, callers
# have a proxy path rather than an error path, and no model feature is ever
# conditioned on a FRED series being present (a feature set that changes
# shape with network weather produces models that cannot be loaded by the
# run that follows -- see predict.py's feature-name guard for what that
# costs). Research may use it freely; the live prediction path may not
# depend on it.
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_TIMEOUT = 12  # deliberately short -- this is an optional enrichment

# The Fed's target rate is published as two different series either side of
# 2008-12-16, when the FOMC switched from a single target to a range. Reading
# only one of them silently truncates the history at exactly the point the
# most interesting easing cycle starts.
FED_TARGET_SINGLE = "DFEDTAR"    # single target,  1982-09-27 .. 2008-12-15
FED_TARGET_LOWER = "DFEDTARL"    # range lower,    2008-12-16 ..
FED_TARGET_UPPER = "DFEDTARU"    # range upper,    2008-12-16 ..


def _yahoo_chart(symbol: str, params: dict, timeout: int = 30) -> dict | None:
    """Raw Yahoo chart call. Returns the `result[0]` payload or None."""
    resp = requests.get(f"{YAHOO_BASE}/{symbol}", params=params, headers=_HEADERS, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise RuntimeError(f"Yahoo error for {symbol}: {chart['error']}")
    results = chart.get("result")
    if not results:
        return None
    return results[0]


def _result_to_frame(result: dict) -> pd.DataFrame:
    """Yahoo's column-oriented payload -> a tidy OHLCV frame, oldest first.

    Yahoo emits `null` inside the OHLCV arrays for sessions it has no print
    for (holidays, halts, and routinely the not-yet-closed current bar). Those
    rows are dropped on `close` rather than forward-filled: a fabricated bar
    would become a fabricated training label, and for a market that genuinely
    shuts, "no bar" is the truth.
    """
    timestamps = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    if not timestamps:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame({
        "time": pd.to_datetime(timestamps, unit="s", utc=True),
        "open": quote.get("open"),
        "high": quote.get("high"),
        "low": quote.get("low"),
        "close": quote.get("close"),
        "volume": quote.get("volume"),
    })
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)
    # Indices and FX carry no meaningful volume on Yahoo; 0 is the honest fill.
    df["volume"] = df["volume"].fillna(0).astype(float)
    return df


# COMEX metals settle at 13:30 and the electronic session closes at 17:00
# America/New_York. A daily bar dated D is therefore final once the clock in
# New York has passed D 17:00 -- which is the ONLY rule here that does not
# depend on how Yahoo happens to stamp a row.
EXCHANGE_TZ = ZoneInfo("America/New_York")
SESSION_CLOSE_HOUR = 17


def bar_is_complete(bar_time: pd.Timestamp, now: dt.datetime | None = None) -> bool:
    """Has the session this daily bar belongs to actually closed?

    Yahoo's own timestamp cannot answer this. It stamps completed daily bars
    at 00:00 New York -- 04:00 UTC in EDT, 05:00 UTC in EST -- and stamps the
    STILL-FORMING bar exactly the same way (measured 2026-09-08 07:58 UTC:
    the half-traded 2026-09-08 session was served stamped 04:00:00, mid-session
    and indistinguishable from a closed one). It also sometimes stamps a
    genuinely finished half-day session with a wall clock instead
    (2025-11-28, the day after Thanksgiving, came back at 14:30 UTC).

    So the previous rule here -- "a clean 00:00 stamp means the bar is done" --
    was wrong in BOTH directions: it kept every partial bar it was written to
    remove, and it threw away a real early-close session. Reading the bar's
    own calendar date in exchange time and comparing it against the exchange
    clock is what the rule was trying to express in the first place.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    bar_date = bar_time.tz_convert(EXCHANGE_TZ).date()
    close = dt.datetime.combine(
        bar_date, dt.time(SESSION_CLOSE_HOUR), tzinfo=EXCHANGE_TZ)
    return now.astimezone(EXCHANGE_TZ) >= close


def drop_forming_bar(frame: pd.DataFrame, now: dt.datetime | None = None) -> pd.DataFrame:
    """Remove the trailing bar while its session is still open.

    ONE implementation, shared by the live path (predict.load_panel) and the
    research bench (research/panel.py). Those two carried a copy each of the
    broken stamp heuristic above, which is exactly how a data-hygiene rule
    gets fixed in one place and left rotting in the other.

    Predicting from a half-formed bar is a quiet leak on both sides: the
    features describe a session that has not happened yet, and `target_date`
    is computed from a session that has not closed, so the row lands a day
    early and the next day's cron then skips it as a duplicate.
    """
    if frame.empty:
        return frame
    if bar_is_complete(frame["time"].iloc[-1], now):
        return frame
    return frame.iloc[:-1].reset_index(drop=True)


def get_daily(symbol: str, years: int = 25) -> pd.DataFrame:
    """Daily OHLCV, oldest -> newest, going back `years`.

    Uses explicit period1/period2 epochs rather than range="max": `max` on a
    25-year window silently downgrades to MONTHLY bars (measured: 268 rows
    instead of 6341), which would quietly destroy the resolution of anything
    trained on it.
    """
    end = int(time.time())
    start = end - int(years * 365.25 * 86400)
    result = _yahoo_chart(symbol, {"period1": start, "period2": end, "interval": "1d"})
    if result is None:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
    return _result_to_frame(result)


def get_intraday(symbol: str, interval: str = "1h", range_: str = "2y") -> pd.DataFrame:
    """Intraday bars. Yahoo caps history by interval: ~2y at 1h, ~60d at 15m/5m."""
    result = _yahoo_chart(symbol, {"range": range_, "interval": interval})
    if result is None:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
    return _result_to_frame(result)


def get_gold_daily(years: int = 25) -> pd.DataFrame:
    return get_daily(GOLD_SYMBOL, years=years)


def get_macro_daily(years: int = 25) -> dict[str, pd.DataFrame]:
    """Every MACRO_SYMBOLS series as its own daily frame.

    Fail-soft per series: one dead symbol leaves a hole in the feature set
    instead of killing the run, exactly like XRP-Guess's safe_signal(). A
    caller that needs to know what it actually got should check the keys.
    """
    out: dict[str, pd.DataFrame] = {}
    for name, symbol in MACRO_SYMBOLS.items():
        try:
            frame = get_daily(symbol, years=years)
            if not frame.empty:
                out[name] = frame
        except Exception as exc:  # noqa: BLE001 -- deliberately broad, see docstring
            print(f"WARNING: macro series {name} ({symbol}) unavailable: {exc}")
    return out


def get_fred_series(series_id: str) -> pd.DataFrame | None:
    """FRED daily series as a (time, value) frame, or None if unreachable.

    None is a normal, expected outcome -- see FRED_CSV above. Callers must
    have a proxy path, not an error path.
    """
    try:
        resp = requests.get(FRED_CSV, params={"id": series_id}, headers=_HEADERS, timeout=FRED_TIMEOUT)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"NOTE: FRED series {series_id} unavailable ({type(exc).__name__}); using proxy instead.")
        return None

    from io import StringIO
    df = pd.read_csv(StringIO(resp.text))
    if df.shape[1] < 2:
        return None
    df.columns = ["time", "value"]
    df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
    # FRED writes "." for a no-print day (market holidays); coerce drops them.
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna().reset_index(drop=True)


def get_fed_target_rate() -> pd.DataFrame | None:
    """The Fed's target policy rate as one continuous daily step series.

    Splices DFEDTAR (a single target, to 2008-12-15) onto the midpoint of
    DFEDTARL/DFEDTARU (a range, from 2008-12-16). Both are CALENDAR-daily, so
    the date a value changes is the date the FOMC actually moved -- which is
    what makes an exact hike/cut event list possible without hardcoding an
    FOMC calendar from memory.

    Using the range MIDPOINT rather than the upper bound is deliberate: the
    upper bound alone is a different level from the pre-2008 single target,
    so splicing on it would print a 12.5 bp "cut" on 2008-12-16 that the FOMC
    never made. The midpoint is the closest continuous reading of the same
    quantity.

    None when FRED is unreachable -- see FRED_CSV. Every caller is research;
    nothing in the live prediction path may require this.
    """
    single = get_fred_series(FED_TARGET_SINGLE)
    lower = get_fred_series(FED_TARGET_LOWER)
    upper = get_fred_series(FED_TARGET_UPPER)
    if lower is None or upper is None:
        return single

    band = lower.merge(upper, on="time", suffixes=("_lo", "_hi"))
    band["value"] = (band["value_lo"] + band["value_hi"]) / 2.0
    band = band[["time", "value"]]
    if single is None:
        return band.reset_index(drop=True)

    single = single[single["time"] < band["time"].iloc[0]]
    return (pd.concat([single, band], ignore_index=True)
            .sort_values("time").reset_index(drop=True))


# --------------------------------------------------------------------------
# Binance PAXG -- the 24/7 half
# --------------------------------------------------------------------------

_KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_asset_volume", "num_trades",
    "taker_buy_base", "taker_buy_quote", "ignore",
]


def get_paxg_klines(interval: str = "1h", limit: int = 500, end_time_ms: int | None = None) -> pd.DataFrame:
    """PAXG/USDT candles. Keyless; 24/7 including weekends."""
    params = {"symbol": PAXG_SYMBOL, "interval": interval, "limit": min(limit, 1000)}
    if end_time_ms is not None:
        params["endTime"] = end_time_ms
    resp = requests.get(f"{BINANCE_BASE}/api/v3/klines", params=params, timeout=20)
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume", "taker_buy_base"])
    df = pd.DataFrame(rows, columns=_KLINE_COLUMNS)
    for col in ("open", "high", "low", "close", "volume", "taker_buy_base"):
        df[col] = df[col].astype(float)
    df["time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df[["time", "open", "high", "low", "close", "volume", "taker_buy_base"]]


def get_paxg_price() -> float:
    resp = requests.get(f"{BINANCE_BASE}/api/v3/ticker/price", params={"symbol": PAXG_SYMBOL}, timeout=15)
    resp.raise_for_status()
    return float(resp.json()["price"])


def get_live_price(symbol: str) -> tuple[float, str]:
    """Best available price for `symbol` right now, and where it came from.

    Gold routes through get_gold_live_price(), which can fall back to PAXG at
    the weekend. Every other symbol has no 24/7 proxy here, so a stale COMEX
    close is returned and LABELLED stale -- see SILVER_SYMBOL.
    """
    if symbol == GOLD_SYMBOL:
        return get_gold_live_price()
    try:
        result = _yahoo_chart(symbol, {"range": "1d", "interval": "1m"}, timeout=20)
        meta = (result or {}).get("meta") or {}
        price = meta.get("regularMarketPrice")
        market_time = meta.get("regularMarketTime")
        if price and market_time:
            age_hours = (time.time() - float(market_time)) / 3600.0
            return float(price), symbol if age_hours <= 6.0 else f"{symbol}(stale)"
        if price:
            return float(price), f"{symbol}(stale)"
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"No live price available for {symbol}: {exc}") from exc
    raise RuntimeError(f"No live price available for {symbol}.")


def get_gold_live_price() -> tuple[float, str]:
    """Best available gold price right now, and which source it came from.

    Prefers GC=F's own last trade. Yahoo keeps serving the previous session's
    close through the weekend, so "COMEX is closed" cannot be detected from
    the value alone -- `regularMarketTime` is checked against the clock, and
    anything staler than STALE_AFTER_HOURS falls through to PAXG converted to
    a futures-equivalent quote (see spot_reference_price for why the raw PAXG
    number must not be returned here as if it were GC=F).

    Returns (price, source) where source is "GC=F", "PAXG->GC=F" or "GC=F(stale)".
    """
    STALE_AFTER_HOURS = 6.0
    gold_price = None
    try:
        result = _yahoo_chart(GOLD_SYMBOL, {"range": "1d", "interval": "1m"}, timeout=20)
        meta = (result or {}).get("meta") or {}
        gold_price = meta.get("regularMarketPrice")
        market_time = meta.get("regularMarketTime")
        if gold_price and market_time:
            age_hours = (time.time() - float(market_time)) / 3600.0
            if age_hours <= STALE_AFTER_HOURS:
                return float(gold_price), GOLD_SYMBOL
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: GC=F live quote failed ({exc}); trying PAXG.")

    try:
        return spot_reference_price(), "PAXG->GC=F"
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: PAXG fallback failed too ({exc}).")

    if gold_price:
        return float(gold_price), "GC=F(stale)"
    raise RuntimeError("No gold price available from either Yahoo or Binance.")


def spot_reference_price() -> float:
    """PAXG converted into a GC=F-equivalent quote.

    PAXG tracks *spot* gold; GC=F is a *futures* contract and trades at a
    basis to spot (financing + storage), measured at ~1.9% on 2026-09-07.
    Feeding a raw PAXG number into a model trained on GC=F would read as an
    instant 1.9% crash. So the ratio is re-measured from the last common
    session rather than hardcoded -- the basis moves with interest rates, and
    a constant would rot.
    """
    paxg_now = get_paxg_price()

    gold = get_daily(GOLD_SYMBOL, years=1)
    paxg_daily = get_paxg_klines(interval="1d", limit=30)
    if gold.empty or paxg_daily.empty:
        return paxg_now  # nothing to calibrate against; caller labels the source

    gold_last_day = gold["time"].iloc[-1].normalize()
    paxg_daily = paxg_daily.assign(day=paxg_daily["time"].dt.normalize())
    match = paxg_daily[paxg_daily["day"] == gold_last_day]
    if match.empty:
        return paxg_now

    basis = float(gold["close"].iloc[-1]) / float(match["close"].iloc[-1])
    return paxg_now * basis


def align_on_gold(gold: pd.DataFrame, others: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Join every macro series onto gold's own trading calendar.

    Gold sets the index because gold is what we predict; a macro series that
    didn't print that day (different holiday calendars -- Treasuries close for
    Columbus Day, COMEX doesn't) is forward-filled from its last real value.
    Forward-fill is right here and wrong in `_result_to_frame`: there, filling
    would invent a gold bar and therefore a training label; here it just says
    "the last known 10Y yield is still the last known 10Y yield", which is
    what a trader on that day actually saw.

    Critically this only ever looks BACKWARD. `reindex(...).ffill()` cannot
    pull a future value into an earlier row, so no lookahead leaks in.
    """
    out = gold.copy()
    index = pd.DatetimeIndex(out["time"]).normalize()
    for name, frame in others.items():
        if frame.empty:
            continue
        series = frame.set_index(pd.DatetimeIndex(frame["time"]).normalize())["close"]
        series = series[~series.index.duplicated(keep="last")]
        out[name] = series.reindex(index, method="ffill").to_numpy()
    return out
