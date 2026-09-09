"""Are ml_model.build_estimator()'s hyperparameters measured, or just a guess
that happened to ship?

max_depth=3, learning_rate=0.03, min_samples_leaf=40, l2_regularization=1.0
were picked by intuition ("gold's daily direction is close to noise, so the
danger is a model confidently memorising it" -- ml_model.py's own comment)
and never grid-searched, which is the one place this project's own
"nothing here is a guess" rule was not applied to the model itself.

Method, copied from research/tilt.py's discipline (chosen on the training
half only, confirmed once on the test half, the full grid printed for
context so a flat/noisy surface is visible rather than hidden behind a
cherry-picked winner):

  * research/edge.py's walk_forward() now takes an `estimator_factory` -- the
    same extensibility research/ratio.py and research/ablation.py already use
    for features/labels, just for hyperparameters. Every candidate is scored
    through the EXACT SAME walk-forward loop production uses, not a copy.
  * Unlike tilt.py, there is no shared cache: each candidate IS a different
    model, so each candidate needs its own full walk_forward() run. What gets
    split in half by time afterwards is the resulting OUTPUT ROWS, not the
    input panel -- one run per candidate, not one run per half.
  * The metric is out-of-sample ACCURACY at HORIZON_DAYS=5, the horizon
    actually deployed -- not a new metric, the same number edge.py's own
    report() already treats as the headline figure.
  * Only two axes are searched: max_depth and min_samples_leaf, both direct
    capacity/overfitting controls (the exact concern the current comment
    raises). learning_rate and l2_regularization are held fixed this pass
    because learning_rate interacts with max_iter under early_stopping=False
    -- tuning it alone would silently under- or over-train relative to what
    max_iter=200 assumes. A joint search of that pair is a separate,
    larger study.
  * GOLD ONLY. edge.py's own widened horizon sweep (2026-09) found silver
    clears no horizon by a statistically meaningful margin (overlap-corrected
    z stays under 1 everywhere it nominally clears the wall) -- there is no
    honest signal in silver to tune hyperparameters against, and doing so
    would just be fitting noise (tilt.py's own warning: "acting on noise is
    itself a kind of overfitting"). The winning combination is instead run
    ONCE on silver afterwards as a sanity check that it does not make things
    worse there, not as a second search.
"""
from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402

import assets as assets_module  # noqa: E402
import edge  # noqa: E402
import ml_model  # noqa: E402
import panel as panel_module  # noqa: E402
from indicators import build_features  # noqa: E402

HORIZON = ml_model.HORIZON_DAYS  # 5 -- the horizon actually deployed.

MAX_DEPTH_GRID = [2, 3, 4]
MIN_SAMPLES_LEAF_GRID = [20, 40, 80]

# Held fixed this pass -- see module docstring.
FIXED_LEARNING_RATE = 0.03
FIXED_L2 = 1.0
FIXED_MAX_ITER = 200

# ml_model.build_estimator()'s current shipped values -- inside the grid on
# purpose, so "did the search beat what we already have" is direct, not
# inferred.
PRODUCTION = (3, 40)


def make_estimator(max_depth: int, min_samples_leaf: int):
    def factory() -> HistGradientBoostingClassifier:
        return HistGradientBoostingClassifier(
            max_iter=FIXED_MAX_ITER, max_depth=max_depth,
            learning_rate=FIXED_LEARNING_RATE, min_samples_leaf=min_samples_leaf,
            l2_regularization=FIXED_L2, early_stopping=False, random_state=0)
    return factory


def accuracy(out: pd.DataFrame, lo: int, hi: int) -> float:
    block = out.iloc[lo:hi]
    predicted = (block["proba_up"] >= 0.5).to_numpy()
    return float(np.mean(predicted == block["label"].to_numpy()))


def main() -> int:
    gold = assets_module.GOLD
    raw = panel_module.load(gold.key).reset_index(drop=True)
    df = build_features(raw, drivers=gold.leading_drivers)
    roundtrip_bps = gold.fee_rate * 2 * 10_000.0
    closes = df["close"].to_numpy(dtype=float)
    mean_move = float(np.mean(np.abs(closes[HORIZON:] / closes[:-HORIZON] - 1.0)))

    print(f"Panel: {len(df)} gun ({df['time'].iloc[0].date()} -> {df['time'].iloc[-1].date()})")
    print(f"Ufuk: {HORIZON} islem gunu (uretimde fiilen calisan ufuk)")
    print(f"max_depth x {MAX_DEPTH_GRID}  min_samples_leaf x {MIN_SAMPLES_LEAF_GRID}  "
          f"({len(MAX_DEPTH_GRID) * len(MIN_SAMPLES_LEAF_GRID)} kombinasyon)")
    print("Her kombinasyon icin ayri bir tam walk-forward kosusu (onbellek yok -- "
          "her aday farkli bir model).\n")

    outputs: dict[tuple[int, int], pd.DataFrame] = {}
    t0 = time.time()
    for depth in MAX_DEPTH_GRID:
        for leaf in MIN_SAMPLES_LEAF_GRID:
            outputs[(depth, leaf)] = edge.walk_forward(
                df, HORIZON, estimator_factory=make_estimator(depth, leaf))
            print(f"  (max_depth={depth}, min_samples_leaf={leaf}) tamam "
                  f"-- {time.time() - t0:.0f}sn toplam")

    any_output = next(iter(outputs.values()))
    n = len(any_output)
    split = n // 2
    times = any_output["time"]
    print(f"\nSatir: {n}  EGITIM: {times.iloc[0].date()} -> {times.iloc[split - 1].date()}  "
          f"TEST: {times.iloc[split].date()} -> {times.iloc[-1].date()}\n")

    print("EGITIM YARISI -- isabet orani (satir=max_depth, sutun=min_samples_leaf)")
    print("      " + "".join(f"{leaf:>9d}" for leaf in MIN_SAMPLES_LEAF_GRID))
    train_acc: dict[tuple[int, int], float] = {}
    for depth in MAX_DEPTH_GRID:
        row = f"{depth:>5d} "
        for leaf in MIN_SAMPLES_LEAF_GRID:
            acc = accuracy(outputs[(depth, leaf)], 0, split)
            train_acc[(depth, leaf)] = acc
            row += f"{100 * acc:>8.2f}%"
        print(row)

    chosen = max(train_acc, key=train_acc.get)
    print(f"\n>>> EGITIMDE SECILEN: max_depth={chosen[0]} min_samples_leaf={chosen[1]} "
          f"(egitim isabet %{100 * train_acc[chosen]:.2f}, "
          f"uretim (3,40) egitim isabet %{100 * train_acc[PRODUCTION]:.2f})")

    combos = sorted({PRODUCTION, chosen})
    print("\nTEST YARISI (gorulmemis)")
    test_acc: dict[tuple[int, int], float] = {}
    for combo in combos:
        label = "URETIM" if combo == PRODUCTION else "SECILEN"
        out = outputs[combo]
        test_acc[combo] = accuracy(out, split, n)
        block = out.iloc[split:]
        edge.report(f"{label} (max_depth={combo[0]}, min_samples_leaf={combo[1]})",
                    (block["proba_up"] >= 0.5).to_numpy().astype(float),
                    block["label"].to_numpy(), HORIZON, mean_move,
                    block["proba_up"].to_numpy(), roundtrip_bps)

    if chosen == PRODUCTION:
        print("\n>>> ARAMA URETIMDEKINDEN FARKLI BIR SEY BULMADI: "
              "(max_depth=3, min_samples_leaf=40) egitim yarisinda zaten en iyisiydi.")
    else:
        delta = test_acc[chosen] - test_acc[PRODUCTION]
        if delta <= 0:
            print(f"\n>>> SECILEN KOMBINASYON EGITIMDE ONE CIKTI AMA TEST YARISINDA "
                  f"URETIMDEN {100 * delta:+.2f} PUAN -- gurultuydu, build_estimator() DEGISMEYECEK.")
        else:
            print(f"\n>>> SECILEN KOMBINASYON TEST YARISINDA URETIMDEN {100 * delta:+.2f} "
                  "PUAN DAHA ISABETLI -- ml_model.build_estimator()'a tasinacak.")

    # --- Gumus saglik kontrolu: arama degil, tek dogrulama (bkz. modul docstring) ---
    print("\n" + "=" * 78)
    print("GUMUS SAGLIK KONTROLU (arama degil, secilenin gumusu bozmadigini dogrulama)")
    print("=" * 78)
    silver = assets_module.SILVER
    silver_raw = panel_module.load(silver.key).reset_index(drop=True)
    silver_df = build_features(silver_raw, drivers=silver.leading_drivers)
    silver_roundtrip = silver.fee_rate * 2 * 10_000.0
    silver_closes = silver_df["close"].to_numpy(dtype=float)
    silver_mean_move = float(np.mean(
        np.abs(silver_closes[HORIZON:] / silver_closes[:-HORIZON] - 1.0)))

    for combo in combos:
        label = "URETIM" if combo == PRODUCTION else "SECILEN"
        out = edge.walk_forward(silver_df, HORIZON, estimator_factory=make_estimator(*combo))
        edge.report(f"Gumus - {label} (max_depth={combo[0]}, min_samples_leaf={combo[1]})",
                    (out["proba_up"] >= 0.5).to_numpy().astype(float),
                    out["label"].to_numpy(), HORIZON, silver_mean_move,
                    out["proba_up"].to_numpy(), silver_roundtrip)

    return 0


if __name__ == "__main__":
    sys.exit(main())
