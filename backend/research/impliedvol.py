"""Does the market's own volatility forecast beat the one this system uses?

WHY THIS FILE EXISTS, and why it is not "another feature"
---------------------------------------------------------
research/ablation.py already answered the obvious version of "add more data":
four different feature groups were tested against the production set and none
could be told apart from it, and that study's conclusion was that the answer
is not more features but more independent observations. So bolting another
price-derived column onto the direction model has a measured, low prior, and
research/drivers.py's 2026-09 candidate sweep is where that low-prior question
gets asked.

This file asks a different question, aimed at the one machine in this project
that is measured to WORK. CLAUDE.md's finding 5: the only mechanism with a
demonstrated contribution is volatility-responsive position sizing
(research/defense.py, 19.9 years out of sample, Sharpe 0.58 -> 0.64, maximum
drawdown 44.4% -> 30.1%). And that machine is fed a BACKWARD-looking number --
predict.py:399 takes the standard deviation of the last trading.VOL_LOOKBACK_DAYS
returns, and backtest.py:182 takes the matching vol_60d column.

GVZ (CBOE's gold volatility index) is the market's FORWARD-looking 30-day
estimate of the same quantity. It is the one candidate in the 2026-09 batch
that is not derived from gold's own price history, and it points straight at
the mechanism that already works rather than at the one that does not.

THE TRAP, MEASURED BEFORE THE STUDY WAS WRITTEN
-----------------------------------------------
Implied volatility sits systematically ABOVE realised volatility -- that gap
is the variance risk premium and it is the reason selling options makes money
on average. On this panel GVZ's median is 1.108x trailing realised volatility.

So handing GVZ straight to trading.vol_scale() would multiply every exposure
by roughly 1/1.108 forever. That is not a volatility forecast improving; that
is "hold about 10% less gold" wearing a volatility forecast's name -- the
exact failure assets.py documents for silver's target_volatility, where gold's
15% budget applied to a metal realising 1.86x the volatility was never
volatility targeting at all. The scale correction here is therefore MEASURED,
and measured on the training half only.

TWO PARTS, AND THE SECOND IS GATED ON THE FIRST
------------------------------------------------
Part 1 asks whether GVZ forecasts realised volatility better than the trailing
estimate does. Part 2 asks whether that improvement survives contact with the
trading rule. Running Part 2 alone would be the mistake: if GVZ is not a
better forecast, then any Calmar difference it produces is a scale artefact --
a different average exposure over a window that happens to trend -- and
adopting it would be acting on the artefact.

Part 1 also refuses the easy version of its own question. GVZ and trailing
realised volatility correlate at r=0.85, so "GVZ scores better alone" is
nearly guaranteed and nearly meaningless. The question that matters is whether
GVZ adds anything the trailing estimate does not already carry, which is an
ENCOMPASSING test: regress future volatility on both and see whether GVZ's
coefficient survives standing next to the incumbent's.

And the significance is measured on NON-OVERLAPPING rows. Consecutive
forward-H-day windows share H-1 days of returns, so their errors are heavily
autocorrelated and an ordinary t-statistic on all 4500 rows is inflated by
roughly sqrt(H). edge.py corrects for exactly this in its own z-scores; here
the correction is to sample every H-th row, which costs sample size and buys
a number that means what it says.

SILVER IS STRUCTURALLY EXCLUDED FROM THE PRIMARY CLAIM
------------------------------------------------------
There is no silver equivalent. CBOE's ^VXSLV stopped being published and Yahoo
now serves a single row for it (measured 2026-09-09). GVZ is gold's implied
volatility, so silver appears here only as an explicitly labelled secondary
check -- "does gold's fear gauge happen to help size silver too" is a separate
and much weaker claim than the one this file is making, and it is not allowed
to borrow the primary result's credibility.
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
import defense  # noqa: E402
import panel as panel_module  # noqa: E402
import trading  # noqa: E402

TRADING_DAYS = 252

# The horizon that matters is 60: trading.VOL_LOOKBACK_DAYS is 60, so that is
# the window the production estimate is implicitly forecasting. 20 is printed
# alongside because GVZ is a 30-CALENDAR-day (~21 trading day) index by
# construction, and showing only the horizon that flatters it would be a
# choice made after seeing the answer.
HORIZONS = (20, 60)

# How much of the volatility estimate comes from GVZ. w=0 IS production, and it
# is inside the grid deliberately -- research/tilt.py's headline result was
# that its own grid chose zero, and a grid that cannot return "the current
# setting was already right" is not a measurement.
IMPLIED_WEIGHT_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)

# Mechanical strategies only. These are the production strategies whose
# behaviour actually depends on the volatility number, and they forecast
# nothing, so they can be replayed without signals. `ensemble` also consumes
# volatility but needs the component signals, which is research/
# ensemble_weights.py's machinery, not this file's.
COST_BPS = 10  # the ETF rung, the one every headline figure here is quoted at


def annualised(series: pd.Series, window: int) -> pd.Series:
    """Trailing realised volatility, as a fraction. Uses only past returns."""
    return series.rolling(window).std() * math.sqrt(TRADING_DAYS)


def forward_vol(returns: pd.Series, horizon: int) -> pd.Series:
    """Realised volatility over the NEXT `horizon` days, as a fraction.

    `rolling(h).std()` at row j covers returns[j-h+1..j]; shifting it back by h
    puts the window returns[i+1..i+h] on row i. That is the quantity a forecast
    made at the close of day i is trying to hit, and it deliberately excludes
    day i's own return -- including it would hand every forecaster a free
    correct answer.
    """
    return returns.rolling(horizon).std().shift(-horizon) * math.sqrt(TRADING_DAYS)


def ols(y: np.ndarray, columns: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Least squares with an intercept. Returns (coefficients, t-statistics)."""
    x = np.column_stack([np.ones(len(y))] + columns)
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    resid = y - x @ beta
    dof = len(y) - x.shape[1]
    sigma2 = float(resid @ resid) / dof
    cov = sigma2 * np.linalg.inv(x.T @ x)
    se = np.sqrt(np.diag(cov))
    return beta, beta / se


def load_common(asset_key: str) -> pd.DataFrame:
    """The asset's panel restricted to rows where GVZ exists.

    Everything downstream runs on this window and NOTHING is compared against a
    figure published for the full 25-year panel. GVZ starts 2008-06, so a
    GVZ-based rule scored on 2008-2026 and set against a baseline scored on
    2001-2026 would be reporting the difference between two market regimes as
    though it were the difference between two volatility estimates.
    """
    df = panel_module.load(asset_key).reset_index(drop=True)
    df = df[df["gvz"].notna()].reset_index(drop=True)
    df["ret"] = df["close"].pct_change()
    df["rv"] = annualised(df["ret"], trading.VOL_LOOKBACK_DAYS)
    df["implied"] = df["gvz"] / 100.0     # GVZ is quoted in points, not a fraction
    return df


# --------------------------------------------------------------------------
# Part 1 -- the forecasting race. No trading, no free parameters except one
# scale ratio, and that ratio is measured on the training half alone.
# --------------------------------------------------------------------------

def part1(df: pd.DataFrame, label: str) -> bool:
    print("\n" + "=" * 92)
    print(f"KISIM 1 -- OYNAKLIK TAHMIN YARISI  ({label})")
    print("=" * 92)

    split = len(df) // 2
    print(f"  Ortak pencere: {len(df)} gun  "
          f"({df['time'].iloc[0].date()} -> {df['time'].iloc[-1].date()})")
    print(f"  EGITIM: {df['time'].iloc[0].date()} -> {df['time'].iloc[split - 1].date()}   "
          f"TEST: {df['time'].iloc[split].date()} -> {df['time'].iloc[-1].date()}")

    # The one fitted quantity in this half of the study, and it is fitted on
    # the training half only. Median rather than mean: the ratio's denominator
    # is a volatility that gets small in calm markets, so the distribution has
    # a long right tail that a mean would chase.
    train = df.iloc[:split]
    ratio_mask = train["rv"].notna() & (train["rv"] > 0)
    ratio = float((train.loc[ratio_mask, "implied"] / train.loc[ratio_mask, "rv"]).median())
    print(f"\n  EGITIMDE olculen ima/gerceklesen orani: {ratio:.4f}  "
          f"(varyans risk primi -- test yarisinda bu sabit uygulanacak)")

    passed_any = False
    for horizon in HORIZONS:
        fwd = forward_vol(df["ret"], horizon)
        scaled = df["implied"] / ratio

        mask = fwd.notna() & df["rv"].notna() & scaled.notna()
        mask.iloc[:split] = False          # TEST half only
        y = fwd[mask].to_numpy(float)
        rv = df["rv"][mask].to_numpy(float)
        iv = scaled[mask].to_numpy(float)
        n = len(y)

        blend = 0.5 * rv + 0.5 * iv
        print(f"\n  --- ufuk {horizon} gun --- (TEST yarisi, n={n})"
              + ("   <-- trading.VOL_LOOKBACK_DAYS ile ayni" if horizon == trading.VOL_LOOKBACK_DAYS else ""))
        print(f"      {'tahminci':<28}{'r':>9}{'RMSE':>10}{'ortalama sapma':>17}")
        for name, pred in (("gecmis rv60 (URETIM)", rv), ("GVZ (olceklenmis)", iv),
                           ("yari yariya harman", blend)):
            r = float(np.corrcoef(pred, y)[0, 1])
            rmse = float(np.sqrt(np.mean((pred - y) ** 2)))
            bias = float(np.mean(pred - y))
            print(f"      {name:<28}{r:>9.4f}{100 * rmse:>9.2f}p{100 * bias:>16.2f}p")

        # The test that decides. r on its own cannot separate "GVZ is better"
        # from "GVZ and rv60 are two views of the same thing and either beats
        # nothing" -- they correlate at 0.85. Only a joint fit can say whether
        # GVZ carries information the incumbent does not already have.
        beta, tstat = ols(y, [rv, iv])
        step = max(horizon, 1)
        yn, rvn, ivn = y[::step], rv[::step], iv[::step]
        _, tstat_indep = ols(yn, [rvn, ivn])

        print(f"      kapsama testi   gelecek_vol ~ a*rv60 + b*GVZ")
        print(f"        a (rv60) = {beta[1]:+.4f}   b (GVZ) = {beta[2]:+.4f}")
        print(f"        ORTUSMEYEN alt ornek (her {step}. satir, n={len(yn)}): "
              f"t(a)={tstat_indep[1]:+.2f}  t(b)={tstat_indep[2]:+.2f}")
        print(f"        (ortusen tam ornek t'leri {tstat[1]:+.1f} / {tstat[2]:+.1f} -- "
              f"~sqrt({step})x sisik, karar icin KULLANILMIYOR)")

        verdict = abs(tstat_indep[2]) > 2.0 and beta[2] > 0
        print(f"        -> GVZ rv60'in YANINDA {'BILGI KATIYOR' if verdict else 'ek bilgi katmiyor'}")
        if horizon == trading.VOL_LOOKBACK_DAYS:
            passed_any = verdict

    return passed_any


# --------------------------------------------------------------------------
# Part 2 -- does the better forecast survive contact with the trading rule?
# --------------------------------------------------------------------------

def exposures(df: pd.DataFrame, weight: float, ratio: float, target_vol: float,
              strategy: str) -> np.ndarray:
    """Target exposure per day, through the REAL production function.

    trading.compute_target_exposure is what predict.py and backtest.py call, so
    a candidate volatility estimate is scored by the same code that would
    consume it in production rather than by a reimplementation of it -- the
    discipline backtest.py's docstring exists to enforce.
    """
    rv = df["rv"].to_numpy(float)
    implied = (df["implied"] / ratio).to_numpy(float)
    price = df["close"].to_numpy(float)
    trend = df["close"].rolling(trading.TREND_WINDOW).mean().to_numpy(float)

    blended = np.where(np.isfinite(implied), (1.0 - weight) * rv + weight * implied, rv)
    out = np.empty(len(df))
    for i in range(len(df)):
        out[i] = trading.compute_target_exposure(
            strategy, price[i], trend[i], blended[i], "UP", 0.0, target_vol)
    return out


def part2(df: pd.DataFrame, asset, label: str) -> None:
    print("\n" + "=" * 92)
    print(f"KISIM 2 -- TICARET KURALINA SOKMAK  ({label})")
    print("=" * 92)

    split = len(df) // 2
    train = df.iloc[:split].reset_index(drop=True)
    test = df.iloc[split:].reset_index(drop=True)
    ratio_mask = train["rv"].notna() & (train["rv"] > 0)
    ratio = float((train.loc[ratio_mask, "implied"] / train.loc[ratio_mask, "rv"]).median())

    for strategy in ("voltarget", "defensive"):
        print(f"\n  --- strateji: {strategy} "
              f"(hedef oynaklik %{100 * asset.target_volatility:.0f}, maliyet {COST_BPS}bp) ---")
        print(f"      {'w (GVZ agirligi)':<20}{'EGITIM Calmar':>15}{'piyasada':>11}"
              f"{'TEST Calmar':>14}{'piyasada':>11}")

        scores: dict[float, float] = {}
        test_scores: dict[float, tuple[float, float]] = {}
        for weight in IMPLIED_WEIGHT_GRID:
            row = ""
            for part, store in ((train, "train"), (test, "test")):
                target = exposures(part, weight, ratio, asset.target_volatility, strategy)
                closes = part["close"].to_numpy(float)
                years = (part["time"].iloc[-1] - part["time"].iloc[0]).days / 365.25
                equity, held = defense.simulate(closes, target, COST_BPS)
                m = defense.metrics(equity, held, years)
                if store == "train":
                    scores[weight] = m["calmar"]
                else:
                    test_scores[weight] = (m["calmar"], m["exposure"])
                # Mean exposure is printed for every candidate, not just the
                # winner: a weight that "wins" purely by holding more or less
                # of a trending asset is a scale effect, and it is only
                # visible in this column.
                row += f"{m['calmar']:>15.3f}{100 * m['exposure']:>10.0f}%"
            marker = "   <-- URETIM" if weight == 0.0 else ""
            print(f"      {weight:<20.2f}{row}{marker}")

        chosen = max(scores, key=scores.get)
        prod_test = test_scores[0.0][0]
        chosen_test = test_scores[chosen][0]
        print(f"\n      >>> EGITIMDE SECILEN: w={chosen:.2f} (egitim Calmar {scores[chosen]:.3f}, "
              f"uretim w=0 {scores[0.0]:.3f})")

        # THE GUARD. "Chosen on the training half, confirmed once on the test
        # half" is this bench's standard rule, and on this particular grid it
        # returns the wrong answer -- so the check is written into the script
        # rather than left to whoever reads the table.
        #
        # The two halves here rank the grid in OPPOSITE orders: training
        # Calmar falls monotonically as w rises, test Calmar rises
        # monotonically. When that happens the split has not resolved the
        # question, it has straddled a regime change -- the training half
        # carries gold's 2011-2015 bear, the test half is the 2017-2026 bull,
        # and w is being scored on which regime it happened to land in. A
        # "confirmation" drawn from a test half that disagrees with the
        # training half about the entire ordering is not a confirmation; it is
        # reading the answer off the held-out data.
        #
        # Rank correlation rather than a magnitude threshold on purpose: it
        # invents no constant, and "the two halves must at least agree on the
        # direction" is the weakest possible thing to demand of an
        # out-of-sample check.
        agreement = pd.Series([scores[w] for w in IMPLIED_WEIGHT_GRID]).corr(
            pd.Series([test_scores[w][0] for w in IMPLIED_WEIGHT_GRID]), method="spearman")
        print(f"      >>> egitim/test siralama uyumu (Spearman): {agreement:+.2f}")

        if agreement <= 0:
            print("      >>> IKI YARI IZGARAYI TERS SIRALIYOR -- bolme soruyu cozmedi, bir")
            print("          rejim degisimini ikiye ayirdi. Test yarisindaki iyilesme bir")
            print("          DOGRULAMA DEGIL. Hicbir sey benimsenmiyor, w=0 kaliyor.")
            continue

        if chosen == 0.0:
            print("      >>> ARAMA URETIMDEKINDEN FARKLI BIR SEY BULMADI: w=0 zaten en iyisiydi.")
        else:
            delta = chosen_test - prod_test
            if delta <= 0:
                print(f"      >>> SECILEN EGITIMDE ONE CIKTI AMA TEST YARISINDA URETIMDEN "
                      f"{delta:+.3f} Calmar -- gurultuydu, DEGISMEYECEK.")
            else:
                print(f"      >>> TEST YARISINDA URETIMDEN {delta:+.3f} Calmar DAHA IYI "
                      f"(w={chosen:.2f}: {chosen_test:.3f} vs {prod_test:.3f}).")


def main() -> int:
    gold = assets_module.GOLD
    df = load_common(gold.key)
    gold_passed = part1(df, "ALTIN -- birincil")
    if gold_passed:
        part2(df, gold, "ALTIN -- birincil")
    else:
        print("\n" + "=" * 92)
        print("KISIM 2 CALISTIRILMADI: GVZ, ufuk 60'ta rv60'in yaninda ek bilgi katmiyor.")
        print("Tahmin gucu yoksa Calmar'da cikacak her fark bir olcek artefaktidir --")
        print("farkli bir ortalama pozisyon, trend eden bir pencerede. Ona gore hareket")
        print("etmek artefakta gore hareket etmek olurdu.")
        print("=" * 92)

    # Secondary, and labelled as such everywhere it prints. GVZ is GOLD's
    # implied volatility; CBOE stopped publishing the silver equivalent
    # (^VXSLV returns a single row from Yahoo, measured 2026-09-09). Whether
    # gold's fear gauge happens to size silver better is a different and much
    # weaker claim, and it does not get to lean on the gold result.
    print("\n\n" + "#" * 92)
    print("### IKINCIL KONTROL -- GUMUS (GVZ altinin ima edilen oynakligidir; bu bir UZATMA)")
    print("#" * 92)
    silver = assets_module.SILVER
    silver_df = load_common(silver.key)
    if part1(silver_df, "GUMUS -- ikincil"):
        part2(silver_df, silver, "GUMUS -- ikincil")
    else:
        print("\n  KISIM 2 CALISTIRILMADI (gumus): GVZ rv60'in yaninda ek bilgi katmiyor.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
