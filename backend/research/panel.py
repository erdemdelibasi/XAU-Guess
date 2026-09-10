"""Builds and caches the gold + macro daily panel the research bench runs on.

Separate from the live path on purpose: research must be able to re-run a
hypothesis a hundred times without hammering Yahoo, and must be reproducible
across a session. `panel.json` is gitignored and rebuilt in ~30 seconds.

Data hygiene applied here, once, so every downstream study inherits it:

  * The final bar is dropped when it is still forming, by
    fetch_data.drop_forming_bar -- the SAME function predict.py uses, so the
    live path and the bench can never disagree about what a closed session
    is. Yahoo happily serves today's partial session as if it were a closed
    bar and gives no usable tell in the timestamp, so completeness is decided
    against the exchange clock instead (see fetch_data.bar_is_complete).

  * Flat bars (open == high == low == close) are FLAGGED, not dropped. Yahoo
    emits these where it has a settlement print but no intraday series --
    2026-09-04 printed 4429.80 four times on volume 16, between real sessions
    of ~48000 contracts. They run 27-38% of bars in 2001-2007 and ~4-5% since
    2018, so dropping them was the first instinct.

    It was wrong, and measuring said so. Against GLD (a clean, independent
    gold series) the daily return implied by a flat bar's close correlates
    0.737, versus 0.892 for normal bars, with a median absolute difference
    of 0.175% -- actually *smaller* than the 0.213% normal bars show. The
    close is a real settlement price. Only open/high/low are fabricated, as
    copies of it.

    So dropping them would have thrown away ~11% of genuine closes AND, worse,
    silently broken calendar continuity: delete Tuesday and Monday's
    "next-day return" quietly becomes a two-day return, with no error anywhere.
    Instead `flat_bar` marks them, and the feature set prefers close-to-close
    measures over high/low ranges (see indicators.py) because the range is
    the only part that is actually missing.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd

# Windows defaults a REDIRECTED stdout to cp1252, which cannot encode the
# Turkish letters this project prints ("Altın" alone is enough). XRP-Guess
# lost a scheduled task to exactly this: every run exited 1 with
# UnicodeEncodeError, the log cut off mid-item, and the failure bookkeeping
# that should have recorded it never ran. Forcing UTF-8 at every entry point
# keeps the script correct however it is invoked.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import assets as assets_module  # noqa: E402
import fetch_data  # noqa: E402

YEARS = 25

# Series that are CANDIDATES, not drivers. Deliberately NOT in
# fetch_data.MACRO_SYMBOLS: that dict feeds the live path too (predict.py
# fetches every entry on every run), so putting an unproven series there buys a
# daily request and a silent failure surface in exchange for nothing. A series
# graduates to MACRO_SYMBOLS only after it clears research/drivers.py's
# Bonferroni bar AND research/lags.py's alignment scan.
#
# Each is here for a stated reason, and history depth is part of the reason --
# a series that starts in 2014 can only ever be measured on a third of this
# panel. GLD/SLV are deliberately absent: they are the metal itself, so they
# would add no information and only inflate the multiple-testing count.
CANDIDATE_SYMBOLS = {
    "gvz": "^GVZ",        # 2008-06. CBOE gold implied volatility -- the market's
                          # own forward view of how much gold will move. Unlike
                          # every other column here it is not derived from price
                          # history, which is the entire point.
    "move": "^MOVE",      # 2002-11. Bond implied volatility. Gold is a rates
                          # asset, so this is VIX's counterpart on the side that
                          # actually drives it.
    "gdx": "GDX",         # 2006-05. Gold miners ETF -- the widely repeated
                          # "miners lead the metal" claim, never tested here.
    "hui": "^HUI",        # 2001-09. The same claim at full panel depth, without
                          # GDX's ETF-era truncation.
    "cny": "CNY=X",       # 2001-09. The largest physical buyer's currency.
    "inr": "INR=X",       # 2003-12. The second largest.
    "hyg": "HYG",         # 2007-04. High-yield credit -- risk appetite of a kind
                          # the VIX level does not capture.
    "vix3m": "^VIX3M",    # 2006-07. With vix, the term structure slope, which is
                          # a cleaner fear measure than either level alone.
    "btc": "BTC-USD",     # 2014-09. The "digital gold" substitution claim.
}


def panel_path(asset_key: str) -> Path:
    return Path(__file__).parent / f"panel_{asset_key}.json"


def flag_flat_bars(gold: pd.DataFrame) -> pd.DataFrame:
    """Adds `flat_bar`: True where open==high==low==close (see module docstring).

    Kept, not dropped -- the close is real, only the range is fabricated.
    """
    out = gold.copy()
    out["flat_bar"] = (
        (out["open"] == out["high"]) & (out["high"] == out["low"]) & (out["low"] == out["close"])
    )
    return out


def build(asset_key: str = "gold", years: int = YEARS) -> pd.DataFrame:
    asset = assets_module.get(asset_key)
    print(f"{asset.label} gunluk verisi cekiliyor ({years} yil, {asset.symbol})...", flush=True)
    prices = fetch_data.get_daily(asset.symbol, years=years)
    raw_rows = len(prices)

    prices = fetch_data.drop_forming_bar(prices)
    prices = flag_flat_bars(prices)
    flat_count = int(prices["flat_bar"].sum())
    print(f"  {raw_rows} ham satir -> {len(prices)} satir "
          f"({raw_rows - len(prices)} olusmakta olan mum atildi; "
          f"{flat_count} duz mum isaretlendi ama TUTULDU -- kapanislari gercek)", flush=True)

    # The asset's own series is swapped out for its counterpart metal --
    # otherwise silver's panel would carry a `silver` column identical to its
    # own close (see assets.macro_symbols_for).
    wanted = {**assets_module.macro_symbols_for(asset), **CANDIDATE_SYMBOLS}
    print(f"Makro seriler cekiliyor ({len(wanted)} seri, "
          f"{len(CANDIDATE_SYMBOLS)}'i aday -- canli yolda degil)...", flush=True)
    macro = {}
    for name, symbol in wanted.items():
        try:
            frame = fetch_data.get_daily(symbol, years=years)
            if not frame.empty:
                macro[name] = frame
        except Exception as exc:  # noqa: BLE001 -- one dead series must not kill the build
            print(f"  WARNING: {name} ({symbol}) alinamadi: {exc}")
    print(f"  {len(macro)}/{len(wanted)} seri geldi: {', '.join(macro)}", flush=True)

    panel = fetch_data.align_on_gold(prices, macro)
    print(f"Panel: {panel.shape[0]} satir x {panel.shape[1]} kolon "
          f"({panel['time'].iloc[0].date()} -> {panel['time'].iloc[-1].date()})", flush=True)
    return panel


def save(panel: pd.DataFrame, asset_key: str) -> None:
    path = panel_path(asset_key)
    payload = panel.copy()
    payload["time"] = payload["time"].dt.strftime("%Y-%m-%dT%H:%M:%S%z")
    path.write_text(json.dumps(payload.to_dict(orient="list")), encoding="utf-8")
    print(f"Kaydedildi: {path.name} ({path.stat().st_size / 1e6:.1f} MB)")


def load(asset_key: str = "gold", rebuild: bool = False) -> pd.DataFrame:
    """Cached panel for `asset_key`, building it first if missing or stale."""
    path = panel_path(asset_key)
    if rebuild or not path.exists():
        panel = build(asset_key)
        save(panel, asset_key)
        return panel
    data = json.loads(path.read_text(encoding="utf-8"))
    panel = pd.DataFrame(data)
    panel["time"] = pd.to_datetime(panel["time"], utc=True, format="mixed")
    return panel


if __name__ == "__main__":
    keys = [a for a in sys.argv[1:] if not a.startswith("--")] or list(assets_module.ASSETS)
    rebuild = "--rebuild" in sys.argv
    for key in keys:
        print(f"\n{'=' * 70}\n### {key.upper()}\n{'=' * 70}")
        load(key, rebuild=rebuild or not panel_path(key).exists())
