"""Is a "leading" driver really leading, or is the calendar just misaligned?

drivers.py found three series whose change today correlates with gold's
return tomorrow past a Bonferroni threshold -- TIP (t=+6.8), IEF (t=+3.9),
VIX (t=-3.6). A next-day correlation of r=0.12 for TIP is large enough to be
worth real money, and therefore large enough to be worth disbelieving until
it survives a test designed to kill it.

The specific worry is alignment. Every series here is joined on a normalized
calendar date, but the instruments do not close at the same instant: COMEX
gold's session runs to 17:00 New York, US bond ETFs stop at 16:00, and Yahoo
stamps the gold daily bar at 04:00 UTC. If that join is off by one day
anywhere, a *contemporaneous* relationship -- of which gold has several very
strong ones -- gets relabelled as a *predictive* one, and it will look
fantastic. This is the same class of error as XRP-Guess's resolve-at-
live-price bug: not a crash, just a number that is quietly measuring
something other than what it claims.

The diagnostic is a cross-correlation scan across lags -5..+5:

    lag  0  driver change today   vs gold return today      (contemporaneous)
    lag +1  driver change today   vs gold return tomorrow   (driver LEADS)
    lag -1  driver change today   vs gold return yesterday  (gold LEADS driver)

What each shape means:
  * A clean spike at lag 0 that decays either side  -> alignment is right,
    the relationship is contemporaneous, nothing to trade.
  * A peak sitting at +1 instead of 0               -> the join is shifted a
    day; the "prediction" is yesterday's news.
  * Meaningful weight at NEGATIVE lags              -> gold leads the driver,
    so a positive lag reading is likely the same effect reflected back.
  * A small but genuinely decaying positive tail    -> a real lead.
"""
from __future__ import annotations

import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import drivers  # noqa: E402
import panel as panel_module  # noqa: E402

LAGS = list(range(-5, 6))
# The three drivers.py flagged, plus dxy/silver as controls: their relationship
# with gold is known to be contemporaneous, so they show what "correctly
# aligned and not predictive" is supposed to look like on this scan.
WATCH = ["tip", "ief", "vix", "dxy", "silver", "us10y"]


def scan(driver_change: np.ndarray, gold_return: np.ndarray) -> dict[int, tuple[float, float, int]]:
    """corr(driver at t, gold return at t+lag) for each lag."""
    out = {}
    for lag in LAGS:
        if lag >= 0:
            x = driver_change[: len(driver_change) - lag] if lag else driver_change
            y = gold_return[lag:]
        else:
            x = driver_change[-lag:]
            y = gold_return[: len(gold_return) + lag]
        out[lag] = drivers._corr_t(np.asarray(x, dtype=float), np.asarray(y, dtype=float))
    return out


def bar(r: float, scale: float) -> str:
    """Tiny ASCII magnitude bar so the shape is visible at a glance."""
    if not np.isfinite(r) or scale <= 0:
        return ""
    width = int(round(abs(r) / scale * 18))
    return ("+" if r > 0 else "-") * max(width, 0)


def main() -> int:
    df = panel_module.load().reset_index(drop=True)
    gold_ret = df["close"].pct_change().to_numpy(dtype=float)
    changes = drivers.build_changes(df)

    print(f"Panel: {len(df)} gun ({df['time'].iloc[0].date()} -> {df['time'].iloc[-1].date()})")
    print("\nlag +1 = surucu ONCE hareket etti, altin ERTESI GUN takip etti (ALINABILIR)")
    print("lag  0 = ayni gun (aciklayici, alinamaz)")
    print("lag -1 = altin once hareket etti, surucu ertesi gun takip etti\n")

    for name in WATCH:
        if name not in changes.columns:
            continue
        result = scan(changes[name].to_numpy(dtype=float), gold_ret)
        peak_lag = max(result, key=lambda k: abs(result[k][0]) if np.isfinite(result[k][0]) else -1)
        scale = abs(result[peak_lag][0])

        verdict = {
            0: "ESZAMANLI (dogru hizalama, alinamaz)",
        }.get(peak_lag, f"TEPE lag={peak_lag:+d}")
        if peak_lag > 0:
            verdict += "  <-- HIZALAMA SUPHESI" if abs(result[peak_lag][0]) > 0.1 else "  (zayif tepe)"

        print("=" * 84)
        print(f"{name.upper()}   tepe lag={peak_lag:+d}   {verdict}")
        print("=" * 84)
        for lag in LAGS:
            r, t, n = result[lag]
            marker = "  <== ayni gun" if lag == 0 else ("  <== tahmin" if lag == 1 else "")
            print(f"   lag {lag:+d}: r={r:+.4f}  t={t:+6.2f}  n={n:5d}  {bar(r, scale):<20}{marker}")
        print()

    print("=" * 84)
    print("SONUC OKUMASI")
    print("=" * 84)
    print("  dxy/silver/us10y kontrol serileridir: iliskilerinin ESZAMANLI oldugu")
    print("  biliniyor. Onlarin tepesi lag 0'da cikiyorsa takvim hizalamasi dogrudur,")
    print("  ve o zaman tip/ief/vix'in lag +1 okumalari gercek birer oncu sinyaldir.")
    print("  Tepe lag 0 yerine +1'e kaymissa, sorun veride degil birlestirmededir.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
