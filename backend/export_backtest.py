"""Writes the backtest's equity curves to a static file the frontend can draw.

WHY THIS EXISTS
---------------
backtest.py prints 19.5 years of measurement to stdout and nothing else. The
workflow is `workflow_dispatch`, so the only copy of the one sample in this
project that carries any information lives in a GitHub Actions log that
expires in ninety days -- while the dashboard shows a live paper book that
started in September 2026 and will not be able to rank anything against
buy-and-hold for roughly a decade (~2500 sessions, against the 16 it has).

The page was therefore showing the noisy sample and hiding the informative
one. This closes that gap: the same numbers backtest.py prints, emitted once
as JSON, drawn as a curve.

WHY A FILE AND NOT A SUPABASE TABLE
-----------------------------------
Everything else on the dashboard is a row someone's cron wrote, so a table is
the reflex. It is the wrong shape here:

  * This payload changes only when a person deliberately re-runs the
    backtest, which is also the only time the numbers in research/README.md
    change. A file in the repo is versioned ALONGSIDE the parameters that
    produced it -- change trading.TREND_OFF_EXPOSURE and the diff shows both
    the constant and the curve it moved, in one commit. A table would let the
    two drift apart silently, which is the failure mode this whole project is
    organised against.
  * A table needs a migration the repo cannot apply itself (see
    predict.PENDING_MIGRATION_COLUMNS for what that costs), a service_role
    write path, and an RLS policy -- for data that is neither live nor
    per-user.
  * It deploys with the frontend on the same Vercel push, so the chart and
    the page that draws it can never be out of step.

WHAT IS IN IT, AND WHAT IS DELIBERATELY NOT
-------------------------------------------
ONE cost rung per asset: the one that asset's live books actually pay
(assets.Asset.fee_rate). backtest.py sweeps the whole ladder because "is there
a signal" and "could a person keep it" are different questions; a chart that
answered a third question -- some other rung -- while sitting on a page whose
paper books run at this one would be comparing two different worlds under one
axis.

`claude` is absent because it cannot be backtested at all (see backtest.py),
and `kanalfinans` because it is driven by a video archive nobody kept. The
frontend states both rather than showing nine curves under a caption that
says ten.

Equity is sampled WEEKLY, not daily. At 4900 sessions a daily curve is ~5x
the bytes for a line that is 1100px wide -- more points than pixels. The last
session is always kept, so the final value the card prints is the real one
rather than whatever the sampling grid happened to land on.

Usage:  cd backend && python export_backtest.py [gold] [silver]
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore", message=".*sklearn.utils.parallel.delayed.*")

import numpy as np  # noqa: E402

import assets as assets_module  # noqa: E402
import backtest as backtest_module  # noqa: E402
import trading  # noqa: E402
from indicators import build_features  # noqa: E402

OUT_PATH = Path(__file__).resolve().parent.parent / "frontend" / "data" / "backtest.json"

# Every 5th session plus the last. One point per trading week.
SAMPLE_EVERY = 5

# Schema version. The frontend refuses to draw a payload it does not
# recognise rather than rendering half a chart from fields that moved -- a
# blank card with a reason beats a curve that is quietly wrong.
SCHEMA = 1


def sample_indices(n: int) -> list[int]:
    """Weekly positions, with the last session ALWAYS included.

    One shared index list for dates and for every strategy's equity, so the
    two can never drift apart -- a curve whose x and y were sampled on
    different grids is off by up to a week and looks perfectly plausible.
    """
    idx = list(range(0, n, SAMPLE_EVERY))
    if idx and idx[-1] != n - 1:
        idx.append(n - 1)
    return idx


def sample(values, idx: list[int]) -> list[float]:
    """`values` at `idx`, rounded to the cent.

    Rounding is safe here and nowhere else in this repo: these are display
    coordinates for a curve spanning $1,000 to ~$10,000, where a cent is four
    orders of magnitude below the line width. Every METRIC below is computed
    on the full unrounded series, so nothing derived from this file inherits
    the rounding.
    """
    return [round(float(values[i]), 2) for i in idx]


def run_asset(asset) -> dict:
    print(f"\n### {asset.label} ({asset.symbol})", flush=True)
    sys.path.insert(0, str(Path(__file__).resolve().parent / "research"))
    import panel as panel_module  # noqa: PLC0415 -- research path added above

    raw = panel_module.load(asset.key)
    df = build_features(raw, asset.leading_drivers)
    print(f"  {len(df)} seans, yuruyen-ileri sinyal yolu hesaplaniyor...", flush=True)
    path = backtest_module.compute_signal_path(df, asset)
    years = (path["time"].iloc[-1] - path["time"].iloc[0]).days / 365.25
    print(f"  {len(path)} test gunu, {years:.1f} yil", flush=True)

    books = backtest_module.simulate(path, asset.fee_rate, asset)

    dates = [t.date().isoformat() for t in path["time"]]
    idx = sample_indices(len(dates))
    strategies = {}
    for name, book in books.items():
        metrics = backtest_module.metrics(book.equity, book.exposure, years)
        strategies[name] = {
            "equity": sample(book.equity, idx),
            "final": round(metrics["final"], 2),
            "cagr": round(metrics["cagr"], 5),
            "vol": round(metrics["vol"], 5),
            "max_dd": round(metrics["max_dd"], 5),
            "calmar": round(metrics["calmar"], 4),
            "exposure": round(metrics["exposure"], 4),
            "trades": book.trades,
            "fees": round(book.fees_paid, 2),
        }
        print(f"    {name:<12} ${metrics['final']:>9,.0f}  "
              f"YBG %{100 * metrics['cagr']:.1f}  maksDD %{100 * metrics['max_dd']:.1f}  "
              f"Calmar {metrics['calmar']:.3f}  {book.trades} islem")

    return {
        "symbol": asset.symbol,
        "label": asset.label,
        "start": dates[0],
        "end": dates[-1],
        "years": round(years, 2),
        "sessions": len(path),
        "starting_cash": trading.STARTING_CASH,
        # One-way, in basis points -- the rung this asset's live books pay.
        "fee_bps": round(asset.fee_rate * 10_000, 1),
        "dates": [dates[i] for i in idx],
        "strategies": strategies,
    }


def main() -> int:
    keys = [a for a in sys.argv[1:] if not a.startswith("-")] or list(assets_module.ASSETS)
    payload = {
        "schema": SCHEMA,
        # Not a timestamp of "now" but of the last session measured -- the
        # question a reader has is how current the MEASUREMENT is, and a
        # generation time would answer a different one and look fresher.
        "assets": {},
        "excluded": {
            "claude": "Geçmişi ücretli bir LLM çağrısıyla tekrar oynatmak hem pahalı "
                      "hem anlamsız olurdu (model o tarihleri zaten biliyor).",
            "kanalfinans": "Bir insanın video arşivine bağlı ve o arşiv tutulmuyor.",
        },
    }
    for key in keys:
        payload["assets"][key] = run_asset(assets_module.get(key))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")
    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"\nYazildi: {OUT_PATH.relative_to(OUT_PATH.parent.parent.parent)} "
          f"({size_kb:.0f} KB)")
    if size_kb > 400:
        print("UYARI: dosya 400 KB'yi asti -- SAMPLE_EVERY'yi buyut.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
