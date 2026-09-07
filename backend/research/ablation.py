"""Why is the ML component stuck at the base rate -- the label, or the features?

research/edge.py established the uncomfortable fact and research/ratio.py
restated it on the production feature set: walk-forward, gold's classifier
scores 53.15% against a 55.3% always-UP baseline, silver's 51.24% against
52.6%. Neither gap is significant on its own -- with overlap accounted for the
standard error is ~1.6 points -- but the direction never changes, across
horizons, across metals, across feature sets. The model reliably fails to beat
a constant.

Before adding anything else to it, this file asks WHY, because the two
candidate explanations call for opposite work:

  A. **The label.** 55.7% of gold's training labels are 1. A classifier
     minimising log-loss learns the marginal first, and predicting 0.557
     everywhere is already close to optimal -- so the training objective
     barely rewards finding deviation. On this reading the model is not
     failing to beat the base rate; it is faithfully reproducing it, because
     that is what it was asked to do. The fix would be a label with the drift
     removed, which is also the shape ensemble.py already wants: it pools
     components as likelihood ratios AGAINST the base rate, so a component
     that predicts EXCESS is the natural input and one that predicts the
     level is partly duplicating a number the ensemble already holds.

  B. **The features.** Nothing in the 27 columns carries directional
     information at a five-day horizon, and no relabelling will conjure it.

These make different predictions, so they are separable. Every variant below
is scored on ONE label-agnostic yardstick -- the information coefficient,
i.e. the correlation between the out-of-sample probability and the actual
forward return. Accuracy cannot be compared across labels (each label has its
own base rate and its own trivial score), but IC can: it asks whether the
signal ranks future returns, whatever it was trained to say.

Pre-registered, because best-of-N is how a bench manufactures results:
  Part A -- 3 alternative labels
  Part B -- 4 alternative feature sets
x 2 metals = 14 comparisons, Bonferroni bar p < 0.05/14.
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
from scipy import stats as scipy_stats  # noqa: E402

import assets as assets_module  # noqa: E402
import edge  # noqa: E402
import ml_model  # noqa: E402
import panel as panel_module  # noqa: E402

HORIZON = ml_model.HORIZON_DAYS
DRIFT_WINDOW = 250          # trailing window for the drift a label is measured against
N_COMPARISONS = 14
BONFERRONI_P = 0.05 / N_COMPARISONS


# --------------------------------------------------------------------------
# Part A: label variants
# --------------------------------------------------------------------------

def label_raw(df: pd.DataFrame, horizon: int) -> np.ndarray:
    """Production label: did it close higher, full stop."""
    future = df["close"].shift(-horizon)
    return np.where(future.notna(), (future > df["close"]).astype(float), np.nan)


def label_excess_median(df: pd.DataFrame, horizon: int) -> np.ndarray:
    """Did it beat its OWN recent typical move?

    The comparison level is the trailing median h-day return, computed only
    from returns already known at row t -- shift(horizon) before rolling, or
    the window would contain the very outcome being labelled. This is the
    single easiest place in the file to leak the future, and it leaks
    invisibly: the label would still look like a plausible 50/50 split.
    """
    fwd = df["close"].shift(-horizon) / df["close"] - 1.0
    known = fwd.shift(horizon)
    drift = known.rolling(DRIFT_WINDOW, min_periods=100).median()
    return np.where(fwd.notna() & drift.notna(), (fwd > drift).astype(float), np.nan)


def label_excess_mean(df: pd.DataFrame, horizon: int) -> np.ndarray:
    """Same idea against the trailing mean -- more sensitive to the big moves
    the median deliberately ignores, which for a metal is not obviously the
    wrong choice."""
    fwd = df["close"].shift(-horizon) / df["close"] - 1.0
    known = fwd.shift(horizon)
    drift = known.rolling(DRIFT_WINDOW, min_periods=100).mean()
    return np.where(fwd.notna() & drift.notna(), (fwd > drift).astype(float), np.nan)


def label_strong_up(df: pd.DataFrame, horizon: int) -> np.ndarray:
    """Is a LARGE up-move coming (> +0.5 trailing sigma)?

    A different question from direction, and a more useful one for a system
    whose only measured edge is position sizing: "a big move is coming" is
    actionable even when "which way" is not.
    """
    fwd = df["close"].shift(-horizon) / df["close"] - 1.0
    known = fwd.shift(horizon)
    sigma = known.rolling(DRIFT_WINDOW, min_periods=100).std()
    return np.where(fwd.notna() & sigma.notna(), (fwd > 0.5 * sigma).astype(float), np.nan)


LABELS = {
    "L0 ham yon (uretim)": label_raw,
    "L1 medyan surukleme ustu": label_excess_median,
    "L2 ortalama surukleme ustu": label_excess_mean,
    "L3 buyuk yukselis (>0.5 sigma)": label_strong_up,
}


# --------------------------------------------------------------------------
# Part B: feature-set variants
# --------------------------------------------------------------------------

PRICE_FEATURES = {
    "rsi14", "macd_hist", "bb_pct", "ema9_21", "px_sma200", "px_ema50",
    "return_1d", "return_5d", "return_20d", "return_60d",
    "vol_20d", "vol_ratio", "donchian_pct",
}
CONTEXT_FEATURES = {
    "dxy_chg", "dxy_chg5", "us10y_chg", "us10y_chg5",
    "counterpart_chg", "spx_chg", "gs_ratio_z",
}


def feature_sets(full: list[str]) -> dict[str, list[str]]:
    """Four pre-registered alternatives to the production column list.

    Groups, not single columns. Twenty-seven one-column ablations would be a
    multiple-testing swamp AND individually underpowered: the paired noise
    band on this sample is ~2.3 points, and no single column moves accuracy
    that far. A group has a chance of clearing it and, more importantly, each
    group is a sentence someone can disagree with.
    """
    return {
        "F0 tam set (uretim)": full,
        "F1 5-gunluk makro yok": [c for c in full if not c.endswith("_chg5")],
        "F2 baglam blogu yok": [c for c in full if c not in CONTEXT_FEATURES],
        "F3 sadece fiyat": [c for c in full if c in PRICE_FEATURES],
        "F4 sadece makro": [c for c in full if c not in PRICE_FEATURES],
    }


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

def _t_from_r(r: float, n_eff: float) -> float:
    if not np.isfinite(r) or n_eff <= 2 or abs(r) >= 1:
        return 0.0
    return float(r * math.sqrt(n_eff - 2) / math.sqrt(1 - r * r))


def min_detectable_ic(n_rows: int, horizon: int, bar_t: float) -> float:
    """The smallest IC this sample could have called significant.

    A negative result without this number is not a result. "Nothing passed"
    can mean the effect is absent or that the test could never have seen it,
    and those call for opposite conclusions -- the first closes a line of
    work, the second says buy more data. With ~4900 overlapping rows at a
    five-day horizon the effective sample is under a thousand, and an IC of
    0.05 -- a perfectly respectable number in this kind of work -- sits below
    what that sample can distinguish from zero.
    """
    n_eff = max(n_rows / horizon, 1)
    return float(bar_t / math.sqrt(max(n_eff - 2, 1) + bar_t ** 2))


def score(run: pd.DataFrame, forward: pd.DataFrame, horizon: int) -> dict:
    """Information coefficient plus a directional read, on shared rows.

    IC is the label-agnostic yardstick: correlation between the out-of-sample
    probability and the realised forward return. A model trained on a
    different label produces probabilities on a different scale, but if it
    knows anything about the future its ranking still lines up with returns.

    Accuracy is reported alongside for continuity with edge.py, and uses each
    model's OWN median probability as the decision threshold rather than 0.5.
    A model trained on a 50/50 label and one trained on a 55.7/44.3 label sit
    at different neutral points; scoring both at 0.5 would penalise one of
    them for a calibration difference that has nothing to do with skill.
    """
    merged = run.merge(forward, on="time", how="inner")
    merged = merged.dropna(subset=["proba_up", "fwd_ret", "up"])
    if len(merged) < 100:
        return {}
    p = merged["proba_up"].to_numpy(dtype=float)
    ret = merged["fwd_ret"].to_numpy(dtype=float)
    ic = float(np.corrcoef(p, ret)[0, 1])
    n_eff = max(len(merged) / horizon, 1)
    called_up = p >= np.median(p)
    acc = float((called_up == (merged["up"].to_numpy() > 0.5)).mean())
    # The per-row contribution to the IC, carried WITH its timestamp. Keeping
    # these as a frame rather than a bare array plus a set of times is not
    # tidiness: paired_ic_test joins two variants on time, and a set has no
    # order to join against, so pairing would silently compare mismatched rows.
    contrib = pd.DataFrame({
        "time": merged["time"].to_numpy(),
        "v": (p - p.mean()) * ret,
    })
    return {
        "n": len(merged),
        "ic": ic,
        "t": _t_from_r(ic, n_eff),
        "acc": acc,
        "base": float(merged["up"].mean()),
        "contrib": contrib,
    }


def paired_ic_test(a: dict, b: dict, horizon: int) -> float:
    """p-value for "variant b has a different IC from variant a", on shared rows.

    Two ICs cannot be compared by eye -- they come from overlapping samples and
    are themselves correlated. Comparing the per-row contributions
    (p - mean p) * return as a PAIRED sample is the version of this question
    that has an answer, and the pairing is what removes the shared market
    movement both variants were exposed to.
    """
    joined = a["contrib"].merge(b["contrib"], on="time", suffixes=("_a", "_b"))
    if len(joined) < 100:
        return 1.0
    diff = (joined["v_b"] - joined["v_a"]).to_numpy(dtype=float)
    n_eff = max(len(diff) / horizon, 1)
    sd = float(np.std(diff, ddof=1))
    if sd == 0:
        return 1.0
    t = float(np.mean(diff) / (sd / math.sqrt(n_eff)))
    return float(2 * scipy_stats.norm.sf(abs(t)))


def forward_frame(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    fwd = df["close"].shift(-horizon) / df["close"] - 1.0
    return pd.DataFrame({
        "time": df["time"],
        "fwd_ret": fwd,
        "up": np.where(fwd.notna(), (fwd > 0).astype(float), np.nan),
    })


def main() -> int:
    started = time.time()
    print("=" * 96)
    print("ML BILESENI NEDEN TABAN ORANA TAKILIYOR? -- etiket mi, ozellikler mi?")
    print("=" * 96)
    print(f"  Ufuk {HORIZON} gun. Olcut: BILGI KATSAYISI (IC) = model olasiligi ile")
    print("  gerceklesen ileri getirinin korelasyonu. Etiketten bagimsizdir, o yuzden")
    print("  farkli etiketlerle egitilmis modeller ayni cetvelle olculebilir.")
    print(f"  {N_COMPARISONS} karsilastirma onceden ilan edildi -> Bonferroni p < {BONFERRONI_P:.4f}\n")

    for key in ("gold", "silver"):
        asset = assets_module.get(key)
        panel = panel_module.load(key)
        frame = ml_model.build_feature_frame(panel, drivers=asset.leading_drivers)
        full = ml_model.available_features(frame)
        fwd = forward_frame(frame, HORIZON)

        print("=" * 96)
        print(f"### {asset.label.upper()}  ({len(frame)} satir, {len(full)} ozellik, "
              f"taban oran {asset.base_rate_up:.3f})")
        print("=" * 96)

        bar_t = float(scipy_stats.norm.isf(BONFERRONI_P / 2))
        mdi = min_detectable_ic(len(frame), HORIZON, bar_t)
        print(f"\n  TESTIN GUCU: {len(frame)} satir, ufuk {HORIZON} -> etkin ornek "
              f"~{len(frame) // HORIZON}. Bu orneklemin sifirdan")
        print(f"  ayirt edebilecegi en kucuk IC = {mdi:.3f} (esik |t|>{bar_t:.2f}).")
        print("  Bunun ALTINDAKI gercek bir etki burada 'gurultu' gorunur --")
        print("  asagidaki her negatif bu sinirla birlikte okunmalidir.")

        print("\nA) ETIKET TASARIMI -- ozellikler sabit, sadece sorulan soru degisiyor")
        print(f"{'etiket':<32}{'egitim 1 orani':>16}{'n':>7}{'IC':>9}{'t':>8}"
              f"{'dogruluk':>11}{'p (L0 karsi)':>15}{'karar':>12}")
        label_results = {}
        for name, fn in LABELS.items():
            values = fn(frame, HORIZON)
            run = edge.walk_forward(frame, HORIZON, features=full, label_values=values)
            res = score(run, fwd, HORIZON)
            if not res:
                print(f"{name:<32}  (yetersiz satir)")
                continue
            label_results[name] = res
            share = float(np.nanmean(values))
            baseline = label_results.get("L0 ham yon (uretim)")
            if name == "L0 ham yon (uretim)":
                pval, verdict = float("nan"), "-- temel --"
            else:
                pval = paired_ic_test(baseline, res, HORIZON)
                verdict = "GECTI" if pval < BONFERRONI_P else "gurultu"
            pv = "-" if not np.isfinite(pval) else f"{pval:.4f}"
            print(f"{name:<32}{share:>16.3f}{res['n']:>7}{res['ic']:>+9.4f}{res['t']:>8.2f}"
                  f"{100 * res['acc']:>10.2f}%{pv:>15}{verdict:>12}")

        print("\nB) OZELLIK SETI -- etiket uretimdeki (L0), sadece kolonlar degisiyor")
        print(f"{'set':<32}{'kolon':>16}{'n':>7}{'IC':>9}{'t':>8}"
              f"{'dogruluk':>11}{'p (F0 karsi)':>15}{'karar':>12}")
        sets = feature_sets(full)
        base_label = label_raw(frame, HORIZON)
        feature_results = {}
        for name, cols in sets.items():
            if not cols:
                continue
            run = edge.walk_forward(frame, HORIZON, features=cols, label_values=base_label)
            res = score(run, fwd, HORIZON)
            if not res:
                continue
            feature_results[name] = res
            baseline = feature_results.get("F0 tam set (uretim)")
            if name == "F0 tam set (uretim)":
                pval, verdict = float("nan"), "-- temel --"
            else:
                pval = paired_ic_test(baseline, res, HORIZON)
                verdict = "GECTI" if pval < BONFERRONI_P else "gurultu"
            pv = "-" if not np.isfinite(pval) else f"{pval:.4f}"
            print(f"{name:<32}{len(cols):>16}{res['n']:>7}{res['ic']:>+9.4f}{res['t']:>8.2f}"
                  f"{100 * res['acc']:>10.2f}%{pv:>15}{verdict:>12}")
        print()

    print("=" * 96)
    print(f"Toplam sure: {time.time() - started:.0f} sn")
    print("=" * 96)
    print("  Bir varyantin IC'si yuksek cikip p testini GECEMIYORSA, o varyant")
    print("  secilmemelidir -- en iyisini secmek tam olarak N icinden en iyisini")
    print("  secmektir ve bu tezgahin varlik sebebi onu yapmamaktir.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
