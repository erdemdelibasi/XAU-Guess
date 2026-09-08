"""Two questions FRED being reachable makes answerable for the first time.

    1. THE PROXY. indicators.py reconstructs the 10Y real yield from two ETFs
       (TIP / IEF) because FRED's own DFII10 was unreachable when this project
       was built. The code says, in several places, that the proxy captures
       the SHAPE and not the LEVEL and must never be quoted as a real yield.
       That was a reasonable assumption. It was never measured. Here it is.

    2. THE OFFICIAL-SECTOR BID. "Central banks are buying" is the standard
       explanation for gold's behaviour since 2022, and it is the one thing a
       reader most often asks this system to track. It cannot be tracked
       directly: the World Gold Council's reserve tonnage is quarterly,
       published with a lag of weeks, and behind a registration wall -- there
       is no keyless daily series, and this project does not use keys for
       market data. Section 3 says so plainly and then measures the only thing
       that IS measurable at daily frequency: the FOOTPRINT such buying would
       leave. If a large, price-insensitive buyer is present, gold rises by
       more than its own macro drivers explain, persistently. That is a
       residual, and a residual can be measured.

       Measuring the footprint is not the same as measuring the buying, and
       section 3 never claims it is. A residual is whatever the model does not
       explain -- central bank demand, ETF flows, a missing variable, or the
       model being wrong.

WHY THE ANSWERS CANNOT SIMPLY BE WIRED IN
-----------------------------------------
Even where FRED wins, the live prediction path may not depend on it. FRED
returned nothing on 2026-09-07 and everything on 2026-09-08 from the same
machine (see fetch_data.FRED_CSV), and a feature column whose presence
follows network weather produces a model whose saved feature list stops
matching the next run's -- which this project has already hit once and guards
against explicitly in predict.py. So the deliverable here is knowledge about
how good the proxy is, not a new dependency.
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

import ablation  # noqa: E402
import assets as assets_module  # noqa: E402
import edge  # noqa: E402
import fetch_data  # noqa: E402
import ml_model  # noqa: E402
import panel as panel_module  # noqa: E402
from indicators import build_features  # noqa: E402

HORIZONS = (1, 5, 20, 60)

# Declared before the run. Section 2 puts only the TRADEABLE lag in the
# family (the same-day column is printed for contrast and claims nothing):
# 4 series x 2 metals = 8. Section 3: 4 horizons x 2 metals = 8. One family
# of 16.
N_TESTS = 16
BONFERRONI_T = float(scipy_stats.norm.isf(0.025 / N_TESTS))

# Rolling window for the macro model in section 3. 250 sessions ~ one year:
# long enough for a stable two-factor fit, short enough that a regime change
# shows up as a moving coefficient rather than being averaged away.
ROLL_WINDOW = 250


def attach_fred(df: pd.DataFrame, series: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Forward-fill FRED series onto the panel's own trading calendar.

    Same direction-of-fill discipline as fetch_data.align_on_gold: only ever
    backward, so no future value can reach an earlier row.
    """
    out = df.copy()
    index = pd.DatetimeIndex(out["time"]).normalize()
    for name, frame in series.items():
        if frame is None or frame.empty:
            continue
        s = frame.set_index(pd.DatetimeIndex(frame["time"]).normalize())["value"]
        s = s[~s.index.duplicated(keep="last")]
        out[name] = s.reindex(index, method="ffill").to_numpy()
    return out


def corr_t(x: np.ndarray, y: np.ndarray, horizon: int) -> tuple[float, float, int]:
    mask = np.isfinite(x) & np.isfinite(y)
    n = int(mask.sum())
    if n < 50:
        return float("nan"), float("nan"), n
    r = float(np.corrcoef(x[mask], y[mask])[0, 1])
    n_eff = max(n / horizon, 3)
    t = r * math.sqrt(max(n_eff - 2, 1)) / math.sqrt(max(1 - r ** 2, 1e-12))
    return r, t, n


# --------------------------------------------------------------------------
# 1) Is the proxy any good?
# --------------------------------------------------------------------------

def section_proxy(df: pd.DataFrame) -> None:
    print("\n" + "=" * 96)
    print("1) VEKIL NE KADAR IYI? -- TIP/IEF yeniden kurulumu vs FRED DFII10")
    print("=" * 96)
    print("  indicators.py 10 yillik REEL FAIZI iki ETF'ten yeniden kuruyor:")
    print("    breakeven ~ TIP/IEF,  real_yield_chg = us10y.diff(5) - (100/sure) x breakeven.diff(5)")
    print("  Kodda yazan iddia: 'sekli yakalar, seviyeyi degil.' Simdiye kadar")
    print("  olculmemisti. DFII10 gercek serinin ta kendisi, artik elimizde.\n")

    true_level = df["dfii10"].to_numpy(dtype=float)
    true_chg5 = pd.Series(true_level).diff(5).to_numpy()
    proxy_chg5 = df["real_yield_chg"].to_numpy(dtype=float)
    # The proxy is built to move the SAME way as the yield: it is
    # nominal-yield change minus breakeven change, both in points.
    r_level, _, n_level = corr_t(true_level, df["breakeven_proxy"].to_numpy(dtype=float), 1)
    r_chg, t_chg, n_chg = corr_t(true_chg5, proxy_chg5, 5)

    print(f"{'karsilastirma':<44}{'r':>10}{'n':>8}")
    print(f"{'SEVIYE: DFII10 vs TIP/IEF orani':<44}{r_level:>+10.3f}{n_level:>8}")
    print(f"{'DEGISIM(5g): DFII10 vs real_yield_chg':<44}{r_chg:>+10.3f}{n_chg:>8}")

    scale_true = float(np.nanstd(true_chg5))
    scale_proxy = float(np.nanstd(proxy_chg5))
    print(f"\n  5 gunluk degisimin std sapmasi: gercek {scale_true:.4f} puan, "
          f"vekil {scale_proxy:.4f} puan (oran {scale_proxy / scale_true:.2f}x)")
    print("  Bu oran 1'e ne kadar yakinsa, indicators.REAL_YIELD_SCALE'in gercek")
    print("  bir faiz hareketini olcekledigi o kadar dogrudur.")
    print("\n  Okunusu: SEVIYE korelasyonu vekilin ne olmadigini gosterir -- TIP/IEF")
    print("  orani bir enflasyon beklentisi vekilidir, reel faizin kendisi degil.")
    print("  Kararlarda kullanilan sey DEGISIM ve karsilastirma orada yapilmali.")


# --------------------------------------------------------------------------
# 2) Which one actually leads the metal?
# --------------------------------------------------------------------------

def section_lead(df: pd.DataFrame, asset, split: int, results: list) -> None:
    print("\n" + "=" * 96)
    print(f"2) HANGISI ONCULUYOR? -- {asset.label}")
    print("=" * 96)
    print("  research/drivers.py'nin ayrimi burada da gecerli: ayni gun iliskisi")
    print("  ACIKLAR ama alinamaz (bugunun reel faizini ogrendiginde bugunun altin")
    print("  kapanisini da ogrenmissindir); alinabilir olan ERTESI GUNdur.")
    print(f"  Esik |t| > {BONFERRONI_T:.2f} (Bonferroni, {N_TESTS} testlik tek aile).\n")

    print("  PENCERELER ESLESTIRILDI. Ilk surumu boyle degildi ve sonucu tersine")
    print("  cevirmisti: gercek seri 1 GUNLUK farkla, vekil ise uretimdeki 5 GUNLUK")
    print("  haliyle karsilastirilmisti. 1 gunluk fark dunku habere cok daha")
    print("  duyarlidir, dolayisiyla ertesi gun korelasyonu dogal olarak daha")
    print("  yuksek cikar -- olculen sey serinin kalitesi degil, pencere uzunlugu")
    print("  olurdu. Asagida her iki seri de HEM 1 gunluk HEM 5 gunluk halde.\n")

    ret = df["close"].pct_change().to_numpy(dtype=float)
    # The proxy, rebuilt at a one-day window with the identical formula
    # indicators.add_macro_columns uses at five, so the only thing that
    # differs between a row pair below is which series it came from.
    duration = 7.5
    proxy_1d = (pd.Series(df["us10y"]).diff()
                - (100.0 / duration) * pd.Series(df["breakeven_proxy"]).pct_change()).to_numpy()
    candidates = {
        "DFII10 1g (gercek)": pd.Series(df["dfii10"]).diff().to_numpy(),
        "TIP/IEF vekili 1g": proxy_1d,
        "DFII10 5g (gercek)": pd.Series(df["dfii10"]).diff(5).to_numpy(),
        "TIP/IEF vekili 5g (uretim)": df["real_yield_chg"].to_numpy(dtype=float),
    }
    print(f"{'seri':<28}{'gecikme':>9}{'r (egitim)':>13}{'r (test)':>11}{'t':>8}{'gecti':>8}")
    for name, x in candidates.items():
        for lag, label in ((0, "ayni gun"), (1, "ertesi gun")):
            y = np.roll(ret, -lag) if lag else ret
            if lag:
                y = y.astype(float).copy()
                y[-lag:] = np.nan
            r_tr, _, _ = corr_t(x[:split], y[:split], 1)
            r_te, t_te, _ = corr_t(x[split:], y[split:], 1)
            passed = (np.isfinite(t_te) and abs(t_te) > BONFERRONI_T
                      and np.sign(r_tr) == np.sign(r_te))
            if lag:  # only the tradeable lag joins the declared family
                results.append((asset.key, name, t_te, bool(passed)))
            print(f"{name:<28}{label:>9}{r_tr:>+13.4f}{r_te:>+11.4f}{t_te:>+8.2f}"
                  f"{('EVET' if passed else 'hayir'):>8}")

    print("\n  Beklenen isaret NEGATIF: reel faiz artarsa sifir getirili bir varligin")
    print("  firsat maliyeti artar. Ayni gun bu iliski buyuk, ertesi gune ne kaldigi")
    print("  bu tablonun sorusu.")


# --------------------------------------------------------------------------
# 3) The official-sector bid, as a footprint
# --------------------------------------------------------------------------

def section_official_bid(df: pd.DataFrame, asset, split: int, results: list) -> None:
    print("\n" + "=" * 96)
    print(f"3) MERKEZ BANKASI ALIMI -- {asset.label}: olcemedigimiz sey ve olcebildigimiz sey")
    print("=" * 96)
    print("  OLCEMEDIGIMIZ: gercek rezerv tonaji. Dunya Altin Konseyi verisi UC AYLIK,")
    print("  haftalarca gecikmeli ve kayit duvarinin arkasinda. Gunluk, anahtarsiz bir")
    print("  serisi YOK ve bu proje piyasa verisi icin anahtar kullanmiyor. Bunu")
    print("  'izliyoruz' demek yanlis olurdu.")
    print("\n  OLCEBILDIGIMIZ: boyle bir alicinin birakacagi IZ. Fiyata duyarsiz, buyuk")
    print("  ve israrli bir alici varsa altin, kendi makro surucülerinin acikladigindan")
    print("  FAZLA yukselir -- ve bu bir artiktir. Her gun 250 seanslik pencerede")
    print("      getiri ~ a + b1 x reel faiz degisimi + b2 x dolar getirisi")
    print("  fit edilir; `a` aciklanamayan surukleme, `b1` reel faize duyarlilik.")
    print("\n  UYARI, ve bu bolumun en onemli cumlesi: artik = 'merkez bankasi alimi'")
    print("  DEGILDIR. Artik, modelin aciklamadigi HER SEYdir -- ETF akislari, eksik")
    print("  bir degisken, ya da modelin kendisinin yanlis olmasi dahil.\n")

    ret = df["close"].pct_change()
    dxy_ret = pd.Series(df["dxy"]).pct_change() if "dxy" in df else pd.Series(np.nan, index=df.index)
    ry_chg = pd.Series(df["dfii10"]).diff()

    alpha = np.full(len(df), np.nan)
    beta = np.full(len(df), np.nan)
    y_all = ret.to_numpy(dtype=float)
    x1 = ry_chg.to_numpy(dtype=float)
    x2 = dxy_ret.to_numpy(dtype=float)
    for i in range(ROLL_WINDOW, len(df)):
        sl = slice(i - ROLL_WINDOW, i)
        y, a1, a2 = y_all[sl], x1[sl], x2[sl]
        mask = np.isfinite(y) & np.isfinite(a1) & np.isfinite(a2)
        if mask.sum() < ROLL_WINDOW // 2:
            continue
        design = np.column_stack([np.ones(mask.sum()), a1[mask], a2[mask]])
        try:
            coef, *_ = np.linalg.lstsq(design, y[mask], rcond=None)
        except np.linalg.LinAlgError:
            continue
        alpha[i] = coef[0]
        beta[i] = coef[1]

    df = df.assign(macro_alpha=alpha, real_yield_beta=beta)
    years = pd.DatetimeIndex(df["time"]).year
    print(f"{'yil':>6}{'yillik artik %':>16}{'reel faiz betasi':>19}{'gerceklesen %':>15}")
    for year in sorted(set(years)):
        m = years == year
        if not np.isfinite(alpha[m]).any():
            continue  # the first ROLL_WINDOW sessions have no fit yet
        a = float(np.nanmean(alpha[m]))
        b = float(np.nanmean(beta[m]))
        realised = float(np.nansum(y_all[m]))
        print(f"{year:>6}{100 * a * 252:>16.1f}{b:>19.3f}{100 * realised:>15.1f}")

    print("\n  'yillik artik' = makro modelin aciklayamadigi surukleme, yillandirilmis.")
    print("  'reel faiz betasi' negatif olmali (faiz artar, metal duser). Bu sayinin")
    print("  sifira dogru kaymasi, o meshur 'altin reel faizden koptu' iddiasinin")
    print("  olculebilir halidir -- ve kopma ile alim ayni sey degildir.\n")

    print("  Peki bu artik ISE YARAR MI? Yani buyuk bir artik, ardindan gelen")
    print("  getiriyi ONCULUYOR mu? Onculuyorsa alinabilir bir sey var demektir.")
    print(f"{'ufuk':>7}{'r (egitim)':>13}{'r (test)':>11}{'t':>8}{'gecti':>8}")
    for horizon in HORIZONS:
        fwd = (df["close"].shift(-horizon) / df["close"] - 1.0).to_numpy(dtype=float)
        r_tr, _, _ = corr_t(alpha[:split], fwd[:split], horizon)
        r_te, t_te, _ = corr_t(alpha[split:], fwd[split:], horizon)
        passed = (np.isfinite(t_te) and abs(t_te) > BONFERRONI_T
                  and np.sign(r_tr) == np.sign(r_te))
        results.append((asset.key, f"alpha{horizon}", t_te, bool(passed)))
        print(f"{str(horizon) + 'g':>7}{r_tr:>+13.4f}{r_te:>+11.4f}{t_te:>+8.2f}"
              f"{('EVET' if passed else 'hayir'):>8}")


# --------------------------------------------------------------------------
# 4) Would the true series improve the model?
# --------------------------------------------------------------------------

def section_feature_ab(df: pd.DataFrame, asset) -> None:
    print("\n" + "=" * 96)
    print(f"4) KOLON KARARI -- {asset.label}: gercek seri vekilin yerini alsa ne olur?")
    print("=" * 96)
    print("  Bu bir DUSUNCE DENEYI, dogrudan uygulanabilir bir degisiklik degil:")
    print("  canli yol FRED'e bagimli olamaz (bkz. modul docstring'i). Ama cevap")
    print("  vekilin bize NEYE MAL OLDUGUNU soyler -- fark yoksa vekil bedava.\n")

    horizon = ml_model.HORIZON_DAYS
    base_features = ml_model.available_features(df)
    frame = df.dropna(subset=base_features + ["dfii10"]).reset_index(drop=True)
    frame["dfii10_chg5"] = frame["dfii10"].diff(5)
    frame = frame.dropna(subset=["dfii10_chg5"]).reset_index(drop=True)
    fwd = ablation.forward_frame(frame, horizon)

    swapped = [c for c in base_features if c != "real_yield_chg"] + ["dfii10_chg5"]
    print(f"  {len(frame)} satir, ufuk {horizon}g. Ayni satirlar, ayni fit programi.")
    print(f"{'ozellik seti':<34}{'kolon':>7}{'IC':>10}{'t':>8}{'dogruluk':>11}{'p (esli)':>11}")
    baseline = ablation.score(edge.walk_forward(frame, horizon, features=base_features),
                              fwd, horizon)
    if not baseline:
        print("  Yetersiz satir -- bolum atlaniyor.")
        return
    print(f"{'uretim (TIP/IEF vekili)':<34}{len(base_features):>7}{baseline['ic']:>+10.4f}"
          f"{baseline['t']:>+8.2f}{baseline['acc']:>11.4f}{'--':>11}")
    variant = ablation.score(edge.walk_forward(frame, horizon, features=swapped), fwd, horizon)
    if variant:
        pval = ablation.paired_ic_test(baseline, variant, horizon)
        print(f"{'gercek DFII10 ile degistirildi':<34}{len(swapped):>7}{variant['ic']:>+10.4f}"
              f"{variant['t']:>+8.2f}{variant['acc']:>11.4f}{pval:>11.3f}")
        verdict = ("vekil olculebilir sekilde daha kotu" if pval < 0.05 and variant["ic"] > baseline["ic"]
                   else "fark olculemedi -- vekil bedava")
        print(f"  -> {verdict}")


def section_window(df: pd.DataFrame, asset) -> None:
    """The finding section 2 actually produced, tested the way a column
    decision has to be tested.

    Section 2 was set up to ask "true series or proxy?" and answered
    "indistinguishable". What it found instead, in both metals and on both
    series, is that the WINDOW is wrong: the one-day real-yield change clears
    the Bonferroni bar on the next day's return and the five-day change --
    which is what production actually computes -- does not.

    That is consistent with everything else here rather than a surprise.
    Every other measured lead in this project is a ONE-day change
    (`tip_chg`, `ief_chg`, `vix_chg` -- research/drivers.py), and
    `real_yield_chg` is the only driver term built on a five-day window. It
    was the odd one out and nobody had checked.

    Before changing anything, the honest objection has to be tested: the
    model ALREADY carries us10y_chg, tip_chg and ief_chg, and a one-day
    real-yield change is close to a linear combination of exactly those. A
    tree may already be reconstructing it. If so the column adds nothing and
    the finding stays a finding about the technical scorer alone.
    """
    print("\n" + "=" * 96)
    print(f"5) PENCERE KARARI -- {asset.label}: real_yield_chg 5 gun mu, 1 gun mu?")
    print("=" * 96)
    print("  Durust itiraz once: model zaten us10y_chg, tip_chg ve ief_chg tasiyor.")
    print("  1 gunluk reel faiz degisimi bunlarin neredeyse dogrusal bir bileskesi --")
    print("  agac onu zaten kuruyor olabilir. Oyleyse kolon bir sey katmaz ve bulgu")
    print("  yalnizca teknik skorlayiciyi ilgilendirir.\n")

    duration = 7.5
    work = df.copy()
    work["real_yield_chg1"] = (
        pd.Series(work["us10y"]).diff()
        - (100.0 / duration) * pd.Series(work["breakeven_proxy"]).pct_change()
    ).to_numpy()

    horizon = ml_model.HORIZON_DAYS
    base_features = ml_model.available_features(work)
    frame = work.dropna(subset=base_features + ["real_yield_chg1"]).reset_index(drop=True)
    fwd = ablation.forward_frame(frame, horizon)
    swapped = [c if c != "real_yield_chg" else "real_yield_chg1" for c in base_features]

    print(f"  {len(frame)} satir, ufuk {horizon}g.")
    print(f"{'ozellik seti':<34}{'kolon':>7}{'IC':>10}{'t':>8}{'dogruluk':>11}{'p (esli)':>11}")
    baseline = ablation.score(edge.walk_forward(frame, horizon, features=base_features),
                              fwd, horizon)
    if not baseline:
        print("  Yetersiz satir -- bolum atlaniyor.")
        return
    print(f"{'uretim (5 gunluk pencere)':<34}{len(base_features):>7}{baseline['ic']:>+10.4f}"
          f"{baseline['t']:>+8.2f}{baseline['acc']:>11.4f}{'--':>11}")
    variant = ablation.score(edge.walk_forward(frame, horizon, features=swapped), fwd, horizon)
    if variant:
        pval = ablation.paired_ic_test(baseline, variant, horizon)
        print(f"{'1 gunluk pencere':<34}{len(swapped):>7}{variant['ic']:>+10.4f}"
              f"{variant['t']:>+8.2f}{variant['acc']:>11.4f}{pval:>11.3f}")

    # The scorer half of the decision. The project's own rule after the
    # duration fix: when a scale changes, check the SATURATION RATE and the
    # MEDIAN score together -- either alone is misleading, and a term that
    # quietly does nothing (median |score| 0.009) is what that rule caught.
    print("\n  TEKNIK SKORLAYICI TARAFI -- olcek sabiti yeniden olculmeli mi?")
    print(f"{'pencere':<20}{'p90 |degisim|':>16}{'onerilen bolen':>17}"
          f"{'mevcut bolenle doyma':>22}{'medyan |skor|':>16}")
    from indicators import REAL_YIELD_SCALE  # noqa: PLC0415 -- read at use, not at import
    for label, col in (("5 gun (uretim)", "real_yield_chg"), ("1 gun", "real_yield_chg1")):
        values = work[col].to_numpy(dtype=float)
        values = values[np.isfinite(values)]
        if not len(values):
            continue
        p90 = float(np.percentile(np.abs(values), 90))
        scores = np.clip(-values / REAL_YIELD_SCALE, -1, 1)
        saturation = float(np.mean(np.abs(scores) >= 0.999))
        median = float(np.median(np.abs(scores)))
        print(f"{label:<20}{p90:>16.4f}{p90:>17.4f}{100 * saturation:>21.1f}%{median:>16.3f}")
    print("  'onerilen bolen' = p90'i tam skora tasiyan deger; indicators.py'nin")
    print("  butun olcek sabitleri bu kurala gore ayarli.")


def run_asset(key: str, fred: dict, results: list) -> None:
    asset = assets_module.get(key)
    panel = panel_module.load(key)
    df = build_features(panel, asset.leading_drivers)
    df = attach_fred(df, fred)
    df = df[df["dfii10"].notna()].reset_index(drop=True)
    split = len(df) // 2

    print("\n" + "#" * 96)
    print(f"### {asset.label.upper()}  ({len(df)} seans, "
          f"{df['time'].iloc[0].date()} -> {df['time'].iloc[-1].date()})")
    print(f"### DFII10 2003'te basliyor, panel 2001'de -- ilk iki yil bu dosyada yok.")
    print("#" * 96)

    if key == "gold":
        section_proxy(df)
    section_lead(df, asset, split, results)
    section_official_bid(df, asset, split, results)
    section_feature_ab(df, asset)
    section_window(df, asset)


def main() -> int:
    started = time.time()
    print("=" * 96)
    print("REEL FAIZ VE MERKEZ BANKASI IZI")
    print("=" * 96)
    print(f"  Onceden ilan edilen aile: {N_TESTS} test, esik |t| > {BONFERRONI_T:.2f}")

    fred = {
        "dfii10": fetch_data.get_fred_series("DFII10"),
        "breakeven": fetch_data.get_fred_series("T10YIE"),
    }
    if fred["dfii10"] is None:
        print("\n  FRED ulasilamadi -- bu calismanin tamami DFII10'a bagli ve vekili")
        print("  zaten olculmek istenen seyin kendisi. Tekrar dene.")
        return 1
    print(f"  DFII10: {len(fred['dfii10'])} gun, {fred['dfii10']['time'].iloc[0].date()} -> "
          f"{fred['dfii10']['time'].iloc[-1].date()}")

    results: list = []
    for key in ("gold", "silver"):
        run_asset(key, fred, results)

    passed = [r for r in results if r[3]]
    print("\n" + "=" * 96)
    print("SONUC")
    print("=" * 96)
    print(f"  Esigi gecen hucre: {len(passed)} / {len(results)}")
    for key, name, stat, _ in passed:
        print(f"    {key:<8}{name:<28}t={stat:+.2f}")
    print(f"\n  ({time.time() - started:.0f} sn)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
