"""Does US policy rate news actually move the metals in a way we could use?

THE QUESTION, STATED SO IT CAN FAIL
-----------------------------------
"Gold goes up when the Fed cuts" is the single most repeated claim about this
asset, and it is repeated in a form that cannot be wrong: it does not say when,
by how much, or against what baseline. This file makes it falsifiable by
splitting it into three separate claims that need separate evidence:

  1. EVENT.   On and around a cut/hike day, do the metals move differently
              from an average day?
  2. REGIME.  Does the base rate itself -- P(closes higher over 5 sessions) --
              differ between easing, tightening and on-hold regimes? This is
              the one that would matter most here, because `ensemble.py`
              measures every component against `assets.Asset.base_rate_up`.
              A base rate that is really two different numbers would mean
              every component's measured "skill" is partly a regime artefact.
  3. SURPRISE. The decision itself is known days in advance from the futures
              market. If anything is tradeable it is the SURPRISE, so the
              same-day move in policy-sensitive yields is used as a proxy for
              it and the metal's response is measured from the NEXT close --
              the first price anyone reading this could actually transact at.

Claim 1 is descriptive. Claims 2 and 3 are the ones that could change code.

WHY THIS CAN BE DONE AT ALL NOW
-------------------------------
CLAUDE.md recorded FRED as unreachable from the development machine
(2026-09-07, repeated 60s timeouts). On 2026-09-08 every series returned in
under 1.2 seconds. That makes the Fed's OWN target series available, which
matters more than it sounds: it means the hike/cut dates below are read out
of the data rather than typed in from memory, and an FOMC calendar
reconstructed from memory across 25 years is exactly the kind of input that
is 95% right and silently wrong in the 5% that carries the events.

fetch_data.get_fed_target_rate() splices DFEDTAR (single target, to
2008-12-15) onto the midpoint of DFEDTARL/DFEDTARU (the range, after), so the
step function is continuous across the 2008 regime change.

DISCIPLINE (same as every other file here)
------------------------------------------
  * Time split. Everything is reported on the TEST half; the training half is
    printed only so a sign flip between halves is visible.
  * Overlap correction. At horizon h consecutive observations share h-1 days
    of outcome, so the effective sample is n/h and naive t-statistics are
    inflated by ~sqrt(h).
  * The bar is the base rate, never 50%. Gold closes higher over 5 sessions
    55.7% of the time; a regime showing "56% up" has shown nothing.
  * The whole grid is ONE family, the threshold is declared before the run,
    and the power of the test is printed next to every negative.
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

import ablation  # noqa: E402  -- score() / paired_ic_test() are reused so the
                     # A/B below is scored by the same ruler as ratio.py's
import assets as assets_module  # noqa: E402
import edge  # noqa: E402
import fetch_data  # noqa: E402
import ml_model  # noqa: E402
import panel as panel_module  # noqa: E402
from indicators import build_features  # noqa: E402

HORIZONS = (1, 5, 20, 60)
REGIMES = ("EASING", "TIGHTENING", "HOLD")

# A change is "recent" for a year. Chosen before looking at any outcome, from
# the mechanics rather than the data: the FOMC meets eight times a year, so a
# full year with no move is an unambiguous on-hold stance, and anything much
# shorter would flip a policy regime on and off between scheduled meetings.
REGIME_MEMORY_DAYS = 365

# The event window. Ten sessions before is enough to see positioning ahead of
# a decision everyone knows the date of; twenty after covers the drift that
# the "gold rallies on cuts" story is really about.
EVENT_BEFORE, EVENT_AFTER = 10, 20

# Declared before the run: 3 regimes x 4 horizons x 2 metals = 24, plus the
# surprise grid's 4 horizons x 2 metals = 8. One family, 32 tests.
N_TESTS = 24 + 8
BONFERRONI_T = float(scipy_stats.norm.isf(0.025 / N_TESTS))


# --------------------------------------------------------------------------
# Policy state, built with no lookahead
# --------------------------------------------------------------------------

def policy_frame(panel: pd.DataFrame, target: pd.DataFrame) -> pd.DataFrame:
    """Panel + the policy columns, every one observable at that row's close.

    The FOMC statement lands at 14:00 New York and COMEX metals close at
    17:00, so a target change dated D is genuinely known before D's close.
    That is why `days_since_*` may be 0 on the event day itself and why the
    event-day return is reported as EXPLANATORY rather than tradeable: the
    return that a reader could have captured starts at the next close.
    """
    out = panel.copy()
    index = pd.DatetimeIndex(out["time"]).normalize()
    series = target.set_index(pd.DatetimeIndex(target["time"]).normalize())["value"]
    series = series[~series.index.duplicated(keep="last")]
    out["fed_target"] = series.reindex(index, method="ffill").to_numpy()

    # Change dates come from the CALENDAR-daily FRED series, not from the
    # panel: a hike decided on a day COMEX did not trade would otherwise be
    # attributed to the next session, or lost.
    moves = target.assign(chg=target["value"].diff())
    moves = moves[moves["chg"].abs() > 1e-9]
    move_days = pd.DatetimeIndex(moves["time"]).normalize()
    move_sign = np.sign(moves["chg"].to_numpy())

    last_cut, last_hike, last_move_size = [], [], []
    for day in index:
        seen = move_days <= day
        if not seen.any():
            last_cut.append(np.nan)
            last_hike.append(np.nan)
            last_move_size.append(np.nan)
            continue
        signs = move_sign[seen]
        days = move_days[seen]
        cuts = days[signs < 0]
        hikes = days[signs > 0]
        last_cut.append((day - cuts[-1]).days if len(cuts) else np.nan)
        last_hike.append((day - hikes[-1]).days if len(hikes) else np.nan)
        last_move_size.append(float(moves["chg"].to_numpy()[seen][-1]))

    out["days_since_cut"] = last_cut
    out["days_since_hike"] = last_hike
    out["last_move"] = last_move_size

    def state(row) -> str:
        cut, hike = row["days_since_cut"], row["days_since_hike"]
        cut = np.inf if pd.isna(cut) else cut
        hike = np.inf if pd.isna(hike) else hike
        if min(cut, hike) > REGIME_MEMORY_DAYS:
            return "HOLD"
        return "EASING" if cut < hike else "TIGHTENING"

    out["policy_state"] = out.apply(state, axis=1)
    out["is_event"] = index.isin(move_days)
    out["event_sign"] = np.where(
        out["is_event"], np.sign(out["fed_target"].diff().fillna(0.0)), 0.0)
    return out


# --------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------

def forward_return(close: pd.Series, horizon: int) -> np.ndarray:
    return (close.shift(-horizon) / close - 1.0).to_numpy(dtype=float)


def proportion_test(hits: int, n: int, baseline: float, horizon: int) -> tuple[float, float]:
    """(observed rate, overlap-corrected z against `baseline`).

    `baseline` is the asset's unconditional up-rate over the same horizon,
    NOT 0.5. Testing a gold subsample against a coin flip returns "highly
    significant" for every subsample large enough, which measures the drift
    and nothing else -- the same error research/season.py caught in its own
    first version and had to rewrite around.
    """
    if n <= 0:
        return float("nan"), float("nan")
    rate = hits / n
    n_eff = max(n / horizon, 1.0)
    se = math.sqrt(max(baseline * (1 - baseline), 1e-12) / n_eff)
    return rate, (rate - baseline) / se


def min_detectable_edge(n: int, horizon: int, baseline: float, bar_t: float) -> float:
    """Smallest deviation from the base rate this subsample could have called.

    Printed next to every negative, for the reason ablation.py states: "nothing
    passed" and "the test could not have seen it" demand opposite follow-ups.
    """
    n_eff = max(n / horizon, 1.0)
    return bar_t * math.sqrt(max(baseline * (1 - baseline), 1e-12) / n_eff)


def correlation_test(x: np.ndarray, y: np.ndarray, horizon: int) -> tuple[float, float, int]:
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 30:
        return float("nan"), float("nan"), int(mask.sum())
    r = float(np.corrcoef(x[mask], y[mask])[0, 1])
    n_eff = max(mask.sum() / horizon, 3)
    t = r * math.sqrt(max(n_eff - 2, 1)) / math.sqrt(max(1 - r ** 2, 1e-12))
    return r, t, int(mask.sum())


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------

def section_events(df: pd.DataFrame, asset) -> None:
    """Descriptive: the average path around a cut and around a hike."""
    close = df["close"].reset_index(drop=True)
    daily = close.pct_change().to_numpy(dtype=float)
    drift = float(np.nanmean(daily))
    idx = np.flatnonzero(df["is_event"].to_numpy())
    signs = df["event_sign"].to_numpy()[idx]

    print(f"\n{'-' * 96}")
    print(f"1) OLAY CALISMASI -- {asset.label}: kesim/artis gununun etrafindaki ortalama yol")
    print(f"{'-' * 96}")
    print(f"  Panelde {len(idx)} politika degisimi ({int((signs < 0).sum())} indirim, "
          f"{int((signs > 0).sum())} artis).")
    print("  Sayilar KUMULATIF ortalama getiri, olay gunu 0 kabul edilerek. Ortalama")
    print(f"  bir gunun surukleme katkisi %{100 * drift:.4f}, yani {EVENT_AFTER} gunluk pencerenin")
    print(f"  'hicbir sey olmasa' beklentisi %{100 * drift * EVENT_AFTER:.2f} -- kiyas budur, sifir degil.\n")

    offsets = list(range(-EVENT_BEFORE, EVENT_AFTER + 1))
    print(f"{'gun':>6}{'INDIRIM kum.%':>16}{'ARTIS kum.%':>15}{'fark (pp)':>12}")
    paths = {}
    for label, mask in (("cut", signs < 0), ("hike", signs > 0)):
        rows = []
        for centre in idx[mask]:
            lo, hi = centre - EVENT_BEFORE, centre + EVENT_AFTER
            if lo < 1 or hi >= len(close):
                continue
            window = daily[lo + 1: hi + 1]
            anchor = EVENT_BEFORE  # cumulative return is measured from day 0
            cum = np.concatenate([[0.0], np.cumsum(window)])
            rows.append(cum - cum[anchor])
        paths[label] = np.array(rows) if rows else np.zeros((0, len(offsets)))

    for j, day in enumerate(offsets):
        if day % 5 and day not in (-1, 1):
            continue
        cut = 100 * float(np.mean(paths["cut"][:, j])) if len(paths["cut"]) else float("nan")
        hike = 100 * float(np.mean(paths["hike"][:, j])) if len(paths["hike"]) else float("nan")
        print(f"{day:>6}{cut:>+16.2f}{hike:>+15.2f}{cut - hike:>+12.2f}")

    # The only number here with a claim attached: +1..+20 AFTER the event,
    # i.e. the part a reader could still have traded.
    for label in ("cut", "hike"):
        if not len(paths[label]):
            continue
        after = paths[label][:, EVENT_BEFORE + EVENT_AFTER] - paths[label][:, EVENT_BEFORE]
        n = len(after)
        t = float(np.mean(after - drift * EVENT_AFTER) /
                  (np.std(after, ddof=1) / math.sqrt(n))) if n > 2 else float("nan")
        name = "INDIRIM" if label == "cut" else "ARTIS"
        print(f"  {name} sonrasi +1..+{EVENT_AFTER}: ortalama %{100 * float(np.mean(after)):+.2f} "
              f"(n={n}), surukleme uzeri t={t:+.2f}")
    print("  Bu bolum BETIMLEYICI. Olay gunu getirisi kararin kendisini iceriyor ve")
    print("  alinamaz; kararin verilebilir kismi bir sonraki kapanistan baslar.")


def section_regimes(df: pd.DataFrame, asset, split: int, results: list) -> None:
    """The actionable one: is `base_rate_up` really one number?"""
    print(f"\n{'-' * 96}")
    print(f"2) REJIM -- {asset.label}: taban oran gevseme/sikilastirma/beklemede farkli mi?")
    print(f"{'-' * 96}")
    print(f"  assets.{asset.key.upper()}.base_rate_up = {asset.base_rate_up:.3f}. ensemble.py HER")
    print("  bilesenin becerisini bu tek sayiya karsi olcuyor. Eger taban oran aslinda")
    print("  rejime gore iki farkli sayiysa, her bilesenin 'becerisi' kismen rejim")
    print("  artefaktidir -- bu yuzden bu bolum kod degistirebilecek olan bolumdur.\n")
    print(f"  Esik: |z| > {BONFERRONI_T:.2f} (Bonferroni, {N_TESTS} testlik tek aile).")
    print("  Kiyas 0.5 DEGIL, varligin kendi taban orani.\n")

    test = df.iloc[split:].reset_index(drop=True)
    train = df.iloc[:split].reset_index(drop=True)

    header = (f"{'rejim':<12}{'ufuk':>6}{'n (test)':>10}{'P(yuk) egitim':>15}"
              f"{'P(yuk) test':>13}{'taban':>8}{'fark pp':>10}{'z':>8}{'gorulebilir pp':>16}{'':>7}")
    print(header)
    print("  " + "-" * (len(header) - 2))

    for horizon in HORIZONS:
        base_all = float(np.nanmean(forward_return(df["close"], horizon) > 0))
        fwd_tr = forward_return(train["close"], horizon)
        fwd_te = forward_return(test["close"], horizon)
        for regime in REGIMES:
            m_tr = (train["policy_state"] == regime).to_numpy() & np.isfinite(fwd_tr)
            m_te = (test["policy_state"] == regime).to_numpy() & np.isfinite(fwd_te)
            n_te = int(m_te.sum())
            if n_te < 30:
                print(f"{regime:<12}{str(horizon) + 'g':>6}{n_te:>10}"
                      f"{'-':>15}{'-':>13}{'-':>8}{'-':>10}{'-':>8}{'-':>16}"
                      f"{'yetersiz':>7}")
                results.append((asset.key, regime, horizon, float("nan"), False))
                continue
            rate_tr = float(np.mean(fwd_tr[m_tr] > 0)) if m_tr.sum() else float("nan")
            rate_te, z = proportion_test(int((fwd_te[m_te] > 0).sum()), n_te,
                                         base_all, horizon)
            mde = min_detectable_edge(n_te, horizon, base_all, BONFERRONI_T)
            # A sign that flips between halves is a coincidence with a
            # t-statistic, not a relationship -- ratio.py's filter, reused.
            stable = np.sign(rate_tr - base_all) == np.sign(rate_te - base_all)
            passed = abs(z) > BONFERRONI_T and stable
            results.append((asset.key, regime, horizon, z, passed))
            mark = "GECTI" if passed else ("~isaret" if not stable else "")
            print(f"{regime:<12}{str(horizon) + 'g':>6}{n_te:>10}{rate_tr:>15.3f}"
                  f"{rate_te:>13.3f}{base_all:>8.3f}{100 * (rate_te - base_all):>+10.1f}"
                  f"{z:>+8.2f}{100 * mde:>16.1f}{mark:>7}")

    print("\n  'gorulebilir pp' = bu alt orneklemin sifirdan ayirt EDEBILECEGI en kucuk")
    print("  sapma. Olculen sapma bunun altindaysa 'etki yok' degil, 'bu orneklem")
    print("  gorecek kadar buyuk degil' demektir -- ikisi zit isler gerektirir.")


def section_surprise(df: pd.DataFrame, asset, split: int, results: list) -> None:
    """The only genuinely tradeable version of the question."""
    print(f"\n{'-' * 96}")
    print(f"3) SURPRIZ -- {asset.label}: karar degil, kararin sasirtma miktari")
    print(f"{'-' * 96}")
    print("  FOMC'nin ne yapacagi karar gununden haftalar once vadeli piyasada")
    print("  fiyatlidir; dolayisiyla 'indirdi' bilgisi tek basina alinabilir bir sey")
    print("  degil. Alinabilir olan varsa SURPRIZDIR. Vekil: 5 yillik tahvil getirisinin")
    print("  olay gunundeki degisimi (^FVX, panelde zaten var, anahtarsiz).")
    print("  Getiri SICRARSA sahin surpriz, DUSERSE guvercin surpriz.")
    print("  Metalin tepkisi BIR SONRAKI kapanistan itibaren olculur -- olay gunu")
    print("  kapanisi kararin kendisini zaten icerir, onu saymak gecmisi okumaktir.\n")

    if "us5y" not in df.columns:
        print("  us5y paneli yok -- bu bolum atlaniyor.")
        return

    events = df[df["is_event"]].copy()
    surprise = df["us5y"].diff().to_numpy(dtype=float)
    df = df.assign(_surprise=surprise)
    events = df[df["is_event"]]
    print(f"  {len(events)} olay gunu. Sahin (getiri artti): "
          f"{int((events['_surprise'] > 0).sum())}, guvercin: "
          f"{int((events['_surprise'] < 0).sum())}\n")

    print(f"{'ufuk':>6}{'n (test)':>10}{'r (egitim)':>13}{'r (test)':>11}"
          f"{'t':>8}{'gecti':>8}")
    for horizon in HORIZONS:
        # Response starts at the NEXT close: shift the forward window by one.
        fwd = (df["close"].shift(-(horizon + 1)) / df["close"].shift(-1) - 1.0).to_numpy(dtype=float)
        x = df["_surprise"].to_numpy(dtype=float)
        event_mask = df["is_event"].to_numpy()
        tr = event_mask.copy(); tr[split:] = False
        te = event_mask.copy(); te[:split] = False
        r_tr, _, _ = correlation_test(x[tr], fwd[tr], horizon)
        r_te, t_te, n_te = correlation_test(x[te], fwd[te], horizon)
        passed = np.isfinite(t_te) and abs(t_te) > BONFERRONI_T and np.sign(r_tr) == np.sign(r_te)
        results.append((asset.key, "SURPRISE", horizon, t_te, bool(passed)))
        print(f"{str(horizon) + 'g':>6}{n_te:>10}{r_tr:>+13.4f}{r_te:>+11.4f}"
              f"{t_te:>+8.2f}{('EVET' if passed else 'hayir'):>8}")

    print("\n  Beklenen isaret NEGATIF olurdu: sahin surpriz (getiriler yukari) ->")
    print("  sifir getirili varligin firsat maliyeti artar -> metal asagi.")


def section_feature_ab(panel: pd.DataFrame, policy: pd.DataFrame, asset) -> None:
    """The prescribed test for a column decision: change ONE thing, same rows.

    Section 2 asked whether the policy regime moves the base rate and got a
    "not that this sample can see". This asks the different question that
    would actually change `ml_model.FEATURE_COLUMNS`: given everything the
    model already reads, does knowing the policy stance add anything?

    It is deliberately run on a KEYLESS proxy rather than on the FRED series
    the rest of this file uses. fetch_data.FRED_CSV explains why: FRED was
    dead on this machine on 2026-09-07 and fine on 2026-09-08, and a feature
    column that appears and disappears with network weather produces a model
    whose saved feature list stops matching the next run's -- a failure this
    project has already had once (see predict.py's feature-name guard).
    So the candidate column is built from ^IRX, the 13-week Treasury bill
    yield: keyless on Yahoo, and the market's own reading of where policy is
    going. Its agreement with the real thing is measured first, because a
    proxy nobody checked is just a second unknown.
    """
    print(f"\n{'-' * 96}")
    print(f"4) KOLON KARARI -- {asset.label}: politika durusu modele bir sey katiyor mu?")
    print(f"{'-' * 96}")

    try:
        irx = fetch_data.get_daily("^IRX", years=25)
    except Exception as exc:  # noqa: BLE001
        print(f"  ^IRX alinamadi ({exc}) -- bolum atlaniyor.")
        return
    if irx.empty:
        print("  ^IRX bos dondu -- bolum atlaniyor.")
        return

    index = pd.DatetimeIndex(panel["time"]).normalize()
    series = irx.set_index(pd.DatetimeIndex(irx["time"]).normalize())["close"]
    series = series[~series.index.duplicated(keep="last")]
    aligned = series.reindex(index, method="ffill")

    df = build_features(panel, asset.leading_drivers)
    # 126 sessions ~ six months: long enough that a single meeting cannot flip
    # the stance, short enough to turn within a cycle. In POINTS of yield, so
    # it is scale-free across a panel where the policy rate ran 0% to 5.4%.
    df["policy_tilt"] = (aligned - aligned.shift(126)).to_numpy()

    proxy_state = np.where(df["policy_tilt"] > 0.10, "TIGHTENING",
                           np.where(df["policy_tilt"] < -0.10, "EASING", "HOLD"))
    truth = policy["policy_state"].to_numpy()
    n = min(len(proxy_state), len(truth))
    both = np.isin(truth[:n], ("EASING", "TIGHTENING")) & np.isin(
        proxy_state[:n], ("EASING", "TIGHTENING"))
    agree = float((proxy_state[:n][both] == truth[:n][both]).mean()) if both.any() else float("nan")
    print(f"  Vekil dogrulamasi: ^IRX 126 gunluk egimi, FRED'in gercek Fed durusuyla")
    print(f"  {both.sum()} seansta karsilastirildi -> %{100 * agree:.1f} uyum.")
    print("  (Uyusmadigi yer bilgi olabilir de gurultu de -- vekil piyasanin BEKLENTISI,")
    print("   FRED'inki gerceklesmis karar. Ikisinin ayni olmasi zaten beklenmez.)\n")

    horizon = ml_model.HORIZON_DAYS
    base_features = ml_model.available_features(df)
    frame = df.dropna(subset=base_features + ["policy_tilt"]).reset_index(drop=True)
    fwd = ablation.forward_frame(frame, horizon)

    print(f"  Yuruyen-ileri A/B, {len(frame)} satir, ufuk {horizon}g. Tek degisen: kolon.")
    print(f"{'ozellik seti':<30}{'kolon':>7}{'IC':>10}{'t':>8}{'dogruluk':>11}{'p (esli)':>11}")
    baseline = ablation.score(edge.walk_forward(frame, horizon, features=base_features),
                              fwd, horizon)
    if not baseline:
        print("  Yetersiz satir -- bolum atlaniyor.")
        return
    print(f"{'uretim (mevcut)':<30}{len(base_features):>7}{baseline['ic']:>+10.4f}"
          f"{baseline['t']:>+8.2f}{baseline['acc']:>11.4f}{'--':>11}")

    variant = ablation.score(
        edge.walk_forward(frame, horizon, features=base_features + ["policy_tilt"]),
        fwd, horizon)
    if variant:
        pval = ablation.paired_ic_test(baseline, variant, horizon)
        verdict = "EKLE" if pval < 0.05 / N_TESTS and variant["ic"] > baseline["ic"] else "ekleme"
        print(f"{'+ policy_tilt (^IRX 126g)':<30}{len(base_features) + 1:>7}"
              f"{variant['ic']:>+10.4f}{variant['t']:>+8.2f}{variant['acc']:>11.4f}"
              f"{pval:>11.3f}   {verdict}")
    print("\n  Tek bolmede permutasyon onemi BURADA YETMEZ: ratio.py'de iki test her iki")
    print("  metalde de isaret bakimindan celisti. Esli test farkin gurultuyu asip")
    print("  asmadigini soyleyen tek sey.")


def run_asset(key: str, target: pd.DataFrame, results: list) -> None:
    asset = assets_module.get(key)
    panel = panel_module.load(key)
    df = policy_frame(panel, target)
    df = df[df["fed_target"].notna()].reset_index(drop=True)
    split = len(df) // 2

    print("\n" + "=" * 96)
    print(f"### {asset.label.upper()}  ({len(df)} seans, "
          f"{df['time'].iloc[0].date()} -> {df['time'].iloc[-1].date()})")
    print(f"### Egitim yarisi ... {df['time'].iloc[split - 1].date()} | "
          f"Test yarisi {df['time'].iloc[split].date()} ...")
    print("=" * 96)
    counts = df["policy_state"].value_counts()
    print("  Rejim dagilimi: " + ", ".join(
        f"{state} {int(counts.get(state, 0))} seans" for state in REGIMES))

    section_events(df, asset)
    section_regimes(df, asset, split, results)
    section_surprise(df, asset, split, results)
    section_feature_ab(panel, df, asset)


def main() -> int:
    started = time.time()
    print("=" * 96)
    print("FED FAIZ DONGUSU: metaller icin olay, rejim ve surpriz -- ayri ayri")
    print("=" * 96)
    print(f"  Onceden ilan edilen aile: {N_TESTS} test, Bonferroni esigi |t|/|z| > {BONFERRONI_T:.2f}")

    target = fetch_data.get_fed_target_rate()
    if target is None:
        print("\n  FRED ulasilamadi -- bu calisma FRED'in Fed hedef faiz serisine bagli")
        print("  ve vekili YOK. Tekrar dene; agdan agiliyor (bkz. fetch_data.FRED_CSV).")
        return 1
    print(f"  Fed hedef faizi: {len(target)} gun, {target['time'].iloc[0].date()} -> "
          f"{target['time'].iloc[-1].date()}, son {float(target['value'].iloc[-1]):.3f}%")

    results: list = []
    for key in ("gold", "silver"):
        run_asset(key, target, results)

    passed = [r for r in results if r[4]]
    print("\n" + "=" * 96)
    print("SONUC")
    print("=" * 96)
    print(f"  Esigi gecen hucre: {len(passed)} / {len(results)}")
    for key, regime, horizon, stat, _ in passed:
        print(f"    {key:<8}{regime:<12}{horizon:>3}g  istatistik={stat:+.2f}")
    if not passed:
        print("  HICBIRI. Okunusu 'faiz onemsiz' DEGIL: faiz seviyesinin ve yonunun")
        print("  metallere etkisi eszamanli olarak devasa (bkz. drivers.py, tip t=+6.6).")
        print("  Bu calismanin soyledigi, o etkinin GUNLUK KARAR PENCERESINDE ayrica")
        print("  alinabilir bir sey birakmadigidir -- politika yonu zaten fiyatlanmis")
        print("  hâlde tahvil serilerinin icinde geliyor ve model onlari zaten okuyor.")
    print(f"\n  ({time.time() - started:.0f} sn)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
