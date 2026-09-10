"""The binding constraint is observations, not features. Can pooling relax it?

research/ablation.py is the most-quoted and least-acted-on result in this
project. It tested four different feature groups against the production set,
could not tell any of them apart, and concluded: the answer is not more
features but **more independent observations**. It even printed the number --
the smallest IC this sample could distinguish from zero is 0.086, against a
measured 0.055. The study can say "not bigger than 0.086". It cannot say
"zero".

Every hypothesis since then, GVZ and GDX included, has been on the FEATURE
side. Nobody has touched the constraint itself. This file does.

The arithmetic, measured rather than assumed: gold yields 5706 trainable rows
and silver 5707. At a five-day horizon consecutive rows overlap, so the
effective independent count is about 1141 per asset. Pooled, ~2282. The
detection floor falls with the square root of that, 0.086 -> ~0.061 -- still
above the measured 0.055, but the same order of magnitude rather than a
different one, and four assets would put it at ~0.043, BELOW what is measured.

WHY POOLING IS NOT FREE, AND WHAT HAD TO BE MEASURED FIRST
-----------------------------------------------------------
A pooled tree splits on a threshold, so a threshold has to mean the same thing
in both assets. Measured (p90 |value|, silver over gold, on the two panels):

    rsi14, bb_pct, donchian_pct, vol_ratio          0.98 - 1.02   fine
    every macro column (tip, vix, dxy, spx, ...)    1.00          identical
    ema9_21, px_sma200, px_ema50                    1.74 - 1.79   NOT fine
    return_1d / 5d / 20d / 60d                      1.81 - 1.84   NOT fine
    vol_20d                                         1.93          NOT fine
    counterpart_chg                                 0.55          NOT fine
    macd_hist                                       0.03          NOT fine

Ten of twenty-seven columns disagree, and the interesting part is that they
disagree by ONE number, about 1.8 -- which is assets.py's own measured "silver
realises 1.86x gold's volatility". macd_hist is the outlier at 0.03 because it
is in raw price units and gold trades near $4400 against silver's $66. Today
that is harmless, since each metal has its own model and never sees the
other's numbers. In a pooled model it is fatal: the tree would spend its
capacity discovering which metal a row came from.

So the pooled feature set expresses every price-derived column in units of
that asset's OWN trailing volatility. **This does not break assets.py's "no
shared constant" rule, it applies it.** That rule forbids copying gold's
numbers onto silver; dividing each asset by its own measured volatility is the
opposite operation, and it is the only thing that makes a shared threshold
honest.

The normaliser is vol_60d -- already computed by indicators.py, the same
window trading.VOL_LOOKBACK_DAYS uses, and trailing rather than full-sample. A
full-sample p90 would have been simpler and would have leaked the future into
every early row.

THE ASSET IDENTITY IS DELIBERATELY NOT A FEATURE
-------------------------------------------------
Adding a "which metal is this" column is the obvious move and it is wrong. The
first thing the tree would learn from it is "if gold, say UP more often" --
which is the base rate, which ablation.py already established is the only
learnable thing here. That would smuggle the known result back inside the
pooled model and let it masquerade as pooling working. Separation has to come
from the normalisation or not at all.

THREE ARMS, AND THE MIDDLE ONE IS NOT OPTIONAL
-----------------------------------------------
    A   production features, target asset only        (today's system)
    B   normalised features, target asset only
    C   normalised features, target + the other metal

Without B, a C-versus-A difference confounds "pooling helped" with
"normalising helped" and there is no way to tell which. The three questions
are asked separately: B vs A (does normalising cost anything), C vs B (does
pooling add anything -- THE question), C vs A (does the package beat what
ships). Every comparison is paired on identical rows through
ablation.paired_ic_test, and every one prints the detection floor beside it,
because this file's entire claim is about that floor moving.

Both metals are run as target. A result that appears on one and not the other
is the same category as gs_ratio_z's contradiction (CLAUDE.md) and is not
adopted.
"""
from __future__ import annotations

import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import ablation  # noqa: E402
import assets as assets_module  # noqa: E402
import edge  # noqa: E402
import ml_model  # noqa: E402
import panel as panel_module  # noqa: E402
from indicators import build_features  # noqa: E402

HORIZON = ml_model.HORIZON_DAYS
BAR_T = 2.807
VOL_REGIME_WINDOW = 252   # one year, for "is this asset agitated FOR ITSELF"

# Columns measured to already mean the same thing in both panels (ratio
# 0.98-1.02), so they pass through untouched.
SCALE_FREE = ("rsi14", "bb_pct", "donchian_pct", "vol_ratio")

# Columns that are already fractions and only need dividing by the asset's own
# volatility to become comparable.
VOL_NORMALISED = ("ema9_21", "px_sma200", "px_ema50",
                  "return_1d", "return_5d", "return_20d", "return_60d")


def driver_union() -> tuple[str, ...]:
    """Every metal's leading drivers, merged.

    A pooled model needs ONE feature vector, and the metals do not agree on
    their driver sets: `ief` clears the bar for gold (t=+3.92) and misses it
    for silver (t=+2.56), so silver's production frame has no `ief_chg` at all.

    Taking the union is legitimate here and would not be in macro_signal.
    assets.py's warning is about a WEIGHTED VOTE -- carrying a driver that does
    not lead spends weight on noise. A tree feature is not a weighted vote; it
    is a column the model may ignore, and indicators.CONTEXT_DRIVERS already
    carries dxy/us10y/spx on exactly that reasoning ("weak on their own, useful
    as split conditions"). It is also the same macro series in both panels --
    measured p90 ratio 1.00 -- so this is not one asset's constant being copied
    onto the other, which is the thing assets.py actually forbids.
    """
    drivers: tuple[str, ...] = ()
    for a in assets_module.ASSETS.values():
        drivers += tuple(d for d in a.leading_drivers if d not in drivers)
    return drivers


def normalised_frame(asset, counterpart_vol: pd.Series | None = None) -> pd.DataFrame:
    """The asset's feature frame with every scale-dependent column rebased.

    Every transform here divides by a TRAILING quantity, so nothing a row sees
    depends on anything that happened after it.
    """
    raw = panel_module.load(asset.key).reset_index(drop=True)
    df = build_features(raw, drivers=driver_union())
    vol = df["vol_60d"].replace(0.0, np.nan)

    out = df.copy()
    for col in VOL_NORMALISED:
        out[f"n_{col}"] = df[col] / vol
    # macd_hist is in price units, so it needs the extra step of becoming a
    # fraction of price before it can become a multiple of volatility. This is
    # the same quantity assets.PriceScales.macd already exists to tame on the
    # indicators.py scoring side -- see the table above indicators.BOND_SCALE.
    out["n_macd_hist"] = df["macd_hist"] / df["close"] / vol
    # vol_20d/vol_60d is exactly vol_ratio, which is already a feature, so the
    # level of volatility is expressed against the asset's own YEAR instead --
    # a different question ("agitated for itself") than vol_ratio's
    # ("agitated versus last quarter").
    out["n_vol_regime"] = vol / vol.rolling(VOL_REGIME_WINDOW).mean()
    # The counterpart's return divided by the COUNTERPART's volatility. Under
    # the production columns this is the one term that points the other way
    # (ratio 0.55) precisely because it is the other metal's move.
    out["n_counterpart_chg"] = (df["counterpart_chg"] / counterpart_vol
                                if counterpart_vol is not None else np.nan)
    return out


def pooled_features(df: pd.DataFrame) -> list[str]:
    """The normalised feature list, in the same spirit as available_features."""
    macro = [c for c in ml_model.FEATURE_COLUMNS
             if c in df.columns and c.endswith(("_chg", "_chg5", "_z"))
             and c != "counterpart_chg"]
    candidates = (list(SCALE_FREE)
                  + [f"n_{c}" for c in VOL_NORMALISED]
                  + ["n_macd_hist", "n_vol_regime", "n_counterpart_chg"]
                  + macro)
    return [c for c in candidates if c in df.columns]


def run_arm(target: pd.DataFrame, features: list[str], forward: pd.DataFrame,
            extra: list[pd.DataFrame] | None = None,
            factory=None) -> dict:
    run = edge.walk_forward(target, HORIZON, features=features,
                            extra_training_frames=extra,
                            estimator_factory=factory)
    return ablation.score(run, forward, HORIZON)


def roomier_estimator():
    """build_estimator with one more level of depth.

    NOT a search -- a single pre-registered diagnostic, reported whatever it
    says. research/hyperparams.py chose max_depth=3 by grid search on GOLD
    ALONE, so if the pooled arm underperforms there are two possible reasons
    and they call for opposite conclusions: pooling genuinely adds nothing, or
    the pooled model was handed twice the data and the capacity of a model
    tuned for half of it. One extra configuration separates them. Running a
    full grid here would be a search on the same rows the headline result is
    read from, which is what hyperparams.py's train/test discipline exists to
    prevent.
    """
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(
        max_iter=200, max_depth=4, learning_rate=0.03, min_samples_leaf=40,
        l2_regularization=1.0, early_stopping=False, random_state=0)


def run_for_asset(asset, counterpart) -> None:
    print("\n" + "#" * 92)
    print(f"### HEDEF: {asset.label.upper()} ({asset.symbol})   "
          f"havuza giren: {counterpart.label}")
    print("#" * 92)

    # Each metal's own volatility, aligned by date, so counterpart_chg can be
    # divided by the volatility of the series it actually describes.
    plain = {}
    for a in (asset, counterpart):
        raw = panel_module.load(a.key).reset_index(drop=True)
        plain[a.key] = build_features(raw, drivers=a.leading_drivers)

    def counterpart_vol_for(a, other):
        vol = plain[other.key][["time", "vol_60d"]].rename(columns={"vol_60d": "cv"})
        merged = plain[a.key][["time"]].merge(vol, on="time", how="left")
        return merged["cv"].replace(0.0, np.nan)

    target_norm = normalised_frame(asset, counterpart_vol_for(asset, counterpart))
    other_norm = normalised_frame(counterpart, counterpart_vol_for(counterpart, asset))

    production_features = ml_model.available_features(plain[asset.key])
    norm_features = pooled_features(target_norm)

    print(f"  uretim ozelligi: {len(production_features)}   "
          f"normallestirilmis ozellik: {len(norm_features)}")
    extra_cols = set(driver_union()) - set(asset.leading_drivers)
    if extra_cols:
        print(f"  NOT: havuz kolu surucu BIRLESIMINI kullaniyor, yani bu varlik icin")
        print(f"  {sorted(extra_cols)} kolonlari da tasiyor -- tek bir ortak ozellik")
        print(f"  vektoru sart. Yani B vs A burada sadece normallestirmeyi degil, bu")
        print(f"  eklemeyi de olcuyor; C vs B ise ikisinden de arinmis durumda.")

    forward = ablation.forward_frame(plain[asset.key], HORIZON)
    forward_norm = ablation.forward_frame(target_norm, HORIZON)

    results = {}
    results["A uretim / tek"] = run_arm(plain[asset.key], production_features, forward)
    results["B normal / tek"] = run_arm(target_norm, norm_features, forward_norm)
    results["C normal / HAVUZ"] = run_arm(target_norm, norm_features, forward_norm,
                                          extra=[other_norm])

    if not all(results.values()):
        print("  yetersiz satir -- kol(lar) puanlanamadi.")
        return

    n_single = results["A uretim / tek"]["n"]
    floor_single = ablation.min_detectable_ic(n_single, HORIZON, BAR_T)
    # The pooled arm predicts the same rows but TRAINS on roughly twice as
    # many, so its detection floor is the one this whole file is about.
    floor_pooled = ablation.min_detectable_ic(n_single * 2, HORIZON, BAR_T)

    print(f"\n  {'kol':<20}{'n':>7}{'IC':>10}{'t':>8}{'isabet':>10}")
    for label, r in results.items():
        print(f"  {label:<20}{r['n']:>7}{r['ic']:>+10.4f}{r['t']:>+8.2f}{100 * r['acc']:>9.2f}%")

    print(f"\n  tespit tabani -- tek varlik: {floor_single:.4f}   "
          f"havuz (2x gozlem): {floor_pooled:.4f}")

    print("\n  ESLESTIRILMIS KARSILASTIRMALAR (ayni satirlar, ortusme duzeltmeli)")
    pairs = (
        ("B normal / tek", "A uretim / tek", "normallestirmenin kendisi zarar veriyor mu"),
        ("C normal / HAVUZ", "B normal / tek", "HAVUZLAMA ekliyor mu  <-- ASIL SORU"),
        ("C normal / HAVUZ", "A uretim / tek", "paket uretimi geciyor mu"),
    )
    for b_key, a_key, question in pairs:
        p = ablation.paired_ic_test(results[a_key], results[b_key], HORIZON)
        delta = results[b_key]["ic"] - results[a_key]["ic"]
        verdict = "AYIRT EDILEMIYOR" if p > 0.05 else ("DAHA IYI" if delta > 0 else "DAHA KOTU")
        print(f"    {b_key:<18} vs {a_key:<18} IC {delta:+.4f}  p={p:.3f}  -> {verdict}")
        print(f"        ({question})")

    # Diagnostic, not a search -- see roomier_estimator's docstring.
    roomy = run_arm(target_norm, norm_features, forward_norm,
                    extra=[other_norm], factory=roomier_estimator)
    if roomy:
        p = ablation.paired_ic_test(results["C normal / HAVUZ"], roomy, HORIZON)
        delta = roomy["ic"] - results["C normal / HAVUZ"]["ic"]
        print(f"\n  TESHIS (arama degil): havuz + max_depth=4 -> IC {roomy['ic']:+.4f} "
              f"(havuz max_depth=3: {results['C normal / HAVUZ']['ic']:+.4f}, "
              f"fark {delta:+.4f}, p={p:.3f})")
        print("     Havuz kolu 2 kat veriyle egitiliyor ama kapasitesi hyperparams.py'de")
        print("     SADECE ALTIN uzerinde secilmisti. Bu satir 'havuzlama katmiyor' ile")
        print("     'modeli ac biraktik' arasindaki farki ayirir.")


def main() -> int:
    print(f"Ufuk: {HORIZON} islem gunu   coklu-test esigi |t| > {BAR_T}")
    print("Platin ve paladyum bu faza GIRMIYOR: duz mum oranlari %52,9 ve %59,9")
    print("(altin %11, gumus %24). compare.flat_bar_quality kapisindan gecmeden")
    print("havuza girerlerse kisiti gevsetmek yerine gurultu eklerler.")

    gold, silver = assets_module.GOLD, assets_module.SILVER
    run_for_asset(gold, silver)
    run_for_asset(silver, gold)

    print("\n" + "=" * 92)
    print("NASIL OKUNMALI")
    print("=" * 92)
    print("  Benimseme sarti: C, A'yi ANLAMLI sekilde gecmeli VE bu IKI metalde de")
    print("  ayni yonde olmali. C vs B asil bilimsel soru: ayni ozelliklerle, sadece")
    print("  daha cok veri. B vs A notr cikmali -- cikmazsa normallestirme bir sey")
    print("  bozuyor demektir ve havuz sonucu o hasarin uzerine binmis olur.")
    print()
    print("  Ayirt edilemez cikarsa bu bir basarisizlik DEGIL: ablation.py'nin")
    print("  'daha cok gozlem lazim' tezinin 2x'te dogrulanmadigi anlamina gelir,")
    print("  ve tespit tabani satiri bunun neden hala kesin olmadigini soyler.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
