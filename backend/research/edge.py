"""The decisive test: does anything here clear gold's break-even wall?

research/wall.py established what "working" would even mean:

    horizon   break-even (10bp ETF)   always-UP baseline
      1 day          56.2%                  53.0%
      5 days         52.7%                  55.7%
     20 days         51.3%                  57.2%

Note what that table already says before any model is fitted: from two days
out, simply being long all the time clears the cost wall. So a directional
model on gold is not competing against a coin flip, it is competing against
"always UP" -- and beating 50% proves nothing whatsoever. XRP-Guess's
components were scored against 50% and looked respectable at 55%; on gold
that same 55% at a 20-day horizon would be WORSE than doing nothing.

Every number below is therefore printed against three bars at once:
50% (chance), the always-UP base rate (free), and the cost wall (necessary).
A model has to beat all three to be worth running.

Method -- walk-forward, out of sample, no exceptions:
  * The model is refit every REFIT_EVERY trading days on data strictly before
    the refit point, then used for exactly the next REFIT_EVERY days.
  * Nothing is selected on the test data. Feature list, hyperparameters and
    the technical rule's weights were all fixed before this file ran.
  * Overlap is reported honestly: at horizon h, consecutive predictions share
    h-1 days of outcome, so the effective sample is far smaller than the row
    count and naive t-statistics are inflated. A non-overlapping subset is
    scored alongside as the conservative reading.
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
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402

import ml_model  # noqa: E402
import panel as panel_module  # noqa: E402
from indicators import build_features, technical_signal  # noqa: E402

REFIT_EVERY = 63          # ~one quarter; ~50 refits across the test half
MIN_TRAIN_ROWS = 750      # ~3 years before the first prediction is allowed
ETF_ROUNDTRIP_BPS = 10
HORIZONS = [1, 5, 20]


def _fit(train: pd.DataFrame, features: list[str], label: str) -> HistGradientBoostingClassifier:
    """Same estimator the live model uses -- imported rather than redefined so
    research can never drift from production without someone noticing."""
    model = ml_model.build_estimator()
    model.fit(train[features], train[label])
    return model


def walk_forward(df: pd.DataFrame, horizon: int,
                 features: list[str] | None = None,
                 label_values: pd.Series | np.ndarray | None = None) -> pd.DataFrame:
    """Out-of-sample probability for every row the walk-forward can reach.

    `features` and `label_values` both default to what production uses. They
    are parameters only so research/ratio.py and research/ablation.py can vary
    exactly one thing against an identical refit schedule and identical rows.
    Running two variants through two different walk-forward implementations
    would measure the implementations.

    `label_values` must already be aligned to `df` and must be NaN wherever
    the outcome is unknown -- see build_feature_frame on why an unknown label
    must never quietly become a False.
    """
    label = "label_up"
    if label_values is None:
        future_close = df["close"].shift(-horizon)
        label_values = np.where(
            future_close.notna(), (future_close > df["close"]).astype(float), np.nan)
    df = df.assign(**{label: np.asarray(label_values, dtype=float)})

    if features is None:
        features = ml_model.available_features(df)
    usable = df.dropna(subset=features + [label]).reset_index(drop=True)

    rows = []
    start = MIN_TRAIN_ROWS
    n = len(usable)
    while start < n:
        stop = min(start + REFIT_EVERY, n)
        # Rows whose label is still unknown at the refit moment must not be
        # trained on: at the moment we stand on row `start`, the outcome of
        # rows start-horizon..start-1 has not happened yet. Cutting the
        # training set `horizon` rows short is what keeps this honest -- this
        # is the single easiest place in the whole file to leak the future.
        train = usable.iloc[: max(start - horizon, 0)]
        if len(train) < MIN_TRAIN_ROWS:
            start = stop
            continue
        model = _fit(train, features, label)
        block = usable.iloc[start:stop]
        proba = model.predict_proba(block[features])[:, 1]
        for (_, row), p in zip(block.iterrows(), proba):
            rows.append({
                "time": row["time"], "close": row["close"], "label": row[label],
                "proba_up": float(p), "row_index": int(row.name),
            })
        start = stop
    return pd.DataFrame(rows)


def technical_walk(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """The rule-based signal over the same rows. No fitting, so no refits --
    but it is scored on exactly the same slice for a fair comparison."""
    future_close = df["close"].shift(-horizon)
    labels = np.where(future_close.notna(), (future_close > df["close"]).astype(float), np.nan)

    rows = []
    for i in range(MIN_TRAIN_ROWS, len(df)):
        if not np.isfinite(labels[i]):
            continue
        # Pass ONLY row i, not df[:i+1]. technical_signal reads .iloc[-1] and
        # nothing else, so the two are identical in result -- but slicing a
        # growing prefix copies an ever-larger frame every iteration, which
        # made this loop quadratic (~13 GB of copying across 5500 rows).
        signal = technical_signal(df.iloc[i : i + 1])
        rows.append({
            "time": df["time"].iloc[i], "close": df["close"].iloc[i], "label": labels[i],
            "score": signal["score"], "confidence": signal["confidence"],
            "direction": signal["direction"],
        })
    return pd.DataFrame(rows)


def report(name: str, predicted_up: np.ndarray, labels: np.ndarray, horizon: int,
           mean_move: float, proba: np.ndarray | None = None) -> dict:
    n = len(labels)
    if n == 0:
        print(f"  {name}: veri yok")
        return {}
    accuracy = float(np.mean(predicted_up == labels))
    base_up = float(np.mean(labels))
    always_up = max(base_up, 1 - base_up)
    wall = 0.5 + ((ETF_ROUNDTRIP_BPS / 10_000.0) / 2.0) / mean_move

    se = math.sqrt(0.25 / n)
    z_chance = (accuracy - 0.5) / se
    # Effective sample after overlap: consecutive predictions at horizon h
    # share h-1 days of outcome, so treat every h-th one as independent.
    n_eff = max(n / horizon, 1)
    z_eff = (accuracy - 0.5) / math.sqrt(0.25 / n_eff)

    verdicts = []
    verdicts.append("CHANCE+" if accuracy > 0.5 else "chance-")
    verdicts.append("BASE+" if accuracy > always_up else "base-")
    verdicts.append("WALL+" if accuracy > wall else "wall-")

    print(f"  {name:<22} n={n:5d}  isabet=%{100 * accuracy:.2f}")
    print(f"    {'vs sans %50.0':<28} {100 * (accuracy - 0.5):+6.2f}p   z={z_chance:+5.2f} (ortusme duzeltmeli z={z_eff:+5.2f})")
    print(f"    {'vs hep-YUKARI %' + format(100 * always_up, '.1f'):<28} {100 * (accuracy - always_up):+6.2f}p")
    print(f"    {'vs maliyet duvari %' + format(100 * wall, '.1f'):<28} {100 * (accuracy - wall):+6.2f}p   -> {' '.join(verdicts)}")
    if proba is not None:
        brier = float(np.mean((proba - labels) ** 2))
        # Brier skill vs the always-UP constant forecast, the honest reference.
        ref = float(np.mean((np.full_like(labels, base_up) - labels) ** 2))
        bss = 1 - brier / ref if ref > 0 else float("nan")
        print(f"    {'Brier':<28} {brier:.4f}  (sabit-taban {ref:.4f}, beceri skoru {bss:+.4f})")
    return {"accuracy": accuracy, "always_up": always_up, "wall": wall, "n": n}


def main() -> int:
    raw = panel_module.load().reset_index(drop=True)
    df = build_features(raw)
    print(f"Panel: {len(df)} gun ({df['time'].iloc[0].date()} -> {df['time'].iloc[-1].date()})")
    print(f"Ozellik sayisi: {len(ml_model.available_features(df))}")
    print(f"Yurüyen-ileri: her {REFIT_EVERY} gunde bir yeniden fit, ilk {MIN_TRAIN_ROWS} satir sadece egitim\n")

    for horizon in HORIZONS:
        t0 = time.time()
        print("=" * 78)
        print(f"### UFUK = {horizon} islem gunu")
        print("=" * 78)

        closes = df["close"].to_numpy(dtype=float)
        mean_move = float(np.mean(np.abs(closes[horizon:] / closes[:-horizon] - 1.0)))
        print(f"  ort |hareket| = %{100 * mean_move:.3f}\n")

        ml_out = walk_forward(df, horizon)
        if not ml_out.empty:
            report("ML (gradient boosting)", (ml_out["proba_up"] >= 0.5).to_numpy().astype(float),
                   ml_out["label"].to_numpy(), horizon, mean_move, ml_out["proba_up"].to_numpy())

        tech_out = technical_walk(df, horizon)
        if not tech_out.empty:
            common = tech_out[tech_out["time"].isin(ml_out["time"])] if not ml_out.empty else tech_out
            report("Teknik kural", (common["direction"] == "UP").to_numpy().astype(float),
                   common["label"].to_numpy(), horizon, mean_move)

            # Blend: average the two directional scores. Deliberately the
            # simplest possible combination -- anything cleverer would be a
            # choice made while looking at the test set.
            if not ml_out.empty:
                merged = ml_out.merge(common[["time", "score"]], on="time", how="inner")
                blend = (merged["proba_up"] - 0.5) * 2 + merged["score"]
                report("Harman (ML + teknik)", (blend >= 0).to_numpy().astype(float),
                       merged["label"].to_numpy(), horizon, mean_move)

        # Non-overlapping subset -- the conservative reading.
        if not ml_out.empty and horizon > 1:
            sparse = ml_out.iloc[::horizon]
            report(f"ML, ortusmesiz (her {horizon}. gun)",
                   (sparse["proba_up"] >= 0.5).to_numpy().astype(float),
                   sparse["label"].to_numpy(), 1, mean_move, sparse["proba_up"].to_numpy())

        print(f"\n  ({time.time() - t0:.0f} saniye)\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
