"""Replays every paper portfolio over real history, against buy-and-hold.

This calls trading.compute_target_exposure() and trading.compute_rebalance()
directly -- the same functions predict.py runs live. A backtest that
reimplements the strategy is testing the reimplementation, which is how a
system ends up with a backtest that passes and a live path that doesn't.

WHAT THIS CAN AND CANNOT TEST
-----------------------------
Testable: buyhold, voltarget, trend, defensive, technical, ml, macro,
ensemble -- everything derived from price and the macro panel, both of which
have deep history.

The `ensemble` row here is NOT the live 5-signal blend under the same name in
`trading.STRATEGIES` / the frontend's "Harman" portfolio. It is a plain
average of `ml_score` and `tech_score` (see compute_signal_path) -- macro and
news are excluded from the blend (macro gets its own separate row instead)
and `claude` cannot appear at all. The live ensemble instead pools every
component through `ensemble.combine()`, weighted by base-rate-relative
likelihood, not a flat average. Read this row as "does a naive tech+ml blend
plus the same risk rules beat buy-and-hold", not as a backtested track record
for the portfolio the dashboard shows under the same name.

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
import miners_signal
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

    def step(self, price: float, target: float, fee_rate: float,
             flat_fee: float = 0.0) -> None:
        """One session. `flat_fee` is a per-trade charge in DOLLARS.

        Defaults to 0.0, so every existing caller and every number already in
        research/README.md is unchanged. It exists because a proportional fee
        and a flat one are not the same shape of cost and the difference is
        not a detail: a percentage fee is invisible to account size, a flat
        one is a function of nothing else. See flat_fee_ladder().
        """
        decision = trading.compute_rebalance(self.cash, self.ounces, price, target)
        if decision["action"] == "BUY":
            gross = decision["usd_amount"]
            fee = gross * fee_rate + flat_fee
            self.cash -= gross
            self.ounces += (gross - fee) / price
            self.trades += 1
            self.fees_paid += fee
        elif decision["action"] == "SELL":
            gross = decision["ounce_amount"] * price
            fee = gross * fee_rate + flat_fee
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
                # The real miners_signal, not a copy -- same reason this file
                # calls trading.compute_target_exposure rather than restating
                # it. It abstains (0.0) on every row before GDX started
                # trading in 2006, which is correct and visible: the `miners`
                # portfolio simply sits at SIGNAL_BASE_EXPOSURE until the
                # series exists, rather than silently trading on a NaN.
                "miners_score": miners_signal.miners_signal(
                    labelled.iloc[start + offset: start + offset + 1])["score"],
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
    "ml": "ml_score", "macro": "macro_score", "miners": "miners_score",
}

# Display-only relabelling for the report table. Printing the bare string
# "ensemble" next to Sharpe/Calmar numbers invites reading it as a backtested
# track record for the live 5-signal "Harman" portfolio; it is actually a
# flat ml+technical average (see compute_signal_path and the module
# docstring's "WHAT THIS CAN AND CANNOT TEST" section). The row name itself
# has to carry that caveat because a reader scanning the table will not
# necessarily reach the footer warning.
DISPLAY_NAME = {"ensemble": "ensemble(ml+tech)"}


def simulate(path: pd.DataFrame, fee_rate: float, asset,
             flat_fee: float = 0.0) -> dict[str, Portfolio]:
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
            book.step(price, target, fee_rate, flat_fee)
    return books


# Sentinel for a book that went to zero or below. Distinct from nan, which
# would read as "no data" for what is actually a definite and severe result.
BUST = object()


def _beats(value, reference) -> bool:
    """Comparison that treats BUST and nan as "no", not as "unknown"."""
    if value is BUST or reference is BUST:
        return value is not BUST and reference is BUST
    return bool(np.isfinite(value) and np.isfinite(reference) and value > reference)


FLAT_FEE_USD = 1.50
# A liquid gold ETF's bid/ask is not zero even when the commission is flat, so
# the spread is carried alongside rather than pretended away. 1 bp one-way is
# COST_LADDER_BPS' cheapest rung; it is an ASSUMPTION, unlike the commission,
# and it is small enough that the flat fee dominates every line below.
FLAT_FEE_SPREAD_BPS = 1.0

# Account sizes to price the flat fee against. $1000 is what every other
# number in this file assumes (trading.STARTING_CASH).
ACCOUNT_SIZES = (1_000, 5_000, 25_000, 100_000, 500_000)


def flat_fee_ladder(path: pd.DataFrame, asset, years: float) -> None:
    """What a per-trade commission in DOLLARS does, by account size.

    WHY THIS IS A DIFFERENT LADDER AND NOT ANOTHER RUNG
    ---------------------------------------------------
    COST_LADDER_BPS is proportional: every rung costs the same fraction of
    every trade, so the answer is independent of how much money is in the
    account. A flat commission is the opposite -- it is independent of the
    TRADE and therefore entirely a function of the account. The two cannot
    share a ladder without one of them lying.

    The arithmetic that makes this urgent: trading.REBALANCE_THRESHOLD is
    0.05, and compute_rebalance trades only as far as the target, so the
    SMALLEST trade this system makes is about 5% of the book. On $1000 that is
    ~$50, and $1.50 on $50 is 300 bp one-way -- four times the bank gram gold
    rung, which research/README.md already measured as the level where every
    strategy here loses to buy-and-hold.

    HOW THE SWEEP WORKS, AND WHY IT IS EXACT RATHER THAN APPROXIMATE
    ----------------------------------------------------------------
    Everything in this simulation except a flat fee is scale-invariant: the
    rebalance decision reads an EXPOSURE (a ratio), trade sizes are a fraction
    of book value, and a proportional fee is a fraction of a trade. So running
    with $N of starting cash and a $1.50 fee is exactly equivalent -- up to the
    overall factor N/1000 -- to running the standard $1000 book with a fee of
    1.50 * 1000/N. This sweeps the fee instead of the starting cash so that
    every equity curve stays in the same units as the rest of the report and
    the two ladders remain readable side by side.

    Read it as: buy-and-hold trades once, so it is untouched by the
    commission and its Calmar is the same in every row. Everything else pays
    per decision.
    """
    print("=" * 100)
    print(f"SABIT KOMISYON MERDIVENI: islem basina ${FLAT_FEE_USD:.2f} "
          f"+ {FLAT_FEE_SPREAD_BPS:.0f}bp makas (tek yon)")
    print("=" * 100)
    print("  Oransal merdivenden AYRI, cunku sabit ucret islem buyuklugunden")
    print("  bagimsizdir -- yani cevabi hesap buyuklugu belirler, sinyal degil.")
    print(f"  En kucuk islem defterin ~%{100 * trading.REBALANCE_THRESHOLD:.0f}'i "
          f"(REBALANCE_THRESHOLD), yani $1.000'lik hesapta ~$50:")
    print(f"  ${FLAT_FEE_USD:.2f} / $50 = %3,0 = 300bp tek yon.")
    print()

    spread_rate = FLAT_FEE_SPREAD_BPS / 10_000.0
    names = [s for s in trading.STRATEGIES if s != "claude"]
    header = f"{'strateji':<19}" + "".join(f"{'$' + format(n, ','):>13}" for n in ACCOUNT_SIZES)
    rows: dict[str, list] = {}
    trades: dict[str, int] = {}
    effective: list[float] = []

    for size in ACCOUNT_SIZES:
        # See the docstring: sweeping the fee is exactly equivalent to sweeping
        # the starting cash, and keeps every printed dollar in the same units.
        scaled = FLAT_FEE_USD * trading.STARTING_CASH / size
        books = simulate(path, spread_rate, asset, flat_fee=scaled)
        for name in names:
            book = books[name]
            # A flat fee can take a book NEGATIVE, which no proportional rung
            # can: on a small sale the $1.50 exceeds the proceeds. metrics()
            # would hand back a nan there (a fractional power of a negative
            # ratio), and printing nan would report a wiped-out account as
            # missing data. It is not missing; it is the answer.
            if min(book.equity) <= 0:
                rows.setdefault(name, []).append(BUST)
            else:
                m = metrics(book.equity, book.exposure, years)
                rows.setdefault(name, []).append(m.get("calmar", float("nan")))
            trades[name] = book.trades
            if name == "miners":
                # Convert the flat fee into the unit the rest of this file
                # speaks, by dividing total fees by the dollar volume that
                # actually changed hands. Printed because the intuitive
                # conversion is WRONG: it is tempting to divide $1.50 by the
                # smallest possible trade (REBALANCE_THRESHOLD * book) and
                # conclude the cost is enormous, but trades are typically far
                # larger than that minimum -- and the book compounds, so late
                # trades are bigger still. Measured, that reasoning is off by
                # a factor of three at $5,000.
                volume = (book.fees_paid - book.trades * scaled) / max(spread_rate, 1e-12)
                effective.append(10_000 * book.fees_paid / volume
                                 if volume > 0 else float("nan"))

    print(f"{'':<19}{'HESAP BUYUKLUGU (Calmar)':^65}")
    print(header)
    print("-" * len(header))
    benchmark = rows["buyhold"]
    for name in sorted(names, key=lambda n: -rows[n][-1]):
        display = DISPLAY_NAME.get(name, name)
        cells = "".join(f"{'IFLAS':>13}" if c is BUST else f"{c:>13.3f}"
                        for c in rows[name])
        print(f"{display:<19}{cells}")
    print("-" * len(header))
    print(f"{'-- miners: efektif bp (tek yon), olculen islem hacmine gore --':<19}")
    print(f"{'':<19}" + "".join(f"{e:>13.1f}" for e in effective))

    print("\n  Al-ve-tut'u Calmar'da gecen stratejiler, hesap buyuklugune gore:")
    for i, size in enumerate(ACCOUNT_SIZES):
        beat = [DISPLAY_NAME.get(n, n) for n in names
                if n != "buyhold" and _beats(rows[n][i], benchmark[i])]
        print(f"    ${size:>9,}: {', '.join(beat) if beat else 'HICBIRI'}")

    # The single number a person with an account actually needs.
    miners = rows["miners"]
    crossover = None
    for i in range(1, len(ACCOUNT_SIZES)):
        # nan-safe on purpose: `IFLAS` and nan are both "does not beat", and a
        # bare `<=` against either is False, which would silently report "never
        # crosses" for a strategy that plainly does.
        if not _beats(miners[i - 1], benchmark[i - 1]) and _beats(miners[i], benchmark[i]):
            crossover = (ACCOUNT_SIZES[i - 1], ACCOUNT_SIZES[i])
    print()
    if crossover:
        print(f"  `miners` al-ve-tut'u ${crossover[0]:,} ile ${crossover[1]:,} arasinda geciyor.")
        print(f"  Bu bir sinyal esigi DEGIL, bir hesap buyuklugu esigi: ayni sinyal,")
        print(f"  kucuk hesapta komisyon altinda kaliyor, buyuk hesapta kalmiyor.")
    elif _beats(miners[0], benchmark[0]):
        print("  `miners` en kucuk hesapta bile al-ve-tut'u geciyor.")
    else:
        print("  `miners` bu araligin HICBIR yerinde al-ve-tut'u gecmiyor.")
    print()

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
        print(f"{'strateji':<19}{'son deger':>12}{'YBG':>9}{'oynak':>9}{'Sharpe':>9}"
              f"{'maks dusus':>12}{'Calmar':>9}{'islem':>8}{'komisyon':>11}{'vs al-tut':>12}")
        for name, m in sorted(results.items(), key=lambda kv: -kv[1].get("calmar", -99)):
            if not m:
                continue
            delta = "" if name == "buyhold" else f"{m['calmar'] - benchmark['calmar']:+.2f} Calmar"
            display = DISPLAY_NAME.get(name, name)
            print(f"{display:<19}${m['final']:>11,.0f}{100 * m['cagr']:>8.1f}%{100 * m['vol']:>8.1f}%"
                  f"{m['sharpe']:>9.2f}{100 * m['max_dd']:>11.1f}%{m['calmar']:>9.2f}"
                  f"{books[name].trades:>8}${books[name].fees_paid:>10,.0f}{delta:>12}")

        beat = [DISPLAY_NAME.get(n, n) for n, m in results.items()
                if n != "buyhold" and m.get("calmar", -99) > benchmark["calmar"]]
        print(f"\n  Al-ve-tut'u Calmar'da gecen: {', '.join(beat) if beat else 'HICBIRI'}")
        print()

    flat_fee_ladder(path, asset, years)


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
    print("  Tablodaki 'ensemble(ml+tech)' satiri da canlidaki 5 bilesenli 'Harman'")
    print("  portfoyunun gecmis performansi DEGIL -- sadece ml_score ile tech_score'un")
    print("  duz ortalamasi (macro/news disarida, claude zaten yok). Canli ensemble")
    print("  ensemble.combine() ile taban-orana gore olabilirlik oranlariyla havuzluyor,")
    print("  duz ortalama degil. Bu satiri 'ayni risk kurallariyla naif bir ml+teknik")
    print("  karisimi al-ve-tut'u geciyor mu' sorusunun cevabi olarak oku.")
    print()
    print("  Buradaki hicbir sonuc 'gelecekte de boyle olur' demek degildir. Ozellikle")
    print("  al-ve-tut'un guclu gorunmesi, panelin 25 yilinin her iki metal icin de")
    print("  olaganustu bir bogaya denk gelmesindendir (altin 273 -> 4430, gumus 4 -> 66).")
    print("  Savunma kurallarinin bedeli boga piyasasinda odenir, karsiligi ayida alinir --")
    print("  research/defense.py'deki rejim ayristirmasi bu takasi acikca gosteriyor.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
