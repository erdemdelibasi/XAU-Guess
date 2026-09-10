"""Entry point, run once per trading day by GitHub Actions.

For EACH metal (gold and silver) it makes one call on where that metal closes
HORIZON_DAYS ahead, blending five components -- a rule-based technical read,
an ML classifier, a macro-driver signal, headline sentiment, and Claude's own
judgment -- then feeds the result into that metal's paper portfolios.

WHY DAILY, AND WHY FIVE DAYS
----------------------------
XRP-Guess predicted 15 minutes ahead because that was how often its cron ran;
the horizon was an accident of scheduling. Its own research bench later
measured the consequence: a 15-minute call on XRP needed 95.6% accuracy just
to pay its trading costs. Here the horizon was chosen first, from
research/wall.py -- gold's break-even falls from 56.2% at one day to 52.7% at
five and 51.3% at twenty, and research/edge.py found the model clears the wall
at five days and nowhere else.

WHAT THIS SYSTEM HONESTLY CLAIMS
--------------------------------
Not much, and the code should not overstate it. Measured out of sample, the
direction model beats chance and loses to always-long. The thing that
measurably works is volatility-responsive position sizing (research/
defense.py: maximum drawdown 44.4% -> 30.1%, Sharpe 0.58 -> 0.64 over 19.9
years). `buyhold` runs here as a first-class portfolio precisely so that
whenever the clever strategies lose to doing nothing, it is visible.

THE TWO METALS ARE NOT ONE ASSET WITH TWO PRICES
------------------------------------------------
Everything that could differ between them does, every one of those
differences is measured (research/compare.py), and all of them live in
assets.py: the base rate the ensemble is calibrated against (0.557 vs 0.539),
the volatility budget (15% vs 28% -- silver realises 1.86x gold's
volatility), the assumed cost (10 vs 20 bp round trip), which macro drivers
actually lead (silver's `ief` misses the significance bar gold's clears), and
the model file. A loop that shared any of those would produce silver numbers
that look perfectly fine and are quietly gold's.

No API keys are needed for market data -- Yahoo Finance and Binance's public
endpoints only. ANTHROPIC_API_KEY is optional; without it the `claude`
component stays neutral and everything else runs unchanged.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

# Windows defaults a REDIRECTED stdout to cp1252, which cannot encode the
# Turkish letters this project prints ("Altın" alone is enough). XRP-Guess
# lost a scheduled task to exactly this: every run exited 1 with
# UnicodeEncodeError, the log cut off mid-item, and the failure bookkeeping
# that should have recorded it never ran.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import assets as assets_module  # noqa: E402
import calibration  # noqa: E402
import claude_signal as claude_module  # noqa: E402
import ensemble  # noqa: E402
import fetch_data  # noqa: E402
import kanal_finans_trading  # noqa: E402
import macro_signal as macro_module  # noqa: E402
import miners_signal  # noqa: E402
import ml_model  # noqa: E402
import news_signal as news_module  # noqa: E402
import trading  # noqa: E402
from db import get_client  # noqa: E402
from indicators import (  # noqa: E402
    build_features, estimate_pct_change, recent_volatility, technical_signal,
)

HISTORY_YEARS = 25
TRADING_DAYS_PER_YEAR = 252


def next_trading_day(start: date, horizon: int) -> date:
    """`horizon` weekdays after `start`.

    Weekdays, not calendar days, because the metals do not trade at the
    weekend. Exchange holidays are deliberately NOT modelled: that needs a CME
    calendar this project has no keyless source for, and the cost of being
    wrong is small because resolution matches the first session on or after
    the target date rather than demanding an exact hit (see
    resolve_due_predictions). Landing on Thanksgiving means resolving a day
    late, not failing.
    """
    return (np.busday_offset(np.datetime64(start, "D"), horizon, roll="forward")
            .astype("datetime64[D]").astype(date))


def _number(value) -> float | None:
    """A finite float, or None -- never NaN.

    Postgres `numeric` has no NaN and PostgREST serialises one as the JSON
    token `NaN`, which is not valid JSON: the insert fails for the whole row,
    so a warmup gap in one display column would cost the entire prediction.
    And because `unique (asset, target_date)` makes a lost row unbackfillable,
    "the whole prediction" means that session, permanently.

    That risk is not hypothetical for the columns below: `trend_average` is a
    200-session rolling mean and `realised_volatility` a 60-session one, so a
    metal whose history came back short -- Yahoo serving a truncated series,
    a newly added asset -- produces NaN in a column that is merely displayed
    and takes the entire row down with it.
    """
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _column_value(frame: pd.DataFrame, column: str) -> float | None:
    """Last value of `column`, or None when the column was never built.

    `gs_ratio` needs the counterpart metal's series, which load_panel fetches
    fail-soft: one dead Yahoo symbol leaves the column absent entirely, and a
    bare frame["gs_ratio"] would then raise KeyError and lose the prediction
    over a display-only number.
    """
    if column not in frame.columns or frame.empty:
        return None
    return _number(frame[column].iloc[-1])


def safe_signal(fn, *args, label: str) -> dict:
    """Call a signal producer, falling back to neutral if it raises.

    One evidence source hiccupping must never block the others or stop a
    prediction being logged.
    """
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001 -- deliberately broad, see docstring
        print(f"WARNING: {label} signal failed ({exc}); using neutral fallback.")
        return {"direction": "UP", "confidence": 0.0, "score": 0.0}


def load_panel(asset) -> pd.DataFrame:
    """This asset's prices plus its macro series, on its own trading calendar."""
    prices = fetch_data.get_daily(asset.symbol, years=HISTORY_YEARS)
    if prices.empty:
        raise RuntimeError(f"No history returned for {asset.symbol} -- cannot predict.")

    # Drop the still-forming session. The rule lives in fetch_data so the
    # research bench applies the identical one -- this file and
    # research/panel.py each used to carry their own copy of a stamp-shape
    # heuristic that turned out to keep every partial bar it existed to
    # remove (see fetch_data.bar_is_complete).
    prices = fetch_data.drop_forming_bar(prices)

    wanted = assets_module.macro_symbols_for(asset)
    macro = {}
    for name, symbol in wanted.items():
        try:
            frame = fetch_data.get_daily(symbol, years=HISTORY_YEARS)
            if not frame.empty:
                macro[name] = frame
        except Exception as exc:  # noqa: BLE001 -- fail soft per series
            print(f"NOTE: macro series {name} ({symbol}) unavailable: {exc}")
    missing = set(wanted) - set(macro)
    if missing:
        print(f"NOTE: macro series unavailable this run: {', '.join(sorted(missing))}")
    return fetch_data.align_on_gold(prices, macro)


def get_component_records(db, asset_key: str) -> tuple[dict, dict]:
    """(display weights, per-component UP/DOWN records) for one asset.

    The records are what ensemble.combine() actually pools. A component with
    no history is simply left out and combine() falls back to its base-rate
    cold-start path.
    """
    rows = db.table("model_state").select("*").eq("asset", asset_key).execute().data
    weights = dict(ensemble.DEFAULT_WEIGHTS)
    records: dict[str, dict] = {}
    for row in rows:
        component = row["component"]
        if component not in ensemble.COMPONENTS:
            continue
        if row.get("weight") is not None:
            weights[component] = float(row["weight"])
        up_calls = int(row.get("up_calls") or 0)
        down_calls = int(row.get("down_calls") or 0)
        if up_calls or down_calls:
            records[component] = {
                "up": (int(row.get("up_correct") or 0), up_calls),
                "down": (int(row.get("down_correct") or 0), down_calls),
            }
    return weights, records


def resolve_due_predictions(db, asset, panel: pd.DataFrame) -> int:
    """Score this asset's predictions whose target session has now closed.

    Resolution uses the CLOSE OF THE TARGET SESSION from history, never the
    live price at the moment the resolver happens to run. XRP-Guess shipped
    that bug and measured the damage: 80 of 240 rows (33.5%) were scored
    against the wrong horizon, recorded accuracy read 51.5% against a true
    46.1%, and because those rows feed the component records they were
    corrupting the learning loop itself, not just the display.

    A prediction is matched to the first session on or after its target date,
    so an exchange holiday resolves a day late rather than never.
    """
    sessions = panel["time"].dt.date.tolist()
    session_close = dict(zip(sessions, panel["close"]))

    due = (db.table("predictions").select("*")
           .eq("asset", asset.key).is_("resolved_at", "null").execute().data)
    resolved = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    for row in due:
        target = date.fromisoformat(row["target_date"])
        match = next((s for s in sessions if s >= target), None)
        if match is None:
            continue  # target session hasn't closed yet -- leave it pending

        resolution_price = float(session_close[match])
        actual = "UP" if resolution_price > float(row["price_at_prediction"]) else "DOWN"

        update = {
            "resolved_at": now_iso,
            "price_at_resolution": resolution_price,
            "actual_direction": actual,
            "correct": actual == row["predicted_direction"],
        }
        for component in ensemble.COMPONENTS:
            prefix = ensemble.COLUMN_PREFIX[component]
            called = row.get(f"{prefix}_direction")
            confidence = row.get(f"{prefix}_confidence")
            # An abstaining component (confidence 0) is scored as NULL, not as
            # wrong. It declined to speak; counting that as an error would
            # punish exactly the behaviour macro_signal/news_signal are
            # designed to produce when the evidence is thin.
            if called is None or confidence is None or float(confidence) <= 0:
                update[f"{prefix}_correct"] = None
            else:
                update[f"{prefix}_correct"] = (actual == called)

        db.table("predictions").update(update).eq("id", row["id"]).execute()
        resolved += 1
        print(f"  cozuldu #{row['id']} (hedef {target}, seans {match}): "
              f"tahmin={row['predicted_direction']} gercek={actual} "
              f"dogru={update['correct']}")
    return resolved


# Columns added by a migration that has to be applied by hand in the Supabase
# SQL editor (see supabase/schema.sql). PostgREST rejects the WHOLE insert if
# a key has no column, so shipping these without the migration would mean no
# prediction is written at all until someone notices.
PENDING_MIGRATION_COLUMNS = ("tech_confidence_raw", "ml_confidence_raw",
                             "macro_confidence_raw", "cold_start")


def insert_prediction(db, row: dict):
    """Insert the row, degrading loudly if the newest migration is not applied.

    The repo cannot apply its own migrations -- schema.sql is the source of
    truth and Supabase does not run it. That is fine for a new column that
    only stores something, and NOT fine if the missing column takes the whole
    prediction down with it: losing a day of rows to a pending ALTER TABLE
    would be a self-inflicted outage, and the day would be gone for good
    because `unique (asset, target_date)` means the row can never be
    backfilled from a later run.

    So: try the full row, and on a schema-cache miss retry without the new
    columns and say so in a line nobody can miss. The system keeps running
    with one feature dormant instead of stopping.
    """
    try:
        return db.table("predictions").insert(row).execute()
    except Exception as exc:  # noqa: BLE001 -- narrowed by the message check
        message = str(exc)
        if not any(column in message for column in PENDING_MIGRATION_COLUMNS):
            raise
        print("=" * 72)
        print("DIKKAT: supabase/schema.sql'deki 2026-09-08 migration'i UYGULANMAMIS.")
        print("  Eksik kolon(lar): " + ", ".join(PENDING_MIGRATION_COLUMNS))
        print("  Tahmin bunlarsiz yazilacak -- sistem calisiyor, ama kalibrasyon")
        print("  egrileri o kolonlar gelene kadar fit EDILEMEZ (retrain.py ham")
        print("  guveni orada ariyor). Supabase SQL Editor'de calistir.")
        print("=" * 72)
        trimmed = {k: v for k, v in row.items() if k not in PENDING_MIGRATION_COLUMNS}
        return db.table("predictions").insert(trimmed).execute()


def run_asset(db, asset) -> int:
    """One metal's full cycle. Returns 1 if a prediction was written."""
    print(f"\n{'=' * 72}\n### {asset.label} ({asset.symbol})\n{'=' * 72}")

    panel = load_panel(asset)
    latest_session = panel["time"].iloc[-1].date()
    print(f"Panel: {len(panel)} seans, son kapanis {latest_session}")

    resolved = resolve_due_predictions(db, asset, panel)
    if resolved:
        print(f"{resolved} tahmin cozuldu.")

    target_date = next_trading_day(latest_session, ml_model.HORIZON_DAYS)

    # Idempotency. A manual re-run overlapping the cron would otherwise write
    # a second row for the same session -- double-counting it in the component
    # records AND firing every portfolio twice for one signal. Checked before
    # any expensive work; the unique constraint in schema.sql is the backstop.
    existing = (db.table("predictions").select("id")
                .eq("asset", asset.key).eq("target_date", target_date.isoformat())
                .execute().data)
    if existing:
        print(f"{target_date} icin tahmin zaten var (id={existing[0]['id']}) -- atlaniyor.")
        return 0

    features = build_features(panel, asset.leading_drivers)
    current_price, price_source = fetch_data.get_live_price(asset.symbol)
    print(f"Fiyat: ${current_price:,.2f} (kaynak {price_source}) -> hedef {target_date} "
          f"({ml_model.HORIZON_DAYS} islem gunu)")

    # ---- components -------------------------------------------------------
    tech = safe_signal(technical_signal, features, asset.price_scales, label="technical")

    model = ml_model.load_model(asset.key)
    model_version = "bootstrap"
    # A model saved before this asset's feature set changed is incompatible
    # and would raise on ml_signal(). Treat that exactly like "no model yet"
    # and retrain on the spot rather than crashing the run.
    #
    # Comparing COUNT alone is not enough -- caught live on 2026-09-07: gold's
    # saved model still had `silver_chg` from before the counterpart_chg
    # unification, silver's had already been retrained onto `counterpart_chg`,
    # and both are 27 columns. The count check passed, the stale model loaded,
    # and predict_proba() raised on the very first live run because sklearn
    # validates DataFrame column NAMES against feature_names_in_, not just
    # their count. Comparing the actual name list is what the count check was
    # supposed to accomplish.
    expected_features = ml_model.available_features(features)
    saved_features = list(getattr(model, "feature_names_in_", []))
    if model is not None and saved_features != expected_features:
        print("Kayitli modelin ozellik listesi artik uyusmuyor -- bayat sayiliyor.")
        model = None
    if model is None:
        print("Uyumlu model yok -- gecmisten simdi bootstrap egitimi yapiliyor.")
        model, metrics = ml_model.train_model(panel, drivers=asset.leading_drivers)
        ml_model.save_model(model, asset.key)
        model_version = datetime.now(timezone.utc).isoformat()
        print(f"Bootstrap egitimi tamam: {metrics}")

    ml = safe_signal(ml_model.ml_signal, model, features, label="ml")
    macro = safe_signal(macro_module.macro_signal, features, asset.leading_drivers, label="macro")

    calibrators = calibration.load(asset.key)
    # The RAW confidence of every calibrated component is kept and stored
    # alongside the calibrated one. Without it the nightly refit is fed its
    # own output: retrain.py reads `<c>_confidence` back out of this table,
    # and once a calibrator exists that column holds a CALIBRATED number, so
    # each night would fit a curve on the previous curve's output and apply
    # the result to raw input. The two live on different scales, and nothing
    # about the compounding would raise -- it would just quietly bend
    # position sizing further every night. Calibration cannot bite for
    # another MIN_RECORDS_TO_FIT (180) resolved rows, which is exactly why
    # this had to be fixed before the first fit rather than after.
    raw_confidence = {"technical": tech["confidence"], "ml": ml["confidence"],
                      "macro": macro["confidence"]}
    # Kept as whole signals, not just their confidences, because the Claude
    # prompt below needs the PRE-calibration read and `tech`/`macro` are about
    # to be rebound to the calibrated ones.
    tech_raw, macro_raw = dict(tech), dict(macro)
    tech = calibration.apply(calibrators.get("technical"), tech, asset.base_rate_up)
    ml = calibration.apply(calibrators.get("ml"), ml, asset.base_rate_up)
    macro = calibration.apply(calibrators.get("macro"), macro, asset.base_rate_up)

    news = safe_signal(news_module.news_signal, asset, label="news")
    context = macro_module.describe_context(features)
    # Claude sees the pre-calibration technical/macro reads: calibrated
    # confidences are shrunk against the base rate and would read to a model
    # as "everything is neutral", which is a display convention rather than
    # information about the market.
    #
    # It must be `tech_raw`/`macro_raw` and not `tech`/`macro`: those two names
    # were rebound to the calibrated signals three lines up, so passing them
    # here said the opposite of what this comment claims. Silent, too -- the
    # prompt still rendered, just with every confidence pushed toward zero, and
    # the first calibrator does not exist for another 180 resolved rows, so
    # nothing would have looked wrong until long after it started mattering.
    claude = safe_signal(claude_module.claude_signal, asset, current_price,
                         tech_raw, macro_raw, context, label="claude")

    weights, records = get_component_records(db, asset.key)
    signals = {"technical": tech, "ml": ml, "macro": macro, "news": news, "claude": claude}
    final = ensemble.combine(signals, weights, records, asset.base_rate_up)

    # ---- sizing inputs ----------------------------------------------------
    daily_returns = panel["close"].pct_change().dropna().to_numpy()
    volatility = float(np.std(daily_returns[-trading.VOL_LOOKBACK_DAYS:])
                       * np.sqrt(TRADING_DAYS_PER_YEAR))
    trend_average = float(panel["close"].rolling(trading.TREND_WINDOW).mean().iloc[-1])
    # Scale the daily move to the horizon: variance adds over independent
    # days, so the standard deviation grows with the square root of time.
    horizon_vol = recent_volatility(panel) * np.sqrt(ml_model.HORIZON_DAYS)

    row = {
        "asset": asset.key,
        "symbol": asset.symbol,
        "target_date": target_date.isoformat(),
        "horizon_days": ml_model.HORIZON_DAYS,
        "price_at_prediction": current_price,
        "price_source": price_source,
        "predicted_direction": final["direction"],
        "confidence": final["confidence"],
        "p_up": final.get("p_up"),
        "edge_over_base": final.get("edge_over_base"),
        # Stored per row so a later change to the constant cannot silently
        # rewrite how past rows should be read.
        "base_rate_used": final.get("base_rate", asset.base_rate_up),
        "predicted_pct_change": _number(estimate_pct_change(final["score"], horizon_vol)),
        "predicted_price": _number(
            current_price * (1 + estimate_pct_change(final["score"], horizon_vol))),
        "trend_average": _number(trend_average),
        "realised_volatility": _number(volatility),
        # The gold/silver ratio and its trailing 250-session z, stored so the
        # UI can show the number IN CONTEXT instead of a bare "67.1" that the
        # reader has no way to place. Display only: research/ratio.py measured
        # this ratio in five different forms against three targets and four
        # horizons and NONE of the 60 cells cleared the bar, so no strategy
        # and no component reads these two columns. They are here to stop the
        # ratio being silently mistaken for a signal, not to become one.
        "gs_ratio": _column_value(features, "gs_ratio"),
        "gs_ratio_z": _column_value(features, "gs_ratio_z"),
        "model_version": model_version,
        # Whether the blend had any component record to pool at all. Stored
        # because the weight_* columns mean different things either way: with
        # records they are measured influence, without them they are the
        # default vote weights, and a UI that renders both as "Etki %25"
        # claims a track record that does not exist.
        "cold_start": bool(final.get("cold_start")),
    }
    for component, signal in signals.items():
        prefix = ensemble.COLUMN_PREFIX[component]
        pct = estimate_pct_change(signal["score"], horizon_vol)
        row[f"{prefix}_direction"] = signal["direction"]
        row[f"{prefix}_confidence"] = signal["confidence"]
        row[f"{prefix}_pct_change"] = _number(pct)
        row[f"{prefix}_price"] = _number(current_price * (1 + pct))
        row[f"weight_{component}"] = weights.get(component)
        if component in raw_confidence:
            row[f"{prefix}_confidence_raw"] = raw_confidence[component]
    if claude.get("reasoning"):
        row["claude_reasoning"] = claude["reasoning"]

    target_exposure = trading.compute_target_exposure(
        "ensemble", current_price, trend_average, volatility,
        final["direction"], final["confidence"], asset.target_volatility)
    row["target_exposure"] = _number(target_exposure)

    inserted = insert_prediction(db, row)
    prediction_id = inserted.data[0]["id"] if inserted.data else None

    # Printed from the LOCALS, not from `row`. Every numeric in `row` has now
    # been through _number() and can legitimately be None, and a None inside an
    # f-string format spec raises -- which would abort run_asset AFTER the insert
    # had succeeded, skipping every portfolio over a formatting error.
    predicted_price = current_price * (1 + estimate_pct_change(final["score"], horizon_vol))
    print(f"\n{target_date}: {final['direction']} "
          f"p_up={final.get('p_up', float('nan')):.3f} "
          f"(taban {asset.base_rate_up:.3f}, fark {final.get('edge_over_base', 0):+.3f}) "
          f"-> ${predicted_price:,.2f}")
    for component, signal in signals.items():
        print(f"    {component:<10} {signal['direction']:<4} guven={signal['confidence']:.4f}")
    print(f"  oynaklik %{100 * volatility:.1f} yillik | 200s ort ${trend_average:,.2f} "
          f"| harman hedef pozisyon %{100 * target_exposure:.0f}")

    # ---- portfolios -------------------------------------------------------
    # `miners` is a strategy but NOT an ensemble component: it answers the
    # one-day question and ensemble.combine() pools a five-day forecast (see
    # miners_signal.py). It is therefore absent from `signals` above and
    # appears only here, where a portfolio needs a direction and a confidence.
    miners = miners_signal.miners_signal(features)
    strategy_signal = {"technical": tech, "ml": ml, "macro": macro, "claude": claude,
                       "miners": miners}
    for name in trading.STRATEGIES:
        signal = final if name == "ensemble" else strategy_signal.get(
            name, {"direction": "UP", "confidence": 0.0})
        try:
            trading.maybe_trade(db, asset, name, prediction_id, current_price,
                                trend_average, volatility,
                                signal["direction"], signal["confidence"])
        except Exception as exc:  # noqa: BLE001 -- one portfolio must not block the rest
            print(f"WARNING: {asset.key}/{name} portfolio update failed ({exc})")

    # The Kanal Finans portfolio is driven by video events, not by this
    # signal -- but its stop-loss has to be watched continuously, not only
    # when a new video lands. This touches Supabase and the price already
    # fetched above, never YouTube, so it runs fine on GitHub Actions even
    # though kanal_finans.py itself cannot (see that module's docstring).
    try:
        kanal_finans_trading.maybe_check_stop_loss(db, asset, current_price)
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: {asset.key}/kanalfinans stop-loss check failed ({exc})")

    return 1


def main() -> int:
    db = get_client()
    written = 0
    for asset in assets_module.ASSETS.values():
        try:
            written += run_asset(db, asset)
        except Exception as exc:  # noqa: BLE001 -- one metal failing must not
            # take the other down with it; they share only the DB client.
            print(f"ERROR: {asset.key} dongusu basarisiz ({type(exc).__name__}: {exc})")
    print(f"\n{written} tahmin yazildi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
