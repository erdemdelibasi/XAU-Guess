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
  * Both instruments. The signal is computed on the ETF (the only place this
    project has a reproducible volume series -- Part 0) and the resulting
    book is run on BOTH the ETF and the futures, because section 16 measured
    a futures-only edge evaporating on the buyable instrument.

Run:  cd backend/research && python flow.py            (~2 min, both metals)
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

ETF = {"gold": "GLD", "silver": "SLV"}
TRADING_DAYS = 252
FLAT_FEE_USD = 1.50
FLAT_SPREAD_BPS = 1.0
VERDICT_ACCOUNT = 10_000
ACCOUNT_SIZES = (5_000, 10_000, 25_000, 100_000)

# Pre-registered bar, restated as code so the verdict cannot drift from the
# docstring.
MAX_MONEY_SHORTFALL = 0.25

# Bonferroni bar for Part 2: 9 instruments x 2 horizons x 2 metals = 36 tests.
PART2_TESTS = 36
BONFERRONI_T = 3.29  # |t| for p < 0.05/36, two-sided, large sample


# ---------------------------------------------------------------------------
# Part 0 -- does this project have a volume series at all?
# ---------------------------------------------------------------------------

def part0() -> None:
    """The gate. Everything downstream is volume, so this runs first.

    THREE tests, because the two futures series fail in two DIFFERENT ways
    and a single test would have cleared one of them.

      A) Same session, two range parameters. Catches nothing here -- all four
         symbols agree with themselves within one minute. Printed anyway,
         because it is the test the obvious version of this check would have
         run, and it PASSES for a series that is unusable.

      B) Across sessions: today's fetch against the panel snapshot cached on
         disk days ago. This is where GC=F fails, and it is the only test
         that sees it -- the SAME dates that read ~600 contracts when the
         panel was built read ~170,000 today, with nothing in between but
         time. Whatever Yahoo stitches its continuous contract from, it
         restitches, retroactively.

      C) Plausibility of the level, by requested depth. COMEX gold trades
         ~200k contracts a day and COMEX silver ~60k. Gold's recent years now
         report that; its deep history reports hundreds. Silver reports tens
         at every depth -- that is not a noisy measurement of 60k, it is a
         different quantity.
    """
    print("\n" + "=" * 100)
    print("  BOLUM 0 -- HACIM SERISI GUVENILIR MI? (her seyin on sarti)")
    print("=" * 100)

    print("\n  A) AYNI OTURUM -- ayni sembol, iki farkli aralikla, ardarda.")
    print("     Bu testi dort sembolun dordu de geciyor; tek basina kosulsaydi")
    print("     kullanilamaz iki seriye de temiz kagit verirdi.\n")
    print(f"      {'sembol':<8}{'ortak gun':>11}{'ayni mi':>10}{'korelasyon':>13}")
    print("      " + "-" * 42)
    for symbol in ("GC=F", "SI=F", "GLD", "SLV"):
        # The forming bar is dropped on BOTH sides. Without it the last row
        # differs between two fetches a second apart -- a live session, not an
        # instability -- and this test would print a false failure.
        a = fetch_data.drop_forming_bar(fetch_data.get_daily(symbol, years=2))
        b = fetch_data.drop_forming_bar(fetch_data.get_daily(symbol, years=16))
        if a.empty or b.empty:
            print(f"      {symbol:<8}{'veri yok':>11}")
            continue
        a, b = a.assign(d=a["time"].dt.date), b.assign(d=b["time"].dt.date)
        m = a[["d", "volume"]].merge(b[["d", "volume"]], on="d",
                                     suffixes=("_a", "_b")).tail(250)
        same = float((m["volume_a"] == m["volume_b"]).mean())
        print(f"      {symbol:<8}{len(m):>11}{('EVET' if same == 1.0 else 'HAYIR'):>10}"
              f"{m['volume_a'].corr(m['volume_b']):>13.3f}")

    print("\n  B) OTURUMLAR ARASI -- bugunun cekisi, diskteki panel anlik")
    print("     goruntusune karsi (gunler once alinmis, ayni tarihler).\n")
    print(f"      {'sembol':<8}{'ortak gun':>11}{'ayni %':>10}{'korelasyon':>13}"
          f"{'medyan o gun':>15}{'medyan bugun':>15}")
    print("      " + "-" * 72)
    for key, symbol in (("gold", "GC=F"), ("silver", "SI=F")):
        path = panel_module.panel_path(key)
        if not path.exists():
            print(f"      {symbol:<8}  panel onbellegi yok -- panel.py ile kurun")
            continue
        snap = panel_module.load(key)
        snap = snap.assign(d=snap["time"].dt.date)
        now = fetch_data.get_daily(symbol, years=2)
        now = now.assign(d=now["time"].dt.date)
        m = snap[["d", "volume"]].merge(now[["d", "volume"]], on="d",
                                        suffixes=("_snap", "_now")).tail(250)
        if m.empty:
            continue
        print(f"      {symbol:<8}{len(m):>11}"
              f"{100 * (m['volume_snap'] == m['volume_now']).mean():>9.1f}%"
              f"{m['volume_snap'].corr(m['volume_now']):>13.3f}"
              f"{m['volume_snap'].median():>15,.0f}{m['volume_now'].median():>15,.0f}")

    print("\n  C) SEVIYE MAKUL MU -- COMEX altini gunde ~200 bin, gumusu ~60 bin")
    print("     kontrat isliyor. Istenen derinlige gore medyan hacim:\n")
    depths = (2, 5, 10, 16, 25)
    print(f"      {'sembol':<8}" + "".join(f"{str(y) + ' yil':>14}" for y in depths)
          + f"{'sifir gun(25y)':>16}")
    print("      " + "-" * (8 + 14 * len(depths) + 16))
    for symbol in ("GC=F", "SI=F", "GLD", "SLV"):
        cells, zeros = [], 0
        for years in depths:
            d = fetch_data.get_daily(symbol, years=years)
            cells.append(float(d["volume"].median()) if not d.empty else float("nan"))
            if years == depths[-1] and not d.empty:
                zeros = int((d["volume"] == 0).sum())
        print(f"      {symbol:<8}" + "".join(f"{c:>14,.0f}" for c in cells)
              + f"{zeros:>16}")

    print("\n  Okuma: GC=F (B)'de dusuyor -- ayni tarih, gunler arayla iki farkli")
    print("  sayi (%3.6'si tutuyor, korelasyon -0.10). Uzerine kurulan bir deger")
    print("  alani her yeniden kurulumda BASKA turlu cikar, hicbir yerde hata")
    print("  vermeden. (C) ayni arizanin derinlik eksenindeki hali: altinin son")
    print("  yillari gercek hacmi doner, derin gecmisi yuzleri.")
    print("  SI=F yalnizca (C)'de dusuyor, ve her derinlikte -- seviyenin kendisi")
    print("  COMEX gumusunun uc mertebe altinda. Yani iki vadeli seri IKI FARKLI")
    print("  sekilde kullanilamaz; tek bir test ikisinden birine temiz kagit")
    print("  verirdi ve (A) tam olarak onu yapiyor.")
    print("  ETF hacmi ucunu de geciyor. Bu yuzden flow_signal.py hacimle ilgili")
    print("  HER seyi ETF serisinden okuyor, metali ise kendi fiyatiyla isliyor")
    print("  -- ve Bolum 4 kurali IKI enstrumanda da kosuyor.")


# ---------------------------------------------------------------------------
# Part 1 -- the frame
# ---------------------------------------------------------------------------

def flow_frame(asset) -> pd.DataFrame:
    """ETF OHLCV with every flow column, plus the futures close beside it.

    The futures close is joined on the ETF's calendar, backward only. It is
    NOT used by any signal column -- it exists so Part 4 can run the same
    position path on the metal's own price and see whether the answer
    survives the instrument change.
    """
    ticker = ETF[asset.key]
    etf = fetch_data.drop_forming_bar(fetch_data.get_daily(ticker, years=25))
    if etf.empty:
        return pd.DataFrame()
    frame = flow_signal.add_flow_columns(etf)

    futures = fetch_data.drop_forming_bar(fetch_data.get_daily(asset.symbol, years=25))
    fut = futures.set_index(pd.DatetimeIndex(futures["time"]).normalize())["close"]
    fut = fut[~fut.index.duplicated(keep="last")]
    index = pd.DatetimeIndex(frame["time"]).normalize()
    frame["futures_close"] = fut.reindex(index, method="ffill").to_numpy()
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
    prices = frame["close"].to_numpy(dtype=float)
    scaled_fee = FLAT_FEE_USD * trading.STARTING_CASH / VERDICT_ACCOUNT
    spread = FLAT_SPREAD_BPS / 10_000.0

    rows = []
    for min_conf in (2, 3, 4):
        for sigmas in (2.0, 3.0, 4.0):
            path = flow_signal.breakout_path(frame, min_confirmations=min_conf,
                                             stop_sigmas=sigmas)
            for flat in (0.0, 0.35):
                targets = flow_signal.exposure_path(path, flat).to_numpy(dtype=float)
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


def part4(asset, test: pd.DataFrame, chosen: tuple, years: float) -> dict:
    print("\n" + "-" * 100)
    print(f"  BOLUM 4 -- secilen tek konfigurasyon, IKINCI YARIDA ({asset.label})")
    print(f"  onay>={chosen[0]}, stop={chosen[1]:.1f} sigma, bosta={chosen[2]:.2f}")
    print("-" * 100)

    path = flow_signal.breakout_path(test, min_confirmations=chosen[0],
                                     stop_sigmas=chosen[1])
    targets = flow_signal.exposure_path(path, chosen[2]).to_numpy(dtype=float)
    entries = int((path["state"].diff() == 1).sum())
    stops = int((path["exit_reason"] == "stop").diff().eq(True).sum())
    print(f"\n      {entries} giris, pozisyonda gecen sure %{100 * path['state'].mean():.0f}, "
          f"ortalama tutus {path['state'].sum() / max(entries, 1):.0f} seans")

    ladder_report(f"ETF ({ETF[asset.key]}) -- ALINABILIR", test, targets, "close", asset, years)
    ladder_report(f"vadeli ({asset.symbol}) -- alinamaz", test, targets,
                  "futures_close", asset, years)
    etf_flat = flat_fee_report(f"ETF ({ETF[asset.key]}) -- ALINABILIR",
                               test, targets, "close", years)
    return {"flat": etf_flat, "entries": entries,
            "in_position": float(path["state"].mean())}


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def run_for_asset(asset) -> dict:
    print("\n" + "#" * 100)
    print(f"### {asset.label.upper()}  --  kirilim rejimi "
          f"(sinyal {ETF[asset.key]} hacminden, kitap iki enstrumanda)")
    print("#" * 100)

    frame = flow_frame(asset)
    if frame.empty:
        print("  veri yok")
        return {}
    # Rows before every column exists are not a shorter history, they are a
    # different rule (no value area, no anchored VWAP). Dropping them here
    # rather than letting breakout_path skip them keeps the two halves the
    # same rule on the same footing.
    frame = frame.dropna(subset=["vah", "avwap", "flow", "sigma", "fib_pos"]).reset_index(drop=True)
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
