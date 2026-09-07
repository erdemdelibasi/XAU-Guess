"""The other question: forget predicting gold -- can we just hold it BETTER?

research/wall.py measured the thing this project actually has to beat. Over
25 years, simply holding gold returned +1522% (11.8% a year) at 18.1%
volatility with a **44.4% maximum drawdown**. From a two-day horizon onward,
"always long" already clears the cost wall on its own. Direction prediction
is therefore not where the value is; a model that gets 55% right and trades
for it can easily end up behind a person who did nothing.

What buy-and-hold is genuinely bad at is the 44.4%. Gold spent 2012-2015
grinding down and took until 2020 to recover. If a rule can sidestep even a
third of that without giving up much upside, it beats holding on every
risk-adjusted measure -- and unlike a directional edge, trend-following
drawdown control does not require being right more often than chance. It
requires being wrong cheaply and right expensively.

So this file tests DEFENSE, not prediction:

    SMA200        long above the 200-day average, flat below   (the classic)
    SMA100 / 50   the same idea at faster speeds
    dual EMA      long while ema50 > ema200
    vol target    scale position to a volatility budget
    dd stop       exit on a drawdown from peak, re-enter on recovery

Discipline is the same as everywhere in this bench: the window is split in
half by time, a variant is chosen on the FIRST half only, and that single
choice is run once on the second. XRP-Guess's cross-sectional momentum study
looked spectacular (+123%/yr) chosen and scored in one window and turned in
-34.3%/yr out of sample; the split is the only thing that catches that.

Costs are charged on every position change, at the three-scenario ladder from
wall.py, because a defensive rule that trades constantly pays for the
privilege.
"""
from __future__ import annotations

import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import panel as panel_module  # noqa: E402

TRADING_DAYS = 252
COST_BPS = {"COMEX 2bp": 2, "ETF 10bp": 10, "Perakende 40bp": 40}


def metrics(equity: np.ndarray, exposure: np.ndarray, years: float) -> dict:
    """Standard risk/return summary for an equity curve."""
    total = equity[-1] / equity[0] - 1.0
    cagr = (equity[-1] / equity[0]) ** (1 / years) - 1.0
    rets = np.diff(equity) / equity[:-1]
    vol = float(np.std(rets)) * np.sqrt(TRADING_DAYS)
    peak = np.maximum.accumulate(equity)
    max_dd = float(np.max(1 - equity / peak))
    return {
        "total": total,
        "cagr": cagr,
        "vol": vol,
        # Risk-free rate deliberately omitted -- it moved from 0% to 5% across
        # this panel, and every strategy here is compared against buy-and-hold
        # on the SAME asset, so a common subtraction changes no ranking.
        "sharpe": cagr / vol if vol > 0 else float("nan"),
        "max_dd": max_dd,
        # Calmar is the metric that matters most here: return per unit of the
        # worst thing that happened, which is precisely what buy-and-hold does
        # badly on gold.
        "calmar": cagr / max_dd if max_dd > 0 else float("nan"),
        "exposure": float(np.mean(exposure)),
    }


def simulate(closes: np.ndarray, target: np.ndarray, cost_bps: float) -> tuple[np.ndarray, np.ndarray]:
    """Equity curve for a series of target exposures in [0, 1].

    `target[i]` is the exposure DECIDED at the close of day i and therefore
    held through day i+1. The shift is what makes this tradeable -- using
    target[i] to earn day i's own return would be reading the answer.
    Cost is charged on the change in exposure.
    """
    rets = np.diff(closes) / closes[:-1]
    held = target[:-1]                      # decided yesterday, earns today
    turnover = np.abs(np.diff(np.concatenate([[0.0], held])))
    cost = turnover * (cost_bps / 10_000.0)
    daily = held * rets - cost
    equity = np.concatenate([[1.0], np.cumprod(1.0 + daily)])
    return equity, held


# --------------------------------------------------------------------------
# Rules. Each returns a target exposure array aligned with `closes`.
# Every one uses only information available at or before day i.
# --------------------------------------------------------------------------

def rule_buy_hold(df: pd.DataFrame) -> np.ndarray:
    return np.ones(len(df))


def rule_sma(df: pd.DataFrame, window: int) -> np.ndarray:
    sma = df["close"].rolling(window).mean()
    return (df["close"] > sma).astype(float).fillna(1.0).to_numpy()


def rule_dual_ema(df: pd.DataFrame, fast: int, slow: int) -> np.ndarray:
    ef = df["close"].ewm(span=fast, adjust=False).mean()
    es = df["close"].ewm(span=slow, adjust=False).mean()
    return (ef > es).astype(float).fillna(1.0).to_numpy()


def rule_vol_target(df: pd.DataFrame, target_vol: float = 0.15, lookback: int = 60) -> np.ndarray:
    """Scale exposure so realised volatility sits near a budget. Capped at 1 --
    no leverage, because a leveraged gold position is a different product with
    different financing, and pretending otherwise flatters the result."""
    realised = df["close"].pct_change().rolling(lookback).std() * np.sqrt(TRADING_DAYS)
    exposure = (target_vol / realised).clip(upper=1.0)
    return exposure.fillna(1.0).to_numpy()


def rule_dd_stop(df: pd.DataFrame, stop: float = 0.15, recover: float = 0.05) -> np.ndarray:
    """Exit after a `stop` drawdown from the running peak; re-enter once price
    has risen `recover` off the trough. The re-entry band is not decoration:
    XRP-Guess measured that without a cooldown, 235 of 236 stop-losses were
    followed by an immediate re-entry that got stopped out again."""
    closes = df["close"].to_numpy(dtype=float)
    exposure = np.ones(len(closes))
    peak, trough, in_market = closes[0], closes[0], True
    for i, price in enumerate(closes):
        if in_market:
            peak = max(peak, price)
            if price <= peak * (1 - stop):
                in_market, trough = False, price
        else:
            trough = min(trough, price)
            if price >= trough * (1 + recover):
                in_market, peak = True, price
        exposure[i] = 1.0 if in_market else 0.0
    return exposure


def rule_sma_vol(df: pd.DataFrame, window: int = 200, target_vol: float = 0.15) -> np.ndarray:
    """Trend filter AND volatility scaling -- the two combined."""
    return rule_sma(df, window) * rule_vol_target(df, target_vol)


VARIANTS = {
    "al-ve-tut":            rule_buy_hold,
    "SMA200":               lambda d: rule_sma(d, 200),
    "SMA100":               lambda d: rule_sma(d, 100),
    "SMA50":                lambda d: rule_sma(d, 50),
    "EMA50/200":            lambda d: rule_dual_ema(d, 50, 200),
    "EMA20/100":            lambda d: rule_dual_ema(d, 20, 100),
    "vol hedefi %15":       lambda d: rule_vol_target(d, 0.15),
    "vol hedefi %12":       lambda d: rule_vol_target(d, 0.12),
    "dusus stopu %15/%5":   lambda d: rule_dd_stop(d, 0.15, 0.05),
    "dusus stopu %10/%5":   lambda d: rule_dd_stop(d, 0.10, 0.05),
    "SMA200 + vol %15":     lambda d: rule_sma_vol(d, 200, 0.15),
}


def evaluate(df: pd.DataFrame, cost_bps: float) -> dict[str, dict]:
    closes = df["close"].to_numpy(dtype=float)
    years = (df["time"].iloc[-1] - df["time"].iloc[0]).days / 365.25
    out = {}
    for name, rule in VARIANTS.items():
        target = rule(df)
        equity, held = simulate(closes, target, cost_bps)
        out[name] = metrics(equity, held, years)
    return out


def print_table(title: str, results: dict[str, dict], baseline: str = "al-ve-tut") -> None:
    print(f"\n{title}")
    print("-" * 94)
    print(f"{'strateji':<22}{'YBG':>8}{'oynak':>8}{'Sharpe':>8}{'maks dusus':>12}{'Calmar':>8}{'piyasada':>10}{'vs tut':>16}")
    base = results.get(baseline, {})
    for name, m in results.items():
        delta = ""
        if base and name != baseline:
            d_cagr = 100 * (m["cagr"] - base["cagr"])
            d_dd = 100 * (m["max_dd"] - base["max_dd"])
            delta = f"{d_cagr:+.1f}p / {d_dd:+.1f}p"
        print(f"{name:<22}{100 * m['cagr']:>7.1f}%{100 * m['vol']:>7.1f}%{m['sharpe']:>8.2f}"
              f"{100 * m['max_dd']:>11.1f}%{m['calmar']:>8.2f}{100 * m['exposure']:>9.0f}%{delta:>16}")


def main() -> int:
    df = panel_module.load().reset_index(drop=True)
    n = len(df)
    split = n // 2
    train = df.iloc[:split].reset_index(drop=True)
    test = df.iloc[split:].reset_index(drop=True)

    print(f"Panel: {n} gun ({df['time'].iloc[0].date()} -> {df['time'].iloc[-1].date()})")
    print(f"EGITIM: {df['time'].iloc[0].date()} -> {df['time'].iloc[split - 1].date()}  ({split} gun)")
    print(f"TEST  : {df['time'].iloc[split].date()} -> {df['time'].iloc[-1].date()}  ({n - split} gun)")
    print("\nSecim SADECE egitim yarisinda yapilir; secilen tek varyant test yarisinda")
    print("bir kez kosturulur. Diger her sey seffaflik icin basiliyor.")

    etf = COST_BPS["ETF 10bp"]

    train_results = evaluate(train, etf)
    print_table(f"=== EGITIM YARISI (maliyet {etf} bp) ===", train_results)

    # The choice. Calmar, not CAGR: the entire premise of this file is that
    # holding gold already earns a fine return and the problem is the
    # drawdown, so ranking on raw return would pick the variant that takes the
    # most risk and call it the winner.
    candidates = {k: v for k, v in train_results.items() if k != "al-ve-tut"}
    chosen = max(candidates, key=lambda k: candidates[k]["calmar"])
    print(f"\n>>> EGITIMDE SECILEN (en yuksek Calmar): {chosen}")
    print(f"    egitim Calmar={candidates[chosen]['calmar']:.2f}  "
          f"(al-ve-tut {train_results['al-ve-tut']['calmar']:.2f})")

    test_results = evaluate(test, etf)
    print_table(f"=== TEST YARISI (gorulmemis veri, maliyet {etf} bp) ===", test_results)

    print("\n" + "=" * 94)
    print("SECILEN VARYANTIN TEST SONUCU  --  tek onemli satir bu")
    print("=" * 94)
    bh, ch = test_results["al-ve-tut"], test_results[chosen]
    print(f"  {chosen}:")
    print(f"     yillik getiri   %{100 * ch['cagr']:+.1f}   (al-ve-tut %{100 * bh['cagr']:+.1f})")
    print(f"     maks dusus      %{100 * ch['max_dd']:.1f}    (al-ve-tut %{100 * bh['max_dd']:.1f})")
    print(f"     Calmar          {ch['calmar']:.2f}     (al-ve-tut {bh['calmar']:.2f})")
    print(f"     Sharpe          {ch['sharpe']:.2f}     (al-ve-tut {bh['sharpe']:.2f})")
    print(f"     piyasada gecen  %{100 * ch['exposure']:.0f}")
    better_calmar = ch["calmar"] > bh["calmar"]
    print(f"\n  >>> {'GECTI' if better_calmar else 'GECEMEDI'}: riske gore "
          f"{'daha iyi' if better_calmar else 'daha kotu'} (Calmar {ch['calmar']:.2f} vs {bh['calmar']:.2f})")

    print("\n" + "=" * 94)
    print("MALIYET DUYARLILIGI (secilen varyant, test yarisi)")
    print("=" * 94)
    for label, bps in COST_BPS.items():
        r = evaluate(test, bps)
        print(f"  {label:<16} {chosen}: YBG %{100 * r[chosen]['cagr']:+.1f}  "
              f"Calmar {r[chosen]['calmar']:.2f}   |   al-ve-tut: YBG %{100 * r['al-ve-tut']['cagr']:+.1f}  "
              f"Calmar {r['al-ve-tut']['calmar']:.2f}")

    walk_forward_selection(df, etf)
    regime_breakdown(df, etf)
    return 0


def walk_forward_selection(df: pd.DataFrame, cost_bps: float,
                           lookback_years: int = 5, step_days: int = TRADING_DAYS) -> None:
    """Re-choose the variant every year on the trailing `lookback_years`.

    Why this exists on top of the single split above: the split's test half
    (2014-2026) is dominated by gold's run from ~$1200 to ~$4400. In a window
    that one-sided, ANY rule that is out of the market part of the time loses
    to holding, and "trend following underperformed" would be a fact about
    the window rather than about the rule. Rolling the choice forward puts
    both of gold's regimes -- the 2012-2015 bear and the 2019-2026 bull --
    into the out-of-sample record instead of splitting one into each half.

    Still strictly out of sample: each year's variant is chosen using only
    data that ended before that year started.
    """
    print("\n" + "=" * 94)
    print(f"YURUYEN-ILERI SECIM (her yil, onceki {lookback_years} yila bakarak yeniden sec)")
    print("=" * 94)

    lookback = lookback_years * TRADING_DAYS
    closes = df["close"].to_numpy(dtype=float)
    target = np.full(len(df), np.nan)
    picks: list[tuple[str, str]] = []

    start = lookback
    while start < len(df):
        stop = min(start + step_days, len(df))
        window = df.iloc[start - lookback:start].reset_index(drop=True)
        scored = evaluate(window, cost_bps)
        candidates = {k: v for k, v in scored.items() if k != "al-ve-tut"}
        pick = max(candidates, key=lambda k: candidates[k]["calmar"])

        # Apply the chosen rule computed on history up to `stop`, then take
        # only the [start:stop] slice -- the rule needs its own warmup, and
        # recomputing it on the short block alone would give a 200-day SMA
        # nothing to average.
        applied = VARIANTS[pick](df.iloc[:stop].reset_index(drop=True))
        target[start:stop] = applied[start:stop]
        picks.append((str(df["time"].iloc[start].date()), pick))
        start = stop

    valid = ~np.isnan(target)
    first = int(np.argmax(valid))
    sub_close = closes[first:]
    sub_target = np.nan_to_num(target[first:], nan=1.0)
    years = (df["time"].iloc[-1] - df["time"].iloc[first]).days / 365.25

    equity, held = simulate(sub_close, sub_target, cost_bps)
    bh_equity, bh_held = simulate(sub_close, np.ones(len(sub_close)), cost_bps)
    m_wf = metrics(equity, held, years)
    m_bh = metrics(bh_equity, bh_held, years)

    print(f"  Donem: {df['time'].iloc[first].date()} -> {df['time'].iloc[-1].date()} ({years:.1f} yil)")
    counts: dict[str, int] = {}
    for _, pick in picks:
        counts[pick] = counts.get(pick, 0) + 1
    print("  Yillara gore secilenler: " + ", ".join(f"{k}x{v}" for k, v in sorted(counts.items(), key=lambda z: -z[1])))
    print()
    print(f"{'':<26}{'YBG':>9}{'oynak':>9}{'Sharpe':>9}{'maks dusus':>13}{'Calmar':>9}{'piyasada':>10}")
    print(f"  {'yuruyen-ileri secim':<24}{100 * m_wf['cagr']:>8.1f}%{100 * m_wf['vol']:>8.1f}%{m_wf['sharpe']:>9.2f}"
          f"{100 * m_wf['max_dd']:>12.1f}%{m_wf['calmar']:>9.2f}{100 * m_wf['exposure']:>9.0f}%")
    print(f"  {'al-ve-tut':<24}{100 * m_bh['cagr']:>8.1f}%{100 * m_bh['vol']:>8.1f}%{m_bh['sharpe']:>9.2f}"
          f"{100 * m_bh['max_dd']:>12.1f}%{m_bh['calmar']:>9.2f}{100 * m_bh['exposure']:>9.0f}%")
    verdict = "GECTI" if m_wf["calmar"] > m_bh["calmar"] else "GECEMEDI"
    print(f"\n  >>> {verdict} (Calmar {m_wf['calmar']:.2f} vs {m_bh['calmar']:.2f})")

    # Every fixed variant over the same span, for context. These are NOT
    # choices -- a variant that wins here was not selectable in advance, and
    # reading one off this table is exactly the error the whole file guards
    # against. It is printed so the walk-forward result can be seen in
    # relation to the spread of what was available.
    print("\n  Ayni donemde sabit varyantlar (SECIM DEGIL, sadece baglam):")
    span = df.iloc[first:].reset_index(drop=True)
    for name, m in evaluate(span, cost_bps).items():
        print(f"    {name:<22} YBG %{100 * m['cagr']:>5.1f}  maks dusus %{100 * m['max_dd']:>5.1f}  Calmar {m['calmar']:.2f}")


def regime_breakdown(df: pd.DataFrame, cost_bps: float) -> None:
    """The same variants, split into gold's actual bull and bear phases.

    A defensive rule is SUPPOSED to lose money in a bull market -- that is
    what paying for insurance looks like. Judging one on a blended average
    hides both halves of the trade-off it is making.
    """
    print("\n" + "=" * 94)
    print("REJIME GORE AYRISTIRMA")
    print("=" * 94)
    periods = [
        ("2001-2011 boga",  "2001-09-07", "2011-09-05"),
        ("2011-2015 ayi",   "2011-09-06", "2015-12-31"),
        ("2016-2019 yatay", "2016-01-01", "2018-12-31"),
        ("2019-2026 boga",  "2019-01-01", "2026-09-04"),
    ]
    for label, lo, hi in periods:
        mask = (df["time"] >= lo) & (df["time"] <= hi)
        window = df[mask].reset_index(drop=True)
        if len(window) < 260:
            continue
        scored = evaluate(window, cost_bps)
        bh = scored["al-ve-tut"]
        print(f"\n  {label}  ({window['time'].iloc[0].date()} -> {window['time'].iloc[-1].date()}, "
              f"al-ve-tut YBG %{100 * bh['cagr']:+.1f}, maks dusus %{100 * bh['max_dd']:.1f})")
        for name in ("SMA200", "EMA50/200", "EMA20/100", "vol hedefi %15", "dusus stopu %15/%5"):
            m = scored[name]
            print(f"     {name:<20} YBG %{100 * m['cagr']:>+6.1f} ({100 * (m['cagr'] - bh['cagr']):>+5.1f}p)   "
                  f"maks dusus %{100 * m['max_dd']:>5.1f} ({100 * (m['max_dd'] - bh['max_dd']):>+5.1f}p)")


if __name__ == "__main__":
    sys.exit(main())
