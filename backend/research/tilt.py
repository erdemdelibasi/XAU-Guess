"""The synthesis: use the model to SIZE the position, not to pick the side.

Two studies in this bench point at the same conclusion from opposite ends.

  research/edge.py -- the model beats chance and, at a 5-day horizon, clears
      the cost wall (53.26% against 52.70%, overlap-corrected z=+2.04). But it
      never beats "always UP" (55.2%), and its Brier skill score is negative
      at every horizon. So there IS information in it, and it is NOT enough
      to decide which side to be on.

  research/defense.py -- rolling, out-of-sample position sizing beat
      buy-and-hold on Calmar (0.28 vs 0.24) and Sharpe (0.64 vs 0.58) by
      cutting maximum drawdown from 44.4% to 30.1%, for 2.1 points of CAGR.

Read together they say: gold's drift is real and worth capturing, the model
cannot improve on being long, but HOW MUCH to be long is a question the model
might answer even when "long or short" is one it cannot.

That is not a workaround, it is the standard reading of a weak signal. A
forecast with a small edge and poor calibration is far better spent tilting an
exposure around a positive baseline than flipping it between 0% and 100%,
because a flip pays full transaction cost to act on a signal barely
distinguishable from noise -- exactly the churn that ate XRP-Guess's
portfolios (11 full round trips in 19 hours, every one paying fees, while the
trend it was trying to catch ran away).

So:  exposure = clip(BASE + TILT x signal, 0, MAX)

BASE > 0 means the default is long, which is what 25 years of data supports.
TILT is how much the model is allowed to move it. TILT = 0 recovers a fixed
long; BASE = 0, TILT = 1 recovers the binary long/flat rule that already
failed. The question is whether anything in between is better than both.

Discipline unchanged: BASE and TILT are chosen on the first half only, and
the single chosen pair runs once on the second.

RESULT (2026-09-07) -- negative, and worth reading before trying this again:

  * The ML-only grid chose TILT = 0.0 on the training half. That is the
    training data saying, unprompted, that the model adds nothing to position
    size. The test half agreed exactly (identical rows).
  * The blended grid chose TILT = 0.4 out of a training surface that was flat
    to two decimals (0.13-0.15 everywhere) -- i.e. it picked noise. Out of
    sample the tilt was worth +0.011 Calmar and -0.029 Sharpe. Nothing.

METHODOLOGICAL WARNING, discovered by this file and applicable to any future
sizing study here: **Calmar cannot rank BASE.** Scaling exposure by a
constant k scales both CAGR and maximum drawdown by roughly k, so their ratio
is nearly invariant -- measured on the test half, fixed 50% exposure scores
Calmar 0.58 against buy-and-hold's 0.59, and the whole 6x6 grid sits between
0.53 and 0.63. The BASE axis of this search was therefore measuring almost
nothing, and any "best BASE" read off it is an artifact. Only the TILT axis
carried real information, and it said zero.

This is not the same mechanism as research/defense.py's positive result.
Volatility targeting there does not forecast anything: it reacts to realised
volatility, which is strongly autocorrelated and therefore actually
predictable, unlike direction. Do not read defense.py's win as evidence that
the direction model works -- they are separate machines.
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

import defense  # noqa: E402
import edge  # noqa: E402
import ml_model  # noqa: E402
import panel as panel_module  # noqa: E402
from indicators import build_features, technical_signal  # noqa: E402

HORIZON = 5           # where edge.py found the model clears the cost wall
ETF_BPS = 10
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "walkforward_h5.json")

BASE_GRID = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
TILT_GRID = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
MAX_EXPOSURE = 1.0


def load_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Walk-forward out-of-sample probabilities, cached.

    edge.py's walk_forward is the single source of these numbers -- recomputing
    them with a copy of the loop would let the two studies silently disagree
    about what the model said.
    """
    if os.path.exists(CACHE):
        cached = pd.read_json(CACHE)
        cached["time"] = pd.to_datetime(cached["time"], utc=True)
        return cached

    print("Yuruyen-ileri sinyaller hesaplaniyor (onbellek yok)...", flush=True)
    t0 = time.time()
    ml_out = edge.walk_forward(df, HORIZON)
    tech = edge.technical_walk(df, HORIZON)
    merged = ml_out.merge(tech[["time", "score"]], on="time", how="inner")
    merged.to_json(CACHE)
    print(f"  {len(merged)} satir, {time.time() - t0:.0f} saniye, onbellege alindi", flush=True)
    return merged


def exposure_from(signal: np.ndarray, base: float, tilt: float) -> np.ndarray:
    """signal in -1..1  ->  exposure in [0, MAX_EXPOSURE]."""
    return np.clip(base + tilt * signal, 0.0, MAX_EXPOSURE)


def evaluate_grid(closes: np.ndarray, signal: np.ndarray, times: pd.Series,
                  cost_bps: float) -> dict[tuple[float, float], dict]:
    years = (times.iloc[-1] - times.iloc[0]).days / 365.25
    out = {}
    for base in BASE_GRID:
        for tilt in TILT_GRID:
            target = exposure_from(signal, base, tilt)
            equity, held = defense.simulate(closes, target, cost_bps)
            out[(base, tilt)] = defense.metrics(equity, held, years)
    return out


def main() -> int:
    raw = panel_module.load().reset_index(drop=True)
    df = build_features(raw)
    signals = load_signals(df)

    closes = signals["close"].to_numpy(dtype=float)
    times = signals["time"]
    # Two signals on one -1..1 scale, then averaged. proba_up is the model's;
    # score is the rule's. Averaging is deliberately the dumbest possible
    # blend -- anything fitted here would be a parameter chosen while looking
    # at the outcome.
    ml_signal = (signals["proba_up"].to_numpy(dtype=float) - 0.5) * 2
    tech_signal = signals["score"].to_numpy(dtype=float)
    blend = np.clip((ml_signal + tech_signal) / 2.0, -1, 1)

    n = len(signals)
    split = n // 2
    print(f"Sinyal satiri: {n}  ({times.iloc[0].date()} -> {times.iloc[-1].date()})")
    print(f"EGITIM: {times.iloc[0].date()} -> {times.iloc[split - 1].date()}")
    print(f"TEST  : {times.iloc[split].date()} -> {times.iloc[-1].date()}")
    print(f"\nUfuk {HORIZON} gun, maliyet {ETF_BPS} bp, maks pozisyon %{100 * MAX_EXPOSURE:.0f}")

    for label, signal in (("HARMAN (ML+teknik)", blend), ("sadece ML", ml_signal)):
        print("\n" + "=" * 92)
        print(f"### SINYAL: {label}")
        print("=" * 92)

        train_grid = evaluate_grid(closes[:split], signal[:split], times.iloc[:split], ETF_BPS)

        print("\nEGITIM YARISI -- Calmar (satir=BASE taban pozisyon, sutun=TILT egim gucu)")
        print("      " + "".join(f"{t:>9.1f}" for t in TILT_GRID))
        for base in BASE_GRID:
            row = f"{base:>5.1f} "
            for tilt in TILT_GRID:
                row += f"{train_grid[(base, tilt)]['calmar']:>9.2f}"
            print(row)

        chosen = max(train_grid, key=lambda k: train_grid[k]["calmar"])
        c_base, c_tilt = chosen
        print(f"\n>>> EGITIMDE SECILEN: BASE={c_base:.1f}  TILT={c_tilt:.1f}  "
              f"(egitim Calmar {train_grid[chosen]['calmar']:.2f})")

        test_grid = evaluate_grid(closes[split:], signal[split:], times.iloc[split:], ETF_BPS)
        years_test = (times.iloc[-1] - times.iloc[split]).days / 365.25

        bh_equity, bh_held = defense.simulate(closes[split:], np.ones(n - split), ETF_BPS)
        bh = defense.metrics(bh_equity, bh_held, years_test)
        picked = test_grid[chosen]
        # The same BASE with no tilt at all: isolates what the model actually
        # contributed from what simply holding less gold contributed.
        flat_same_base = test_grid[(c_base, 0.0)]

        print("\nTEST YARISI (gorulmemis)")
        print(f"{'':<28}{'YBG':>9}{'oynak':>9}{'Sharpe':>9}{'maks dusus':>13}{'Calmar':>9}{'piyasada':>10}")
        for name, m in (("al-ve-tut (%100)", bh),
                        (f"sabit %{100 * c_base:.0f} (egim YOK)", flat_same_base),
                        (f"BASE={c_base:.1f} TILT={c_tilt:.1f}", picked)):
            print(f"  {name:<26}{100 * m['cagr']:>8.1f}%{100 * m['vol']:>8.1f}%{m['sharpe']:>9.2f}"
                  f"{100 * m['max_dd']:>12.1f}%{m['calmar']:>9.2f}{100 * m['exposure']:>9.0f}%")

        print(f"\n  Egimin KENDI katkisi (ayni tabana gore): "
              f"Calmar {picked['calmar'] - flat_same_base['calmar']:+.3f}, "
              f"Sharpe {picked['sharpe'] - flat_same_base['sharpe']:+.3f}, "
              f"YBG {100 * (picked['cagr'] - flat_same_base['cagr']):+.2f}p")
        if c_tilt == 0.0:
            print("  >>> EGITIM TILT=0 SECTI: model pozisyon boyutuna da bir sey katmiyor.")
        elif picked["calmar"] > flat_same_base["calmar"]:
            print("  >>> Egim, ayni tabanli sabit pozisyondan Calmar olarak IYI.")
        else:
            print("  >>> Egim, ayni tabanli sabit pozisyondan Calmar olarak KOTU "
                  "(model sinyali boyutlandirmada da yardim etmiyor).")

        print("\n  TEST yarisinda tam izgara (SECIM DEGIL, sadece baglam) -- Calmar:")
        print("      " + "".join(f"{t:>9.1f}" for t in TILT_GRID))
        for base in BASE_GRID:
            row = f"{base:>5.1f} "
            for tilt in TILT_GRID:
                row += f"{test_grid[(base, tilt)]['calmar']:>9.2f}"
            print(row)

    return 0


if __name__ == "__main__":
    sys.exit(main())
