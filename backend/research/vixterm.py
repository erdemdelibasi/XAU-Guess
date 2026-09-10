"""Is `vix3m` simply a better version of the `vix` slot production already has?

research/drivers.py's 2026-09 candidate sweep threw off a result nobody had
asked for. `^VIX3M` -- the 3-month VIX, the same index methodology at a longer
tenor -- cleared the Bonferroni bar on BOTH metals out of sample, and on both
it scored HIGHER than the `vix` that assets.py already carries as a measured
lead:

    altin    vix t=-3.58    vix3m t=-3.68
    gumus    vix t=-4.57    vix3m t=-4.95

That is not a new driver. Its lag profile is the same shape as vix's (nothing
at lag 0, a clean negative at lag +1), the sign is the same, and the economic
story is the one CLAUDE.md already documents: a volatility spike is BAD for
gold the next day, because forced liquidation sells what can be sold. The
plausible reading is that vix3m is the same signal measured with less noise --
a 30-day implied volatility is dominated by whatever happens to be expiring,
a 90-day one much less so.

So the question is not "add vix3m". It is "should vix3m REPLACE vix", and a
swap has a fixed procedure on this bench: a paired A/B that changes exactly
one thing and scores both arms on the SAME rows (research/ablation.py,
research/ratio.py). Permutation importance on a single split is explicitly
not enough -- CLAUDE.md records that the two contradicted each other on both
metals the last time this question came up, for `gs_ratio_z`.

THE SWAP HAS TWO CONSUMERS AND THEY MUST BE TESTED SEPARATELY
--------------------------------------------------------------
`vix` is not one thing in this system. It reaches production twice:

  1. `ml_model.FEATURE_COLUMNS` carries `vix_chg` / `vix_chg5`, so it is a
     column the classifier can split on.
  2. `assets.Asset.leading_drivers` puts it in `macro_signal`, where
     `_vix_score` turns its daily change into a weighted directional vote.

A swap could help one and hurt the other, and a single blended number would
hide that. Both are measured here, through the real production functions
(`edge.walk_forward(features=...)` and `edge.macro_walk`), never a copy.

TWO COSTS A NAIVE COMPARISON WOULD MISS
----------------------------------------
**History.** `^VIX3M` starts 2006-07; `^VIX` covers the whole panel. And
`ml_model.prepare_training_frame` DROPS rows carrying a NaN feature, so the
swap would silently delete ~1200 sessions -- about a fifth of the panel --
from every future training run. That cost is printed here rather than
discovered later, and both arms are restricted to the common window so the
comparison itself is paired rather than a comparison of two sample sizes.

**Scale.** `macro_signal.VIX_SCALE` and `indicators.VIX_SCALE` are divisors
measured on VIX's OWN distribution of daily point changes. A 3-month index
moves less per day by construction, so handing its change to a constant tuned
for the 1-month index would quietly shrink the term toward zero -- the exact
failure CLAUDE.md records for `real_yield_chg`, where a duration fix left a
weighted component with a median |score| of 0.009, doing nothing at all while
still occupying a weight. The rescale factor used here is measured on the
TRAINING half only.
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
BAR_T = 2.807   # the same multiple-test bar drivers.py applies

# The percentile every scale constant in this project is defined against: a
# 90th-percentile move should map to a full-scale score. Reused rather than
# reinvented -- see the block above indicators.BOND_SCALE.
SCALE_PERCENTILE = 90


def frames(asset) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(full panel, common window), both carrying vix and vix3m changes."""
    raw = panel_module.load(asset.key).reset_index(drop=True)
    # Ask for vix3m alongside the asset's real drivers so build_features emits
    # vix3m_chg / vix3m_chg5. It is a level in points, and indicators.LEVEL_SERIES
    # is what makes that a difference rather than a return.
    drivers = tuple(dict.fromkeys(asset.leading_drivers + ("vix", "vix3m")))
    full = build_features(raw, drivers=drivers)
    common = full[full["vix3m_chg"].notna()].reset_index(drop=True)
    return full, common


def measure_scale(df: pd.DataFrame, split: int) -> dict:
    """p90 of each series' daily change, on the TRAINING half only."""
    out = {}
    for name in ("vix_chg", "vix3m_chg"):
        values = df[name].iloc[:split].abs().dropna()
        out[name] = float(np.percentile(values, SCALE_PERCENTILE))
    return out


def swap_features(features: list[str]) -> list[str]:
    mapping = {"vix_chg": "vix3m_chg", "vix_chg5": "vix3m_chg5"}
    return [mapping.get(c, c) for c in features]


def verdict_line(delta: float, p: float) -> str:
    if p > 0.05:
        return "AYIRT EDILEMIYOR"
    return "ADAY DAHA IYI" if delta > 0 else "ADAY DAHA KOTU"


def compare(results: dict, label_a: str, label_b: str) -> tuple[float, float]:
    print(f"     {'kol':<18}{'n':>7}{'IC':>10}{'t':>8}{'isabet':>10}")
    for label, r in results.items():
        print(f"     {label:<18}{r['n']:>7}{r['ic']:>+10.4f}{r['t']:>+8.2f}{100 * r['acc']:>9.2f}%")
    p = ablation.paired_ic_test(results[label_a], results[label_b], HORIZON)
    delta = results[label_b]["ic"] - results[label_a]["ic"]
    print(f"\n     eslestirilmis fark: IC {delta:+.4f}   p={p:.3f}")
    print(f"     -> {verdict_line(delta, p)}")
    return delta, p


PROD = "URETIM (vix)"
CAND = "ADAY (vix3m)"


def run_ml_arm(asset, common: pd.DataFrame) -> None:
    print("\n" + "-" * 88)
    print("  A) ML OZELLIK SETI  --  vix_chg/vix_chg5  ->  vix3m_chg/vix3m_chg5")
    print("-" * 88)

    production = ml_model.available_features(common)
    swapped = swap_features(production)
    if swapped == production:
        print("     vix_chg uretim ozellik setinde yok -- test edilecek bir sey yok.")
        return

    forward = ablation.forward_frame(common, HORIZON)
    results = {}
    for label, cols in ((PROD, production), (CAND, swapped)):
        run = edge.walk_forward(common, HORIZON, features=cols)
        scored = ablation.score(run, forward, HORIZON)
        if not scored:
            print(f"     {label}: yetersiz satir")
            return
        results[label] = scored

    compare(results, PROD, CAND)
    floor = ablation.min_detectable_ic(len(common), HORIZON, BAR_T)
    print(f"     bu ornekle sifirdan ayirt edilebilecek en kucuk IC: {floor:.4f}")


def run_macro_arm(asset, common: pd.DataFrame, scales: dict) -> None:
    print("\n" + "-" * 88)
    print("  B) MAKRO BILESENI  --  macro_signal'in `vix` yuvasi")
    print("-" * 88)

    # Rescale vix3m's change onto VIX's own distribution so the SAME measured
    # VIX_SCALE divisor stays correct. This is what lets the real _vix_score run
    # unmodified: the substitution happens in the INPUT, not the code -- the
    # discipline ablation.py applies to a feature list, applied to a column.
    factor = scales["vix_chg"] / scales["vix3m_chg"]
    print(f"     egitim yarisinda olculen p{SCALE_PERCENTILE}: "
          f"vix_chg={scales['vix_chg']:.4f}  vix3m_chg={scales['vix3m_chg']:.4f}")
    print(f"     vix3m'i vix'in olcegine tasiyan carpan: {factor:.4f}")
    print(f"     (uretime girerse bu bir VIX3M_SCALE demektir: "
          f"macro_signal {3.0 / factor:.3f}, indicators {2.4 / factor:.3f})")

    swapped = common.copy()
    swapped["vix_chg"] = swapped["vix3m_chg"] * factor

    forward = ablation.forward_frame(common, HORIZON)
    runs = {PROD: edge.macro_walk(common, HORIZON, drivers=asset.leading_drivers),
            CAND: edge.macro_walk(swapped, HORIZON, drivers=asset.leading_drivers)}

    # Only rows where BOTH arms actually voted. macro_signal abstains by design
    # and the two arms abstain on different days; scoring each on its own rows
    # would compare two different samples and call it an A/B.
    speaking = None
    for out in runs.values():
        voted = set(out.loc[out["confidence"] > 0, "time"])
        speaking = voted if speaking is None else (speaking & voted)

    results = {}
    for label, out in runs.items():
        block = out[out["time"].isin(speaking)].rename(columns={"score": "proba_up"})
        scored = ablation.score(block, forward, HORIZON)
        if not scored:
            print(f"     {label}: yetersiz satir")
            return
        results[label] = scored

    print(f"\n     iki kolun da konustugu gun sayisi: {len(speaking)}")
    compare(results, PROD, CAND)


def run_for_asset(asset) -> None:
    print("\n" + "#" * 88)
    print(f"### {asset.label.upper()} ({asset.symbol})   surucu seti: {asset.leading_drivers}")
    print("#" * 88)

    full, common = frames(asset)
    split = len(common) // 2
    lost = len(full) - len(common)
    print(f"  Tam panel     : {len(full)} gun "
          f"({full['time'].iloc[0].date()} -> {full['time'].iloc[-1].date()})")
    print(f"  Ortak pencere : {len(common)} gun "
          f"({common['time'].iloc[0].date()} -> {common['time'].iloc[-1].date()})")
    print(f"  TAKASIN GECMIS BEDELI: {lost} seans (%{100 * lost / len(full):.1f}). "
          f"ml_model.prepare_training_frame")
    print(f"  NaN tasiyan satiri DUSURUR, yani bu satirlar vix3m'e gecildiginde her")
    print(f"  egitim kosusundan sessizce cikardi. Karsilastirmanin kendisi ortak")
    print(f"  pencerede yapiliyor -- iki kol da ayni satirlari goruyor.")

    scales = measure_scale(common, split)
    run_ml_arm(asset, common)
    run_macro_arm(asset, common, scales)


def main() -> int:
    print(f"Ufuk: {HORIZON} islem gunu (uretimde fiilen calisan ufuk)")
    for asset in assets_module.ASSETS.values():
        run_for_asset(asset)

    print("\n" + "=" * 88)
    print("NASIL OKUNMALI")
    print("=" * 88)
    print("  Takasin kabul edilmesi icin iki kolun EN AZ birinde anlamli bir iyilesme,")
    print("  digerinde ise bir kotulesme OLMAMASI gerekir -- ve bu iki metalde de ayni")
    print("  yonde cikmalidir. p=0,49'a dayanarak kolon degistirmek tam olarak bu")
    print("  tezgahin onlemek icin var oldugu seydir (bkz. gs_ratio_z, CLAUDE.md).")
    print("  Gecmis bedeli de bedava degildir: ~%20 satir kaybi, ayirt edilemeyen bir")
    print("  IC farkinin yaninda net bir KAYIPTIR -- ablation.py'nin kendi sonucu")
    print("  bu projede bagimsiz gozlem sayisinin baglayici kisit oldugunu soyluyor.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
