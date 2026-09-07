"""The gold/silver ratio: famous story, never measured on this bench.

Both README files carried a standing admission -- "altin/gumus orani
ortalamaya donus OLCULMEDI" -- because the ratio was displayed in the UI and
fed to the ML model as `gs_ratio_z` while no study had ever asked whether it
carries anything. This file removes that admission one way or the other.

The naive version of this question is a trap, for two reasons:

  1. **A full-sample mean is look-ahead.** The ratio traded 31 in 2011 and
     124 in 2020; anyone who "knew" the long-run average in 2011 knew it by
     reading the future. Only a TRAILING mean is tradeable, so every test
     here uses a causal rolling z-score, never a full-sample one.

  2. **Reversion can arrive through either leg, and only one is reachable.**
     log(ratio) change is exactly gold's log return minus silver's, so "the
     ratio reverts" is a statement about a LONG-SHORT spread. This system
     holds no shorts and never will -- it is a paper book of long positions.
     If a high ratio reverts because gold falls, a long-only book cannot
     collect it; the only channel it can collect is silver rising. So the
     spread test and the per-leg tests are separate questions, and the second
     is the one that decides whether any production code changes.

Sections:
  1. What the ratio has actually done (levels, not stories)
  2. Is it mean-reverting? -- AR(1) half-life, split-half stability
  3. Does a trailing z predict the SPREAD? (the long-short question)
  4. Does it predict EACH LEG? (the long-only question)
  5. A long-only rotation portfolio, with a vol-matched control
  6. Does the ML model actually use the gs_ratio_z it is already given?
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
from scipy import stats as scipy_stats  # noqa: E402

import assets as assets_module  # noqa: E402
import edge  # noqa: E402
import ml_model  # noqa: E402
import panel as panel_module  # noqa: E402

TRADING_DAYS = 252
# The lookback indicators.py already uses for gs_ratio_z. Kept identical so a
# result here transfers to the live feature without reinterpretation.
Z_WINDOW = 250
HORIZONS = [1, 5, 20, 60]
TARGETS = ("spread", "gold", "silver")

# Five ways of turning the ratio into a signal. Testing only the production
# one (z250) would leave the honest objection unanswered: maybe the IDEA is
# right and only the FORM is wrong. Reversion and momentum are opposite
# hypotheses about the same series, so both are represented -- a level says
# "it is stretched, expect a snap back", a change says "it is moving, expect
# it to keep moving", and the ratio is not obliged to obey either.
VARIANTS = {
    "z250":   "seviye z, 250g (uretimdeki gs_ratio_z)",
    "z1250":  "seviye z, 1250g (~5 yil, arayuzun gosterdigi)",
    "mom20":  "20 gunluk oran degisimi (momentum, donusun TERSI hipotez)",
    "mom60":  "60 gunluk oran degisimi",
    "pct250": "250g icindeki yuzdelik sirasi (varyansa dayanikli seviye)",
}

# The whole grid is ONE family of tests: 5 forms x 3 targets x 4 horizons.
# Announcing the count before looking is the point -- picking the best cell of
# sixty and quoting its p-value is how a bench manufactures a discovery. At
# this size the two-sided 5% bar sits at |t| > 3.34.
N_TESTS = len(VARIANTS) * len(TARGETS) * len(HORIZONS)
BONFERRONI_T = float(scipy_stats.norm.isf(0.025 / N_TESTS))


def _t_from_r(r: float, n_eff: float) -> float:
    """t for a correlation, on the EFFECTIVE sample size.

    At horizon h consecutive rows share h-1 days of outcome, so the naive n
    overstates independence by roughly h. Dividing first is the difference
    between "significant" and honest: at h=60 it shrinks t by ~7.7x.
    """
    if not np.isfinite(r) or n_eff <= 2 or abs(r) >= 1:
        return 0.0
    return float(r * math.sqrt(n_eff - 2) / math.sqrt(1 - r * r))


def _corr(x: np.ndarray, y: np.ndarray, horizon: int) -> tuple[float, float, int]:
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 50:
        return 0.0, 0.0, int(mask.sum())
    r = float(np.corrcoef(x[mask], y[mask])[0, 1])
    return r, _t_from_r(r, max(mask.sum() / horizon, 1)), int(mask.sum())


def _paired_test(a: pd.DataFrame, b: pd.DataFrame, horizon: int) -> dict:
    """McNemar on two models scored over the identical rows.

    An accuracy difference read off two percentages is not a result -- the
    question is whether it exceeds what re-running on a different sample would
    have moved it anyway. McNemar looks only at the rows where the two models
    DISAGREE, which is the whole information content of an A/B on shared data.

    The overlap correction matters as much here as in _t_from_r: at horizon 5
    consecutive disagreements are largely the same event counted five times,
    so the raw counts are divided by the horizon before the statistic. Without
    that division this test declares almost anything significant.
    """
    merged = a[["time", "proba_up", "label"]].merge(
        b[["time", "proba_up", "label"]], on="time", suffixes=("_a", "_b"))
    right_a = (merged["proba_up_a"] >= 0.5).astype(float) == merged["label_a"]
    right_b = (merged["proba_up_b"] >= 0.5).astype(float) == merged["label_b"]
    only_a = float((right_a & ~right_b).sum()) / horizon
    only_b = float((~right_a & right_b).sum()) / horizon
    n_eff = max(len(merged) / horizon, 1)
    se = math.sqrt(0.25 / n_eff) * math.sqrt(2)  # SE of a paired accuracy gap

    if only_a + only_b < 5:
        return {"p": 1.0, "se": se, "verdict": "yeterli anlasmazlik yok"}
    chi2 = (abs(only_a - only_b) - 1) ** 2 / (only_a + only_b)
    p = float(scipy_stats.chi2.sf(chi2, 1))
    verdict = ("FARK GERCEK -- kolon uzerinde islem yapilabilir" if p < 0.05
               else "fark gurultu icinde; bu kanitla uretim degistirilmez")
    return {"p": p, "se": se, "verdict": verdict}


def load_pair() -> pd.DataFrame:
    """Gold close + silver close on gold's calendar.

    Read from the GOLD panel rather than merging the two panels, because that
    is precisely what indicators.add_macro_columns sees when it builds
    gs_ratio: same alignment, same backward-only fill. A study run on a
    differently-merged frame would be measuring a series the live system does
    not actually have.
    """
    df = panel_module.load("gold")[["time", "close", "silver"]].copy()
    df = df.rename(columns={"close": "gold"})
    df = df.dropna(subset=["gold", "silver"]).reset_index(drop=True)
    df["ratio"] = df["gold"] / df["silver"]
    df["log_ratio"] = np.log(df["ratio"])

    ratio = df["ratio"]
    df["z250"] = (ratio - ratio.rolling(250).mean()) / ratio.rolling(250).std()
    df["z1250"] = (ratio - ratio.rolling(1250).mean()) / ratio.rolling(1250).std()
    df["mom20"] = ratio.pct_change(20)
    df["mom60"] = ratio.pct_change(60)
    # Percentile rank inside the trailing window. Unlike a z-score this does
    # not assume the ratio is normal, and the ratio very much is not -- it
    # spent 2020 at 125 against a 69 median. Centred on zero so its sign means
    # the same thing as the z-scores.
    df["pct250"] = ratio.rolling(250).rank(pct=True) - 0.5
    # The production feature keeps its own name so section 5 and section 8
    # both read the same column the live system builds.
    df["z"] = df["z250"]
    return df


def half_life(log_ratio: pd.Series) -> tuple[float, float]:
    """AR(1) half-life in trading days, plus the mean-reversion coefficient.

    Regress d(log r) on lagged log r. A negative slope is reversion and the
    half-life is -ln2 / ln(1+slope). A slope indistinguishable from zero is a
    random walk -- no reversion at all, whatever the chart looks like.
    """
    y = log_ratio.diff().to_numpy(dtype=float)[1:]
    x = log_ratio.to_numpy(dtype=float)[:-1]
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 100:
        return float("nan"), float("nan")
    slope, _ = np.polyfit(x[mask], y[mask], 1)
    if slope >= 0:
        return float("inf"), float(slope)
    return float(-math.log(2) / math.log(1 + slope)), float(slope)


# --------------------------------------------------------------------------
# 5) Long-only rotation
# --------------------------------------------------------------------------

def rotation_curve(df: pd.DataFrame, threshold: float, vol_match: bool,
                   gold_fee: float, silver_fee: float) -> dict:
    """Hold one metal at a time, chosen by the trailing ratio z.

    High z means gold is expensive against silver, so the reversion trade a
    long-only book CAN take is to own silver. Low z, own gold. In between,
    stay put -- a band rather than a line, so the portfolio does not flip on
    every wobble across zero.

    `vol_match` is the control that stops this being a trick. Silver is 1.86x
    gold's volatility, so ANY rule that spends time in silver takes more risk
    and, in a sample where both metals rose, shows a higher return for that
    reason alone. With vol_match on, the silver leg is scaled by the causal
    volatility ratio so both states carry comparable risk and the comparison
    is about timing rather than about leverage.
    """
    gold_ret = df["gold"].pct_change().to_numpy(dtype=float)
    silver_ret = df["silver"].pct_change().to_numpy(dtype=float)
    z = df["z"].to_numpy(dtype=float)

    # Causal volatility ratio: what was knowable at each point, not the
    # full-sample 1.86 (which is itself a look-ahead number).
    g_vol = df["gold"].pct_change().rolling(250).std().to_numpy(dtype=float)
    s_vol = df["silver"].pct_change().rolling(250).std().to_numpy(dtype=float)

    equity = [1.0]
    holding = "gold"
    trades = 0
    for i in range(1, len(df)):
        prev = holding
        # z[i-1]: the signal must be formed on yesterday's close to be acted
        # on in today's session. Using z[i] would price today's move into the
        # decision that captures it.
        if np.isfinite(z[i - 1]):
            if z[i - 1] > threshold:
                holding = "silver"
            elif z[i - 1] < -threshold:
                holding = "gold"
        if holding == "gold":
            r = gold_ret[i]
        else:
            r = silver_ret[i]
            if vol_match and np.isfinite(g_vol[i - 1]) and np.isfinite(s_vol[i - 1]) and s_vol[i - 1] > 0:
                r = r * min(g_vol[i - 1] / s_vol[i - 1], 1.0)
        if not np.isfinite(r):
            r = 0.0
        cost = 0.0
        if holding != prev:
            trades += 1
            # A rotation is two transactions: exit one metal, enter the other.
            cost = gold_fee + silver_fee
        equity.append(equity[-1] * (1 + r) * (1 - cost))

    return _curve_stats(np.array(equity), trades, df)


def buyhold_curve(df: pd.DataFrame, column: str) -> dict:
    ret = df[column].pct_change().fillna(0.0).to_numpy(dtype=float)
    return _curve_stats(np.cumprod(1 + ret), 1, df)


def blend_curve(df: pd.DataFrame, weight_gold: float = 0.5) -> dict:
    """Daily-rebalanced fixed blend -- the "just own both" null hypothesis any
    rotation rule has to beat before it means anything."""
    g = df["gold"].pct_change().fillna(0.0).to_numpy(dtype=float)
    s = df["silver"].pct_change().fillna(0.0).to_numpy(dtype=float)
    return _curve_stats(np.cumprod(1 + weight_gold * g + (1 - weight_gold) * s), 1, df)


def pair_curve(df: pd.DataFrame, mode: str, rebalance_days: int,
               gold_fee: float, silver_fee: float) -> dict:
    """Hold BOTH metals, rebalanced periodically. No timing whatsoever.

    Sections 3-5 asked whether the ratio's LEVEL says which metal to own, and
    it does not. This asks a different question the ratio study kept walking
    past: whether owning the pair beats owning gold, purely through the two
    series being imperfectly correlated. That is diversification, not
    prediction -- there is nothing to forecast and nothing to be right about,
    which is exactly why it is worth measuring on a bench where the
    forecasting has repeatedly come up empty.

    `invvol` weights each metal by the inverse of its trailing volatility, so
    the two legs contribute comparable risk. Applied to gold and silver that
    lands near 65/35 rather than 50/50, and 50/50 is NOT the neutral choice
    people assume: with silver 1.86x as volatile, an equal-dollar split is
    already about two-thirds silver risk.
    """
    g_ret = df["gold"].pct_change().fillna(0.0).to_numpy(dtype=float)
    s_ret = df["silver"].pct_change().fillna(0.0).to_numpy(dtype=float)
    g_vol = df["gold"].pct_change().rolling(60).std().to_numpy(dtype=float)
    s_vol = df["silver"].pct_change().rolling(60).std().to_numpy(dtype=float)

    def target_gold_weight(i: int) -> float:
        if mode == "fixed50":
            return 0.5
        if np.isfinite(g_vol[i]) and np.isfinite(s_vol[i]) and g_vol[i] > 0 and s_vol[i] > 0:
            inv_g, inv_s = 1.0 / g_vol[i], 1.0 / s_vol[i]
            return inv_g / (inv_g + inv_s)
        return 0.5

    v_gold, v_silver = 0.5, 0.5
    equity = [1.0]
    rebalances = 0
    for i in range(1, len(df)):
        v_gold *= 1 + g_ret[i]
        v_silver *= 1 + s_ret[i]
        total = v_gold + v_silver
        if i % rebalance_days == 0 and total > 0:
            want = target_gold_weight(i - 1) * total
            moved = abs(want - v_gold)
            if moved / total > 0.005:   # skip trivial rebalances
                rebalances += 1
                # Moving `moved` dollars means selling one metal and buying
                # the other: both sides pay.
                cost = moved * (gold_fee + silver_fee)
                total -= cost
                v_gold = target_gold_weight(i - 1) * total
                v_silver = total - v_gold
        equity.append(v_gold + v_silver)
    return _curve_stats(np.array(equity), rebalances, df)


def _curve_stats(equity: np.ndarray, trades: int, df: pd.DataFrame) -> dict:
    years = (df["time"].iloc[-1] - df["time"].iloc[0]).days / 365.25
    daily = np.diff(equity) / equity[:-1]
    peak = np.maximum.accumulate(equity)
    max_dd = float(np.max(1 - equity / peak))
    cagr = float(equity[-1] ** (1 / years) - 1)
    vol = float(np.std(daily) * math.sqrt(TRADING_DAYS))
    return {
        "cagr": cagr,
        "vol": vol,
        "sharpe": cagr / vol if vol > 0 else 0.0,
        "max_dd": max_dd,
        "calmar": cagr / max_dd if max_dd > 0 else 0.0,
        "trades": trades,
        "final": float(equity[-1]),
    }


def main() -> int:
    df = load_pair()
    gold, silver = assets_module.GOLD, assets_module.SILVER
    split = len(df) // 2
    train, test = df.iloc[:split], df.iloc[split:]

    print("=" * 92)
    print("1) ORAN NE YAPMIS -- hikaye degil, seviyeler")
    print("=" * 92)
    r = df["ratio"]
    print(f"  n={len(df)}  {df['time'].iloc[0].date()} -> {df['time'].iloc[-1].date()}")
    print(f"  guncel={r.iloc[-1]:.1f}  medyan={r.median():.1f}  "
          f"min={r.min():.1f} ({df['time'].iloc[int(r.idxmin())].date()})  "
          f"maks={r.max():.1f} ({df['time'].iloc[int(r.idxmax())].date()})")
    print(f"  guncel z (kayan {Z_WINDOW}g): {df['z'].iloc[-1]:+.2f}")
    print(f"\n  Ilk yarinin medyani {train['ratio'].median():.1f}, ikinci yarininki "
          f"{test['ratio'].median():.1f}.")
    print("  Bu tek basina bir uyaridir: 'ortalama' sabit bir sayi degil, kaymis bir")
    print("  seviye. Tum-orneklem ortalamasina donusu test etmek gelecegi okumaktir;")
    print(f"  asagidaki her test kayan {Z_WINDOW} gunluk z kullaniyor.")

    print()
    print("=" * 92)
    print("2) ORAN GERCEKTEN ORTALAMAYA DONUYOR MU? -- AR(1) yari-omru")
    print("=" * 92)
    print(f"{'donem':<28}{'egim':>12}{'yari-omur (gun)':>20}{'yorum':>30}")
    for label, sub in (("tamami", df), ("ilk yari (egitim)", train), ("ikinci yari (test)", test)):
        hl, slope = half_life(sub["log_ratio"])
        if not np.isfinite(hl):
            note, hl_txt = "donus YOK (rastgele yuruyus)", "sonsuz"
        else:
            note = "cok yavas" if hl > TRADING_DAYS else "kullanilabilir hiz"
            hl_txt = f"{hl:.0f}"
        print(f"{label:<28}{slope:>+12.5f}{hl_txt:>20}{note:>30}")
    print("\n  Yari-omur bir yildan uzunsa 5 gunluk bir ufuk icin pratikte sabittir:")
    print("  dogru olsa bile bizim karar penceremizde hicbir sey soylemez.")

    print()
    print("=" * 92)
    print("3) z SPREAD'I ONGORUYOR MU? -- uzun/kisa sorusu")
    print("=" * 92)
    print("  log(oran) degisimi = altin log getirisi - gumus log getirisi.")
    print("  Yani bu tam olarak 'altin al / gumus sat' spread'inin testidir.")
    print(f"  Beklenen isaret NEGATIF (yuksek z -> oran duser).  Bonferroni esigi "
          f"|t|>{BONFERRONI_T:.2f} ({N_TESTS} test)\n")
    print(f"{'ufuk':>7}{'r (egitim)':>14}{'r (test)':>12}{'t (test, ortusme dzt)':>25}{'gecti mi':>12}")
    spread_hits = []
    for h in HORIZONS:
        fwd = (df["log_ratio"].shift(-h) - df["log_ratio"]).to_numpy(dtype=float)
        z = df["z"].to_numpy(dtype=float)
        r_tr, _, _ = _corr(z[:split], fwd[:split], h)
        r_te, t_te, _ = _corr(z[split:], fwd[split:], h)
        passed = abs(t_te) > BONFERRONI_T and r_te < 0
        spread_hits.append((h, r_te, t_te, passed))
        print(f"{str(h) + 'g':>7}{r_tr:>+14.4f}{r_te:>+12.4f}{t_te:>25.2f}"
              f"{('EVET' if passed else 'hayir'):>12}")

    print()
    print("=" * 92)
    print("4) HANGI BACAKTAN GELIYOR? -- sadece-uzun sorusu, karari veren test")
    print("=" * 92)
    print("  Spread donse bile, donus altinin DUSMESIYLE geliyorsa sadece-uzun bir")
    print("  defter bunu toplayamaz. Toplayabilecegi tek kanal gumusun YUKSELMESI.")
    print("  Yuksek z icin beklenen: altin bacaginda negatif, gumus bacaginda POZITIF.\n")
    print(f"{'ufuk':>7}{'bacak':>10}{'r (egitim)':>14}{'r (test)':>12}"
          f"{'t (test)':>12}{'gecti mi':>12}")
    leg_hits = []
    for h in HORIZONS:
        z = df["z"].to_numpy(dtype=float)
        for leg in ("gold", "silver"):
            fwd = (df[leg].shift(-h) / df[leg] - 1.0).to_numpy(dtype=float)
            r_tr, _, _ = _corr(z[:split], fwd[:split], h)
            r_te, t_te, _ = _corr(z[split:], fwd[split:], h)
            passed = abs(t_te) > BONFERRONI_T
            leg_hits.append((h, leg, r_te, t_te, passed))
            print(f"{str(h) + 'g':>7}{leg:>10}{r_tr:>+14.4f}{r_te:>+12.4f}"
                  f"{t_te:>12.2f}{('EVET' if passed else 'hayir'):>12}")

    print()
    print("=" * 92)
    print("4b) FORM MU YANLIS? -- oranin bes ayri hali, ayni izgarada")
    print("=" * 92)
    print("  Yukaridaki iki bolum uretimdeki hali (z250) test etti. Durust itiraz")
    print("  su: belki FIKIR dogru, sadece FORM yanlis. Bes form birden taraniyor;")
    print("  ucu seviye (donus hipotezi), ikisi degisim (momentum -- tam tersi).")
    print(f"  Butun izgara TEK bir aile: {len(VARIANTS)} form x {len(TARGETS)} hedef x "
          f"{len(HORIZONS)} ufuk = {N_TESTS} test, esik |t|>{BONFERRONI_T:.2f}\n")
    for name, description in VARIANTS.items():
        print(f"  {name:<8}{description}")
    print()
    header = f"{'form':<9}{'hedef':>8}" + "".join(f"{str(h) + 'g':>16}" for h in HORIZONS)
    print(header)
    print("  " + "-" * (len(header) - 2))
    grid_hits = []
    for name in VARIANTS:
        x = df[name].to_numpy(dtype=float)
        for target in TARGETS:
            if target == "spread":
                fwd_of = lambda h: (df["log_ratio"].shift(-h) - df["log_ratio"]).to_numpy(dtype=float)
            else:
                fwd_of = lambda h, col=target: (df[col].shift(-h) / df[col] - 1.0).to_numpy(dtype=float)
            cells = []
            for h in HORIZONS:
                fwd = fwd_of(h)
                r_te, t_te, _ = _corr(x[split:], fwd[split:], h)
                # Sign agreement between halves is a second, harder filter: a
                # correlation that flips sign between the two halves is not a
                # relationship, it is a coincidence with a good t-statistic.
                r_tr, _, _ = _corr(x[:split], fwd[:split], h)
                stable = np.sign(r_tr) == np.sign(r_te)
                passed = abs(t_te) > BONFERRONI_T and stable
                if passed:
                    grid_hits.append((name, target, h, r_te, t_te))
                mark = "*" if passed else (" " if stable else "~")
                cells.append(f"{r_te:>+9.4f}/{t_te:>5.2f}{mark}")
            print(f"{name:<9}{target:>8}" + "".join(f"{c:>16}" for c in cells))
    print("\n  hucre = r (test yarisi) / t (ortusme duzeltmeli).  * = esigi gecti,")
    print("  ~ = iki yari arasinda ISARET DEGISTIRDI (iliski degil, tesaduf).")
    print(f"  Gecen hucre sayisi: {len(grid_hits)} / {N_TESTS}")

    print()
    print("=" * 92)
    print("5) SADECE-UZUN ROTASYON -- z yuksekse gumus tut, dusukse altin")
    print("=" * 92)
    print(f"  Maliyet: her rotasyon iki islem ({100 * gold.fee_rate:.2f}% + "
          f"{100 * silver.fee_rate:.2f}% = {100 * (gold.fee_rate + silver.fee_rate):.2f}%)")
    print("  'oynaklik esitli' surum kontroldur: gumus 1.86 kat oynak oldugu icin")
    print("  gumuste gecirilen her gun otomatik olarak daha fazla risk demektir ve")
    print("  yukselen bir orneklemde bu tek basina getiriyi sisirir.\n")

    print(f"{'strateji':<34}{'YBG':>9}{'oynaklik':>11}{'Sharpe':>9}"
          f"{'maks dusus':>13}{'Calmar':>9}{'islem':>8}")
    for name, s in (("hep altin", buyhold_curve(df, "gold")),
                    ("hep gumus", buyhold_curve(df, "silver")),
                    ("50/50 harman", blend_curve(df, 0.5))):
        print(f"{name:<34}{100 * s['cagr']:>8.1f}%{100 * s['vol']:>10.1f}%"
              f"{s['sharpe']:>9.2f}{100 * s['max_dd']:>12.1f}%{s['calmar']:>9.2f}{s['trades']:>8}")
    print("  " + "-" * 88)
    for vol_match in (False, True):
        tag = "oynaklik esitli" if vol_match else "ham"
        for thr in (0.5, 1.0, 1.5):
            s = rotation_curve(df, thr, vol_match, gold.fee_rate, silver.fee_rate)
            name = f"rotasyon z>{thr:.1f} ({tag})"
            print(f"{name:<34}{100 * s['cagr']:>8.1f}%{100 * s['vol']:>10.1f}%"
                  f"{s['sharpe']:>9.2f}{100 * s['max_dd']:>12.1f}%{s['calmar']:>9.2f}{s['trades']:>8}")
    print("\n  Esik izgarasi bir SONUC DEGIL, duyarlilik kontroludur. Uc esigin en")
    print("  iyisini secip raporlamak tam olarak ucten en iyisini secmektir.")

    print(f"\n  Sadece test yarisi ({test['time'].iloc[0].date()} sonrasi):")
    print(f"{'strateji':<34}{'YBG':>9}{'Sharpe':>9}{'maks dusus':>13}{'Calmar':>9}")
    for name, s in (("hep altin", buyhold_curve(test, "gold")),
                    ("hep gumus", buyhold_curve(test, "silver")),
                    ("50/50 harman", blend_curve(test, 0.5))):
        print(f"{name:<34}{100 * s['cagr']:>8.1f}%{s['sharpe']:>9.2f}"
              f"{100 * s['max_dd']:>12.1f}%{s['calmar']:>9.2f}")
    for vol_match in (False, True):
        tag = "oynaklik esitli" if vol_match else "ham"
        s = rotation_curve(test, 1.0, vol_match, gold.fee_rate, silver.fee_rate)
        label = f"rotasyon z>1.0 ({tag})"
        print(f"{label:<34}{100 * s['cagr']:>8.1f}%{s['sharpe']:>9.2f}"
              f"{100 * s['max_dd']:>12.1f}%{s['calmar']:>9.2f}")

    print()
    print("=" * 92)
    print("5b) ZAMANLAMA DEGIL, BIRLIKTE TUTMA -- ciftin kendisi ne veriyor?")
    print("=" * 92)
    print("  Bolum 3-5 oranin SEVIYESININ hangi metali tutacagimizi soyleyip")
    print("  soylemedigini sordu: soylemiyor. Bu bolum baska bir soru soruyor --")
    print("  ikisini BIRDEN tutmak, sadece altin tutmayi geciyor mu? Burada tahmin")
    print("  edilecek bir sey yok, dolayisiyla yanilacak bir sey de yok.")
    print("  'ters-oynaklik' agirliklandirmasi iki bacaga esit RISK verir; 50/50")
    print("  sanildigi gibi tarafsiz degildir -- gumus 1.86 kat oynak oldugu icin")
    print("  esit dolar bolusumu zaten ucte iki gumus riskidir.\n")
    print(f"{'portfoy':<34}{'YBG':>9}{'oynaklik':>11}{'Sharpe':>9}"
          f"{'maks dusus':>13}{'Calmar':>9}{'denge':>8}")
    for label, sub in (("TAMAMI", df), ("TEST YARISI", test)):
        print(f"  --- {label} ---")
        rows = [
            ("hep altin", buyhold_curve(sub, "gold")),
            ("hep gumus", buyhold_curve(sub, "silver")),
            ("50/50, aylik denge", pair_curve(sub, "fixed50", 21, gold.fee_rate, silver.fee_rate)),
            ("ters-oynaklik, aylik denge", pair_curve(sub, "invvol", 21, gold.fee_rate, silver.fee_rate)),
        ]
        for name, s in rows:
            print(f"{name:<34}{100 * s['cagr']:>8.1f}%{100 * s['vol']:>10.1f}%"
                  f"{s['sharpe']:>9.2f}{100 * s['max_dd']:>12.1f}%"
                  f"{s['calmar']:>9.2f}{s['trades']:>8}")

    print()
    print("=" * 92)
    print("6) MODEL ZATEN VERILEN gs_ratio_z'YI KULLANIYOR MU?")
    print("=" * 92)
    print("  gs_ratio_z ml_model.FEATURE_COLUMNS icinde. Orada olmasi kullanildigi")
    print("  anlamina gelmez -- permutasyon onemi bunu olcer: kolonu karistir,")
    print("  dogruluk ne kadar duser?\n")
    for key in ("gold", "silver"):
        asset = assets_module.get(key)
        frame = ml_model.build_feature_frame(
            panel_module.load(key), drivers=asset.leading_drivers)
        features = ml_model.available_features(frame)
        cut = int(len(frame) * 0.7)
        tr, te = frame.iloc[:cut], frame.iloc[cut:]
        model = ml_model.build_estimator()
        model.fit(tr[features], tr["label_up"])
        base_acc = float((model.predict(te[features]) == te["label_up"]).mean())

        rng = np.random.default_rng(0)
        drops = {}
        for col in features:
            losses = []
            for _ in range(5):
                shuffled = te.copy()
                shuffled[col] = rng.permutation(shuffled[col].to_numpy())
                losses.append(base_acc - float(
                    (model.predict(shuffled[features]) == shuffled["label_up"]).mean()))
            drops[col] = float(np.mean(losses))
        ranked = sorted(drops.items(), key=lambda kv: -kv[1])
        rank = [c for c, _ in ranked].index("gs_ratio_z") + 1 if "gs_ratio_z" in drops else -1
        print(f"  {asset.label}: temel dogruluk {100 * base_acc:.1f}%  "
              f"(gs_ratio_z sirasi {rank}/{len(features)}, "
              f"dusurdugu dogruluk {100 * drops.get('gs_ratio_z', 0):+.2f}p)")
        print("    en onemli 5 : " + ", ".join(f"{c} {100 * v:+.2f}p" for c, v in ranked[:5]))
        print("    en onemsiz 3: " + ", ".join(f"{c} {100 * v:+.2f}p" for c, v in ranked[-3:]))

    print()
    print("=" * 92)
    print("7) KARAR TESTI -- gs_ratio_z olmadan model daha mi iyi? (yuruyen-ileri)")
    print("=" * 92)
    print("  Bolum 6'daki permutasyon tek bir bolmede 5 karistirma; uretim kodunu")
    print("  degistirmek icin zayif kanit. Burasi asil test: ayni yeniden-egitim")
    print("  takvimi, ayni satirlar, tek fark kolonun var/yok olmasi.")
    print("  Karsilastirma AYNI satirlarda yapiliyor -- gs_ratio_z 250 gunluk isinma")
    print("  ister, cikarilinca dropna daha COK satir birakir ve iki kosu farkli")
    print("  donemleri puanlardi.\n")
    print(f"{'varlik':<9}{'ozellik seti':<22}{'n':>7}{'dogruluk':>11}"
          f"{'taban':>9}{'fark':>9}{'karar':>16}")
    ab_results = {}
    for key in ("gold", "silver"):
        asset = assets_module.get(key)
        frame = ml_model.build_feature_frame(
            panel_module.load(key), drivers=asset.leading_drivers)
        full = ml_model.available_features(frame)
        without = [c for c in full if c != "gs_ratio_z"]

        runs = {}
        for tag, feats in (("mevcut (gs_ratio_z var)", full), ("gs_ratio_z CIKARILDI", without)):
            runs[tag] = edge.walk_forward(frame, ml_model.HORIZON_DAYS, features=feats)

        a, b = runs["mevcut (gs_ratio_z var)"], runs["gs_ratio_z CIKARILDI"]
        shared = set(a["time"]) & set(b["time"])
        mcnemar = _paired_test(a[a["time"].isin(shared)], b[b["time"].isin(shared)],
                               ml_model.HORIZON_DAYS)
        for tag, run in runs.items():
            sub = run[run["time"].isin(shared)]
            acc = float(((sub["proba_up"] >= 0.5).astype(float) == sub["label"]).mean())
            base = float(sub["label"].mean())
            gap = acc - base
            verdict = "tabani geciyor" if gap > 0 else "tabanin altinda"
            ab_results[(key, tag)] = (acc, base, len(sub))
            print(f"{asset.label:<9}{tag:<22}{len(sub):>7}{100 * acc:>10.2f}%"
                  f"{100 * base:>8.1f}%{100 * gap:>+8.2f}p{verdict:>16}")
        delta = ab_results[(key, "gs_ratio_z CIKARILDI")][0] - ab_results[(key, "mevcut (gs_ratio_z var)")][0]
        print(f"{'':<9}{'-> cikarmanin etkisi':<22}{'':>7}{100 * delta:>+10.2f}p"
              f"   (esli test p={mcnemar['p']:.3f}, "
              f"gurultu bandi +-{100 * mcnemar['se']:.2f}p)")
        print(f"{'':<9}{'':<22}{'':>7}   {mcnemar['verdict']}\n")

    print()
    print("=" * 92)
    print("KARAR")
    print("=" * 92)
    spread_ok = [h for h, _, _, ok in spread_hits if ok]
    leg_ok = [(h, leg) for h, leg, _, _, ok in leg_hits if ok]
    print(f"  Spread (uzun/kisa) testini gecen ufuklar : {spread_ok if spread_ok else 'HICBIRI'}")
    print(f"  Bacak (sadece-uzun) testini gecenler     : {leg_ok if leg_ok else 'HICBIRI'}")
    print(f"  {N_TESTS} hucrelik form taramasini gecen    : "
          f"{[f'{n}/{t}/{h}g' for n, t, h, _, _ in grid_hits] if grid_hits else 'HICBIRI'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
