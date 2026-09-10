"""Does anything in this repo survive on the instrument a person can buy?

Section 16 measured that the miners lead is largely a futures SESSION
BOUNDARY effect: `GC=F`'s daily bar runs ~23 hours (18:00 the previous
evening to 17:00) while `GDX`'s runs 09:30-16:00, so the futures bar for t+1
opens two hours after GDX closes and mechanically collects part of the same
day's reaction. On `GLD`, which closes at 16:00 alongside GDX, the lead
collapses from +0.150 to +0.040 and the strategy loses to buy-and-hold.

That finding is about one strategy but the exposure is general: **every
number in research/README.md was measured on `GC=F`/`SI=F`, and no retail
account can hold a COMEX futures contract.** What a person actually buys is
`GLD`, `IAU`, `GLDM` or `SLV`. This file re-runs the entire scoreboard there.

WHAT IS EXPECTED, AND WHY THAT IS NOT AN ANSWER
------------------------------------------------
The mechanisms differ in how much they should care about the instrument:

  * `voltarget` / `trend` / `defensive` respond to REALISED volatility and to
    a moving average of the asset's own price. Both are properties of the
    price series itself, so they ought to transfer.
  * `technical` / `ml` / `macro` read features built from the same price
    series plus macro columns that are identical in both panels.
  * `miners` was the one whose edge was a clock, and it is already known to
    fail here.

But "ought to transfer" is not a measurement, and this bench exists because
the plausible answer has been wrong repeatedly (the gs_ratio rotation that
vanished under volatility matching, the damping grid whose winner just
imitated always-UP, the GVZ weights the two halves ranked in opposite order).

PRE-REGISTERED, before any of it ran
-------------------------------------
SURVIVES = beats `buyhold` on Calmar, on the ETF, at the $10,000 rung with a
$1.50 flat commission -- the account and cost structure actually in play.
Every strategy is reported at every rung either way; nothing is selected
after the fact, and the futures column sits beside the ETF column so the
DIFFERENCE is the measured quantity rather than the ETF number alone.

THE CONSTANTS ARE RE-MEASURED, NOT INHERITED
---------------------------------------------
assets.py's whole point is that copying one asset's constants to another
silently rebases its scoreboard. An ETF tracking gold is not gold futures,
so its constants are measured here and printed beside the futures ones. All
three price scales normalise ratios (`macd_hist/close`, `ema9/ema21 - 1`,
`close/sma200 - 1`), so the ~10x price-level difference between GLD ($403)
and GC=F ($4384) does not matter by construction -- but the VOLATILITY of
those ratios does, and that is an empirical question.

The counterpart is swapped to its ETF too. Leaving `silver` as `SI=F` in
GLD's panel would feed `counterpart_chg` a futures return carrying exactly
the session-boundary phase shift this file exists to measure.
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import replace

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import assets as assets_module  # noqa: E402
import backtest as backtest_module  # noqa: E402
import fetch_data  # noqa: E402
import panel as panel_module  # noqa: E402
import trading  # noqa: E402
from indicators import PriceScales, build_features  # noqa: E402

# The tradeable proxy for each metal. GLD and SLV are the deepest and most
# liquid; IAU is carried for gold as a cross-check with a different expense
# ratio (0.25% vs 0.40%) and a different sponsor, so a result that appears in
# one and not the other is a fund artefact rather than a market fact.
ETF = {"gold": "GLD", "silver": "SLV"}
CROSS_CHECK = {"gold": "IAU"}

FLAT_FEE_USD = 1.50
FLAT_SPREAD_BPS = 1.0
ACCOUNT_SIZES = (5_000, 10_000, 25_000, 100_000)
VERDICT_ACCOUNT = 10_000        # the rung the pre-registered bar is read at

TRADING_DAYS = 252
SCALE_PERCENTILE = 90
HORIZON = 5                     # ml_model.HORIZON_DAYS, for the base rate


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

def etf_panel(asset, ticker: str) -> pd.DataFrame:
    """The research panel, rebuilt with an ETF in the metal's seat.

    Same hygiene as research/panel.build: the forming bar is dropped by the
    SAME function predict.py uses, flat bars are flagged rather than dropped,
    and macro series are joined on the price series' own calendar with a
    backward-only ffill.

    `drop_forming_bar` decides completeness against COMEX's 17:00 close while
    an ETF settles at 16:00. That is conservative in the safe direction -- it
    waits an extra hour before trusting a bar -- and it can only ever affect
    the final row.
    """
    prices = fetch_data.get_daily(ticker, years=25)
    if prices.empty:
        return pd.DataFrame()
    prices = panel_module.flag_flat_bars(fetch_data.drop_forming_bar(prices))

    wanted = dict(fetch_data.MACRO_SYMBOLS)
    wanted.pop(asset.key, None)
    # The counterpart goes in as ITS etf, not as futures -- see module docstring.
    wanted[asset.counterpart_key] = ETF[asset.counterpart_key]

    macro = {}
    for name, symbol in wanted.items():
        try:
            frame = fetch_data.get_daily(symbol, years=25)
            if not frame.empty:
                macro[name] = frame
        except Exception as exc:  # noqa: BLE001 -- one dead series must not kill it
            print(f"    WARNING: {name} ({symbol}) alinamadi: {exc}")
    return fetch_data.align_on_gold(prices, macro)


# ---------------------------------------------------------------------------
# Part 1 -- the constants assets.py forbids copying
# ---------------------------------------------------------------------------

def measure_constants(frame: pd.DataFrame) -> dict:
    """price_scales, target volatility and base rate, measured on THIS series.

    Each scale is 1 / p90(|quantity|) so a 90th-percentile move maps to a full
    score -- the definition assets.py states and research/compare.py applies.
    """
    def scale(values: pd.Series) -> float:
        v = values.abs().dropna()
        p90 = float(np.percentile(v, SCALE_PERCENTILE)) if len(v) else float("nan")
        return float("nan") if not p90 else 1.0 / p90

    close = frame["close"]
    ret = close.pct_change()
    fwd = close.shift(-HORIZON) / close - 1.0
    return {
        "macd": scale(frame["macd_hist"] / close),
        "ema_cross": scale(frame["ema9_21"]),
        "sma200": scale(frame["px_sma200"]),
        "vol": float(ret.std() * np.sqrt(TRADING_DAYS)),
        "base_rate": float((fwd.dropna() > 0).mean()),
        "n": len(frame),
    }


def part1(asset, futures: pd.DataFrame, etf_frames: dict) -> dict:
    print("\n" + "=" * 100)
    print("  BOLUM 1 -- assets.py'nin KOPYALANMASINI YASAKLADIGI SABITLER")
    print("=" * 100)
    print("  Uc olcek de bir ORAN normalize ediyor (macd_hist/close, ema9/ema21-1,")
    print("  close/sma200-1), yani GLD'nin ~$403 ile GC=F'in ~$4384'u arasindaki")
    print("  10 kat fiyat farki tanim geregi onemsiz. Onemli olan o oranlarin")
    print("  OYNAKLIGI, ve o ampirik bir soru.")

    rows = {asset.symbol: measure_constants(futures)}
    for ticker, frame in etf_frames.items():
        rows[ticker] = measure_constants(frame)

    print(f"\n  {'seri':<8}{'n':>7}{'macd':>10}{'ema_cross':>12}{'sma200':>10}"
          f"{'yillik oynak':>15}{'taban oran':>13}")
    for name, m in rows.items():
        print(f"  {name:<8}{m['n']:>7}{m['macd']:>10.1f}{m['ema_cross']:>12.1f}"
              f"{m['sma200']:>10.2f}{100 * m['vol']:>14.1f}%{m['base_rate']:>13.3f}")

    live = asset.price_scales
    print(f"\n  {'uretimde (assets.py)':<8}{'':>7}{live.macd:>10.1f}"
          f"{live.ema_cross:>12.1f}{live.sma200:>10.2f}"
          f"{100 * asset.target_volatility:>14.1f}%{asset.base_rate_up:>13.3f}")
    print()
    print("  Backtest her seri icin KENDI olculen PRICE_SCALES'ini kullaniyor --")
    print("  vadelinin olceklerini ETF'e devretmek, CLAUDE.md'nin gumus icin")
    print("  belgeledigi 'kopyalanan sabit' arizasinin aynisi olurdu.")
    print()
    print("  Ama target_volatility DEGISTIRILMIYOR ve bu bilincli: o bir olcum")
    print("  degil, bir RISK TERCIHI. Altin %18,1 gerceklestiriyor %15 hedefliyor,")
    print("  gumus %33,7 gerceklestiriyor %28 hedefliyor -- ikisi de gerceklesenin")
    print("  ~%83'u. Her seriye kendi gerceklesen oynakligini hedefletmek,")
    print("  `voltarget`i iki sutunda FARKLI bir strateji yapardi ve aradaki fark")
    print("  artik enstruman olmazdi. Yukaridaki oynaklik sutunu bunun adil")
    print("  oldugunu gormek icin basiliyor. base_rate_up de sabit: backtest.py")
    print("  onu hic okumuyor.")
    return rows


# ---------------------------------------------------------------------------
# Part 2 -- the whole scoreboard, on the tradeable thing
# ---------------------------------------------------------------------------

def asset_for(asset, measured: dict):
    """The asset's record with ONLY the price scales re-measured.

    `price_scales` are re-measured because assets.py defines them as
    1/p90(|quantity|) ON THIS SERIES -- they are a property of the data, and
    inheriting them is the documented failure that rebased silver's entire
    scoreboard.

    `target_volatility` is deliberately NOT re-measured, and getting this
    wrong would have quietly invalidated the comparison. It is a risk
    PREFERENCE, not a measurement: gold realises 18.1% and targets 15%,
    silver realises 33.7% and targets 28% -- both about 83% of realised, i.e.
    a chosen budget. Substituting each series' own realised volatility would
    have made `voltarget` on GLD aim at a different risk level than
    `voltarget` on GC=F, so the two columns would no longer be the same
    strategy and the difference between them would not be the instrument.
    Part 1 prints both series' realised volatility precisely so a reader can
    check that keeping the target is fair.

    `base_rate_up` is likewise left alone: backtest.py never reads it (only
    ensemble/calibration do, and neither is replayed here), so substituting
    it would change nothing while implying it had.

    dataclasses.replace rather than a new literal, so a field added to Asset
    later cannot be silently dropped here.
    """
    return replace(
        asset,
        price_scales=PriceScales(macd=measured["macd"],
                                 ema_cross=measured["ema_cross"],
                                 sma200=measured["sma200"]),
    )


def run_books(path: pd.DataFrame, scoped, years: float) -> dict:
    """Every strategy at every account size, under a flat commission."""
    out: dict[str, dict[int, object]] = {}
    for size in ACCOUNT_SIZES:
        scaled = FLAT_FEE_USD * trading.STARTING_CASH / size
        books = backtest_module.simulate(path, FLAT_SPREAD_BPS / 10_000.0,
                                         scoped, flat_fee=scaled)
        for name, book in books.items():
            if min(book.equity) <= 0:
                out.setdefault(name, {})[size] = backtest_module.BUST
            else:
                out.setdefault(name, {})[size] = backtest_module.metrics(
                    book.equity, book.exposure, years)
    return out


def report(label: str, results: dict) -> list[str]:
    print(f"\n  --- {label} ---")
    print(f"      {'strateji':<19}" +
          "".join(f"{'$' + format(n, ','):>13}" for n in ACCOUNT_SIZES))
    print("      " + "-" * (19 + 13 * len(ACCOUNT_SIZES)))
    bench = results["buyhold"]

    def calmar(cell):
        return cell if cell is backtest_module.BUST else cell.get("calmar", float("nan"))

    ordered = sorted(results, key=lambda n: -(
        -99 if calmar(results[n][ACCOUNT_SIZES[-1]]) is backtest_module.BUST
        else calmar(results[n][ACCOUNT_SIZES[-1]])))
    for name in ordered:
        cells = "".join(
            f"{'IFLAS':>13}" if results[name][s] is backtest_module.BUST
            else f"{calmar(results[name][s]):>13.3f}" for s in ACCOUNT_SIZES)
        display = backtest_module.DISPLAY_NAME.get(name, name)
        print(f"      {display:<19}{cells}")

    survivors = [n for n in results if n != "buyhold" and backtest_module._beats(
        calmar(results[n][VERDICT_ACCOUNT]), calmar(bench[VERDICT_ACCOUNT]))]
    print(f"\n      ${VERDICT_ACCOUNT:,} rungunda al-ve-tut'u gecen: "
          f"{', '.join(backtest_module.DISPLAY_NAME.get(s, s) for s in survivors) if survivors else 'HICBIRI'}")
    return survivors


def run_for_asset(asset) -> None:
    print("\n" + "#" * 100)
    print(f"### {asset.label.upper()}  --  vadeli ({asset.symbol}) vs ETF")
    print("#" * 100)

    futures_raw = panel_module.load(asset.key).reset_index(drop=True)
    futures = build_features(futures_raw, asset.leading_drivers)

    tickers = [ETF[asset.key]] + list(
        t for t in (CROSS_CHECK.get(asset.key),) if t)
    etf_frames = {}
    for ticker in tickers:
        print(f"  {ticker} paneli kuruluyor...", flush=True)
        raw = etf_panel(asset, ticker)
        if raw.empty:
            print(f"    {ticker}: veri yok, atlandi.")
            continue
        etf_frames[ticker] = build_features(raw, asset.leading_drivers)
        f = etf_frames[ticker]
        print(f"    {len(f)} gun ({f['time'].iloc[0].date()} -> {f['time'].iloc[-1].date()})")

    measured = part1(asset, futures, etf_frames)

    print("\n" + "=" * 100)
    print(f"  BOLUM 2 -- TUM SKORBORD, islem basina ${FLAT_FEE_USD:.2f} "
          f"+ {FLAT_SPREAD_BPS:.0f}bp (Calmar)")
    print("=" * 100)

    scoped = {name: asset_for(asset, measured[name])
              for name in [asset.symbol] + list(etf_frames)}
    paths = {}
    for name, frame in [(asset.symbol, futures)] + list(etf_frames.items()):
        t0 = time.time()
        print(f"\n  {name}: yuruyen-ileri sinyal yolu hesaplaniyor...", flush=True)
        paths[name] = backtest_module.compute_signal_path(frame, scoped[name])
        print(f"    {len(paths[name])} ham test gunu  ({time.time() - t0:.0f}sn)")

    # ---- THE COMMON WINDOW, and the comparison is worthless without it -----
    # GC=F's panel starts 2001 and GLD's 2004-11, and each then loses ~1400
    # rows to MIN_TRAIN_ROWS plus the 200/250-day indicator warmups. Left
    # alone the futures column covers 19.5 years and the ETF column 16.1 --
    # so the futures column contains the 2008-2011 gold boom and the ETF
    # column does not, which by itself lifts buy-and-hold's Calmar from 0.177
    # to 0.231. Comparing those two would measure the CALENDAR and report it
    # as the instrument.
    start = max(p["time"].iloc[0] for p in paths.values())
    end = min(p["time"].iloc[-1] for p in paths.values())
    print(f"\n  ORTAK PENCERE: {start.date()} -> {end.date()}")
    for name in list(paths):
        full = paths[name]
        paths[name] = full[(full["time"] >= start) & (full["time"] <= end)].reset_index(drop=True)
        print(f"    {name}: {len(full)} -> {len(paths[name])} gun")
    years = (end - start).days / 365.25
    print(f"    {years:.1f} yil, her sutun icin ayni")

    verdicts = {}
    for name, path in paths.items():
        verdicts[name] = report(
            f"{name}  ({'VADELI -- alinamaz' if name == asset.symbol else 'ETF -- alinabilir'})",
            run_books(path, scoped[name], years))

    print("\n  KARSILASTIRMA -- olculen sey FARK:")
    base = set(verdicts.get(asset.symbol, []))
    for name, survivors in verdicts.items():
        if name == asset.symbol:
            continue
        lost = sorted(base - set(survivors))
        gained = sorted(set(survivors) - base)
        print(f"    {name}: vadelide gecip burada DUSEN -> "
              f"{', '.join(lost) if lost else 'yok'}")
        if gained:
            print(f"    {name}: sadece burada gecen -> {', '.join(gained)}")


def main() -> int:
    started = time.time()
    print("=" * 100)
    print("BU DEPODAKI KENAR, GERCEKTEN ALINABILEN ENSTRUMANDA DA VAR MI?")
    print("=" * 100)
    print("  Her sayi bugune kadar GC=F/SI=F uzerinde olculdu -- perakende bir")
    print("  hesabin tutamayacagi vadeli kontratlar. Burada ayni skorbord")
    print(f"  GLD/IAU/SLV uzerinde, islem basina ${FLAT_FEE_USD:.2f} sabit komisyonla.")
    print(f"  ON-KAYIT: 'gecer' = ETF uzerinde, ${VERDICT_ACCOUNT:,} hesapta,")
    print("  al-ve-tut'u Calmar'da gecmek. Her strateji her rungda raporlanir.")

    for asset in assets_module.ASSETS.values():
        run_for_asset(asset)

    print("\n" + "=" * 100)
    print(f"Toplam sure: {time.time() - started:.0f} sn")
    print("=" * 100)
    print("  `claude` ve `kanalfinans` burada da yok (backtest.py'nin kapsam")
    print("  uyarisi). `ensemble` satiri yine ml+teknik duz ortalamasidir,")
    print("  canlidaki 5 bilesenli harman degil.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
