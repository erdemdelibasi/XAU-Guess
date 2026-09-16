"""Daily OHLCV from TradingView's chart feed, for the one thing Yahoo cannot do.

WHY THIS FILE EXISTS
--------------------
The breakout panel (flow_signal.py) needs volume, and research/flow.py part 0
measured that this project had no usable futures volume series:

    GC=F  the same 250 dates matched a days-old snapshot 3.6% of the time
          (r = -0.10), and a 25-year request returned a median of 219
          contracts where a 2-year request returned 181,246.
    SI=F  stable and implausible at every depth -- median 40-124 contracts
          against COMEX silver's ~60,000, with 627 zero-volume sessions.

So the panel was built on GLD/SLV, whose volume is real. That worked and it
cost the thing the panel is actually about: a person watching **ounce** gold
reads levels in GLD dollars ($404.96) and has to convert in their head.

TradingView has the series that fixes both. Measured on 2026-09-15:

    COMEX:GC1!   median volume 176,514  |  depth-invariant: the same 500
    COMEX:SI1!   median volume  57,776  |  dates match a 6,000-bar request
                                           99.8% / 100.0% of the time
    history       12,000 daily bars, back to 1979, with NO login
    prices        quoted per troy ounce -- $4,334 and $64, not $394 and $57

And gold's level agrees with an INDEPENDENT source: a fresh Yahoo GC=F fetch
gives a median of 176,343 against TradingView's 176,514, i.e. both vendors
are measuring the same quantity. Silver's does not agree and that is the
point -- 57,776 against Yahoo's 168.

SPOT WAS CHECKED FIRST AND HAS NO VOLUME AT ALL
------------------------------------------------
"Ounce gold" most directly means spot XAU/USD, so that was measured before
anything was built. `TVC:GOLD` and `TVC:SILVER` return volume **0 on every
bar**, as does `FX_IDC:XAUUSD`, because spot metal is an OTC market with no
consolidated tape. The OANDA feeds do return a number (574,434 and 179,253),
and it is the wrong number: one retail broker's own ticks, a sample of that
broker's customers rather than the market. Two brokers would disagree, and
neither would be "where the market traded".

A volume profile is a claim about where the MARKET traded. There is no
series that can support that claim for spot, from any vendor, so the panel
uses the COMEX contract -- which is priced in the same unit the reader wants
and is already what frontend/app.js marks the portfolios to (TV_FUTURES).

WHAT THIS IS NOT
----------------
An undocumented framed WebSocket protocol, not a published API. It can change
without notice, and TradingView's terms do not invite automated extraction.
Every caller must therefore treat an empty frame as normal -- `daily()`
returns an empty DataFrame rather than raising, exactly like
fetch_data.get_macro_daily's per-series fail-soft -- and nothing in the
prediction path may depend on it. Today only track_breakout.py and
research/flow.py call it, and neither one trades.
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import string

import pandas as pd

WS_URL = "wss://data.tradingview.com/socket.io/websocket"
ORIGIN = "https://www.tradingview.com"
# Sent as-is by the web client for a logged-out visitor.
ANON_TOKEN = "unauthorized_user_token"

# The two contracts the panel reads. Per troy ounce, real volume, and the
# same tickers frontend/app.js already marks the portfolios to -- so the card
# and the portfolio boxes cannot drift onto different instruments.
SYMBOLS = {"gold": "COMEX:GC1!", "silver": "COMEX:SI1!"}

# One frame per request; the feed streams until `series_completed`. 25s is
# generous for 6,000 bars (measured ~3s) and short enough that a hung socket
# in a cron job fails the step instead of holding it open.
TIMEOUT_SECONDS = 25
MAX_ATTEMPTS = 3


def _frame(payload: str) -> str:
    """TradingView's ~m~<length>~m~<payload> framing."""
    return f"~m~{len(payload)}~m~{payload}"


def _call(method: str, params: list) -> str:
    return _frame(json.dumps({"m": method, "p": params}, separators=(",", ":")))


def _session(prefix: str) -> str:
    return prefix + "".join(random.choice(string.ascii_lowercase) for _ in range(12))


async def _fetch(symbol: str, bars: int) -> list[dict]:
    # Imported here rather than at module scope so that importing this module
    # never fails on a machine that has not installed the dependency. The
    # panel is allowed to be missing; an ImportError at the top of a module
    # assets.py imports would take the whole backend down with it.
    import websockets

    chart = _session("cs_")
    async with websockets.connect(WS_URL, origin=ORIGIN, max_size=None,
                                  additional_headers={"User-Agent": "Mozilla/5.0"}) as ws:
        await ws.send(_call("set_auth_token", [ANON_TOKEN]))
        await ws.send(_call("chart_create_session", [chart, ""]))
        await ws.send(_call("resolve_symbol", [
            chart, "sym_1", '={"symbol":"%s","adjustment":"splits"}' % symbol]))
        await ws.send(_call("create_series", [chart, "s_1", "s1", "sym_1", "1D", bars, ""]))

        rows: list[dict] = []
        async with asyncio.timeout(TIMEOUT_SECONDS):
            while True:
                raw = await ws.recv()
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", "replace")
                for part in re.findall(r"~m~\d+~m~(.+?)(?=~m~\d+~m~|$)", raw):
                    # The server pings with ~h~<n> and drops the connection
                    # unless the exact frame is echoed back.
                    if part.startswith("~h~"):
                        await ws.send(_frame(part))
                        continue
                    try:
                        message = json.loads(part)
                    except json.JSONDecodeError:
                        continue
                    name = message.get("m", "")
                    if name == "timescale_update":
                        for block in message["p"][1:]:
                            if isinstance(block, dict) and "s_1" in block:
                                rows = block["s_1"].get("s", [])
                    elif name == "series_completed" and rows:
                        return rows
                    elif name in ("critical_error", "protocol_error", "symbol_error"):
                        raise RuntimeError(f"TradingView reddetti: {message}")


def daily(symbol: str, bars: int = 6000) -> pd.DataFrame:
    """Daily OHLCV for `symbol`, oldest first. Empty frame on any failure.

    Columns match fetch_data.get_daily exactly (time/open/high/low/close/
    volume, tz-aware UTC), so a caller can swap sources without touching the
    code downstream of it -- which is what lets research/flow.py score the
    same rule on both vendors.

    Never raises. The panel this feeds is allowed to go stale; nothing it
    feeds makes a trading decision.
    """
    empty = pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            rows = asyncio.run(_fetch(symbol, bars))
        except Exception as exc:  # noqa: BLE001 -- see the docstring
            print(f"NOTE: TradingView {symbol} denemesi {attempt}/{MAX_ATTEMPTS} "
                  f"basarisiz ({type(exc).__name__}: {exc})")
            continue
        if not rows:
            continue

        frame = pd.DataFrame([r["v"][:6] for r in rows],
                             columns=["ts", "open", "high", "low", "close", "volume"])
        frame["time"] = pd.to_datetime(frame["ts"], unit="s", utc=True)
        frame = frame.drop(columns=["ts"])
        for column in ("open", "high", "low", "close", "volume"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        # A row without a close is not a session. Same rule and same reason as
        # fetch_data._result_to_frame: a fabricated bar becomes a fabricated
        # level, and for a market that genuinely shut, "no bar" is the truth.
        frame = frame.dropna(subset=["close"]).sort_values("time").reset_index(drop=True)
        frame["volume"] = frame["volume"].fillna(0.0)
        return frame[["time", "open", "high", "low", "close", "volume"]]

    print(f"WARNING: TradingView {symbol} icin veri alinamadi ({MAX_ATTEMPTS} deneme).")
    return empty


def daily_for(asset_key: str, bars: int = 6000) -> pd.DataFrame:
    return daily(SYMBOLS[asset_key], bars=bars)


if __name__ == "__main__":  # quick manual check
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    for key, ticker in SYMBOLS.items():
        frame = daily(ticker, bars=int(sys.argv[1]) if len(sys.argv) > 1 else 2000)
        if frame.empty:
            print(f"{key:<8} veri yok")
            continue
        print(f"{key:<8} {ticker:<12} {len(frame):>5} bar  "
              f"{frame['time'].iloc[0].date()} -> {frame['time'].iloc[-1].date()}  "
              f"kapanis {frame['close'].iloc[-1]:>10,.2f}  "
              f"medyan hacim {frame['volume'].median():>12,.0f}")
