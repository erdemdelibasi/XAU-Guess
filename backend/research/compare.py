"""Silver against gold: is it the same game at a different price?

Every constant in assets.py that carries a number comes from here. The whole
reason this file exists is that "add silver" is exactly the kind of change
that looks like a one-line config edit and quietly is not -- ensemble.py
measures each component's skill against `base_rate_up`, and trading.py sizes
positions against `target_volatility`. Copying gold's values onto silver
would silently rebase silver's entire component scoreboard and turn its
volatility targeting into "hold less silver", which is a different and
untested strategy.

Checks, in order of how badly getting them wrong would hurt:

  1. Data quality. Silver's panel carries 1532 flat bars (24.4%) against
     gold's 683 (10.9%). For gold, those closes were validated against GLD
     and turned out real. Silver gets the same test against SLV before any
     of its numbers are trusted.
  2. Break-even wall -- silver moves more, but its spread is a wider
     fraction of its price. Which wins is an empirical question.
  3. Base rate and buy-and-hold. The bar every model has to clear.
  4. Do the same three leading drivers lead silver too, or does it need
     its own set?
"""
from __future__ import annotations

import math
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import assets as assets_module  # noqa: E402
import drivers  # noqa: E402
import fetch_data  # noqa: E402
import panel as panel_module  # noqa: E402
import wall  # noqa: E402

TRADING_DAYS = 252
HORIZONS = [1, 5, 20]
# Validation ETF per metal: an independent, clean series for the same
# underlying, used only to check whether flat-bar closes are real.
VALIDATION_ETF = {"gold": "GLD", "silver": "SLV"}


def flat_bar_quality(asset_key: str) -> dict:
    """Do this asset's flat-bar closes track an independent series?

    Gold's did (r=0.737 against GLD, versus 0.892 for normal bars), which is
    why panel.py keeps them. Silver has more than twice as many, so the same
    question has to be asked again rather than assumed.
    """
    asset = assets_module.get(asset_key)
    prices = fetch_data.get_daily(asset.symbol, years=25)
    etf = fetch_data.get_daily(VALIDATION_ETF[asset_key], years=25)
    if prices.empty or etf.empty:
        return {}

    prices = panel_module.flag_flat_bars(prices)
    prices["day"] = prices["time"].dt.normalize()
    etf = etf.assign(day=etf["time"].dt.normalize())
    merged = prices.merge(etf[["day", "close"]].rename(columns={"close": "etf"}), on="day")
    merged["ret"] = merged["close"].pct_change()
    merged["etf_ret"] = merged["etf"].pct_change()
    merged = merged.dropna(subset=["ret", "etf_ret"])
    # Only rows whose PREVIOUS bar was normal, so `ret` is a clean one-day
    # return rather than one spanning a suspect bar.
    merged["prev_flat"] = merged["flat_bar"].shift(1).fillna(False).astype(bool)
    clean = merged[~merged["prev_flat"]]

    out = {"flat_share": float(prices["flat_bar"].mean())}
    for label, subset in (("flat", clean[clean["flat_bar"]]), ("normal", clean[~clean["flat_bar"]])):
        if len(subset) < 30:
            continue
        out[f"{label}_n"] = len(subset)
        out[f"{label}_corr"] = float(subset["ret"].corr(subset["etf_ret"]))
        out[f"{label}_err"] = float((subset["ret"] - subset["etf_ret"]).abs().median())
    return out


def price_stats(df: pd.DataFrame) -> dict:
    closes = df["close"].to_numpy(dtype=float)
    years = (df["time"].iloc[-1] - df["time"].iloc[0]).days / 365.25
    daily = np.diff(closes) / closes[:-1]
    peak = np.maximum.accumulate(closes)
    return {
        "n": len(closes),
        "years": years,
        "total": closes[-1] / closes[0] - 1.0,
        "cagr": (closes[-1] / closes[0]) ** (1 / years) - 1.0,
        "vol": float(np.std(daily)) * math.sqrt(TRADING_DAYS),
        "max_dd": float(np.max(1 - closes / peak)),
        "first": float(closes[0]),
        "last": float(closes[-1]),
    }


def main() -> int:
    panels = {key: panel_module.load(key) for key in assets_module.ASSETS}

    print("=" * 88)
    print("1) VERI KALITESI -- duz mumlarin kapanislari gercek mi?")
    print("=" * 88)
    print("  Altin icin bu test duz mumlarin TUTULMASINA karar verdirdi (r=0.737).")
    print("  Gumuste iki katindan fazla duz mum var, o yuzden soru yeniden soruluyor.\n")
    print(f"{'varlik':<10}{'duz oran':>11}{'duz r':>9}{'normal r':>10}"
          f"{'duz |fark|':>13}{'normal |fark|':>15}{'karar':>18}")
    for key in assets_module.ASSETS:
        q = flat_bar_quality(key)
        if not q or "flat_corr" not in q:
            print(f"{key:<10}{'-':>11}  (yetersiz veri)")
            continue
        # A flat bar's close is trustworthy when it tracks the ETF at a
        # correlation in the same league as a normal bar's.
        verdict = "TUT (kapanis gercek)" if q["flat_corr"] > 0.6 * q["normal_corr"] else "SUPHELI"
        print(f"{key:<10}{100 * q['flat_share']:>10.1f}%{q['flat_corr']:>9.3f}{q['normal_corr']:>10.3f}"
              f"{100 * q['flat_err']:>12.3f}%{100 * q['normal_err']:>14.3f}%{verdict:>18}")

    print()
    print("=" * 88)
    print("2) FIYAT DAVRANISI")
    print("=" * 88)
    print(f"{'varlik':<10}{'gun':>7}{'ilk':>10}{'son':>10}{'toplam':>10}"
          f"{'YBG':>8}{'oynaklik':>10}{'maks dusus':>12}")
    stats = {}
    for key, df in panels.items():
        s = price_stats(df)
        stats[key] = s
        print(f"{key:<10}{s['n']:>7}{s['first']:>10.2f}{s['last']:>10.2f}"
              f"{100 * s['total']:>9.0f}%{100 * s['cagr']:>7.1f}%{100 * s['vol']:>9.1f}%"
              f"{100 * s['max_dd']:>11.1f}%")
    ratio = stats["silver"]["vol"] / stats["gold"]["vol"]
    print(f"\n  Gumusun oynakligi altinin {ratio:.2f} kati.")
    print(f"  -> assets.SILVER.target_volatility, altininkinin ayni katiyla olceklenmeli")
    print(f"     ({100 * 0.15:.0f}% x {ratio:.2f} = {100 * 0.15 * ratio:.0f}%), yoksa ayni butce")
    print("     gumusu kalici olarak dusuk pozisyonda tutar -- bu 'oynaklik hedefleme'")
    print("     degil, 'daha az gumus tut' olur ve hic test edilmemistir.")

    print()
    print("=" * 88)
    print("3) TABAN ORAN VE BASABAS DUVARI")
    print("=" * 88)
    print("  Taban oran = modelin asmasi gereken bedava esik ('hep YUKARI' de).")
    for key, df in panels.items():
        asset = assets_module.get(key)
        closes = df["close"].to_numpy(dtype=float)
        bps = asset.fee_rate * 2 * 10_000
        print(f"\n  {asset.label} (varsayilan gidis-donus {bps:.0f} bp):")
        print(f"    {'ufuk':>6}{'ort |hareket|':>16}{'taban oran':>13}{'basabas':>11}{'fark':>9}")
        for h in HORIZONS:
            move = float(np.mean(np.abs(closes[h:] / closes[:-h] - 1.0)))
            up_rate = float(np.mean(closes[h:] > closes[:-h]))
            be = wall.breakeven(move, bps)
            gap = up_rate - be
            note = "hep-YUKARI yetiyor" if gap >= 0 else f"model {-100 * gap:.1f}p katmali"
            print(f"    {str(h) + 'g':>6}{100 * move:>15.3f}%{100 * up_rate:>12.1f}%"
                  f"{100 * be:>10.1f}%{note:>28}")
        h = 5
        measured_base = float(np.mean(closes[h:] > closes[:-h]))
        print(f"    -> assets.{key.upper()}.base_rate_up (5g) = {measured_base:.3f}  "
              f"(kodda {asset.base_rate_up:.3f})")

    print()
    print("=" * 88)
    print("4) AYNI SURUCULER GUMUSU DE ONCULUYOR MU?")
    print("=" * 88)
    print("  Altinda test yarisinda Bonferroni esigini gecenler: tip, ief, vix.")
    print("  Gumus icin ayri olculmeli -- ayni makro hikaye ayni sekilde islemeyebilir.\n")
    print(f"{'varlik':<10}{'surucu':>10}{'esZAMANLI r':>14}{'ONCU r (test)':>16}{'t':>9}{'gecti mi':>11}")
    for key, df in panels.items():
        gold_ret = df["close"].pct_change()
        changes = drivers.build_changes(df)
        split = len(df) // 2
        next_day = gold_ret.shift(-1).to_numpy(dtype=float)
        for name in ("tip", "ief", "vix"):
            if name not in changes.columns:
                continue
            x = changes[name].to_numpy(dtype=float)
            r_same, _, _ = drivers._corr_t(x, gold_ret.to_numpy(dtype=float))
            r_te, t_te, _ = drivers._corr_t(x[split:], next_day[split:])
            passed = "EVET" if abs(t_te) > 3.29 else "hayir"
            print(f"{key:<10}{name:>10}{r_same:>+14.3f}{r_te:>+16.4f}{t_te:>9.2f}{passed:>11}")

    print()
    print("=" * 88)
    print("5) ALTIN/GUMUS ORANI -- iki varliga birden bakan tek sayi")
    print("=" * 88)
    gold_df, silver_df = panels["gold"], panels["silver"]
    merged = gold_df[["time", "close"]].merge(
        silver_df[["time", "close"]], on="time", suffixes=("_gold", "_silver"))
    gs = merged["close_gold"] / merged["close_silver"]
    print(f"  n={len(gs)}  guncel={gs.iloc[-1]:.1f}  medyan={gs.median():.1f}  "
          f"min={gs.min():.1f}  maks={gs.max():.1f}")
    z = (gs.iloc[-1] - gs.tail(1250).mean()) / gs.tail(1250).std()
    print(f"  son 5 yila gore z-skor: {z:+.2f}")
    print("  (Yuksek oran = gumus altina gore ucuz. Ortalamaya donus hikayesi meshurdur;")
    print("   ama bu tezgahta OLCULMEDI -- inanmadan once xsec benzeri bir test gerekir.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
