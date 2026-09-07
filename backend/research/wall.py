"""THE first measurement: how accurate does a directional call on gold have
to be before it pays for its own trading costs?

XRP-Guess learned this the expensive way. At a 15-minute horizon XRP moved
0.219% on average against a 0.20% round-trip fee, so break-even sat at
**95.6% direction accuracy** -- an arithmetic wall that no amount of model
work could climb. Every strategy in that project was fighting a fight it had
already lost before the first line of model code.

    break-even accuracy = 0.5 + (one-way cost / mean |move|)

Derivation: over N trades you win `p·N` times and lose `(1-p)·N` times, each
by the average move `m`, and you pay the round-trip cost `c` on every one.
Profit is zero when `p·m - (1-p)·m = c`, i.e. `p = 0.5 + c/(2m)`, and `c/2`
is the one-way cost. Nothing about the asset or the model enters it.

So before building anything for gold, measure the same wall. This file does
only that, prints it, and stops. No model, no signal, no fitting -- the whole
point is that the answer does not depend on any of those.

Costs are printed as a ladder rather than a single number, because "gold" is
not one instrument. A COMEX futures round trip and a Turkish bank's gram-gold
spread differ by two orders of magnitude, and the wall moves with them.
"""
from __future__ import annotations

import os
import statistics
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import panel as panel_module  # noqa: E402

# Round-trip cost in basis points (1 bp = 0.01%). Each is a real instrument a
# person could actually use to express a view on gold, not a hypothetical.
COST_SCENARIOS_BPS = {
    "COMEX vadeli (GC)":        2,    # $0.10 tick on ~$4400 + ~$4/contract on $440k notional
    "ETF / CFD (GLD, XAUUSD)":  10,   # 1-2 bp spread each way + commission, retail broker
    "Perakende spread'li":      40,   # wider retail CFD / tokenized gold (PAXG ~0.2% each way)
    "Banka gram altin (TR)":    150,  # bank buy/sell spread on physical gram gold
}
# For reference only, so the gold numbers have something to sit against.
# 20 bp, not 200: XRP-Guess's FEE_RATE is 0.001 = 0.10% per side, so the
# round trip is 0.20% = 20 bp. Reproducing its published 95.6% break-even is
# the check that this constant is in the right units.
XRP_15M_ROUNDTRIP_BPS = 20
XRP_15M_MEAN_MOVE_PCT = 0.219

HORIZONS = [1, 2, 3, 5, 10, 20, 60]


def measure(closes: np.ndarray, horizon: int) -> dict:
    """Absolute percentage move over `horizon` trading days, and its spread.

    Uses the mean, not the median, because the break-even identity above is
    an expectation: the money you make on a correct call is the *average*
    move, and gold's distribution has fat enough tails that the median would
    understate it. The median is printed alongside precisely so the gap is
    visible rather than assumed away.
    """
    future = closes[horizon:]
    present = closes[:-horizon]
    moves = np.abs(future / present - 1.0)
    return {
        "n": len(moves),
        "mean": float(np.mean(moves)),
        "median": float(np.median(moves)),
        "p90": float(np.percentile(moves, 90)),
        # Annualised-ish: how much of a year one horizon covers, ~252 sessions.
        "per_year": 252.0 / horizon,
    }


def breakeven(mean_move: float, roundtrip_bps: float) -> float:
    one_way = (roundtrip_bps / 10_000.0) / 2.0
    return 0.5 + one_way / mean_move


def main() -> int:
    df = panel_module.load()
    closes = df["close"].to_numpy(dtype=float)
    print(f"Panel: {len(df)} gun  ({df['time'].iloc[0].date()} -> {df['time'].iloc[-1].date()})\n")

    print("=" * 78)
    print("1) ALTININ HAREKET BUYUKLUGU (ufka gore)")
    print("=" * 78)
    print(f"{'ufuk':>6} {'gozlem':>8} {'ort |hareket|':>15} {'medyan':>10} {'p90':>10} {'yil/tur':>9}")
    stats = {}
    for h in HORIZONS:
        s = measure(closes, h)
        stats[h] = s
        label = f"{h}g"
        print(f"{label:>6} {s['n']:>8} {100 * s['mean']:>14.3f}% {100 * s['median']:>9.3f}% "
              f"{100 * s['p90']:>9.3f}% {s['per_year']:>9.1f}")

    print()
    print("=" * 78)
    print("2) BASABAS YON ISABETI  =  %50 + (tek yon maliyet / ort |hareket|)")
    print("=" * 78)
    header = f"{'ufuk':>6}" + "".join(f"{name.split(' (')[0][:16]:>18}" for name in COST_SCENARIOS_BPS)
    print(header)
    print(f"{'':>6}" + "".join(f"{str(bps) + ' bp gidis-donus':>18}" for bps in COST_SCENARIOS_BPS.values()))
    print("-" * 78)
    for h in HORIZONS:
        row = f"{str(h) + 'g':>6}"
        for bps in COST_SCENARIOS_BPS.values():
            be = breakeven(stats[h]["mean"], bps)
            row += f"{'%' + format(100 * be, '.1f'):>18}"
        print(row)

    print()
    print("=" * 78)
    print("3) XRP-Guess ILE KARSILASTIRMA")
    print("=" * 78)
    xrp_be = breakeven(XRP_15M_MEAN_MOVE_PCT / 100.0, XRP_15M_ROUNDTRIP_BPS)
    print(f"  XRP, 15 dakika, 200 bp gidis-donus:")
    print(f"     ort |hareket| %{XRP_15M_MEAN_MOVE_PCT:.3f}  ->  basabas %{100 * xrp_be:.1f}")
    print(f"     (bu duvar asilamadi; olculen isabet %50,0)\n")

    h, bps = 1, COST_SCENARIOS_BPS["ETF / CFD (GLD, XAUUSD)"]
    gold_be = breakeven(stats[h]["mean"], bps)
    print(f"  ALTIN, 1 gun, {bps} bp gidis-donus (ETF/CFD):")
    print(f"     ort |hareket| %{100 * stats[h]['mean']:.3f}  ->  basabas %{100 * gold_be:.1f}")
    print(f"     gereken avantaj: yazi-turadan {100 * (gold_be - 0.5):+.1f} puan "
          f"(XRP'de {100 * (xrp_be - 0.5):+.1f} puandi)")
    ratio = (xrp_be - 0.5) / (gold_be - 0.5)
    move_ratio = stats[h]["mean"] / (XRP_15M_MEAN_MOVE_PCT / 100.0)
    cost_ratio = XRP_15M_ROUNDTRIP_BPS / bps
    print(f"\n  >>> Altinin duvari XRP'ninkinden {ratio:.1f}x DAHA ALCAK.")
    print(f"      Sebep model degil aritmetik: hareket {move_ratio:.1f}x buyuk,")
    print(f"      maliyet {cost_ratio:.1f}x ucuz -> {move_ratio:.1f} x {cost_ratio:.1f} = {ratio:.1f}x.")
    print("      Ayni modeli daha iyi yapmadik; oynanan oyunu degistirdik.")

    print()
    print("=" * 78)
    print("4) HAREKETIN MALIYETE ORANI (yuksek = daha yasanabilir)")
    print("=" * 78)
    print("  Ayni sayinin tersten okunusu: bir isaretin ne kadar 'yeri' var.")
    for h in HORIZONS:
        ratio_etf = stats[h]["mean"] / (COST_SCENARIOS_BPS["ETF / CFD (GLD, XAUUSD)"] / 10_000.0)
        print(f"    {h:>3}g: hareket maliyetin {ratio_etf:>6.1f} kati")
    xrp_ratio = (XRP_15M_MEAN_MOVE_PCT / 100.0) / (XRP_15M_ROUNDTRIP_BPS / 10_000.0)
    print(f"    XRP 15dk: hareket maliyetin {xrp_ratio:>6.1f} kati  <-- projenin oldugu yer")

    print()
    print("=" * 78)
    print("5) YON DAGILIMI (naif 'hep YUKARI' ne yapardi)")
    print("=" * 78)
    print("  Altin uzun vadede yukseldigi icin 'hep YUKARI' demek bedava bir")
    print("  isabet tabani verir. Bir modelin asmasi gereken esik %50 degil BU.")
    etf_bps = COST_SCENARIOS_BPS["ETF / CFD (GLD, XAUUSD)"]
    for h in HORIZONS:
        future, present = closes[h:], closes[:-h]
        up_rate = float(np.mean(future > present))
        be = breakeven(stats[h]["mean"], etf_bps)
        gap = 100 * (be - up_rate)
        verdict = "hep-YUKARI zaten yetiyor" if gap <= 0 else f"model {gap:+.1f} puan daha katmali"
        print(f"    {h:>3}g: %{100 * up_rate:.1f} yukari  |  basabas %{100 * be:.1f}  ->  {verdict}")

    print()
    print("=" * 78)
    print("6) ASIL RAKIP: AL-VE-TUT")
    print("=" * 78)
    total_years = (df["time"].iloc[-1] - df["time"].iloc[0]).days / 365.25
    total_return = closes[-1] / closes[0] - 1
    cagr = (1 + total_return) ** (1 / total_years) - 1
    daily_ret = np.diff(closes) / closes[:-1]
    ann_vol = float(np.std(daily_ret)) * np.sqrt(252)
    # Max drawdown of simply holding.
    peak = np.maximum.accumulate(closes)
    max_dd = float(np.max(1 - closes / peak))
    print(f"  Ayni {total_years:.1f} yilda sadece TUTMAK:")
    print(f"     toplam getiri  %{100 * total_return:+.0f}   (yillik bilesik %{100 * cagr:+.1f})")
    print(f"     yillik oynaklik %{100 * ann_vol:.1f}   ->  Sharpe ~{cagr / ann_vol:.2f} (faizsiz)")
    print(f"     en buyuk dusus  %{100 * max_dd:.1f}")
    print()
    print("  Bu, sistemin gercek rakibi. XRP-Guess'te her strateji al-ve-tut'un")
    print("  altinda kaldi ve proje bunu durustce yazdi. Buradaki hedef 'yon")
    print("  tahmin etmek' degil: ya al-ve-tut'u RISKE GORE gecmek (ayni getiri,")
    print("  daha az dusus), ya da hicbir sey yapmamak. %50'yi gecmek yetmez.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
