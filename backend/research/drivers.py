"""Do gold's supposed macro drivers actually PREDICT it, or only explain it?

This is the question that separates gold from XRP. Crypto has no accepted
fundamental anchor, so XRP-Guess could only ever mine price for patterns and
found none that beat costs. Gold does have an economic story -- a dollar
price for a zero-yield asset, so it should fall when the dollar strengthens
and when holding cash pays more. If that story is real AND leads, there is
something here that XRP never had.

The trap this file exists to avoid: **contemporaneous correlation is not a
signal.** Gold and the dollar move against each other within the same
session, strongly and reliably. That relationship is real and completely
untradeable -- by the time today's DXY close is known, today's gold close is
known too. Only a driver whose move *today* says something about gold
*tomorrow* can be traded.

So every number here is computed two ways, side by side:

    ESZAMANLI  corr(driver change today, gold return today)     -> not tradeable
    ONCU       corr(driver change today, gold return tomorrow)  -> tradeable

A driver that scores high on the first and zero on the second is exactly what
efficient markets predict, and finding that is a real result, not a failure.

Discipline (inherited from XRP-Guess's research bench, which learned it the
hard way on cross-sectional momentum): the window is split in half by time.
Anything chosen is chosen on the FIRST half only, then run once on the second.
A number picked and scored in the same window means nothing.
"""
from __future__ import annotations

import math
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import panel as panel_module  # noqa: E402

# How each driver is turned into a daily "change". Yields are already in
# percent, so a difference is the natural change; prices get a return.
LEVEL_DIFF = {"us10y", "us5y", "us30y", "vix"}   # diff of the level
PRICE_RETURN = {"dxy", "spx", "silver", "copper", "oil", "eurusd", "usdjpy", "tip", "ief"}

# Derived series that encode a gold-specific relationship rather than a raw
# market. Each is a ratio or spread practitioners actually watch.
def derived(df: pd.DataFrame) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    if {"us10y", "tip", "ief"} <= set(df.columns):
        # Real-yield proxy. FRED's DFII10 is the true series but was
        # unreachable from this network (see fetch_data.FRED_CSV). TIP/IEF is
        # inflation-protected vs nominal Treasuries of similar duration, so
        # the ratio moves with breakeven inflation; nominal minus breakeven
        # is the real yield. This is a proxy for the SHAPE, not the level.
        breakeven_proxy = (df["tip"] / df["ief"])
        out["real_yield_proxy"] = df["us10y"] - 100.0 * (breakeven_proxy / breakeven_proxy.iloc[0] - 1.0)
    if {"silver"} <= set(df.columns):
        out["gold_silver_ratio"] = df["close"] / df["silver"]
    if {"copper"} <= set(df.columns):
        out["copper_gold_ratio"] = df["copper"] / df["close"]
    if {"us10y", "us5y"} <= set(df.columns):
        out["curve_10y5y"] = df["us10y"] - df["us5y"]
    return out


def build_changes(df: pd.DataFrame) -> pd.DataFrame:
    """One column per driver, each as its daily change, aligned to gold."""
    changes = pd.DataFrame(index=df.index)
    for col in df.columns:
        if col in LEVEL_DIFF:
            changes[col] = df[col].diff()
        elif col in PRICE_RETURN:
            changes[col] = df[col].pct_change()
    for name, series in derived(df).items():
        # Ratios and spreads: use the change in the ratio itself.
        changes[name] = series.diff() if name.startswith("curve") or name.startswith("real") else series.pct_change()
    return changes


def _corr_t(x: np.ndarray, y: np.ndarray) -> tuple[float, float, int]:
    """Pearson correlation plus its t-statistic and sample size."""
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    n = len(x)
    if n < 30 or np.std(x) == 0 or np.std(y) == 0:
        return float("nan"), float("nan"), n
    r = float(np.corrcoef(x, y)[0, 1])
    if abs(r) >= 1.0:
        return r, float("inf"), n
    t = r * math.sqrt((n - 2) / (1 - r * r))
    return r, t, n


def main() -> int:
    df = panel_module.load().reset_index(drop=True)
    gold_ret = df["close"].pct_change()
    changes = build_changes(df)

    n = len(df)
    split = n // 2
    print(f"Panel: {n} gun  ({df['time'].iloc[0].date()} -> {df['time'].iloc[-1].date()})")
    print(f"EGITIM yarisi : satir 0..{split}      ({df['time'].iloc[0].date()} -> {df['time'].iloc[split].date()})")
    print(f"TEST  yarisi  : satir {split}..{n}   ({df['time'].iloc[split].date()} -> {df['time'].iloc[-1].date()})")
    print()

    # today's driver change vs today's gold return  (explains, can't trade)
    same_day = gold_ret
    # today's driver change vs TOMORROW's gold return (leads, can trade)
    next_day = gold_ret.shift(-1)

    print("=" * 96)
    print("SURUCU ETKISI: esZAMANLI (aciklar) vs ONCU (tahmin eder)")
    print("=" * 96)
    print(f"{'surucu':>20} | {'ESZAMANLI r':>12} {'t':>8} | {'ONCU r (egitim)':>16} {'t':>7} | {'ONCU r (TEST)':>14} {'t':>7} | {'isaret':>6}")
    print("-" * 96)

    rows = []
    for col in changes.columns:
        x = changes[col].to_numpy(dtype=float)

        r_same, t_same, _ = _corr_t(x, same_day.to_numpy(dtype=float))
        r_tr, t_tr, n_tr = _corr_t(x[:split], next_day.to_numpy(dtype=float)[:split])
        r_te, t_te, n_te = _corr_t(x[split:], next_day.to_numpy(dtype=float)[split:])

        if not np.isfinite(r_tr) or not np.isfinite(r_te):
            continue
        consistent = "EVET" if (r_tr * r_te > 0) else "hayir"
        rows.append((col, r_same, t_same, r_tr, t_tr, r_te, t_te, consistent))
        print(f"{col:>20} | {r_same:>+12.3f} {t_same:>8.1f} | {r_tr:>+16.4f} {t_tr:>7.2f} | "
              f"{r_te:>+14.4f} {t_te:>7.2f} | {consistent:>6}")

    print()
    print("=" * 96)
    print("OKUMA")
    print("=" * 96)
    strong_same = [r for r in rows if abs(r[1]) > 0.25]
    print(f"  Esamanli |r| > 0.25 olan surucu sayisi : {len(strong_same)}")
    for r in sorted(strong_same, key=lambda z: -abs(z[1])):
        print(f"     {r[0]:>20}: r={r[1]:+.3f}  (t={r[2]:.0f})")

    # Bonferroni threshold across everything tested, so a lucky column can't
    # be mistaken for a discovery.
    k = max(len(rows), 1)
    bonf = 2.807 if k <= 10 else 3.29   # ~alpha 0.005 / 0.001 two-sided
    print(f"\n  Oncu isaret (TEST yarisi), coklu-test esigi |t| > {bonf:.2f} ({k} test):")
    survivors = [r for r in rows if abs(r[6]) > bonf and r[7] == "EVET"]
    if not survivors:
        print("     HICBIRI GECMIYOR.")
    for r in sorted(survivors, key=lambda z: -abs(z[6])):
        print(f"     {r[0]:>20}: TEST r={r[5]:+.4f} t={r[6]:+.2f}  (egitim r={r[3]:+.4f})")

    print(f"\n  Egitim->test isaret tutarliligi: "
          f"{sum(1 for r in rows if r[7] == 'EVET')}/{len(rows)}")

    print()
    print("  Yorum sablonu:")
    print("   - Esamanli buyuk + oncu sifir  = iliski gercek ama ALINAMAZ (etkin piyasa).")
    print("   - Oncu t esigi geciyor + isaret tutarli = uzerinde calisilmaya deger.")
    print("   - Sadece egitimde guclu = asiri uydurma; XRP'de kesitsel momentum boyleydi.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
