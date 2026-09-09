"""Replays every paper portfolio over real history, against buy-and-hold.

This calls trading.compute_target_exposure() and trading.compute_rebalance()
directly -- the same functions predict.py runs live. A backtest that
reimplements the strategy is testing the reimplementation, which is how a
system ends up with a backtest that passes and a live path that doesn't.

WHAT THIS CAN AND CANNOT TEST
-----------------------------
Testable: buyhold, voltarget, trend, defensive, technical, ml, ensemble --
everything derived from price and the macro panel, both of which have deep
history.

Not testable: `claude`. Replaying a paid LLM call across 6000 historical days
would cost real money for a signal research/edge.py already suggests is worth
little, and the model would be reading dates it has memorised. It runs
live-only, exactly as XRP-Guess's claude/news/orderbook components did, and
this limitation is printed in the report rather than hidden.

Costs are swept across research/wall.py's full ladder (2 / 10 / 40 / 150 bp
round trip) instead of assuming one number. The cheap rung answers "is there
a signal", the expensive rung answers "could a person with a normal broker
actually keep it". On gold those can differ enormously: at 150 bp a strategy
that rebalances weekly gives up more than gold's entire annual drift.
"""
from __future__ import annotations

import sys
import warnings
from dataclasses import dataclass, field

sys.stdout.reconfigure(encoding="utf-8")

# HistGradientBoosting emits one of these per fit from its own internal
# parallelism. ~80 refits x 4 cost scenarios buried the actual report under
# hundreds of identical lines; the warning is about sklearn's internals, not
# about anything this file does.
warnings.filterwarnings("ignore", message=".*sklearn.utils.parallel.delayed.*")

import numpy as np
import pandas as pd

import assets as assets_module
import ml_model
import trading
from indicators import build_features, technical_signal

TRADING_DAYS = 252
# The same ladder as research/wall.py, expressed one-way (the constant
# trading.FEE_RATE is one-way too, so these substitute directly).
COST_LADDER_BPS = {"COMEX 2bp": 1.0, "ETF 10bp": 5.0, "Perakende 40bp": 20.0, "Banka 150bp": 75.0}


def cost_ladder_for(asset) -> dict[str, float]:
    """The shared ladder, plus this asset's OWN assumed cost if it is missing.

    Silver assumes 20 bp round trip (10 bp one-way) and the shared ladder has
    no such rung, so without this the report never actually shows silver at
    the cost its live portfolios use -- the reader is left comparing a metal
    against four numbers, none of which is the one that matters for it.
    """
    ladder = dict(COST_LADDER_BPS)
    own = asset.fee_rate * 10_000
    if not any(abs(own - v) < 0.01 for v in ladder.values()):
        ladder[f"{asset.label} varsayilani {2 * own:.0f}bp"] = own
    return dict(sorted(ladder.items(), key=lambda kv: kv[1]))
REFIT_EVERY = 63
MIN_TRAIN_ROWS = 750


@dataclass
class Portfolio:
    """One strategy's simulated book. Mirrors the columns in strategy_portfolios."""
    strategy: str
    cash: float = trading.STARTING_CASH
    ounces: float = 0.0
    trades: int = 0
    fees_paid: float = 0.0
    equity: list[float] = field(default_factory=list)
    exposure: list[float] = field(default_factory=list)

    def value(self, price: float) -> float:
        return self.cash + self.ounces * price

    def step(self, price: float, target: float, fee_rate: float) -> None:
        decision = trading.compute_rebalance(self.cash, self.ounces, price, target)
        if decision["action"] == "BUY":
            gross = decision["usd_amount"]
            fee = gross * fee_rate
            self.cash -= gross
            self.ounces += (gross - fee) / price
            self.trades += 1
            self.fees_paid += fee
        elif decision["action"] == "SELL":
            gross = decision["ounce_amount"] * price
            fee = gross * fee_rate
            self.cash += gross - fee
            self.ounces -= decision["ounce_amount"]
            self.trades += 1
            self.fees_paid += fee
        value = self.value(price)
        self.equity.append(value)
        self.exposure.append((self.ounces * price) / value if value > 0 else 0.0)


def metrics(equity: list[float], exposure: list[float], years: float) -> dict:
    arr = np.asarray(equity, dtype=float)
    if len(arr) < 2 or years <= 0:
        return {}
    total = arr[-1] / arr[0] - 1.0
    cagr = (arr[-1] / arr[0]) ** (1 / years) - 1.0
    rets = np.diff(arr) / arr[:-1]
    vol = float(np.std(rets)) * np.sqrt(TRADING_DAYS)
    peak = np.maximum.accumulate(arr)
    max_dd = float(np.max(1 - arr / peak))
    return {
        "total": total, "cagr": cagr, "vol": vol,
        "sharpe": cagr / vol if vol > 0 else float("nan"),
        "max_dd": max_dd,
        "calmar": cagr / max_dd if max_dd > 0 else float("nan"),
        "exposure": float(np.mean(exposure)),
        "final": float(arr[-1]),
    }


def compute_signal_path(df: pd.DataFrame, asset) -> pd.DataFrame:
    """Walk-forward signals for every testable day, computed ONCE.

    Cached across the cost ladder deliberately: the signal does not depend on
    what a trade costs, so recomputing it per cost scenario would be four
    times the work for identical numbers. (XRP-Guess's backtest made the same
    split for the same reason.) The PORTFOLIO half must still be re-run per
    scenario, because a worse fill changes the next day's holdings and
    therefore the next day's decision.
    """
    features = ml_model.available_features(df)
    labelled = df.dropna(subset=features).reset_index(drop=True)

    rows: list[dict] = []
    start = MIN_TRAIN_ROWS
    n = len(labelled)
    horizon = ml_model.HORIZON_DAYS

    while start < n:
        stop = min(start + REFIT_EVERY, n)
        future = labelled["close"].shift(-horizon)
        label = np.where(future.notna(), (future > labelled["close"]).astype(float), np.nan)
        train = labelled.iloc[: max(start - horizon, 0)].copy()
        train["label_up"] = label[: max(start - horizon, 0)]
        train = train.dropna(subset=["label_up"])
        if len(train) < MIN_TRAIN_ROWS:
            start = stop
            continue

        model = ml_model.build_estimator()
        model.fit(train[features], train["label_up"])
        block = labelled.iloc[start:stop]
        proba = model.predict_proba(block[features])[:, 1]

        for offset, ((_, row), p) in enumerate(zip(block.iterrows(), proba)):
            tech = technical_signal(labelled.iloc[start + offset: start + offset + 1],
                                    asset.price_scales)
            ml_score = float(np.clip((p - 0.5) * 2, -1, 1))
            rows.append({
                "time": row["time"], "close": float(row["close"]),
                "sma200": float(row["sma200"]) if pd.notna(row.get("sma200")) else float("nan"),
                # vol_60d, NOT vol_20d: trading.VOL_LOOKBACK_DAYS is 60, and
                # feeding the backtest a 20-day estimate would be testing a
                # different, noisier strategy than the one that runs live --
                # the exact class of backtest/live divergence this file's
                # docstring warns about, hidden inside a column name.
                "vol": float(row["vol_60d"]) * np.sqrt(TRADING_DAYS) if pd.notna(row.get("vol_60d")) else float("nan"),
                "ml_score": ml_score,
                "tech_score": tech["score"],
                # The blend is a plain average of two -1..1 scores. Anything
                # weighted would be a parameter chosen by looking at the
                # outcome, which is the error this whole bench exists to avoid.
                "ensemble_score": float(np.clip((ml_score + tech["score"]) / 2.0, -1, 1)),
                "macro_score": _macro_score(row, asset.leading_drivers),
            })
        start = stop
    return pd.DataFrame(rows)


def _macro_score(row: pd.Series, drivers: tuple[str, ...]) -> float:
    """Standalone macro signal from THIS ASSET's measured leads.

    Weights follow the measured t-statistics from research/drivers.py
    (tip +6.8, ief +5.2, vix -5.4) rather than being fitted here -- fitting
    them on the same history the backtest scores would be circular. Silver
    passes only ("tip", "vix"): its `ief` misses the significance bar
    (research/compare.py). The weights renormalise over whatever is actually
    present, so a shorter driver list weakens the signal's COVERAGE rather
    than silently shrinking its whole scale -- which would have made silver's
    macro portfolio look calm when it was really just quieter.
    """
    weights = {"tip": 0.40, "ief": 0.30, "vix": 0.30}
    parts, used = [], 0.0
    for name in drivers:
        value = row.get(f"{name}_chg")
        if pd.isna(value):
            continue
        raw = (np.clip(-float(value) / 3.0, -1, 1) if name == "vix"
               else np.clip(float(value) * 150, -1, 1))
        parts.append(raw * weights[name])
        used += weights[name]
    if not parts or used == 0:
        return 0.0
    return float(np.clip(sum(parts) / used, -1, 1))


SCORE_COLUMN = {
    "ensemble": "ensemble_score", "technical": "tech_score",
    "ml": "ml_score", "macro": "macro_score",
}


def simulate(path: pd.DataFrame, fee_rate: float, asset) -> dict[str, Portfolio]:
    """Replay every strategy over `path` at one cost level."""
    books = {s: Portfolio(s) for s in trading.STRATEGIES if s != "claude"}
    for _, row in path.iterrows():
        price = row["close"]
        for name, book in books.items():
            column = SCORE_COLUMN.get(name)
            score = float(row[column]) if column else 0.0
            direction = "UP" if score >= 0 else "DOWN"
            target = trading.compute_target_exposure(
                name, price, row["sma200"], row["vol"], direction, abs(score),
                asset.target_volatility,
            )
            book.step(price, target, fee_rate)
    return books


def run_asset(asset, panel_module) -> None:
    print("\n" + "#" * 100)
    print(f"### {asset.label} ({asset.symbol})")
    print("#" * 100)
    raw = panel_module.load(asset.key)
    df = build_features(raw, asset.leading_drivers)
    print(f"  {len(df)} seans ({df['time'].iloc[0].date()} -> {df['time'].iloc[-1].date()})")

    print("Yuruyen-ileri sinyal yolu hesaplaniyor...", flush=True)
    path = compute_signal_path(df, asset)
    years = (path["time"].iloc[-1] - path["time"].iloc[0]).days / 365.25
    print(f"  {len(path)} test gunu, {years:.1f} yil "
          f"({path['time'].iloc[0].date()} -> {path['time'].iloc[-1].date()})\n")

    for label, one_way_bps in cost_ladder_for(asset).items():
        fee_rate = one_way_bps / 10_000.0
        books = simulate(path, fee_rate, asset)
        results = {name: metrics(b.equity, b.exposure, years) for name, b in books.items()}
        benchmark = results["buyhold"]

        # Mark the rung this asset actually assumes live, so the reader is not
        # left comparing silver's real cost against gold's default.
        is_default = abs(one_way_bps - asset.fee_rate * 10_000) < 0.01
        marker = "   <-- bu varligin canlida varsaydigi maliyet" if is_default else ""
        print("=" * 100)
        print(f"MALIYET SENARYOSU: {label}  (tek yon {one_way_bps:.0f} bp){marker}")
        print("=" * 100)
        print(f"{'strateji':<14}{'son deger':>12}{'YBG':>9}{'oynak':>9}{'Sharpe':>9}"
              f"{'maks dusus':>12}{'Calmar':>9}{'islem':>8}{'komisyon':>11}{'vs al-tut':>12}")
        for name, m in sorted(results.items(), key=lambda kv: -kv[1].get("calmar", -99)):
            if not m:
                continue
            delta = "" if name == "buyhold" else f"{m['calmar'] - benchmark['calmar']:+.2f} Calmar"
            print(f"{name:<14}${m['final']:>11,.0f}{100 * m['cagr']:>8.1f}%{100 * m['vol']:>8.1f}%"
                  f"{m['sharpe']:>9.2f}{100 * m['max_dd']:>11.1f}%{m['calmar']:>9.2f}"
                  f"{books[name].trades:>8}${books[name].fees_paid:>10,.0f}{delta:>12}")

        beat = [n for n, m in results.items()
                if n != "buyhold" and m.get("calmar", -99) > benchmark["calmar"]]
        print(f"\n  Al-ve-tut'u Calmar'da gecen: {', '.join(beat) if beat else 'HICBIRI'}")
        print()


def main() -> int:
    sys.path.insert(0, __file__.rsplit("backend", 1)[0] + "backend/research")
    import panel as panel_module

    keys = [a for a in sys.argv[1:] if not a.startswith("-")] or list(assets_module.ASSETS)
    for key in keys:
        run_asset(assets_module.get(key), panel_module)

    print("=" * 100)
    print("KAPSAM UYARISI")
    print("=" * 100)
    print("  `claude` ve `kanalfinans` bu backtest'te YOK. Ilki icin 6000 gunluk gecmisi")
    print("  ucretli bir LLM cagrisiyla tekrar oynatmak hem pahali hem anlamsiz olurdu")
    print("  (model o tarihleri zaten biliyor); ikincisi bir insanin video arsivine bagli")
    print("  ve o arsiv tutulmuyor. Ikisi de yalnizca canli degerlendirilebilir.")
    print()
    print("  Buradaki hicbir sonuc 'gelecekte de boyle olur' demek degildir. Ozellikle")
    print("  al-ve-tut'un guclu gorunmesi, panelin 25 yilinin her iki metal icin de")
    print("  olaganustu bir bogaya denk gelmesindendir (altin 273 -> 4430, gumus 4 -> 66).")
    print("  Savunma kurallarinin bedeli boga piyasasinda odenir, karsiligi ayida alinir --")
    print("  research/defense.py'deki rejim ayristirmasi bu takasi acikca gosteriyor.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
