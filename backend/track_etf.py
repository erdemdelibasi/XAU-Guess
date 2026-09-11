"""Paper books for the instruments a person can actually buy.

WHY THIS FILE EXISTS
--------------------
Every portfolio in predict.py is valued in COMEX futures (GC=F / SI=F), and
no retail account can hold a futures contract. research/README.md section 16
found that this is not a cosmetic difference: the `miners` edge turned out to
be largely a session-boundary artefact of the futures bar and vanished on
GLD. Section 17 then re-ran the entire scoreboard on GLD/IAU/SLV in a common
window with a flat commission, and the ranking changed fundamentally in both
directions.

So these books answer the question the futures books cannot: what would have
happened in an account that actually bought the thing.

WHAT IT DOES AND DOES NOT CLAIM
--------------------------------
Section 17's headline is not that a strategy makes money. It is the opposite,
and it has to stay attached to these portfolios wherever they are shown:

    GLD, $10,000, 16.1 years, $1.50 per trade
      voltarget   $36,257   maxDD 39.2%   Sharpe 0.59   131 trades
      buyhold     $34,844   maxDD 45.6%   Sharpe 0.48     1 trade

$1,413 over sixteen years is noise. What is not noise is six points of
drawdown and eleven points of Sharpe, bought with about eight trades a year.
These books exist to watch whether that RISK reduction holds up live -- not
to wait for it to make money. Three other strategies beat buy-and-hold on
Calmar in the same test and finished with LESS money than doing nothing.

BOTH METALS GET A BOOK, AND THEY DO NOT CLAIM THE SAME THING
-------------------------------------------------------------
This project is a two-metal one everywhere else, and stopping at gold exactly
where the metal becomes buyable would have been a silent narrowing. SLV was
measured on SLV rather than inherited from GLD:

    SLV, $10,000, 16.1 years, $1.50 per trade
      voltarget   $35,023   maxDD 70.8%   Sharpe 0.32   114 trades
      buyhold     $33,286   maxDD 76.3%   Sharpe 0.24     1 trade

Same shape, far rougher ground. Silver's buy-and-hold drawdown is 76.3%
against gold's 45.6% -- the 25-year table in assets.py showing up in a live
book -- so the five points `voltarget` cuts here are a smaller bite out of a
much larger wound than gold's six. Reporting gold's pair beside a silver book
would misstate both numbers, which is why daily_report.ETF_CLAIM and the
frontend's TRACKED_ETFS carry one string per instrument rather than one
shared one.

ONLY MECHANICAL STRATEGIES RUN HERE
------------------------------------
trading.MECHANICAL -- buyhold, voltarget, trend, defensive -- and that is a
measured choice rather than a convenient one. Of everything that beat
buy-and-hold on the ETF at a $10,000 account in section 17, all but
`ensemble` is mechanical. They also happen to be exactly the strategies that
need price history and nothing else: no ML model, no calibrator, no macro
panel, no Claude call. `ensemble` is left out because bringing it would mean
a third model file and a daily LLM call for one row.

COST IS MODELLED AS THE BROKER CHARGES IT
------------------------------------------
`assets.GLD.flat_fee_usd` is $1.50 per trade and `fee_rate` is 1 bp of spread.
Section 15 measured how far apart a flat and a proportional fee are -- on a
$1000 book a $1.50 commission bankrupts the highest-turnover strategies -- so
a tracker paying a percentage while the person pays a flat fee would flatter
itself every single day.

RUNS ON THE SAME CRON AS predict.py, AFTER IT
----------------------------------------------
ETFs settle 16:00 New York and predict.py runs at 23:00 UTC (19:00 New York),
so by then the session this file reads is long closed. It touches no model
and no LLM, so it cannot fail for a reason predict.py would not also hit.
"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import numpy as np

import assets as assets_module
import fetch_data
import trading
from db import get_client

# Enough history for the 200-day trend average plus a comfortable margin.
# trading.VOL_LOOKBACK_DAYS is 60 and the SMA is 200, so two years is the
# binding requirement; three is asked for so a run is never one holiday short.
HISTORY_YEARS = 3
MIN_ROWS = 220


def latest_state(asset) -> dict | None:
    """Price, 200-day average and realised volatility from closed sessions only.

    `drop_forming_bar` is the SAME function predict.py and research/panel.py
    use. It decides completeness against the exchange clock rather than
    Yahoo's timestamp, which is what stops a half-formed session from being
    traded on -- see fetch_data.bar_is_complete for the two ways the old
    timestamp-shape rule was wrong.
    """
    frame = fetch_data.get_daily(asset.symbol, years=HISTORY_YEARS)
    if frame.empty:
        print(f"WARNING: {asset.symbol} icin veri gelmedi -- atlaniyor.")
        return None
    frame = fetch_data.drop_forming_bar(frame)
    if len(frame) < MIN_ROWS:
        print(f"WARNING: {asset.symbol} icin yeterli gecmis yok "
              f"({len(frame)} < {MIN_ROWS}) -- atlaniyor.")
        return None

    closes = frame["close"].to_numpy(dtype=float)
    returns = np.diff(closes) / closes[:-1]
    return {
        "price": float(closes[-1]),
        "date": frame["time"].iloc[-1].date(),
        # trading.VOL_LOOKBACK_DAYS, not a local number: backtest.py records
        # that feeding the signal path a 20-day estimate while production used
        # 60 was testing a different, noisier strategy under the same name.
        "volatility": trading.realised_volatility(returns),
        "trend_average": float(np.mean(closes[-200:])),
    }


def books_exist(db, asset_key: str) -> bool:
    """Are this asset's portfolio rows seeded?

    Checked up front rather than discovered per strategy. trading.
    get_portfolio_state uses `.single()`, which RAISES when the row is
    missing, and run_asset catches per strategy -- so without this the run
    would print four cryptic exceptions, report itself as done, and leave the
    reader to work out that a migration was never applied. The repo cannot
    apply its own migrations (see CLAUDE.md), so saying exactly which one is
    the whole job here.
    """
    rows = db.table("portfolios").select("strategy").eq("asset", asset_key).execute().data
    return bool(rows)


def run_asset(db, asset) -> int:
    if not books_exist(db, asset.key):
        print(f"\n{asset.label} ({asset.symbol}): `{asset.key}` portfoy satirlari yok.")
        print("  supabase/schema.sql'deki `gld` seed'i Supabase SQL Editor'de")
        print("  calistirilmamis. O migration uygulanana kadar bu defterler islemez.")
        return 0

    state = latest_state(asset)
    if state is None:
        return 0

    print(f"\n{'=' * 72}\n### {asset.label} ({asset.symbol})\n{'=' * 72}")
    print(f"Son kapanis {state['date']}: ${state['price']:,.2f} | "
          f"oynaklik %{100 * state['volatility']:.1f} yillik | "
          f"200g ort ${state['trend_average']:,.2f}")
    print(f"Komisyon: islem basina ${asset.flat_fee_usd:.2f} + "
          f"{asset.fee_rate * 10_000:.0f}bp makas")

    for strategy in trading.MECHANICAL:
        # direction/confidence are passed but ignored: every strategy here is
        # in trading.MECHANICAL, which compute_target_exposure returns from
        # before it reads either. They are supplied rather than defaulted so
        # that wiring a forecast in later would have to be a deliberate edit.
        try:
            trading.maybe_trade(db, asset, strategy, None, state["price"],
                                state["trend_average"], state["volatility"],
                                "UP", 0.0)
        except Exception as exc:  # noqa: BLE001 -- one book must not block the rest
            print(f"WARNING: {asset.key}/{strategy} guncellenemedi ({exc})")
    return 1


def main() -> int:
    db = get_client()
    done = 0
    for asset in assets_module.TRACKED.values():
        done += run_asset(db, asset)
    if not done:
        print("Hicbir ETF guncellenemedi.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
