"""Does gold have a real calendar effect, or just a well-told story?

Gold is the asset seasonality folklore loves most, and the stories are at
least physically plausible in a way crypto's never were: Indian wedding
season buying in autumn, Chinese New Year demand in January-February, a
summer lull. Unlike a chart pattern, these describe actual humans buying
actual metal on a schedule.

Plausible is not the same as tradeable, and calendar studies are unusually
easy to fool yourself with, for two specific reasons this file guards against:

  1. **Multiple testing.** Twelve months, five weekdays, four week-of-month
     buckets -- about 21 comparisons. At the usual 5% threshold roughly one
     will look "significant" by luck alone. Everything here is therefore
     judged against a Bonferroni-corrected bar, and the naive count of
     "significant" months is printed next to it so the gap is visible.

  2. **One window.** A month that worked 2001-2013 and stopped is not a
     seasonal effect, it is a coincidence that ran out. Every bucket is
     scored on both halves separately and the two are shown side by side.
     A real calendar effect should survive; XRP-Guess's cross-sectional
     momentum is the cautionary example of what happens when only the first
     half is consulted (+123%/yr in-sample, -34.3%/yr out).

Costs matter here too and are easy to forget: a "trade only in September"
rule holds a position ~8% of the year, so its edge is spread over very few
days and pays entry/exit costs on every one of them.
"""
from __future__ import annotations

import math
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import panel as panel_module  # noqa: E402

MONTH_NAMES = ["Ocak", "Subat", "Mart", "Nisan", "Mayis", "Haziran",
               "Temmuz", "Agustos", "Eylul", "Ekim", "Kasim", "Aralik"]
DAY_NAMES = ["Pazartesi", "Sali", "Carsamba", "Persembe", "Cuma"]


def bucket_stats(returns: np.ndarray, reference: float = 0.0) -> tuple[float, float, int]:
    """(mean daily return, t-statistic against `reference`, n).

    `reference` must be the mean of a TYPICAL day, not zero. Testing a
    calendar bucket against zero asks "does gold go up in January", and since
    gold drifts up in general the answer is yes for almost every bucket --
    which makes the t-statistic a measure of sample size rather than of
    seasonality.

    This file's first version did exactly that and produced a nonsense result
    worth recording: the "mid-month" bucket came out significant at t=3.24
    while "turn-of-month" did not at t=1.45, even though their means were
    0.0515% and 0.0487% -- indistinguishable. The entire difference was that
    one bucket held 5056 days and the other 1215. Against the right reference
    both correctly collapse to nothing.
    """
    clean = returns[np.isfinite(returns)]
    n = len(clean)
    if n < 20:
        return float("nan"), float("nan"), n
    mean = float(np.mean(clean))
    sd = float(np.std(clean, ddof=1))
    if sd == 0:
        return mean, float("nan"), n
    return mean, (mean - reference) / (sd / math.sqrt(n)), n


def analyse(df: pd.DataFrame, key: pd.Series, labels: list[str], title: str,
            split: int) -> None:
    returns = df["close"].pct_change().to_numpy(dtype=float)
    n_tests = len(labels)
    # Bonferroni: alpha 0.05 spread over n_tests, two-sided.
    from statistics import NormalDist
    bonf_t = NormalDist().inv_cdf(1 - 0.05 / (2 * n_tests))

    # The reference every bucket is measured against: an average day in the
    # same window. See bucket_stats() -- against zero this whole table would
    # just be re-measuring gold's upward drift.
    finite = returns[np.isfinite(returns)]
    ref_all = float(np.mean(finite))
    ref_first = float(np.nanmean(returns[:split]))
    ref_second = float(np.nanmean(returns[split:]))

    print("\n" + "=" * 92)
    print(title)
    print("=" * 92)
    print(f"  (t degerleri ORTALAMA BIR GUNE gore: tum donem %{100 * ref_all:.4f}/gun)")
    print(f"{'':<12}{'TUM DONEM':>26}{'ILK YARI':>20}{'IKINCI YARI':>20}{'':>8}")
    print(f"{'':<12}{'ort/gun':>10}{'t':>8}{'n':>8}{'ort/gun':>11}{'t':>9}{'ort/gun':>11}{'t':>9}{'tutarli':>10}")

    naive_hits, bonf_hits, consistent = 0, 0, 0
    for i, label in enumerate(labels):
        mask = (key == i).to_numpy()
        all_mean, all_t, all_n = bucket_stats(returns[mask], ref_all)
        first = mask.copy(); first[split:] = False
        second = mask.copy(); second[:split] = False
        m1, t1, _ = bucket_stats(returns[first], ref_first)
        m2, t2, _ = bucket_stats(returns[second], ref_second)

        # Consistency is about the DEVIATION from a typical day keeping its
        # sign, not about the raw return staying positive -- in a window where
        # gold rose, nearly every bucket's raw mean is positive regardless.
        same_sign = (np.isfinite(m1) and np.isfinite(m2)
                     and ((m1 - ref_first) * (m2 - ref_second) > 0))
        if np.isfinite(all_t):
            if abs(all_t) > 1.96:
                naive_hits += 1
            if abs(all_t) > bonf_t:
                bonf_hits += 1
        if same_sign:
            consistent += 1

        flag = ""
        if np.isfinite(all_t) and abs(all_t) > bonf_t and same_sign:
            flag = "  <== GECTI"
        elif np.isfinite(all_t) and abs(all_t) > 1.96:
            flag = "  (naif anlamli)"

        print(f"{label:<12}{100 * all_mean:>9.4f}%{all_t:>8.2f}{all_n:>8}"
              f"{100 * m1:>10.4f}%{t1:>9.2f}{100 * m2:>10.4f}%{t2:>9.2f}"
              f"{'EVET' if same_sign else 'hayir':>10}{flag}")

    print(f"\n  naif |t|>1.96 gecen  : {naive_hits}/{n_tests}   "
          f"(sansa beklenen ~{0.05 * n_tests:.1f})")
    print(f"  Bonferroni |t|>{bonf_t:.2f} : {bonf_hits}/{n_tests}")
    print(f"  iki yarida ayni isaret: {consistent}/{n_tests}   (sansa beklenen ~{n_tests / 2:.1f})")


def month_strategy_test(df: pd.DataFrame, split: int, cost_bps: float = 10) -> None:
    """Pick the best month on the first half, hold only that month in the second.

    The point is not that anybody would trade this. It is that a calendar
    edge, if real, has to survive being chosen in advance -- and this is the
    cheapest possible way to make it try.
    """
    import defense

    returns = df["close"].pct_change().to_numpy(dtype=float)
    months = df["time"].dt.month.to_numpy() - 1

    train_means = {}
    for m in range(12):
        mask = (months == m)
        mask[split:] = False
        mean, t, n = bucket_stats(returns[mask])
        train_means[m] = mean if np.isfinite(mean) else -1e9

    best = max(train_means, key=lambda k: train_means[k])
    worst = min(train_means, key=lambda k: train_means[k])
    print("\n" + "=" * 92)
    print("SECILMIS AY STRATEJISI (egitimde sec, testte kosur)")
    print("=" * 92)
    print(f"  Egitim yarisinin EN IYI ayi : {MONTH_NAMES[best]}  (ort %{100 * train_means[best]:.4f}/gun)")
    print(f"  Egitim yarisinin EN KOTU ayi: {MONTH_NAMES[worst]}  (ort %{100 * train_means[worst]:.4f}/gun)")

    test = df.iloc[split:].reset_index(drop=True)
    test_closes = test["close"].to_numpy(dtype=float)
    test_months = test["time"].dt.month.to_numpy() - 1
    years = (test["time"].iloc[-1] - test["time"].iloc[0]).days / 365.25

    setups = {
        f"sadece {MONTH_NAMES[best]}": (test_months == best).astype(float),
        f"{MONTH_NAMES[worst]} haric": (test_months != worst).astype(float),
        "al-ve-tut": np.ones(len(test)),
    }
    print(f"\n  TEST yarisi ({test['time'].iloc[0].date()} -> {test['time'].iloc[-1].date()}, "
          f"maliyet {cost_bps} bp)")
    print(f"{'':<24}{'YBG':>9}{'oynak':>9}{'Sharpe':>9}{'maks dusus':>13}{'piyasada':>10}")
    for name, target in setups.items():
        equity, held = defense.simulate(test_closes, target, cost_bps)
        m = defense.metrics(equity, held, years)
        print(f"  {name:<22}{100 * m['cagr']:>8.1f}%{100 * m['vol']:>8.1f}%{m['sharpe']:>9.2f}"
              f"{100 * m['max_dd']:>12.1f}%{100 * m['exposure']:>9.0f}%")


def main() -> int:
    df = panel_module.load().reset_index(drop=True)
    split = len(df) // 2
    print(f"Panel: {len(df)} gun ({df['time'].iloc[0].date()} -> {df['time'].iloc[-1].date()})")
    print(f"Yarilar: ...{df['time'].iloc[split - 1].date()} | {df['time'].iloc[split].date()}...")

    analyse(df, df["time"].dt.month - 1, MONTH_NAMES, "AYA GORE GUNLUK GETIRI", split)

    weekday = df["time"].dt.dayofweek
    weekday_df = df[weekday < 5].reset_index(drop=True)
    analyse(weekday_df, weekday_df["time"].dt.dayofweek, DAY_NAMES,
            "HAFTA GUNUNE GORE GUNLUK GETIRI", len(weekday_df) // 2)

    # Turn-of-month: the last 3 and first 3 sessions of each month, a widely
    # claimed effect across many assets.
    day_of_month = df["time"].dt.day
    days_in_month = df["time"].dt.days_in_month
    tom = pd.Series(np.where((day_of_month <= 3) | (day_of_month >= days_in_month - 2), 0, 1))
    analyse(df, tom, ["ay donumu", "ay ortasi"], "AY DONUMU ETKISI", split)

    month_strategy_test(df, split)

    print("\n" + "=" * 92)
    print("OKUMA")
    print("=" * 92)
    print("  Bir takvim etkisinin gercek sayilmasi icin UC sey birden gerekli:")
    print("    (1) Bonferroni esigini gecmeli -- yoksa 21 testten biri sansa gecer;")
    print("    (2) iki yarida ayni isareti tutmali -- yoksa 'bitmis bir tesaduf'tur;")
    print("    (3) onceden secilip testte para kazandirmali -- IC paraya esit degil,")
    print("        bu dersi XRP-Guess kesitsel reversal'da odeyerek ogrendi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
