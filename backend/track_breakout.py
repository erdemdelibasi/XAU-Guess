"""Writes the breakout panel's state -- order flow, anchored VWAP, volume profile.

WHAT THIS IS, AND WHY IT IS A SEPARATE SCRIPT
----------------------------------------------
Same shape as track_etf.py and for the same reasons: no model, no LLM, no
macro panel, nothing but price and volume history. It runs in predict.py's
workflow step rather than inside predict.py because a failure here -- a dead
Yahoo series, a missing migration -- must not take down the prediction, and
because `breakout` is not a prediction component. It does not vote in
ensemble.combine(), it does not appear in trading.STRATEGIES, and it sizes
nothing.

IT DELIBERATELY TRADES NOTHING
------------------------------
research/flow.py scored this rule against a bar declared before any result
was looked at: beat buy-and-hold on Calmar on the BUYABLE instrument at the
$10,000 rung in BOTH metals, and finish no more than 25% behind it in money.
Out of sample, 2016-2026:

    gold    Calmar 0.566 vs 0.495  PASS  |  $24,556 vs $37,163  -33.9%  FAIL
    silver  Calmar 0.116 vs 0.232  FAIL  |  $16,488 vs $31,275  -47.3%  FAIL

So the bar was not cleared and no paper portfolio was created. The panel
ships anyway, with that table on it, because the rule's state is a real and
legible description of the market -- and because a project whose value is
honest negative results should be able to show a measured loss on screen.
`miners` set the precedent the other way round (a real signal too expensive
to trade); this is the same discipline applied to a rule that is simply not
better than holding.

THE WINDOW IS REWRITTEN, NOT APPENDED TO
----------------------------------------
Every column is a deterministic function of price and volume history, so
recomputing a past session returns the same numbers -- and rewriting means
the chart is complete on the first run instead of filling in over six months.
See supabase/schema.sql's comment on breakout_state.
"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from datetime import datetime, timezone

import pandas as pd

import assets as assets_module
import fetch_data
import flow_signal
from db import get_client

# Deep enough that the state at the newest session is a genuine continuation
# rather than an artefact of where the walk started. The binding requirement
# is flow_signal.AVWAP_ANCHOR_LOOKBACK (252 sessions) plus a full warm-up;
# eight years is ~2000 rows, still one request, and positions in this rule
# average under a month, so nothing that matters today was opened outside it.
HISTORY_YEARS = 8
# How much of the path is published. ~9 months: long enough that the chart
# shows several complete positions, short enough that one row per session
# per asset stays a trivial write.
WINDOW_SESSIONS = 190
# Columns that must exist before a session can be published at all. A row
# missing its value area is not a flat row, it is a row where the rule had
# not started yet, and charting it would draw a gap as if it were a decision.
REQUIRED = ("vah", "val", "avwap", "flow", "sigma", "fib_pos")


def _num(value):
    """Supabase wants JSON. numpy floats and NaN are neither."""
    if value is None or pd.isna(value):
        return None
    return float(value)


def build_rows(asset) -> list[dict]:
    """The published window for one asset, newest last. Pure except for I/O."""
    params = asset.breakout
    if params is None:
        return []

    etf = fetch_data.drop_forming_bar(
        fetch_data.get_daily(params.etf_symbol, years=HISTORY_YEARS))
    if etf.empty:
        print(f"WARNING: {params.etf_symbol} icin veri gelmedi -- {asset.key} atlaniyor.")
        return []

    frame = flow_signal.add_flow_columns(etf)

    # The metal's own close, on the ETF's calendar, backward-fill only. It is
    # DISPLAY: the panel prints both because they are different instruments
    # and the reader is holding the metal, not the fund. No signal column
    # reads it -- see flow_signal.py's docstring for why the signal lives on
    # the ETF series in the first place.
    metal = fetch_data.drop_forming_bar(
        fetch_data.get_daily(asset.symbol, years=HISTORY_YEARS))
    if not metal.empty:
        series = metal.set_index(pd.DatetimeIndex(metal["time"]).normalize())["close"]
        series = series[~series.index.duplicated(keep="last")]
        frame["metal_close"] = series.reindex(
            pd.DatetimeIndex(frame["time"]).normalize(), method="ffill").to_numpy()
    else:
        frame["metal_close"] = float("nan")

    # reset_index is not cosmetic here. breakout_path records `entry_index` as
    # a POSITION within the frame it walked, while dropna leaves the original
    # labels with gaps in them. The two happen to be read positionally below
    # and would agree either way -- until someone reasonably reads
    # `entry_index` as a label and looks the row up with .loc, which would
    # silently return a different session. Making label and position the same
    # removes the trap rather than documenting it.
    ready = frame.dropna(subset=list(REQUIRED)).reset_index(drop=True)
    if ready.empty:
        print(f"WARNING: {asset.key} icin yeterli gecmis yok -- atlaniyor.")
        return []

    # The path is walked over the WHOLE prepared frame and only then sliced.
    # Walking the published window alone would restart the state machine 190
    # sessions ago and could report "flat" on a position that has been open
    # for a year -- the class of bug that produces a plausible wrong answer.
    path = flow_signal.breakout_path(
        ready, min_confirmations=params.min_confirmations,
        stop_sigmas=params.stop_sigmas)
    votes = flow_signal.vote_totals(ready)

    joined = ready.join(path).assign(votes=votes)
    window = joined.tail(WINDOW_SESSIONS)
    now_iso = datetime.now(timezone.utc).isoformat()
    dates = [t.date() for t in ready["time"]]

    rows = []
    for _, row in window.iterrows():
        entry_index = row["entry_index"]
        entry_date = (dates[int(entry_index)]
                      if pd.notna(entry_index) and 0 <= int(entry_index) < len(dates)
                      else None)
        rows.append({
            "asset": asset.key,
            "session_date": row["time"].date().isoformat(),
            "etf_symbol": params.etf_symbol,
            "close": _num(row["close"]),
            "metal_close": _num(row.get("metal_close")),
            "state": int(row["state"]),
            "stop": _num(row["stop"]),
            "entry_price": _num(row["entry_price"]),
            "entry_date": entry_date.isoformat() if entry_date else None,
            "exit_reason": str(row["exit_reason"]) or None,
            "avwap": _num(row["avwap"]),
            "avwap_anchor": _num(row["avwap_anchor"]),
            "poc": _num(row["poc"]),
            "vah": _num(row["vah"]),
            "val": _num(row["val"]),
            "flow": _num(row["flow"]),
            "rsi14": _num(row["rsi14"]),
            "macd_hist": _num(row["macd_hist"]),
            "cci20": _num(row["cci20"]),
            "mom10": _num(row["mom10"]),
            "stoch_k": _num(row["stoch_k"]),
            "fib_pos": _num(row["fib_pos"]),
            "fib_high": _num(row["fib_high"]),
            "fib_low": _num(row["fib_low"]),
            "votes": int(row["votes"]),
            # The six votes individually, from the SCALAR function the live
            # path uses -- not re-derived in the browser. See the column's
            # comment in schema.sql. flow_signal.vote_totals() above is the
            # vectorised twin of this; tests/test_flow_signal.py scores both
            # on the same rows so the pair cannot drift apart.
            "votes_detail": flow_signal.confirmation_votes(row),
            "updated_at": now_iso,
        })
    return rows


def report(asset, rows: list[dict]) -> None:
    last = rows[-1]
    print(f"\n{'=' * 72}\n### {asset.label} -- kirilim takibi "
          f"({asset.breakout.etf_symbol} hacminden)\n{'=' * 72}")
    metal = (f" | {asset.symbol} ${last['metal_close']:,.2f}"
             if last["metal_close"] else "")
    print(f"Son seans {last['session_date']}: {asset.breakout.etf_symbol} "
          f"${last['close']:,.2f}{metal}")
    if last["state"]:
        gain = last["close"] / last["entry_price"] - 1.0 if last["entry_price"] else 0.0
        print(f"DURUM: POZISYONDA -- giris {last['entry_date']} "
              f"${last['entry_price']:,.2f} (%{100 * gain:+.1f}), "
              f"stop ${last['stop']:,.2f}")
    else:
        print(f"DURUM: BOSTA -- son cikis sebebi: {last['exit_reason'] or 'henuz giris yok'}")
    print(f"Deger alani ${last['val']:,.2f} - ${last['vah']:,.2f} "
          f"(POC ${last['poc']:,.2f}) | AVWAP ${last['avwap']:,.2f} | "
          f"akis {last['flow']:+.3f} | onay {last['votes']:+d}/6")
    in_pos = sum(r["state"] for r in rows)
    print(f"Yayinlanan pencere: {len(rows)} seans, {in_pos} tanesi pozisyonda "
          f"(%{100 * in_pos / len(rows):.0f})")


def run_asset(db, asset) -> int:
    rows = build_rows(asset)
    if not rows:
        return 0
    try:
        # Chunked: PostgREST rejects an oversized body outright and a 190-row
        # upsert with 25 columns is close enough to the default limit that a
        # future column would silently push it over.
        for start in range(0, len(rows), 100):
            db.table("breakout_state").upsert(
                rows[start:start + 100], on_conflict="asset,session_date").execute()
    except Exception as exc:  # noqa: BLE001
        print(f"\nHATA: {asset.key} icin breakout_state yazilamadi ({exc}).")
        print("  supabase/schema.sql'in 2026-09-15 migration'i Supabase SQL")
        print("  Editor'de calistirilmamis olabilir -- tablo yoksa PostgREST")
        print("  sorguyu komple reddeder ve sayfadaki kart bos kalir.")
        return 0
    report(asset, rows)
    return 1


def main() -> int:
    db = get_client()
    done = 0
    for asset in assets_module.ASSETS.values():
        try:
            done += run_asset(db, asset)
        except Exception as exc:  # noqa: BLE001 -- one metal must not block the other
            print(f"WARNING: {asset.key} kirilim durumu guncellenemedi ({exc})")
    if not done:
        print("Hicbir varlik icin kirilim durumu yazilamadi.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
