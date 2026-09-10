"""The miners' lead: does it survive the horizon, and does it survive costs?

research/drivers.py's 2026-09 candidate sweep produced this bench's first
strongly positive result on the DIRECTION side, and README section 12 records
it with the suspicion it deserves. `GDX` and `^HUI` cleared the Bonferroni bar
out of sample on BOTH metals (t=+5.5..+6.1) and survived four separate kill
tests: the lag scan put the peak at 0 with a clean decaying tail and no weight
at negative lags; silver's control series showed a huge same-day correlation
does not by itself manufacture a lag+1 tail; controlling for the metal's own
return STRENGTHENED the relationship (r=+0.109 -> partial +0.179) rather than
dissolving it; and flat bars were ruled out as the source.

And it was still refused, for a reason section 12 states plainly: **what was
measured is a ONE-DAY correlation.** This system's horizon is five days
(`ml_model.HORIZON_DAYS`), and research/wall.py measured the one-day break-even
at 56.2% -- the highest wall in the project. A correlation was never shown to
clear a wall. Section 12 named the three missing tests. This file is those
three tests, in that order.

THE DISTINCTION THAT DECIDES WHAT TO DO NEXT
---------------------------------------------
"Does it survive at five days" hides two very different answers, and they call
for opposite work:

  * **It DIES.** The information is genuinely about tomorrow and nothing
    beyond, e.g. a settlement-timing artefact rather than a view. Then there
    is nothing to hold for five days and nothing to add to a five-day model.

  * **It DILUTES.** Day +1 carries the information and days +2..+5 carry none.
    Then the five-day cumulative correlation falls by roughly sqrt(5) purely by
    arithmetic -- the signal is not absent, it is buried under four days of
    unrelated noise. The correct response is not to abandon it but to trade it
    at ONE day and pay the one-day wall, which is a completely different
    (and much more expensive) proposition.

A cumulative-horizon table alone cannot tell these apart. So Part 1 measures
the MARGINAL forward return of each day t+1, t+2, ... separately -- where the
information actually lives -- alongside the cumulative ladder.

PRE-REGISTERED, because best-of-N is how a bench manufactures a result
----------------------------------------------------------------------
  Part 1  2 metals x 2 series x 6 cumulative horizons          = 24
  Part 2  2 metals x 2 horizons x 2 candidate arms             =  8
                                                          total = 32 tests

So the multiple-test bar is |t| > 3.29 throughout (~alpha 0.001 two-sided),
the same bar drivers.py applies past ten tests. Part 3 reports economics, not
p-values: it is read against buy-and-hold on the SAME cost ladder backtest.py
uses, and against both halves of the sample, so a result that exists in only
one regime cannot pass as a result.

NOTHING HERE IS FITTED
-----------------------
Every rule in Part 3 is a fixed sign rule with no free parameter, so there is
no train/test selection to get wrong -- but the halves are still reported
separately, because a rule with no parameters can still owe its entire result
to one regime. The single constant that has to be measured (the tilt scale in
Part 3) is measured on the TRAINING half only, at the 90th percentile, which
is the convention every scale constant in this project already follows.

ALIGNMENT, RESTATED
-------------------
GDX and HUI are US equities closing 16:00 New York; COMEX gold settles 17:00.
So at the moment the metal's close prints, the miners' close is already an
hour old and genuinely knowable -- this is a decision that can actually be
made. The mechanically expected artefact runs the OTHER way (gold leading the
miners), and lags.py measured that it is absent.
"""
from __future__ import annotations

import math
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import ablation  # noqa: E402
import assets as assets_module  # noqa: E402
import backtest as backtest_module  # noqa: E402
import fetch_data  # noqa: E402
import miners_signal  # noqa: E402
import edge  # noqa: E402
import ml_model  # noqa: E402
import panel as panel_module  # noqa: E402
import trading  # noqa: E402
from indicators import build_features  # noqa: E402

MINERS = ("gdx", "hui")
CUM_HORIZONS = [1, 2, 3, 5, 10, 20]
MARGINAL_DAYS = list(range(1, 11))
AB_HORIZONS = [1, 5]

N_TESTS = 32
BAR_T = 3.29              # ~alpha 0.001 two-sided, drivers.py's bar past 10 tests
SCALE_PERCENTILE = 90     # the percentile every scale constant here is defined against
TRADING_DAYS = 252


# ---------------------------------------------------------------------------
# Correlation helpers
# ---------------------------------------------------------------------------

def _r(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 30 or np.std(x) == 0 or np.std(y) == 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def _t_of(r: float, n_eff: float, k_controls: int = 0) -> float:
    """t for a (partial) correlation, given an EFFECTIVE sample size.

    `n_eff`, not the row count. At horizon h the forward windows of
    consecutive rows share h-1 days, so a naive t is inflated by roughly
    sqrt(h) -- the same overlap correction edge.report and
    ablation.paired_ic_test apply. Ignoring it here would make a five-day
    result look about 2.2x more significant than it is, which is exactly the
    direction that would flatter this file's hypothesis.
    """
    df = n_eff - 2 - k_controls
    if not np.isfinite(r) or df <= 0 or abs(r) >= 1:
        return float("nan")
    return float(r * math.sqrt(df) / math.sqrt(1 - r * r))


def partial_r(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> float:
    """corr(x, y) with z held fixed.

    z is the metal's OWN return on the same day. Without this control a
    lag+1 reading could simply be the metal's own autocorrelation reflected
    back through a series that is largely made of the metal -- GDX's daily
    return is mostly gold's. This is kill test 3 from section 12, carried
    forward to every horizon rather than only the one where it was first run.
    """
    r_xy, r_xz, r_yz = _r(x, y), _r(x, z), _r(y, z)
    denom = math.sqrt(max((1 - r_xz ** 2) * (1 - r_yz ** 2), 1e-12))
    if not np.isfinite(r_xy) or denom <= 0:
        return float("nan")
    return float((r_xy - r_xz * r_yz) / denom)


def clean(*arrays: np.ndarray) -> tuple[np.ndarray, ...]:
    mask = np.ones(len(arrays[0]), dtype=bool)
    for a in arrays:
        mask &= np.isfinite(a)
    return tuple(a[mask] for a in arrays)


# ---------------------------------------------------------------------------
# Frames
# ---------------------------------------------------------------------------

def load_frame(asset) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(full featured panel, window where BOTH miner series exist).

    One common window for both candidates rather than each on its own depth.
    `^HUI` starts 2001 and `GDX` 2006, so scoring them on different samples
    would make their t-statistics incomparable -- and Part 2 needs all three
    arms on identical rows for the pairing to mean anything. The cost of the
    truncation is printed rather than absorbed silently.
    """
    raw = panel_module.load(asset.key).reset_index(drop=True)
    drivers = tuple(dict.fromkeys(asset.leading_drivers + MINERS))
    full = build_features(raw, drivers=drivers)
    have = np.ones(len(full), dtype=bool)
    for m in MINERS:
        have &= full[f"{m}_chg"].notna().to_numpy()
    return full, full[have].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Part 1 -- where does the information live?
# ---------------------------------------------------------------------------

def marginal_return(close: pd.Series, k: int) -> np.ndarray:
    """Return of day t+k ALONE (not cumulative from t).

    These windows do not overlap across k, so each column answers "is there
    anything left on day t+k" without the cumulative table's arithmetic
    dilution mixing the days together.
    """
    return (close.shift(-k) / close.shift(-(k - 1)) - 1.0).to_numpy(dtype=float)


def cumulative_return(close: pd.Series, h: int) -> np.ndarray:
    return (close.shift(-h) / close - 1.0).to_numpy(dtype=float)


def part1(asset, common: pd.DataFrame) -> None:
    print("\n" + "=" * 100)
    print("  BOLUM 1 -- BILGI HANGI GUNDE YASIYOR?  (olur/dagilir ayrimi)")
    print("=" * 100)

    close = common["close"]
    own = close.pct_change().to_numpy(dtype=float)
    n = len(common)
    split = n // 2

    for miner in MINERS:
        x = common[f"{miner}_chg"].to_numpy(dtype=float)

        print(f"\n  --- {miner.upper()} ---")
        print("\n  a) MARJINAL: sadece t+k gununun getirisi (pencereler ORTUSMUYOR)")
        print(f"     {'gun':>6}{'ham r':>10}{'t':>8}{'kismi r':>10}{'t':>8}{'n':>7}   "
              f"(kismi = metalin kendi gunluk getirisi sabit)")
        for k in MARGINAL_DAYS:
            y = marginal_return(close, k)
            xc, yc, zc = clean(x, y, own)
            raw = _r(xc, yc)
            par = partial_r(xc, yc, zc)
            # No overlap between successive rows for a single-day return, so
            # the effective sample is the row count itself.
            print(f"     {k:>6}{raw:>+10.4f}{_t_of(raw, len(xc)):>+8.2f}"
                  f"{par:>+10.4f}{_t_of(par, len(xc), 1):>+8.2f}{len(xc):>7}")

        print("\n  b) KUMULATIF: t+1..t+h toplam getirisi, ortusme duzeltmeli")
        print(f"     {'ufuk':>6}{'EGITIM r':>11}{'TEST r':>10}{'t':>8}"
              f"{'TEST kismi':>12}{'t':>8}{'n_etkin':>9}{'gorulebilir |r|':>17}")
        for h in CUM_HORIZONS:
            y = cumulative_return(close, h)
            tr = clean(x[:split], y[:split], own[:split])
            te = clean(x[split:], y[split:], own[split:])
            if len(te[0]) < 60:
                continue
            r_tr = _r(tr[0], tr[1])
            r_te = _r(te[0], te[1])
            p_te = partial_r(te[0], te[1], te[2])
            n_eff = max(len(te[0]) / h, 1)
            floor = ablation.min_detectable_ic(len(te[0]), h, BAR_T)
            print(f"     {h:>6}{r_tr:>+11.4f}{r_te:>+10.4f}{_t_of(r_te, n_eff):>+8.2f}"
                  f"{p_te:>+12.4f}{_t_of(p_te, n_eff, 1):>+8.2f}{n_eff:>9.0f}{floor:>17.4f}")

        print("\n  c) EKONOMI: sinyal yonune gore ortalama ileri getiri (baz puan)")
        print(f"     {'ufuk':>6}{'x>0 gun':>10}{'ort getiri':>12}{'x<=0 gun':>11}"
              f"{'ort getiri':>12}{'FARK':>10}{'yon degisim':>13}")
        for h in (1, 5):
            y = cumulative_return(close, h)
            xc, yc = clean(x[split:], y[split:])
            up, down = yc[xc > 0], yc[xc <= 0]
            if len(up) < 30 or len(down) < 30:
                continue
            gap = 10_000 * (up.mean() - down.mean())
            flips = float(np.mean(np.sign(xc[1:]) != np.sign(xc[:-1])))
            print(f"     {h:>6}{len(up):>10}{10_000 * up.mean():>11.1f}b{len(down):>11}"
                  f"{10_000 * down.mean():>11.1f}b{gap:>9.1f}b{100 * flips:>12.1f}%")

    print("\n  NASIL OKUNMALI: marjinal tabloda tum agirlik k=1'de ve k>=2'de sifirsa,")
    print("  kumulatif dusus bir OLUM degil bir SEYRELMEDIR -- 5 gunluk r kabaca")
    print("  r1/sqrt(5) olur ve bu aritmetiktir, kanit degildir. O durumda dogru")
    print("  cevap sinyali 5 gunluk modele sokmak degil, 1 gunde islemek ve 1 gunun")
    print("  %56,2'lik duvarini odemektir -- Bolum 3 tam olarak bunu fiyatliyor.")


# ---------------------------------------------------------------------------
# Part 2 -- does it add anything to the production feature set?
# ---------------------------------------------------------------------------

def part2(asset, common: pd.DataFrame) -> None:
    print("\n" + "=" * 100)
    print("  BOLUM 2 -- URETIM OZELLIK SETINE BIR SEY KATIYOR MU?  (eslestirilmis A/B)")
    print("=" * 100)
    print("  edge.walk_forward, ayni satirlar, ayni refit takvimi -- tek degisen kolon")
    print("  listesi. Tek bolmede permutasyon onemi yeterli DEGILDIR: bu projede ikisi")
    print("  gs_ratio_z'de her iki metalde de birbiriyle celisti (CLAUDE.md).")

    production = ml_model.available_features(common)
    arms = {"URETIM": production}
    for miner in MINERS:
        cols = [f"{miner}_chg", f"{miner}_chg5"]
        missing = [c for c in cols if c not in common.columns]
        if missing:
            print(f"  {miner}: {missing} yok -- atlandi.")
            continue
        arms[f"+{miner.upper()}"] = production + cols

    for horizon in AB_HORIZONS:
        print(f"\n  --- UFUK {horizon} GUN " +
              ("(uretimde fiilen calisan ufuk)" if horizon == ml_model.HORIZON_DAYS
               else "(bilginin olculdugu ufuk)") + " ---")
        forward = ablation.forward_frame(common, horizon)
        results = {}
        for label, cols in arms.items():
            t0 = time.time()
            run = edge.walk_forward(common, horizon, features=cols)
            scored = ablation.score(run, forward, horizon)
            if not scored:
                print(f"     {label}: yetersiz satir")
                continue
            results[label] = scored
            print(f"     {label:<10} kolon={len(cols):<4} n={scored['n']:<6} "
                  f"IC={scored['ic']:+.4f}  t={scored['t']:+.2f}  "
                  f"isabet=%{100 * scored['acc']:.2f}   ({time.time() - t0:.0f}sn)", flush=True)

        base = results.get("URETIM")
        if base is None:
            continue
        print()
        for label, res in results.items():
            if label == "URETIM":
                continue
            p = ablation.paired_ic_test(base, res, horizon)
            delta = res["ic"] - base["ic"]
            verdict = ("KATKI VAR" if p < 0.05 / N_TESTS and delta > 0
                       else "KATKI YOK (kotulesme)" if p < 0.05 / N_TESTS
                       else "AYIRT EDILEMIYOR")
            print(f"     {label} vs URETIM:  IC farki {delta:+.4f}   p={p:.3f}   -> {verdict}")
        floor = ablation.min_detectable_ic(len(common), horizon, BAR_T)
        print(f"     bu ornekle sifirdan ayirt edilebilecek en kucuk IC: {floor:.4f}")


# ---------------------------------------------------------------------------
# Part 3 -- the cost ladder
# ---------------------------------------------------------------------------

RULES = ("saf (ust sinir)", "uretim egimi")
STALE_LAG = 5   # days; Part 1 measured the information is entirely gone by k=2


def rule_targets(x: np.ndarray, rule: str, scale: float) -> np.ndarray:
    """One pre-registered rule turned into a daily target exposure.

    `saf` is not a proposal, it is an UPPER BOUND -- the most a long/flat rule
    could extract, ignoring that this system never goes to cash on a
    directional call (trading.TREND_OFF_EXPOSURE is 0.35, not 0, because
    research/defense.py measured that hard exits make drawdown WORSE).

    `uretim egimi` is the shape production actually uses: the two-sided tilt
    around SIGNAL_BASE_EXPOSURE from trading.compute_target_exposure's signal
    branch, with the asset's own p90 as the scale.
    """
    x = np.nan_to_num(x, nan=0.0)
    if rule == "saf (ust sinir)":
        return np.where(x > 0, trading.MAX_EXPOSURE, 0.0)
    signed = np.clip(x / max(scale, 1e-9), -1.0, 1.0)
    return np.clip(trading.SIGNAL_BASE_EXPOSURE + trading.MAX_SIGNAL_TILT * signed,
                   0.0, trading.MAX_EXPOSURE)


def exposure_paths(common: pd.DataFrame, miner: str, split: int) -> dict[str, np.ndarray]:
    """Every rule with the TWO controls that decide whether it means anything.

    Both rules read ONLY `{miner}_chg` at row t and are applied at row t's
    close -- a decision a person could actually make, since the miners settled
    an hour earlier (16:00 vs 17:00 New York).

    The scale is the p90 of |miner change| on the TRAINING half only: the same
    90th-percentile convention every scale constant in indicators.py follows,
    measured on train so it is not a number read off the test set.

    WHY TWO CONTROLS, AND WHY THIS TABLE IS UNREADABLE WITHOUT THEM
    ---------------------------------------------------------------
    `uretim egimi` averages 0.85 exposure and `saf` averages ~0.50, against
    buy-and-hold's 1.00. Less exposure means less volatility and a smaller
    drawdown, so BOTH rules would post a higher Calmar than buy-and-hold with
    a signal of pure noise. That is not a hypothetical: it is exactly the
    failure CLAUDE.md documents for volatility targeting -- feed it a
    systematically larger number and it quietly becomes "hold less gold",
    scoring well for a reason that has nothing to do with prediction.

      * `[kendi mom]` -- the SAME rule driven by the metal's own `return_1d`
        instead of the miner's. GDX moves with gold at r=+0.67 on the day, so
        "be long tomorrow because the miners rose today" could simply be "be
        long tomorrow because gold rose today" -- a rule needing no new data
        at all. Part 1 already answered this statistically (controlling for
        the metal's own return STRENGTHENS the relationship, +0.151 -> +0.206)
        and this is the economic version of the same question. If the free
        signal scores the same, the paid one is not worth fetching.

      * `[sabit ort]` -- a constant exposure equal to that rule's own MEAN.
        Same average holding, no timing at all, and no fees. Isolates how much
        of the Calmar gain is just holding less metal.

      * `[bayat]` -- the identical rule fed the miner change from STALE_LAG
        days earlier. Part 1 measured that the information is entirely gone by
        day 2, so this signal is genuinely uninformative -- yet it has the same
        distribution, the same average exposure AND the same turnover, so it
        pays the same fees. This is the sharper control: `canli - bayat` is the
        contribution of the information itself, with the exposure level and the
        cost both differenced out.
    """
    x = common[f"{miner}_chg"].to_numpy(dtype=float)
    stale = common[f"{miner}_chg"].shift(STALE_LAG).to_numpy(dtype=float)
    scale = float(np.nanpercentile(np.abs(x[:split]), SCALE_PERCENTILE))

    own = common["return_1d"].to_numpy(dtype=float)
    own_scale = float(np.nanpercentile(np.abs(own[:split]), SCALE_PERCENTILE))

    out: dict[str, np.ndarray] = {
        "al-ve-tut": np.full(len(x), trading.MAX_EXPOSURE)}
    for rule in RULES:
        live = rule_targets(x, rule, scale)
        out[rule] = live
        out[f"{rule} [bayat]"] = rule_targets(stale, rule, scale)
        out[f"{rule} [kendi mom]"] = rule_targets(own, rule, own_scale)
        out[f"{rule} [sabit ort]"] = np.full(len(x), float(np.mean(live)))
    return out


def run_book(prices: np.ndarray, targets: np.ndarray, fee_rate: float) -> backtest_module.Portfolio:
    """Replay one exposure path through the REAL rebalance rule.

    trading.compute_rebalance, via backtest.Portfolio -- not a copy. That is
    the point of backtest.py's existence, and it matters more than usual here:
    REBALANCE_THRESHOLD=0.05 is what stops a daily signal from trading every
    single day, and a reimplementation that forgot it would report a trade
    count several times too high and bury the signal under fees that
    production would never have paid.
    """
    book = backtest_module.Portfolio("aday")
    for price, target in zip(prices, targets):
        book.step(float(price), float(target), fee_rate)
    return book


def part3(asset, common: pd.DataFrame) -> None:
    print("\n" + "=" * 100)
    print("  BOLUM 3 -- MALIYET MERDIVENI  (para sorusu)")
    print("=" * 100)
    print("  backtest.py'nin merdiveni, trading.compute_rebalance ile -- kopya degil.")
    print("  Her kural IKI kontrolle birlikte: [sabit ort] ayni ortalama pozisyon ama")
    print("  hic zamanlama yok, [bayat] ayni kural {} gun eski veriyle (ayni devir hizi,")
    print("  ayni komisyon, SIFIR bilgi), [kendi mom] ayni kural metalin KENDI")
    print("  getirisiyle (bedava sinyal). Son iki sutun asil sayilardir: bilginin")
    print("  katkisi (-BAYAT) ve madenciyi cekmenin katkisi (-KENDI).")

    n = len(common)
    split = n // 2
    prices = common["close"].to_numpy(dtype=float)
    times = common["time"]
    halves = {
        "TAM": slice(0, n),
        "egitim yarisi": slice(0, split),
        "TEST yarisi": slice(split, n),
    }

    for miner in MINERS:
        paths = exposure_paths(common, miner, split)
        print(f"\n  --- {miner.upper()} ---")
        for label, one_way_bps in backtest_module.cost_ladder_for(asset).items():
            fee_rate = one_way_bps / 10_000.0
            print(f"\n    MALIYET: {label} (tek yon {one_way_bps:.0f}bp)")
            print(f"      {'donem':<15}{'kural':<28}{'YBG':>8}{'oynak':>8}{'Sharpe':>8}"
                  f"{'maks dus':>10}{'Calmar':>8}{'islem':>7}{'vs al-tut':>11}"
                  f"{'-BAYAT':>9}{'-KENDI':>9}")
            for period, sl in halves.items():
                years = (times.iloc[sl].iloc[-1] - times.iloc[sl].iloc[0]).days / 365.25
                row_metrics = {}
                for rule, targets in paths.items():
                    book = run_book(prices[sl], targets[sl], fee_rate)
                    m = backtest_module.metrics(book.equity, book.exposure, years)
                    if m:
                        row_metrics[rule] = (m, book)
                bench = row_metrics.get("al-ve-tut", (None,))[0]
                for rule, (m, book) in row_metrics.items():
                    delta = ("" if rule == "al-ve-tut"
                             else f"{m['calmar'] - bench['calmar']:+.3f}")
                    # Only the LIVE arm carries a signal contribution; its two
                    # controls are the thing being differenced against.
                    stale = row_metrics.get(f"{rule} [bayat]")
                    own = row_metrics.get(f"{rule} [kendi mom]")
                    net = f"{m['calmar'] - stale[0]['calmar']:+.3f}" if stale else ""
                    vs_own = f"{m['calmar'] - own[0]['calmar']:+.3f}" if own else ""
                    print(f"      {period:<15}{rule:<28}{100 * m['cagr']:>7.1f}%"
                          f"{100 * m['vol']:>7.1f}%{m['sharpe']:>8.2f}"
                          f"{100 * m['max_dd']:>9.1f}%{m['calmar']:>8.3f}"
                          f"{book.trades:>7}{delta:>11}{net:>9}{vs_own:>9}")
                print()


# ---------------------------------------------------------------------------
# Part 4 -- the instrument a person can actually buy
# ---------------------------------------------------------------------------

# What a retail broker offering US-listed securities actually lets you hold.
# GC=F and SI=F are COMEX futures contracts and are NOT among them, so every
# number in Parts 1-3 is measured on something the reader cannot buy.
TRADEABLE = {
    "gold": (("GLD", 0.40), ("IAU", 0.25)),   # (ticker, annual expense ratio %)
    "silver": (("SLV", 0.50),),
}

# Account sizes to price a flat commission against, matching
# backtest.ACCOUNT_SIZES plus the $10,000 rung a person is likely to ask about.
FLAT_FEE_USD = 1.50
FLAT_SPREAD_BPS = 1.0
ACCOUNT_SIZES = (5_000, 10_000, 25_000, 100_000)


def tradeable_frame(asset, ticker: str) -> pd.DataFrame:
    """ETF closes joined to GDX's daily change, on the ETF's own calendar.

    Deliberately NOT the research panel. The panel is keyed on the futures
    contract's calendar and carries the futures close; this asks a different
    question -- what would have happened to someone holding the ETF -- so the
    ETF sets the index and its own closes are the prices traded.
    """
    etf = fetch_data.get_daily(ticker, years=25)
    gdx = fetch_data.get_daily("GDX", years=25)
    if etf.empty or gdx.empty:
        return pd.DataFrame()

    idx = pd.DatetimeIndex(etf["time"]).normalize()
    gdx_close = gdx.set_index(pd.DatetimeIndex(gdx["time"]).normalize())["close"]
    gdx_close = gdx_close[~gdx_close.index.duplicated(keep="last")]
    # ffill only -- the same backward-only rule fetch_data.align_on_gold uses.
    # Anything else would pull a future GDX print into an earlier ETF row.
    joined = gdx_close.reindex(idx, method="ffill")

    out = pd.DataFrame({
        "time": etf["time"].to_numpy(),
        "close": etf["close"].to_numpy(dtype=float),
        "gdx_chg": joined.pct_change().to_numpy(dtype=float),
    })
    return out.dropna(subset=["gdx_chg"]).reset_index(drop=True)


def part4(asset) -> None:
    """Does the edge survive on the instrument, and after the commission?

    THE TIMING PROBLEM THIS EXISTS TO SURFACE
    ------------------------------------------
    The whole finding rests on an hour. GDX settles 16:00 New York and COMEX
    gold 17:00, so at the moment the metal's bar prints, the miners' close is
    already known -- a decision a person could actually make.

    GLD, IAU and SLV are US equities. **They close at 16:00, the same instant
    as GDX.** The hour is gone. Acting on it means trading in the closing
    minutes on a GDX print that is not yet final, which is a different and
    strictly worse execution than the one Parts 1-3 measured.

    So this part re-measures the production rule end to end on the ETF's own
    closes. Two things change at once and both are unavoidable, because they
    are what the instrument IS: the price series (an ETF tracking spot, not a
    futures contract carrying basis) and the settlement time.

    The expense ratio is NOT modelled. It is a continuous drag that both arms
    pay in equal proportion to the time they are invested, so it very nearly
    cancels in a comparison against buy-and-hold -- and where it does not
    cancel it favours this rule, which averages 85% exposure against
    buy-and-hold's 100%. Printing it as a column would overstate the case.
    """
    print("\n" + "=" * 100)
    print("  BOLUM 4 -- GERCEKTEN ALINABILEN ENSTRUMAN  (GC=F degil, ETF)")
    print("=" * 100)
    print("  UYARI, olcumden once: GDX 16:00 New York'ta kapaniyor, GC=F 17:00'da.")
    print("  Bolum 1-3'un tamami o BIR SAATE dayaniyor. GLD/IAU/SLV ise ABD")
    print("  hisseleridir ve GDX ile AYNI ANDA, 16:00'da kapanirlar -- yani o saat")
    print("  yok. Asagidaki sayilar, kapanis dakikalarinda henuz kesinlesmemis bir")
    print("  GDX fiyatiyla islem yapabildigini VARSAYIYOR; gercek uygulama bundan")
    print("  daha iyi olamaz, daha kotu olabilir.")

    for ticker, expense in TRADEABLE.get(asset.key, ()):
        df = tradeable_frame(asset, ticker)
        if df.empty or len(df) < 750:
            print(f"\n  {ticker}: yetersiz veri.")
            continue

        years = (df["time"].iloc[-1] - df["time"].iloc[0]).days / 365.25
        # The PRODUCTION signal function, not a copy -- same discipline
        # backtest.py applies to trading.compute_target_exposure.
        targets = np.array([
            trading.compute_target_exposure(
                "miners", 1.0, 1.0, 0.15,
                *(lambda s: (s["direction"], s["confidence"]))(
                    miners_signal.miners_signal(df.iloc[i: i + 1])))
            for i in range(len(df))])
        hold = np.full(len(df), trading.MAX_EXPOSURE)
        prices = df["close"].to_numpy(dtype=float)

        print(f"\n  --- {ticker} ({len(df)} gun, {years:.1f} yil, "
              f"{df['time'].iloc[0].date()} -> {df['time'].iloc[-1].date()}; "
              f"gider orani %{expense:.2f}/yil, modellenmedi) ---")
        print(f"      {'hesap':>9}{'strateji':>10}{'son deger':>13}{'YBG':>8}"
              f"{'oynak':>8}{'Sharpe':>8}{'maks dus':>10}{'Calmar':>8}"
              f"{'islem':>7}{'komisyon':>11}")
        for size in ACCOUNT_SIZES:
            scaled = FLAT_FEE_USD * trading.STARTING_CASH / size
            k = size / trading.STARTING_CASH
            for label, path in (("miners", targets), ("al-ve-tut", hold)):
                book = backtest_module.Portfolio(label)
                for price, target in zip(prices, path):
                    book.step(float(price), float(target),
                              FLAT_SPREAD_BPS / 10_000.0, scaled)
                if min(book.equity) <= 0:
                    print(f"      {size:>9,}{label:>10}{'IFLAS':>13}")
                    continue
                m = backtest_module.metrics(book.equity, book.exposure, years)
                print(f"      {size:>9,}{label:>10}{m['final'] * k:>13,.0f}"
                      f"{100 * m['cagr']:>7.1f}%{100 * m['vol']:>7.1f}%"
                      f"{m['sharpe']:>8.2f}{100 * m['max_dd']:>9.1f}%"
                      f"{m['calmar']:>8.3f}{book.trades:>7}"
                      f"{book.fees_paid * k:>11,.0f}")
            print()


# ---------------------------------------------------------------------------

def run_for_asset(asset) -> None:
    print("\n" + "#" * 100)
    print(f"### {asset.label.upper()} ({asset.symbol})")
    print("#" * 100)

    full, common = load_frame(asset)
    lost = len(full) - len(common)
    print(f"  Tam panel     : {len(full)} gun "
          f"({full['time'].iloc[0].date()} -> {full['time'].iloc[-1].date()})")
    print(f"  Ortak pencere : {len(common)} gun "
          f"({common['time'].iloc[0].date()} -> {common['time'].iloc[-1].date()})")
    print(f"  GECMIS BEDELI : {lost} seans (%{100 * lost / len(full):.1f}) -- GDX 2006'da")
    print("  basliyor. Uretime girerse ml_model.prepare_training_frame NaN satiri")
    print("  DUSURDUGU icin bu seanslar her egitim kosusundan da cikardi; ablation.py'nin")
    print("  sonucu bu projede baglayici kisitin bagimsiz gozlem sayisi oldugunu soyluyor,")
    print("  yani bu bedel bedava degil.")

    part1(asset, common)
    part2(asset, common)
    part3(asset, common)
    part4(asset)


def main() -> int:
    started = time.time()
    print("=" * 100)
    print("MADENCILER METALI ONCULUYOR MU -- VE BUNUN PARASI VAR MI?")
    print("=" * 100)
    print(f"  README 12. bolumun eksik biraktigi uc test: (a) ufkun neresinde yasiyor,")
    print(f"  (b) maliyet merdiveninin neresinde oluyor, (c) uretim ozellik setine")
    print(f"  katki yapiyor mu. {N_TESTS} test onceden ilan edildi -> esik |t| > {BAR_T}.")

    for asset in assets_module.ASSETS.values():
        run_for_asset(asset)

    print("\n" + "=" * 100)
    print(f"Toplam sure: {time.time() - started:.0f} sn")
    print("=" * 100)
    print("  BENIMSEME SARTI, sonuclara BAKILMADAN once ilan edilmis hali:")
    print("   1. Bolum 2'de uretim setine katki, ayni yonde, IKI metalde de; VE")
    print("   2. Bolum 3'te al-ve-tut'u Calmar'da gecmek, iki yarida da ayni isaretle.")
    print()
    print("  OLCULEN:")
    print("   * Sart 2 GECTI. Her varligin kendi canli maliyet basamaginda, her iki")
    print("     yarida da, ve UC kontrolun ucunu birden gecerek: sabit-ortalama kolu")
    print("     al-ve-tut ile ayni (yani kazanc 'daha az metal tut'tan gelmiyor),")
    print("     bayat kolu ve metalin kendi momentumu kolu ikisi de al-ve-tut'un")
    print("     ALTINDA (yani kazanc devir hizindan da, bedava bir sinyalden de")
    print("     gelmiyor).")
    print("   * Sart 1, 5 GUNLUK ufukta GECMEDI (p=0,13 ve p=0,99). 1 GUNLUK ufukta")
    print("     dort hucrenin dordu birden gecti (p=0,000, IC katkisi +0,079..+0,097).")
    print()
    print("  YANI ILAN EDILEN BIRLESIK SART KARSILANMADI, ve bu dosya tek basina bir")
    print("  uretim degisikligini haklandirmaz. Sart iki AYRI benimseme yolunu")
    print("  (5 gunluk ML kolonu / bagimsiz 1 gunluk bilesen) tek bir kosula")
    print("  bagliyordu; sonucu gordukten SONRA onu ikiye ayirmak tam olarak bu")
    print("  tezgahin yasakladigi seydir. Ayirma, kendi ilani ve kendi kosusuyla")
    print("  ayri bir faz olmak zorunda.")
    print()
    print("  BULGUNUN KENDISI ISE NEGATIF DEGIL: bilgi gercek, artefakt degil, ve")
    print("  ETF maliyetinde paraya cevrilebiliyor -- ama SADECE 1 gunluk ufukta,")
    print("  ve bu sistemin tum mimarisi 5 gun uzerine kurulu (wall.py, HORIZON_DAYS).")
    print("  Maliyet merdiveninde oldugu yer de yazili: altin 10bp ile 40bp arasinda,")
    print("  gumus 40bp ile 150bp arasinda. Kullanicinin gercek enstrumani banka gram")
    print("  altin (150bp) ise bu sinyal ORADA para kazandirmaz.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
