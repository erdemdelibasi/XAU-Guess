"""Two questions, one shared replay: is CORRELATION_DAMPING/SHRINK_ALPHA
measured or inherited, and does component disagreement carry any position-
sizing information ensemble.combine()'s pooled confidence doesn't already?

ensemble.py's own docstring admits the first: CORRELATION_DAMPING=0.7 and
SHRINK_ALPHA=60.0 are "inherited rather than re-measured: this project has no
live history yet." It does now, in the sense that matters here -- a
walk-forward replay of technical+ml+macro gives ~19 years of out-of-sample
component records to test them against, the same way research/edge.py tests
the model itself.

`claude` and `news` are NOT in this replay. Claude cannot be backtested
(CLAUDE.md: replaying 6000 days through a paid LLM call is expensive and
meaningless -- the model already knows those dates) and there is no
historical headline archive for `news`. This mirrors backtest.py's own
"ensemble" row, which is already an ml+technical proxy for exactly this
reason (see commit 3b8f433). Their weight in the LIVE ensemble is untouched.

METHOD -- research/tilt.py's discipline, twice:

  1. Build technical/ml/macro's out-of-sample calls for every eligible day
     (edge.walk_forward, edge.technical_walk, edge.macro_walk -- the same
     production code every other study here reuses), merged on `time`.
  2. Reconstruct, for EVERY day, the rolling component record retrain.py
     would have had at that point: the last RECORD_WINDOW_ROWS=750 calls
     that had ALREADY RESOLVED by that day (a call made on day s resolves on
     day s+HORIZON). This is done with shift(HORIZON) + rolling(750).sum(),
     vectorised, not a per-row Python reconstruction -- the loop that
     remains only calls ensemble.combine() itself, never reimplements it.
  3. Grid-search (correlation_damping, shrink_alpha) by Brier skill score
     (calibration, not direction -- see ensemble.py's own XRP-Guess anecdote:
     "claiming 58.0% while delivering 55.6%" is a calibration failure).
     Chosen on the training half, confirmed once on the test half, full
     grid printed either way.
  4. With that combo settled, compute a daily disagreement measure (fraction
     of VOTING components whose direction differs from the pooled one) and
     grid-search DISAGREEMENT_TILT the same way research/tilt.py grid-
     searched TILT -- through trading.compute_target_exposure() and
     defense.simulate()/metrics(), by Calmar, chosen on the training half,
     confirmed once on the test half against disagreement_tilt=0.0 (today's
     behaviour) run on the identical signal.

GOLD ONLY, same reasoning as research/hyperparams.py: edge.py's own widened
horizon sweep found silver clears no horizon by a statistically meaningful
margin, so there is no honest signal there to tune either search against.
"""
from __future__ import annotations

import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import assets as assets_module  # noqa: E402
import defense  # noqa: E402
import edge  # noqa: E402
import ensemble  # noqa: E402
import ml_model  # noqa: E402
import panel as panel_module  # noqa: E402
import retrain  # noqa: E402
import trading  # noqa: E402
from indicators import build_features  # noqa: E402

HORIZON = ml_model.HORIZON_DAYS  # 5 -- the horizon actually deployed.
COMPONENTS = ("technical", "ml", "macro")

CORRELATION_DAMPING_GRID = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
SHRINK_ALPHA_GRID = [20, 40, 60, 80, 120]
PRODUCTION_DAMPING_SHRINK = (0.7, 60)  # ensemble.py's current shipped values

DISAGREEMENT_TILT_GRID = [0.0, 0.25, 0.5, 0.75, 1.0]

# Guard against the exact illusion ensemble.py's own design exists to avoid.
# Brier skill score is measured against the always-UP-at-the-base-rate
# forecast, and that reference is ITSELF reachable by this search: damping
# toward 0 pulls p_up toward the base rate on every day, which on an asset
# that rises 55.7% of the time means predicting UP almost every day. The
# first run of this study picked (damping=0.3, shrink_alpha=120) this way --
# it predicted UP on 99.8% of test-half days (vs production's 87.7%) and
# "improved" BSS/accuracy purely by imitating always-UP more closely, not by
# extracting more information from the components. A combo that votes UP
# this consistently is not measuring ensemble skill, it is rediscovering the
# base rate through the back door -- exactly what component_evidence()
# assigns zero credit for by design. Any candidate this one-sided is
# rejected regardless of its score, the same way retrain.py's "SABIT? tek
# yonlu" flags a component that never takes the other side.
DEGENERATE_UP_RATE = 0.95


def build_signal_frame(df: pd.DataFrame, gold) -> pd.DataFrame:
    """One row per day technical, ml AND macro all produced an out-of-sample
    call, with each component's direction/confidence -- ml_model.ml_signal's
    own confidence formula (|proba_up - 0.5| * 2) is reproduced here rather
    than re-derived, since edge.walk_forward only returns proba_up."""
    ml_out = edge.walk_forward(df, HORIZON)
    tech_out = edge.technical_walk(df, HORIZON, gold.price_scales)
    macro_out = edge.macro_walk(df, HORIZON, gold.leading_drivers)

    merged = ml_out[["time", "close", "label"]].copy()
    merged["ml_direction"] = np.where(ml_out["proba_up"].to_numpy() >= 0.5, "UP", "DOWN")
    merged["ml_confidence"] = np.abs(ml_out["proba_up"].to_numpy() - 0.5) * 2

    merged = merged.merge(
        tech_out[["time", "direction", "confidence"]].rename(
            columns={"direction": "technical_direction", "confidence": "technical_confidence"}),
        on="time", how="inner")
    merged = merged.merge(
        macro_out[["time", "direction", "confidence"]].rename(
            columns={"direction": "macro_direction", "confidence": "macro_confidence"}),
        on="time", how="inner")
    return merged.reset_index(drop=True)


def rolling_records(merged: pd.DataFrame, component: str) -> dict[str, np.ndarray]:
    """As-of-day-i rolling (up_correct, up_calls, down_correct, down_calls)
    for one component -- the last RECORD_WINDOW_ROWS resolved calls, exactly
    like retrain.rebuild_component_records, computed vectorised instead of a
    per-row loop. shift(HORIZON) is what keeps day i from seeing its own, or
    any still-unresolved, outcome."""
    direction = merged[f"{component}_direction"]
    confidence = merged[f"{component}_confidence"]
    is_up = ((confidence > 0) & (direction == "UP")).astype(int)
    is_down = ((confidence > 0) & (direction == "DOWN")).astype(int)
    correct = (merged["label"] == 1).astype(int)
    up_correct = is_up & correct
    down_correct = is_down & (1 - correct)

    window = retrain.RECORD_WINDOW_ROWS

    def asof(series: pd.Series) -> np.ndarray:
        return series.shift(HORIZON, fill_value=0).rolling(window, min_periods=1).sum().to_numpy()

    return {
        "up_calls": asof(is_up), "up_correct": asof(up_correct),
        "down_calls": asof(is_down), "down_correct": asof(down_correct),
    }


def pooled_p_up(merged: pd.DataFrame, records: dict[str, dict[str, np.ndarray]],
                base_rate: float, correlation_damping: float, shrink_alpha: float) -> np.ndarray:
    """Run the REAL ensemble.combine() over every day for one (damping,
    shrink_alpha) candidate. A Python loop, but a cheap one -- no fitting,
    combine() is a handful of logit/exp calls. Columns are pulled to numpy
    ONCE before the loop; indexing a DataFrame column by name inside a
    4891-row x 40-combo loop would redo the column lookup on every element."""
    n = len(merged)
    directions = {c: merged[f"{c}_direction"].to_numpy() for c in COMPONENTS}
    confidences = {c: merged[f"{c}_confidence"].to_numpy() for c in COMPONENTS}
    out = np.empty(n)
    for i in range(n):
        signals = {c: {"direction": directions[c][i], "confidence": confidences[c][i]}
                  for c in COMPONENTS}
        recs = {c: {"up": (records[c]["up_correct"][i], records[c]["up_calls"][i]),
                    "down": (records[c]["down_correct"][i], records[c]["down_calls"][i])}
                for c in COMPONENTS}
        result = ensemble.combine(signals, records=recs, base_rate=base_rate,
                                  correlation_damping=correlation_damping, shrink_alpha=shrink_alpha)
        out[i] = result["p_up"]
    return out


def disagreement_of(merged: pd.DataFrame, pooled_direction: np.ndarray) -> np.ndarray:
    """Fraction of VOTING (non-abstaining) components whose direction
    differs from the pooled call, per day. 0.0 = unanimous (including "only
    one component spoke, so nothing to disagree with")."""
    n = len(merged)
    directions = {c: merged[f"{c}_direction"].to_numpy() for c in COMPONENTS}
    confidences = {c: merged[f"{c}_confidence"].to_numpy() for c in COMPONENTS}
    out = np.zeros(n)
    for i in range(n):
        voters = [directions[c][i] for c in COMPONENTS if confidences[c][i] > 0]
        if not voters:
            continue
        disagreeing = sum(1 for d in voters if d != pooled_direction[i])
        out[i] = disagreeing / len(voters)
    return out


def main() -> int:
    gold = assets_module.GOLD
    raw = panel_module.load(gold.key).reset_index(drop=True)
    df = build_features(raw, drivers=gold.leading_drivers)
    roundtrip_bps = gold.fee_rate * 2 * 10_000.0
    closes_full = df["close"].to_numpy(dtype=float)
    mean_move = float(np.mean(np.abs(closes_full[HORIZON:] / closes_full[:-HORIZON] - 1.0)))

    merged = build_signal_frame(df, gold)
    n = len(merged)
    split = n // 2
    print(f"Birlesik satir: {n}  EGITIM: {merged['time'].iloc[0].date()} -> "
          f"{merged['time'].iloc[split - 1].date()}  TEST: {merged['time'].iloc[split].date()} -> "
          f"{merged['time'].iloc[-1].date()}\n")

    records = {c: rolling_records(merged, c) for c in COMPONENTS}
    labels = merged["label"].to_numpy()

    # ---- Arama 1: CORRELATION_DAMPING x SHRINK_ALPHA -----------------------
    print("=" * 78)
    print("ARAMA 1: CORRELATION_DAMPING x SHRINK_ALPHA (Brier beceri skoruna gore)")
    print("=" * 78)

    def brier_skill(p_up: np.ndarray, y: np.ndarray) -> float:
        base_up = float(np.mean(y))
        brier = float(np.mean((p_up - y) ** 2))
        ref = float(np.mean((np.full_like(y, base_up) - y) ** 2))
        return 1 - brier / ref if ref > 0 else float("nan")

    p_up_grid: dict[tuple[float, float], np.ndarray] = {}
    for d in CORRELATION_DAMPING_GRID:
        for s in SHRINK_ALPHA_GRID:
            p_up_grid[(d, s)] = pooled_p_up(merged, records, gold.base_rate_up, d, s)

    train_bss = {combo: brier_skill(p[:split], labels[:split]) for combo, p in p_up_grid.items()}
    print("EGITIM YARISI -- Brier beceri skoru (satir=damping, sutun=shrink_alpha)")
    print("      " + "".join(f"{s:>9d}" for s in SHRINK_ALPHA_GRID))
    for d in CORRELATION_DAMPING_GRID:
        row = f"{d:>5.1f} "
        for s in SHRINK_ALPHA_GRID:
            row += f"{train_bss[(d, s)]:>9.4f}"
        print(row)

    chosen_ds = max(train_bss, key=train_bss.get)
    print(f"\n>>> EGITIMDE SECILEN: damping={chosen_ds[0]} shrink_alpha={chosen_ds[1]} "
          f"(beceri {train_bss[chosen_ds]:+.4f}, "
          f"uretim {PRODUCTION_DAMPING_SHRINK} beceri {train_bss[PRODUCTION_DAMPING_SHRINK]:+.4f})")

    ds_combos = sorted({PRODUCTION_DAMPING_SHRINK, chosen_ds})
    print("\nTEST YARISI (gorulmemis)")
    test_bss = {}
    up_rate = {}
    for combo in ds_combos:
        label = "URETIM" if combo == PRODUCTION_DAMPING_SHRINK else "SECILEN"
        p = p_up_grid[combo][split:]
        test_bss[combo] = brier_skill(p, labels[split:])
        up_rate[combo] = float(np.mean(p >= 0.5))
        edge.report(f"{label} (damping={combo[0]}, shrink_alpha={combo[1]})",
                    (p >= 0.5).astype(float), labels[split:], HORIZON, mean_move, p, roundtrip_bps)
        print(f"    YUKSELIS tahmin orani (test): %{100 * up_rate[combo]:.1f}")

    if chosen_ds == PRODUCTION_DAMPING_SHRINK:
        print(f"\n>>> ARAMA URETIMDEKINDEN FARKLI BIR SEY BULMADI: {PRODUCTION_DAMPING_SHRINK} "
              "egitim yarisinda zaten en iyisiydi.")
        winning_ds = PRODUCTION_DAMPING_SHRINK
    elif up_rate[chosen_ds] >= DEGENERATE_UP_RATE:
        print(f"\n>>> SECILEN KOMBINASYON TEST YARISINDA DAHA IYI SKOR ALDI AMA GUNLERIN "
              f"%{100 * up_rate[chosen_ds]:.1f}'INDE YUKSELIS DIYOR (uretim: %{100 * up_rate[PRODUCTION_DAMPING_SHRINK]:.1f}) "
              "-- bu bir kalibrasyon kazanci degil, hep-YUKARI'yi taklit etmek. ensemble.py'nin "
              "component_evidence() tam olarak bunu sifir kanit sayacak sekilde tasarlandi; arama "
              "kendi metrigiyle ayni illuzyonu yeniden kesfetti. ensemble.py DEGISMEYECEK.")
        winning_ds = PRODUCTION_DAMPING_SHRINK
    else:
        delta = test_bss[chosen_ds] - test_bss[PRODUCTION_DAMPING_SHRINK]
        if delta <= 0:
            print(f"\n>>> SECILEN KOMBINASYON EGITIMDE ONE CIKTI AMA TEST YARISINDA URETIMDEN "
                  f"{delta:+.4f} BECERI -- gurultuydu, ensemble.py DEGISMEYECEK.")
            winning_ds = PRODUCTION_DAMPING_SHRINK
        else:
            print(f"\n>>> SECILEN KOMBINASYON TEST YARISINDA URETIMDEN {delta:+.4f} BECERI DAHA IYI "
                  "-- ensemble.CORRELATION_DAMPING/SHRINK_ALPHA'ya tasinacak.")
            winning_ds = chosen_ds

    # ---- Arama 2: anlasmazlik bazli boyutlandirma ---------------------------
    print("\n" + "=" * 78)
    print("ARAMA 2: DISAGREEMENT_TILT (Calmar'a gore, secilen/uretim damping+shrink ile)")
    print("=" * 78)

    winning_p_up = p_up_grid[winning_ds]
    pooled_direction = np.where(winning_p_up >= 0.5, "UP", "DOWN")
    pooled_confidence = np.abs(winning_p_up - 0.5) * 2
    disagreement = disagreement_of(merged, pooled_direction)
    print(f"Ortalama anlasmazlik: %{100 * float(np.mean(disagreement)):.1f}  "
          f"(gunlerin %{100 * float(np.mean(disagreement > 0)):.1f}'inde en az bir bilesen ayrisiyor)")

    trend_average = df["close"].rolling(trading.TREND_WINDOW).mean()
    volatility = (df["close"].pct_change().rolling(trading.VOL_LOOKBACK_DAYS).std()
                  * np.sqrt(252.0))
    sizing = merged[["time", "close"]].merge(
        pd.DataFrame({"time": df["time"], "trend_average": trend_average, "volatility": volatility}),
        on="time", how="left")
    closes = sizing["close"].to_numpy(dtype=float)
    trend_arr = sizing["trend_average"].to_numpy()
    vol_arr = sizing["volatility"].to_numpy()

    def target_for(tilt: float) -> np.ndarray:
        return np.array([
            trading.compute_target_exposure(
                "ensemble", closes[i], trend_arr[i], vol_arr[i],
                pooled_direction[i], pooled_confidence[i], gold.target_volatility,
                disagreement=disagreement[i], disagreement_tilt=tilt)
            for i in range(n)
        ])

    def calmar_for(target: np.ndarray, lo: int, hi: int) -> float:
        years = (merged["time"].iloc[hi - 1] - merged["time"].iloc[lo]).days / 365.25
        equity, held = defense.simulate(closes[lo:hi], target[lo:hi], roundtrip_bps)
        return defense.metrics(equity, held, years)["calmar"]

    train_calmar = {t: calmar_for(target_for(t), 0, split) for t in DISAGREEMENT_TILT_GRID}
    print("EGITIM YARISI -- Calmar")
    for t in DISAGREEMENT_TILT_GRID:
        print(f"  disagreement_tilt={t:.2f}   Calmar={train_calmar[t]:.3f}")

    chosen_tilt = max(train_calmar, key=train_calmar.get)
    print(f"\n>>> EGITIMDE SECILEN: disagreement_tilt={chosen_tilt} "
          f"(egitim Calmar {train_calmar[chosen_tilt]:.3f})")

    test_calmar = {t: calmar_for(target_for(t), split, n) for t in {0.0, chosen_tilt}}
    print("\nTEST YARISI (gorulmemis)")
    for t in sorted(test_calmar):
        label = "TILT YOK (uretim)" if t == 0.0 else "SECILEN"
        print(f"  {label:<20} disagreement_tilt={t:.2f}   Calmar={test_calmar[t]:.3f}")

    if chosen_tilt == 0.0:
        print("\n>>> EGITIM disagreement_tilt=0 SECTI: anlasmazlik pozisyon boyutuna "
              "bir sey katmiyor.")
    else:
        delta = test_calmar[chosen_tilt] - test_calmar[0.0]
        if delta <= 0:
            print(f"\n>>> SECILEN TILT EGITIMDE ONE CIKTI AMA TEST YARISINDA TILT=0'DAN "
                  f"{delta:+.3f} CALMAR -- gurultuydu, trading.py DEGISMEYECEK.")
        else:
            print(f"\n>>> SECILEN TILT TEST YARISINDA TILT=0'DAN {delta:+.3f} CALMAR DAHA IYI "
                  "-- trading.py'ye bir DISAGREEMENT_TILT sabiti olarak tasinacak.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
