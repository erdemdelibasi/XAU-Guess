"""Where should the ML component's direction be cut -- at 0.5, or at the prior?

THE OBSERVATION
---------------
This repo corrects for the base rate almost everywhere. `ensemble.py` pools
evidence as a likelihood ratio against it, `calibration.py` anchors isotonic
on it, `daily_report.py` and `app.js` headline `edge_over_base` instead of
confidence, and `research/edge.py`'s own docstring says in as many words that
beating 50% proves nothing on an asset that rises 55.7% of the time.

One place does not: `ml_model.ml_signal` reports

    direction = "UP" if proba_up >= 0.5

The model outputs a probability and the prior is known to be 0.557 (gold) /
0.539 (silver). A day where the model says 0.52 is a day it thinks the metal
is LESS likely to rise than an empty forecast does -- and the component
reports it as UP. `research/edge.py` scores the same rule at the same 0.5.

Why it matters more here than it would elsewhere: `ensemble.combine` consumes
a component's SIGN and its historical record, never its per-day magnitude. So
the only channel the model's probability has into the blend is which side of
the threshold it lands on. Put the threshold on the wrong side of the prior
and the UP bucket is diluted with sub-prior days, which is precisely the
condition under which `component_evidence` correctly returns ~0 and the
component goes silent.

THE PRE-REGISTRATION -- written before the first run
----------------------------------------------------
The threshold moves from 0.5 to the asset's own base rate only if, on the
SAME walk-forward rows, in BOTH metals:

  (1) BOTH sides clear their own ignorance point:
      P(up | said UP) > base_rate AND P(down | said DOWN) > 1 - base_rate.
      This is the condition 0.5 is suspected of breaking, and a rule that
      only fixes one side is not obviously better than the one it replaces.

  (2) The PREQUENTIAL Brier skill of the component's pooled posterior --
      logit(base) + component_evidence(...) * damping, with the counters
      built strictly from earlier rows, exactly as production accumulates
      them -- is both positive and higher than under 0.5.

  (3) Neither metal's smaller side fires fewer than 200 times. A side that
      speaks twenty times in twenty years is not a measurement, and a rule
      whose DOWN calls are that rare cannot contribute in live use either.

Anything short of all three: production keeps 0.5 and the negative result is
recorded here, with the power of the test beside it.

METHOD
------
`edge.walk_forward` produces the out-of-sample probabilities -- the same
function production's model is refit by, so this measures the threshold and
not a second implementation of the model. Both arms score the SAME rows, so
the comparison is paired: the only thing that differs between them is the
number the probability is compared against.

The ignorance points are this sample's own realised rate, not assets.py's
constant, because a threshold has to be judged against the drift the test
rows actually had. Both are printed; they differ by well under a point.

Run:  cd backend/research && python threshold.py      (~3 min, both metals)
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
import ensemble  # noqa: E402
import ml_model  # noqa: E402
import panel as panel_module  # noqa: E402
from edge import walk_forward  # noqa: E402
from indicators import build_features  # noqa: E402

HORIZON = ml_model.HORIZON_DAYS
# Pre-registered, from the docstring. Restated as code so the verdict cannot
# drift from the sentence that declared it.
MIN_SIDE_CALLS = 200


def sides(proba: np.ndarray, labels: np.ndarray, cut: float) -> dict:
    """The two buckets a threshold produces, with each one's own hit rate."""
    said_up = proba >= cut
    up_n = int(said_up.sum())
    down_n = int((~said_up).sum())
    return {
        "cut": cut,
        "up_n": up_n,
        "up_correct": int(labels[said_up].sum()) if up_n else 0,
        "p_up_given_up": float(labels[said_up].mean()) if up_n else float("nan"),
        "down_n": down_n,
        "down_correct": int((1 - labels[~said_up]).sum()) if down_n else 0,
        "p_down_given_down": float((1 - labels[~said_up]).mean()) if down_n else float("nan"),
    }


def z_for(rate: float, n: int, null: float, horizon: int = HORIZON) -> float:
    """z against an ignorance point, with the overlap correction edge.py uses.

    At horizon h consecutive rows share h-1 days of outcome, so the effective
    sample is n/h. Reporting the naive z here would make a 5,000-row panel
    look like 5,000 independent coin flips, which is the inflation this
    project's every negative result is careful to avoid.
    """
    n_eff = max(n / horizon, 1.0)
    if n_eff <= 1 or not np.isfinite(rate):
        return float("nan")
    return (rate - null) / math.sqrt(max(null * (1 - null), 1e-9) / n_eff)


def prequential_brier(proba: np.ndarray, labels: np.ndarray, cut: float,
                      base_rate: float) -> tuple[float, int]:
    """Brier of the pooled posterior this threshold implies, scored honestly.

    For every row the component's record is built from EARLIER rows only --
    the counters production accumulates in `model_state`, replayed. The
    posterior is then the one `ensemble.combine` would produce from this
    component alone:

        logit(base) + component_evidence(direction, up_rec, down_rec) * damping

    Rows before either side has any record contribute the prior itself, which
    is what combine() falls back to, so both arms are scored on every row.
    """
    up_correct = up_total = down_correct = down_total = 0
    squared = 0.0
    for p, y in zip(proba, labels):
        direction = "UP" if p >= cut else "DOWN"
        evidence = ensemble.component_evidence(
            direction, (up_correct, up_total), (down_correct, down_total), base_rate)
        logodds = ensemble._logit(base_rate) + evidence * ensemble.CORRELATION_DAMPING
        p_hat = 1.0 / (1.0 + math.exp(-logodds))
        squared += (p_hat - y) ** 2
        if direction == "UP":
            up_total += 1
            up_correct += int(y == 1)
        else:
            down_total += 1
            down_correct += int(y == 0)
    n = len(labels)
    return (squared / n if n else float("nan")), n


def report_asset(asset) -> dict:
    raw = panel_module.load(asset.key).reset_index(drop=True)
    df = build_features(raw, drivers=asset.leading_drivers)
    out = walk_forward(df, HORIZON)
    if out.empty:
        print(f"  {asset.label}: veri yok")
        return {}

    proba = out["proba_up"].to_numpy(dtype=float)
    labels = out["label"].to_numpy(dtype=float)
    realised = float(labels.mean())
    constant = asset.base_rate_up

    print(f"\n{'#' * 78}\n### {asset.label.upper()} -- ML yon esigi\n{'#' * 78}")
    print(f"  {len(out)} ornek disi satir, {out['time'].iloc[0].date()} -> "
          f"{out['time'].iloc[-1].date()}")
    print(f"  Taban oran: bu satirlarda %{100 * realised:.2f}, "
          f"assets.py'de %{100 * constant:.1f}")
    print(f"  proba_up dagilimi: min %{100 * proba.min():.1f}  "
          f"ort %{100 * proba.mean():.1f}  medyan %{100 * np.median(proba):.1f}  "
          f"maks %{100 * proba.max():.1f}")
    print(f"  proba_up < 0,5: {int((proba < 0.5).sum())} satir | "
          f"< taban: {int((proba < realised).sum())} satir")

    arms = {"0,50 (uretim)": 0.5, f"{realised:.3f} (taban)": realised}
    results = {}
    print(f"\n  {'esik':>16}{'UP der':>9}{'P(up|UP)':>11}{'fark':>8}{'z':>7}"
          f"{'DOWN der':>10}{'P(dn|DN)':>11}{'fark':>8}{'z':>7}")
    print("  " + "-" * 87)
    for name, cut in arms.items():
        s = sides(proba, labels, cut)
        lift_up = s["p_up_given_up"] - realised
        lift_dn = s["p_down_given_down"] - (1 - realised)
        z_up = z_for(s["p_up_given_up"], s["up_n"], realised)
        z_dn = z_for(s["p_down_given_down"], s["down_n"], 1 - realised)
        print(f"  {name:>16}{s['up_n']:>9}{100 * s['p_up_given_up']:>10.2f}%"
              f"{100 * lift_up:>+7.2f}{z_up:>7.2f}"
              f"{s['down_n']:>10}{100 * s['p_down_given_down']:>10.2f}%"
              f"{100 * lift_dn:>+7.2f}{z_dn:>7.2f}")
        brier, n = prequential_brier(proba, labels, cut, realised)
        results[name] = {**s, "lift_up": lift_up, "lift_down": lift_dn,
                         "brier": brier, "n": n}

    # The prior-only forecast is what a component has to beat to be worth
    # pooling at all: predict the base rate every single day.
    brier_prior = float(np.mean((realised - labels) ** 2))
    print(f"\n  Prequential Brier (dusuk daha iyi) -- yalnizca prior: {brier_prior:.5f}")
    for name, res in results.items():
        skill = 1.0 - res["brier"] / brier_prior
        res["skill"] = skill
        print(f"    {name:>16}: {res['brier']:.5f}  beceri {100 * skill:>+6.3f}%")

    # Transparency grid. NOT the verdict -- the two arms above are.
    print("\n  Seffaflik: esik taramasi (hukum DEGIL, yukaridaki iki kol hukum)")
    print(f"    {'esik':>7}{'UP der':>9}{'fark':>8}{'DOWN der':>10}{'fark':>8}")
    for cut in (0.45, 0.48, 0.50, 0.52, 0.54, 0.56, 0.58, 0.60):
        s = sides(proba, labels, cut)
        print(f"    {cut:>7.2f}{s['up_n']:>9}{100 * (s['p_up_given_up'] - realised):>+8.2f}"
              f"{s['down_n']:>10}"
              f"{100 * (s['p_down_given_down'] - (1 - realised)):>+8.2f}")
    return {"asset": asset, "realised": realised, "arms": results}


def verdict(all_results: list[dict]) -> None:
    print("\n" + "=" * 78)
    print("  ON-KAYITLI BARAJA KARSI HUKUM")
    print("=" * 78)
    print("  (1) iki taraf da kendi bilgisizlik noktasini gecmeli")
    print("  (2) prequential Brier becerisi pozitif VE 0,50'ninkinden yuksek")
    print(f"  (3) kucuk taraf en az {MIN_SIDE_CALLS} kez konusmali")
    print("  Uc sart, IKI metalde birden.\n")

    passed = True
    for res in all_results:
        if not res:
            passed = False
            continue
        label = res["asset"].label
        names = list(res["arms"])
        prod, cand = res["arms"][names[0]], res["arms"][names[1]]
        c1 = cand["lift_up"] > 0 and cand["lift_down"] > 0
        c2 = cand["skill"] > 0 and cand["skill"] > prod["skill"]
        c3 = min(cand["up_n"], cand["down_n"]) >= MIN_SIDE_CALLS
        passed &= c1 and c2 and c3
        print(f"  {label:<8} (1) {'EVET' if c1 else 'HAYIR'}   "
              f"(2) {'EVET' if c2 else 'HAYIR'} "
              f"(beceri {100 * cand['skill']:+.3f}% vs {100 * prod['skill']:+.3f}%)   "
              f"(3) {'EVET' if c3 else 'HAYIR'} (kucuk taraf {min(cand['up_n'], cand['down_n'])})")

    print()
    if passed:
        print("  HUKUM: esik taban orana tasinir (ml_model.ml_signal).")
    else:
        print("  HUKUM: esik 0,5'te KALIR. Negatif sonuc kayda gecer.")


def main() -> int:
    results = [report_asset(asset) for asset in assets_module.ASSETS.values()]
    verdict(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
