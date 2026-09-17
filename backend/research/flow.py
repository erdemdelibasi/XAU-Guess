"""Breakout regime: order flow, anchored VWAP and volume profile -- measured.

THE REQUEST THIS ANSWERS
------------------------
"Enter on a breakout and hold until the trend actually breaks or a stop is
hit", decided primarily by order flow, anchored VWAP and volume profile, with
RSI / MACD / CCI / momentum / stochastic / Fibonacci as confirmations.

That is a genuinely different machine from everything else in this repo. Every
existing strategy re-aims a continuous exposure every session; this one takes
a position and sits in it for weeks. So it cannot be scored by IC or by
5-day hit rate -- the question is not "which way tomorrow", it is "does the
position, held to its own exit, beat holding the metal".

PRE-REGISTERED BAR -- written before any result below was looked at
-------------------------------------------------------------------
Copied deliberately from research/instrument.py's SURVIVES definition, so
this rule is judged by the same bar as everything else that reached
production, plus the money caveat section 17 of the README exists to enforce:

    `breakout` is adopted as a paper portfolio if, on the BUYABLE instrument
    (GLD / SLV) at the $10,000 flat-commission rung, out of sample on the
    second half of the window:

      (1) it beats `buyhold` on Calmar in BOTH metals, AND
      (2) it does not finish more than 25% below `buyhold` in final equity
          in either metal.

Condition (2) is there because of the most expensive lesson in this repo:
Calmar is not money. `voltarget` beats buy-and-hold on Calmar in every column
measured and is worth $1,413 more on a $10,000 account over 16 years -- noise.
A rule that sits in cash 70% of the time can post a beautiful Calmar while
quietly handing back a decade of the metal's drift, and a dashboard that
prints only the Calmar would be advertising that as a win.

If (1) passes and (2) fails, the panel ships and the PORTFOLIO does not --
the `miners` precedent exactly (a real signal that is expensive to put money
on, shown on screen with the caveat attached to it).

METHOD
------
  * Window split in half by time. The three swept parameters are chosen on
    the FIRST half only; that single configuration is then run ONCE on the
    second half. Everything else printed is transparency, not a menu.
  * Only three parameters are swept (entry confirmations, stop width, flat
    exposure). The six oscillator thresholds are their textbook neutral
    points and are NOT swept -- a six-way threshold grid on top of a
    three-way parameter grid is large enough to find a winner in noise.
  * Results are printed on the cost ladder AND at the flat per-trade
    commission a real ETF broker charges, because those are different shapes
    of cost (README section 15).
  * Both instruments. The signal is computed on the COMEX contract (the only
    place this project has a reproducible volume series -- Part 0) and the
    resulting book is run on BOTH that contract and the buyable ETF, because
    section 16 measured a futures-only edge evaporating on the ETF.

PHASE 2 -- SOURCE CHANGE, AND A SECOND PRE-REGISTRATION
--------------------------------------------------------
Phase 1 ran on GLD/SLV and FAILED the bar above (gold won on Calmar and
finished 33.9% behind in money; silver lost on both). Part 0 then measured
that TradingView serves what Yahoo could not: real COMEX volume, depth-
invariant, 6,000 daily bars back to 2002 -- on a contract already quoted PER
TROY OUNCE, which is the unit the panel is read in.

That is a new data source, so it is a NEW experiment and it gets its own
pre-registration rather than inheriting Phase 1's verdict:

    The bar is UNCHANGED -- (1) and (2) above, on the buyable instrument at
    the $10,000 rung, in both metals.

    What changes is the construction: the signal is built on COMEX:GC1! /
    COMEX:SI1! and the buyable leg applies it to GLD / SLV with ONE FULL
    SESSION OF LAG. The futures bar closes at 17:00 New York and the ETF at
    16:00, so an unlagged ETF leg would spend an hour of information its
    trader did not have -- the same session-boundary artefact section 16
    found under `miners`, and invisible at day resolution. The lag can only
    make the ETF leg look worse than reality, never better.

    The parameter sweep is scored on that SAME construction, on the training
    half only, so selection and judgement measure one thing rather than two.

    A futures-on-futures column is printed alongside for comparability with
    the rest of the scoreboard. It is NOT the verdict: no retail account
    holds a COMEX contract.

PHASE 2 WAS RE-RUN ON 2026-09-17, BECAUSE ITS LAG WAS NOT REAL
---------------------------------------------------------------
The pre-registration above is unchanged and so is the split; what changed is
that the construction now does what it says. TradingView stamps a daily bar
with the session's OPEN and Yahoo with the trade date it closes on, so the
ETF join landed a session early and `lagged()` cancelled it back out: a
signal known at 17:00 New York was executed at the SAME day's 16:00 ETF
close. A one-hour look-ahead can only flatter the rule, so phase 2's first
numbers were measured on a construction more generous than the one they
claimed -- including the sweep that chose the parameters.
tv_history.to_trade_dates() fixed the stamp and every number below comes
from the re-run. Both sets are kept in research/README.md section 18 rather
than overwritten, for the same reason phase 1 was kept.

Run:  cd backend/research && python flow.py            (~3 min, both metals)
"""
from __future__ import annotations

import math
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import assets as assets_module  # noqa: E402
import backtest as backtest_module  # noqa: E402
import fetch_data  # noqa: E402
import flow_signal  # noqa: E402
import trading  # noqa: E402
import panel as panel_module  # noqa: E402
import tv_history  # noqa: E402

ETF = {"gold": "GLD", "silver": "SLV"}
TRADING_DAYS = 252
FLAT_FEE_USD = 1.50
FLAT_SPREAD_BPS = 1.0
VERDICT_ACCOUNT = 10_000
ACCOUNT_SIZES = (5_000, 10_000, 25_000, 100_000)
# Daily bars requested from TradingView. 6000 reaches 2002-11 on both
# contracts, i.e. the same depth as the 25-year Yahoo panel the rest of this
# bench runs on. The feed serves 12,000 (back to 1979) without a login, but
# COMEX volume before the electronic era is a different animal and this study
# has no reason to reach for it.
TV_BARS = 6000

# Pre-registered bar, restated as code so the verdict cannot drift from the
# docstring.
MAX_MONEY_SHORTFALL = 0.25

# Bonferroni bar for Part 2: 9 instruments x 2 horizons x 2 metals = 36 tests.
PART2_TESTS = 36
BONFERRONI_T = 3.29  # |t| for p < 0.05/36, two-sided, large sample


# ---------------------------------------------------------------------------
# Part 0 -- does this project have a volume series at all?
# ---------------------------------------------------------------------------

def _stability(frame_a, frame_b, tail: int = 250) -> tuple[int, float, float]:
    """(common days, fraction identical, correlation) on the overlapping tail."""
    a = frame_a.assign(d=frame_a["time"].dt.date)
    b = frame_b.assign(d=frame_b["time"].dt.date)
    m = a[["d", "volume"]].merge(b[["d", "volume"]], on="d",
                                 suffixes=("_a", "_b")).tail(tail)
    if m.empty:
        return 0, float("nan"), float("nan")
    return (len(m), float((m["volume_a"] == m["volume_b"]).mean()),
            float(m["volume_a"].corr(m["volume_b"])))


def _vendor_pairs():
    """(label, shallow, deep) for test A, across both vendors."""
    out = []
    for symbol in ("GC=F", "SI=F"):
        out.append((f"Yahoo {symbol}",
                    fetch_data.drop_forming_bar(fetch_data.get_daily(symbol, years=2)),
                    fetch_data.drop_forming_bar(fetch_data.get_daily(symbol, years=16))))
    for ticker in tv_history.SYMBOLS.values():
        out.append((f"TV {ticker}",
                    tv_history.daily(ticker, bars=500),
                    tv_history.daily(ticker, bars=6000)))
    return out


def part0() -> None:
    """The gate. Everything downstream is volume, so this runs first.

    PHASE 1 asked "does this project have a volume series" of Yahoo alone,
    found it did not on the futures, and built the panel on GLD/SLV instead.
    That worked, and it cost the thing the panel is actually about: a reader
    watching OUNCE gold got levels quoted in GLD dollars.

    PHASE 2 asks the same question of a second vendor, because the finding was
    never "futures have no volume" -- COMEX prints ~200,000 gold contracts a
    day -- it was "this vendor cannot serve it". Same three tests, now across
    both vendors:

      A) Same session, two requested depths. Yahoo PASSES this for all four
         symbols, and it is the test that catches nothing. Kept for exactly
         that reason.
      B) Same DATE, different day or different depth -- does the number hold
         still. This is where Yahoo's GC=F fails.
      C) Is the LEVEL plausible against what COMEX actually trades. This is
         where Yahoo's SI=F fails.

    Plus a fourth question only a second vendor can answer: do two independent
    sources agree? Agreement is not proof, but a disagreement of three orders
    of magnitude settles which one is wrong.
    """
    print("\n" + "=" * 100)
    print("  BOLUM 0 -- HACIM SERISI GUVENILIR MI? (her seyin on sarti)")
    print("=" * 100)

    print("\n  ONCE SPOT: 'ons altin' en dogrudan XAU/USD demek, o yuzden once o")
    print("  olculdu. Spot metal tezgah-ustu bir piyasa ve konsolide bir tape'i YOK:\n")
    for ticker in ("TVC:GOLD", "TVC:SILVER", "FX_IDC:XAUUSD", "OANDA:XAUUSD", "OANDA:XAGUSD"):
        frame = tv_history.daily(ticker, bars=500)
        if frame.empty:
            print(f"      {ticker:<16} SERI YOK -- saglanmiyor")
            continue
        print(f"      {ticker:<16} {len(frame):>4} bar, medyan hacim "
              f"{frame['volume'].median():>12,.0f}")
    print("\n      Okuma: TVC ve FX_IDC her barda SIFIR. OANDA bir sayi doner ve o")
    print("      sayi yanlis olandir -- tek bir perakende araci kurumun kendi")
    print("      tikleri, piyasanin degil. Bir hacim profili 'PIYASA nerede islem")
    print("      gordu' iddiasidir; spot icin o iddiayi tasiyabilecek seri yok.")

    print("\n  A) AYNI OTURUM -- ayni sembol, iki farkli derinlikle ardarda.\n")
    print(f"      {'kaynak/sembol':<24}{'ortak gun':>11}{'ayni %':>9}{'korelasyon':>13}")
    print("      " + "-" * 57)
    for label, shallow, deep in _vendor_pairs():
        n, same, corr = _stability(shallow, deep)
        print(f"      {label:<24}{n:>11}{100 * same:>8.1f}%{corr:>13.3f}")
    print("\n      Dordu de geciyor. Tek basina kosulsaydi kullanilamaz iki seriye")
    print("      de temiz kagit verirdi.")

    print("\n  B) AYNI TARIH, BASKA ZAMAN -- diskteki panel anlik goruntusu (gunler")
    print("     once alinmis) vs bugunun cekisi. Yahoo'nun GC=F'i burada dusuyor.\n")
    print(f"      {'sembol':<10}{'ortak gun':>11}{'ayni %':>9}{'korelasyon':>13}"
          f"{'medyan o gun':>15}{'medyan bugun':>15}")
    print("      " + "-" * 73)
    for key, symbol in (("gold", "GC=F"), ("silver", "SI=F")):
        if not panel_module.panel_path(key).exists():
            print(f"      {symbol:<10}  panel onbellegi yok -- panel.py ile kurun")
            continue
        snap = panel_module.load(key)
        now = fetch_data.get_daily(symbol, years=2)
        n, same, corr = _stability(snap, now)
        j = (snap.assign(d=snap["time"].dt.date)[["d", "volume"]]
             .merge(now.assign(d=now["time"].dt.date)[["d", "volume"]],
                    on="d", suffixes=("_o", "_n")).tail(250))
        print(f"      {symbol:<10}{n:>11}{100 * same:>8.1f}%{corr:>13.3f}"
              f"{j['volume_o'].median():>15,.0f}{j['volume_n'].median():>15,.0f}")

    print("\n  C) SEVIYE MAKUL MU -- COMEX altini gunde ~200 bin, gumusu ~60 bin")
    print("     kontrat isliyor. Istenen derinlige gore medyan hacim:\n")
    depths = (2, 5, 10, 16, 25)
    print(f"      {'Yahoo':<12}" + "".join(f"{str(y) + ' yil':>14}" for y in depths))
    print("      " + "-" * (12 + 14 * len(depths)))
    for symbol in ("GC=F", "SI=F", "GLD", "SLV"):
        cells = [fetch_data.get_daily(symbol, years=y)["volume"].median() for y in depths]
        print(f"      {symbol:<12}" + "".join(f"{c:>14,.0f}" for c in cells))
    tv_depths = (500, 2000, 6000)
    print(f"\n      {'TradingView':<12}" + "".join(f"{str(b) + ' bar':>14}" for b in tv_depths))
    print("      " + "-" * (12 + 14 * len(tv_depths)))
    for ticker in tv_history.SYMBOLS.values():
        cells = [tv_history.daily(ticker, bars=b)["volume"].median() for b in tv_depths]
        print(f"      {ticker:<12}" + "".join(f"{c:>14,.0f}" for c in cells))

    print("\n  D) IKI KAYNAK BIRBIRINI TUTUYOR MU -- ayni 250 gun, TradingView vs")
    print("     TAZE bir Yahoo cekisi.\n")
    print(f"      {'metal':<10}{'hacim kor':>12}{'medyan TV':>14}{'medyan YF':>14}"
          f"{'kapanis kor':>14}{'kapanis fark':>14}")
    print("      " + "-" * 78)
    for key, yahoo_symbol in (("gold", "GC=F"), ("silver", "SI=F")):
        tv = tv_history.daily_for(key, bars=2000)
        yf = fetch_data.drop_forming_bar(fetch_data.get_daily(yahoo_symbol, years=3))
        if tv.empty or yf.empty:
            continue
        j = (tv.assign(d=tv["time"].dt.date)[["d", "volume", "close"]]
             .merge(yf.assign(d=yf["time"].dt.date)[["d", "volume", "close"]],
                    on="d", suffixes=("_tv", "_yf")).tail(250))
        gap = (j["close_tv"] / j["close_yf"] - 1.0).abs().median()
        print(f"      {key:<10}{j['volume_tv'].corr(j['volume_yf']):>12.3f}"
              f"{j['volume_tv'].median():>14,.0f}{j['volume_yf'].median():>14,.0f}"
              f"{j['close_tv'].corr(j['close_yf']):>14.4f}{100 * gap:>13.3f}%")

    print("\n  HUKUM: Yahoo'nun vadeli hacmi kullanilamaz -- GC=F (B)'de, SI=F (C)'de")
    print("  dusuyor. TradingView'inki ucunu de geciyor, ve altinda BAGIMSIZ Yahoo")
    print("  cekisiyle SEVIYEDE ortusuyor; gumuste ortusmuyor, ki asil mesele o.")
    print("  Ustelik COMEX kontrati ZATEN $/ons kote ediliyor, yani panel hem gercek")
    print("  hacme hem okuyucunun istedigi birime ayni anda kavusuyor. Sinyal bu")
    print("  yuzden Faz 2'de COMEX:GC1!/SI1! uzerinde kuruluyor.")
    print("\n  (D)'nin kapanis sutunu 2026-09-17'de YENIDEN olculdu ve onceki")
    print("  okuma bir hizalama artefaktiydi: TradingView gunluk bari seansin")
    print("  ACILDIGI gunle damgaliyor, Yahoo kapandigi islem gunuyle. Ham")
    print("  tarihlerle eslestirilince gunluk getirinin kendisi 'satici farki'")
    print("  diye olculuyordu (altinda medyan %1,04). tv_history.to_trade_dates()")
    print("  damgayi duzeltti; asil fark yukaridaki sutunda.")


# ---------------------------------------------------------------------------
# Part 1 -- the frame
# ---------------------------------------------------------------------------

def flow_frame(asset) -> pd.DataFrame:
    """The COMEX contract with every flow column, plus the ETF close beside it.

    PHASE 2 SOURCE CHANGE. Phase 1 built this on GLD/SLV because Yahoo could
    not serve futures volume. Part 0 measured that TradingView can, so the
    signal now lives on the instrument the reader is actually watching:
    COMEX:GC1! and COMEX:SI1! are quoted per troy ounce and are already what
    frontend/app.js marks the portfolios to.

    The ETF close is joined on the futures calendar, backward only, for the
    buyable-instrument leg. No signal column reads it.

    THE JOIN IS ONLY HONEST BECAUSE tv_history STAMPS TRADE DATES. Until
    2026-09-17 it stamped the session's OPEN, so this reindex attached the
    ETF close from the day BEFORE the futures bar finished -- and lagged()
    below then shifted execution forward by one row, cancelling that error
    out into a same-session look-ahead. Two mistakes that hid each other, and
    the symptom was a side finding recorded here as "unexplained": the LAGGED
    ETF leg beat the futures-on-futures leg (0.531 vs 0.429 at 2bp), which is
    what a hidden look-ahead looks like from outside.
    """
    frame = flow_signal.add_flow_columns(
        fetch_data.drop_forming_bar(tv_history.daily_for(asset.key, bars=TV_BARS)))
    if frame.empty:
        return frame

    etf = fetch_data.drop_forming_bar(fetch_data.get_daily(ETF[asset.key], years=25))
    if etf.empty:
        frame["etf_close"] = float("nan")
        return frame
    series = etf.set_index(pd.DatetimeIndex(etf["time"]).normalize())["close"]
    series = series[~series.index.duplicated(keep="last")]
    frame["etf_close"] = series.reindex(
        pd.DatetimeIndex(frame["time"]).normalize(), method="ffill").to_numpy()
    return frame


# ---------------------------------------------------------------------------
# Part 2 -- does each instrument carry direction on its own?
# ---------------------------------------------------------------------------

def _binary_states(frame: pd.DataFrame) -> dict[str, pd.Series]:
    """Each instrument reduced to a long/flat state, so all nine compare."""
    return {
        "akis (CMF>0)": (frame["flow"] > 0).astype(float),
        "AVWAP ustu": (frame["close"] > frame["avwap"]).astype(float),
        "VAH kirilimi": (frame["close"] > frame["vah"]).astype(float),
        "RSI>50": (frame["rsi14"] > 50).astype(float),
        "MACD hist>0": (frame["macd_hist"] > 0).astype(float),
        "CCI>100": (frame["cci20"] > 100).astype(float),
        "MOM>0": (frame["mom10"] > 0).astype(float),
        "STO>50": (frame["stoch_k"] > 50).astype(float),
        "Fib>0.382": (frame["fib_pos"] > 0.382).astype(float),
    }


def part2(asset, frame: pd.DataFrame) -> None:
    """Hit rate of each instrument's long state, against the base rate.

    Beating 50% proves nothing on these metals -- gold closes higher over 5
    sessions 55.7% of the time on its own. Every cell below is therefore
    printed against THIS asset's base rate on THIS window, and the t-statistic
    is corrected for the overlap a multi-day horizon creates.
    """
    print("\n" + "-" * 100)
    print(f"  BOLUM 2 -- her enstruman TEK BASINA yon tasiyor mu? ({asset.label})")
    print("-" * 100)

    close = frame["close"]
    states = _binary_states(frame)
    for horizon in (5, 20):
        fwd = close.shift(-horizon) / close - 1.0
        base = float((fwd.dropna() > 0).mean())
        n_eff = max(fwd.notna().sum() / horizon, 1)
        print(f"\n    ufuk {horizon} seans -- taban oran %{100 * base:.1f} "
              f"(etkin gozlem ~{n_eff:.0f}, Bonferroni esigi |t|>{BONFERRONI_T})")
        print(f"      {'enstruman':<16}{'gun':>7}{'isabet':>9}{'fark(p)':>10}{'t':>8}")
        print("      " + "-" * 50)
        for name, state in states.items():
            mask = state.notna() & fwd.notna() & (state > 0)
            n = int(mask.sum())
            if n < 100:
                continue
            hit = float((fwd[mask] > 0).mean())
            # Effective sample for THIS subset, same overlap correction.
            eff = max(n / horizon, 1)
            se = math.sqrt(max(base * (1 - base), 1e-9) / eff)
            t = (hit - base) / se if se > 0 else 0.0
            print(f"      {name:<16}{n:>7}{100 * hit:>8.1f}%"
                  f"{100 * (hit - base):>+10.1f}{t:>8.2f}")
    print("\n    Not: bu tablo kurali DEGIL, bilesenlerini olcuyor. Bir kirilim")
    print("    kuralinin iddiasi 'her uzun gun ortalamadan iyi' degil, 'tuttugu")
    print("    pozisyon cikisina kadar metali gecer' -- onu Bolum 4 olcuyor.")


# ---------------------------------------------------------------------------
# Parts 3 and 4 -- the rule itself
# ---------------------------------------------------------------------------

def run_book(prices: np.ndarray, targets: np.ndarray, fee_rate: float,
             flat_fee: float, years: float) -> dict:
    """One book, stepped through trading.compute_rebalance -- the live code.

    Not a reimplementation: backtest.Portfolio.step calls the same function
    predict.py's maybe_trade calls, which is why the rebalance threshold, the
    dust guard and the fee shape here are the production ones.
    """
    book = backtest_module.Portfolio("breakout")
    for price, target in zip(prices, targets):
        if not np.isfinite(price) or price <= 0:
            continue
        book.step(float(price), float(target), fee_rate, flat_fee)
    if not book.equity or min(book.equity) <= 0:
        return {"bust": True, "trades": book.trades}
    out = backtest_module.metrics(book.equity, book.exposure, years)
    out["trades"] = book.trades
    out["fees"] = book.fees_paid
    out["bust"] = False
    return out


def buyhold_book(prices: np.ndarray, fee_rate: float, flat_fee: float,
                 years: float) -> dict:
    return run_book(prices, np.ones(len(prices)), fee_rate, flat_fee, years)


def sweep(frame: pd.DataFrame, years: float) -> tuple[tuple, pd.DataFrame]:
    """Choose (min_confirmations, stop_sigmas, flat_exposure) on this frame.

    Scored on the ETF at the verdict rung, on Calmar. Eighteen cells; the
    whole grid is printed so the reader can see how flat or peaked the
    surface is, which is the difference between a chosen parameter and a
    lucky one.
    """
    # Scored on the SAME construction the verdict is read on -- the buyable
    # ETF leg with a one-session lag -- so selection and judgement are not
    # measuring two different things. Training half only, always.
    prices = frame["etf_close"].to_numpy(dtype=float)
    scaled_fee = FLAT_FEE_USD * trading.STARTING_CASH / VERDICT_ACCOUNT
    spread = FLAT_SPREAD_BPS / 10_000.0

    rows = []
    for min_conf in (2, 3, 4):
        for sigmas in (2.0, 3.0, 4.0):
            path = flow_signal.breakout_path(frame, min_confirmations=min_conf,
                                             stop_sigmas=sigmas)
            for flat in (0.0, 0.35):
                targets = lagged(flow_signal.exposure_path(path, flat).to_numpy(dtype=float))
                res = run_book(prices, targets, spread, scaled_fee, years)
                rows.append({"min_conf": min_conf, "sigmas": sigmas, "flat": flat,
                             "calmar": np.nan if res["bust"] else res["calmar"],
                             "cagr": np.nan if res["bust"] else res["cagr"],
                             "max_dd": np.nan if res["bust"] else res["max_dd"],
                             "trades": res["trades"],
                             "exposure": np.nan if res["bust"] else res["exposure"]})
    grid = pd.DataFrame(rows)
    best = grid.loc[grid["calmar"].idxmax()]
    return (int(best["min_conf"]), float(best["sigmas"]), float(best["flat"])), grid


def part3(asset, train: pd.DataFrame, years: float) -> tuple:
    print("\n" + "-" * 100)
    print(f"  BOLUM 3 -- parametre secimi, YALNIZCA ilk yarida ({asset.label})")
    print("-" * 100)
    chosen, grid = sweep(train, years)
    print(f"\n      {'onay':>6}{'sigma':>7}{'bosta':>7}{'Calmar':>9}"
          f"{'YBG':>9}{'dusus':>9}{'islem':>8}{'poz.%':>8}")
    print("      " + "-" * 63)
    for _, r in grid.sort_values("calmar", ascending=False).iterrows():
        print(f"      {int(r['min_conf']):>6}{r['sigmas']:>7.1f}{r['flat']:>7.2f}"
              f"{r['calmar']:>9.3f}{100 * r['cagr']:>8.1f}%{100 * r['max_dd']:>8.1f}%"
              f"{int(r['trades']):>8}{100 * r['exposure']:>7.0f}%")
    print(f"\n      SECILEN: onay>={chosen[0]}, stop={chosen[1]:.1f} sigma, "
          f"bosta pozisyon={chosen[2]:.2f}")
    print("      Bu tek konfigurasyon ikinci yarida BIR KEZ kosacak.")
    return chosen


def ladder_report(label: str, frame: pd.DataFrame, targets: np.ndarray,
                  price_column: str, asset, years: float) -> dict:
    """The proportional cost ladder on one instrument."""
    prices = frame[price_column].to_numpy(dtype=float)
    print(f"\n      --- {label} -- oransal maliyet merdiveni ---")
    print(f"          {'basamak':<16}{'kirilim':>10}{'al-ve-tut':>12}"
          f"{'YBG':>9}{'dusus':>9}{'islem':>8}")
    print("          " + "-" * 64)
    out = {}
    for rung, one_way in backtest_module.cost_ladder_for(asset).items():
        fee = one_way / 10_000.0
        rule = run_book(prices, targets, fee, 0.0, years)
        bench = buyhold_book(prices, fee, 0.0, years)
        rc = np.nan if rule["bust"] else rule["calmar"]
        bc = np.nan if bench["bust"] else bench["calmar"]
        out[rung] = (rc, bc)
        print(f"          {rung:<16}{rc:>10.3f}{bc:>12.3f}"
              f"{100 * rule['cagr']:>8.1f}%{100 * rule['max_dd']:>8.1f}%"
              f"{rule['trades']:>8}")
    return out


def flat_fee_report(label: str, frame: pd.DataFrame, targets: np.ndarray,
                    price_column: str, years: float) -> dict:
    """The flat per-trade commission, by account size. The verdict lives here."""
    prices = frame[price_column].to_numpy(dtype=float)
    spread = FLAT_SPREAD_BPS / 10_000.0
    print(f"\n      --- {label} -- $1,50 sabit komisyon, hesap buyuklugune gore ---")
    print(f"          {'hesap':<12}{'kirilim C':>12}{'al-tut C':>11}"
          f"{'kirilim $':>12}{'al-tut $':>11}{'islem':>8}")
    print("          " + "-" * 66)
    out = {}
    for size in ACCOUNT_SIZES:
        scaled = FLAT_FEE_USD * trading.STARTING_CASH / size
        rule = run_book(prices, targets, spread, scaled, years)
        bench = buyhold_book(prices, spread, scaled, years)
        if rule["bust"] or bench["bust"]:
            print(f"          ${size:<11,}{'IFLAS':>12}")
            out[size] = None
            continue
        # Books are run on the standard $1000 ledger with a scaled fee, which
        # is identical to an $N ledger with the real fee (instrument.py's
        # scale-invariance note). Final equity is reported back at the
        # account's own scale so the money column means what it says.
        k = size / trading.STARTING_CASH
        out[size] = {"calmar": rule["calmar"], "bench_calmar": bench["calmar"],
                     "final": rule["final"] * k, "bench_final": bench["final"] * k,
                     "max_dd": rule["max_dd"], "bench_dd": bench["max_dd"],
                     "cagr": rule["cagr"], "bench_cagr": bench["cagr"],
                     "trades": rule["trades"]}
        print(f"          ${size:<11,}{rule['calmar']:>12.3f}{bench['calmar']:>11.3f}"
              f"{rule['final'] * k:>12,.0f}{bench['final'] * k:>11,.0f}"
              f"{rule['trades']:>8}")
    return out


def lagged(targets: np.ndarray) -> np.ndarray:
    """Yesterday's target, for the buyable-instrument leg.

    THIS SHIFT IS THE WHOLE REASON THE ETF LEG IS HONEST. The signal now
    lives on COMEX:GC1!, whose daily bar closes at 17:00 New York; GLD closes
    at 16:00. Applying today's futures signal to today's ETF close would use
    an hour of information the ETF trader did not have -- a smaller version of
    exactly the session-boundary artefact research/README.md section 16 found
    under `miners`, and one a day-resolution study cannot see.

    A full session of lag is conservative in the safe direction: it can only
    make the ETF leg look worse than a real trader could have done, never
    better.

    IT ONLY MEANS THAT IF THE FRAME IS ALIGNED. This shift is one ROW, so it
    buys a full session only while `etf_close` sits on the same trade date as
    the futures bar beside it -- which is tv_history.to_trade_dates()'s job.
    While that stamping was wrong this shift quietly restored what the join
    had taken away, and this docstring described a lag the numbers did not
    have.
    """
    out = np.empty_like(targets)
    out[0] = 0.0
    out[1:] = targets[:-1]
    return out


def part4(asset, test: pd.DataFrame, chosen: tuple, years: float) -> dict:
    print("\n" + "-" * 100)
    print(f"  BOLUM 4 -- secilen tek konfigurasyon, IKINCI YARIDA ({asset.label})")
    print(f"  onay>={chosen[0]}, stop={chosen[1]:.1f} sigma, bosta={chosen[2]:.2f}")
    print("-" * 100)

    path = flow_signal.breakout_path(test, min_confirmations=chosen[0],
                                     stop_sigmas=chosen[1])
    targets = flow_signal.exposure_path(path, chosen[2]).to_numpy(dtype=float)
    entries = int((path["state"].diff() == 1).sum())
    print(f"\n      {entries} giris, pozisyonda gecen sure %{100 * path['state'].mean():.0f}, "
          f"ortalama tutus {path['state'].sum() / max(entries, 1):.0f} seans")

    # Primary column: signal and price on the SAME instrument, same bar, no
    # alignment question to answer.
    ladder_report(f"vadeli ({tv_history.SYMBOLS[asset.key]}) -- $/ons, sinyalin kendi serisi",
                  test, targets, "close", asset, years)
    # Buyable column: one full session of lag -- see lagged().
    ladder_report(f"ETF ({ETF[asset.key]}) -- ALINABILIR, sinyal 1 seans gecikmeli",
                  test, lagged(targets), "etf_close", asset, years)
    etf_flat = flat_fee_report(f"ETF ({ETF[asset.key]}) -- ALINABILIR, 1 seans gecikmeli",
                               test, lagged(targets), "etf_close", years)
    fut_flat = flat_fee_report(f"vadeli ({tv_history.SYMBOLS[asset.key]}) -- kiyas icin",
                               test, targets, "close", years)

    # THE VARIANT THE LIVE BOOK ACTUALLY RUNS, when it is not the chosen one.
    # breakout_trading.py is all-in / all-out: "hold until the trend breaks"
    # cannot express a 35% floor, so whenever the sweep picks flat>0 the paper
    # book is running the hard-exit sibling of the rule this study judged.
    # Measured on the same test half, at the same rungs, so the book on screen
    # quotes a number of its OWN instead of borrowing the verdict's -- the
    # same reason the ETF books do not quote the futures column.
    book_flat = etf_flat
    if chosen[2] != 0.0:
        book_targets = flow_signal.exposure_path(path, 0.0).to_numpy(dtype=float)
        book_flat = flat_fee_report(
            f"ETF ({ETF[asset.key]}) -- DEFTERIN varyanti: tam giris / tam cikis",
            test, lagged(book_targets), "etf_close", years)
    return {"flat": etf_flat, "futures_flat": fut_flat, "book_flat": book_flat,
            "book_is_chosen": chosen[2] == 0.0, "entries": entries,
            "in_position": float(path["state"].mean())}


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def run_for_asset(asset) -> dict:
    print("\n" + "#" * 100)
    print(f"### {asset.label.upper()}  --  kirilim rejimi "
          f"(sinyal {tv_history.SYMBOLS[asset.key]}, $/ons, gercek COMEX hacmi)")
    print("#" * 100)

    frame = flow_frame(asset)
    if frame.empty:
        print("  veri yok")
        return {}
    # Rows before every column exists are not a shorter history, they are a
    # different rule (no value area, no anchored VWAP). Dropping them here
    # rather than letting breakout_path skip them keeps the two halves the
    # same rule on the same footing.
    frame = frame.dropna(subset=["vah", "avwap", "flow", "sigma", "fib_pos",
                                "etf_close"]).reset_index(drop=True)
    span_years = (frame["time"].iloc[-1] - frame["time"].iloc[0]).days / 365.25
    print(f"\n  {len(frame)} seans, {frame['time'].iloc[0].date()} -> "
          f"{frame['time'].iloc[-1].date()} ({span_years:.1f} yil)")

    part2(asset, frame)

    cut = len(frame) // 2
    train = frame.iloc[:cut].reset_index(drop=True)
    test = frame.iloc[cut:].reset_index(drop=True)
    train_years = (train["time"].iloc[-1] - train["time"].iloc[0]).days / 365.25
    test_years = (test["time"].iloc[-1] - test["time"].iloc[0]).days / 365.25
    print(f"\n  Bolme: egitim {train['time'].iloc[0].date()}->{train['time'].iloc[-1].date()} "
          f"({train_years:.1f} yil) | test {test['time'].iloc[0].date()}->"
          f"{test['time'].iloc[-1].date()} ({test_years:.1f} yil)")

    chosen = part3(asset, train, train_years)
    result = part4(asset, test, chosen, test_years)
    result["chosen"] = chosen
    return result


def verdict(results: dict) -> None:
    print("\n" + "=" * 100)
    print("  BOLUM 5 -- ON-KAYITLI BARAJA KARSI HUKUM")
    print("=" * 100)
    print("\n  Baraj (sonuclara BAKILMADAN once ilan edildi):")
    print("    (1) $10.000 rungunda, ETF uzerinde, IKI metalde de Calmar'da")
    print("        al-ve-tut'u gecmek, VE")
    print(f"    (2) hicbir metalde son sermayede al-ve-tut'un %{100 * MAX_MONEY_SHORTFALL:.0f}"
          " altina dusmemek.\n")

    passed_calmar, passed_money = True, True
    print(f"      {'metal':<10}{'Calmar':>9}{'al-tut':>9}{'gecti':>8}"
          f"{'son $':>12}{'al-tut $':>12}{'fark':>9}{'gecti':>8}")
    print("      " + "-" * 77)
    for key, res in results.items():
        cell = (res.get("flat") or {}).get(VERDICT_ACCOUNT)
        label = assets_module.get(key).label
        if not cell:
            print(f"      {label:<10}{'veri yok':>9}")
            passed_calmar = passed_money = False
            continue
        c_ok = cell["calmar"] > cell["bench_calmar"]
        shortfall = 1.0 - cell["final"] / cell["bench_final"]
        m_ok = shortfall <= MAX_MONEY_SHORTFALL
        passed_calmar &= c_ok
        passed_money &= m_ok
        print(f"      {label:<10}{cell['calmar']:>9.3f}{cell['bench_calmar']:>9.3f}"
              f"{('EVET' if c_ok else 'HAYIR'):>8}"
              f"{cell['final']:>12,.0f}{cell['bench_final']:>12,.0f}"
              f"{-100 * shortfall:>+8.1f}%{('EVET' if m_ok else 'HAYIR'):>8}")

    # The book's own variant, when the sweep chose a floor the book cannot
    # hold. NOT part of the bar -- the bar judges the configuration the sweep
    # selected, and moving the goalposts to whichever sibling scores better is
    # exactly what a pre-registration exists to stop. It is printed because a
    # $1,000 book is running it in public.
    if any(not res.get("book_is_chosen", True) for res in results.values()):
        print("\n      Defterin fiilen kostugu varyant (tam giris/tam cikis), ayni")
        print("      test yarisinda -- BARAJA DAHIL DEGIL:")
        for key, res in results.items():
            cell = (res.get("book_flat") or {}).get(VERDICT_ACCOUNT)
            label = assets_module.get(key).label
            if not cell:
                continue
            gap = 1.0 - cell["final"] / cell["bench_final"]
            print(f"      {label:<10}{cell['calmar']:>9.3f}{cell['bench_calmar']:>9.3f}"
                  f"{'':>8}{cell['final']:>12,.0f}{cell['bench_final']:>12,.0f}"
                  f"{-100 * gap:>+8.1f}%")

    print()
    if passed_calmar and passed_money:
        print("  HUKUM: baraj GECILDI -- kural kagit portfoy olarak uretime girer,")
        print("  ve panel hem Calmar'i hem parayi basar.")
    elif passed_calmar:
        print("  HUKUM: (1) gecti, (2) GECILEMEDI. `miners` emsali: sinyal gercek,")
        print("  uzerine para koymak pahali. PANEL girer, PORTFOY girmez, ve ekranda")
        print("  al-ve-tut'un parada onde oldugu acikca yazar.")
    else:
        print("  HUKUM: baraj GECILEMEDI. Panel bir olcumu gosterir, bir tavsiyeyi")
        print("  degil -- ve o olcum 'bu kural al-ve-tut'u gecmiyor' cumlesidir.")


def main() -> int:
    part0()
    results = {}
    for key in assets_module.ASSETS:
        results[key] = run_for_asset(assets_module.get(key))
    verdict(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
