"""Nightly maintenance: refit the model, rebuild the component records,
refit the calibrators, and report the things that fail silently if unwatched.

Runs after the market has closed. Everything here is idempotent -- running it
twice in a day changes nothing, because each step recomputes from the full
resolved history rather than incrementing counters.

THE REPORTING IS NOT DECORATION
-------------------------------
Three of the prints below exist because of specific failures that produced no
error at all:

  * **Calibrator ceilings.** In XRP-Guess a calibrator's maximum output fell
    below the confidence needed to open a position, and a strategy simply
    stopped trading. No exception, no log line, just a portfolio that went
    quiet for weeks. The ceiling is compared against the live threshold every
    night now so that cannot recur unnoticed.

  * **Realised base rate vs the asset's constant.** ensemble.py measures
    every component against assets.Asset.base_rate_up (gold 0.557, silver
    0.539). If a metal's actual behaviour drifts away from its constant,
    every component's measured "skill" is quietly rebased and nothing
    complains. Printing both side by side makes a regime change visible
    instead of absorbed.

  * **Per-component UP/DOWN split.** A component that has said UP on 121 of
    127 opportunities is not a signal, it is a constant -- and on an asset
    that rises 54-56% of the time it will still post a respectable-looking
    accuracy. XRP-Guess found exactly that in its news component only by
    going and looking. The split is printed every night here.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")

import assets as assets_module
import calibration
import ensemble
import ml_model
import predict as predict_module
import trading
from db import get_client

# Rows the component records are built from. Long enough to be statistically
# meaningful at one resolved row per trading day (~250/yr), short enough that
# a component's behaviour from five years ago doesn't dominate its current
# reputation.
RECORD_WINDOW_ROWS = 750
PAGE_SIZE = 1000


def fetch_resolved(db, asset_key: str) -> list[dict]:
    """Every resolved prediction for one asset, newest last.

    Supabase's REST API caps a response at ~1000 rows, so this pages rather
    than silently truncating -- a truncated history would quietly rebuild the
    component records from a partial record.
    """
    rows: list[dict] = []
    start = 0
    while True:
        page = (db.table("predictions").select("*")
                .eq("asset", asset_key)
                .not_.is_("resolved_at", "null")
                .order("target_date")
                .range(start, start + PAGE_SIZE - 1)
                .execute().data)
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        start += PAGE_SIZE
    return rows


def rebuild_component_records(db, asset, resolved: list[dict]) -> dict[str, dict]:
    """Recompute each component's UP and DOWN track record and store it.

    Recomputed from scratch every night rather than incremented, so a
    double-run, a backfill, or a corrected row can never leave the counters
    permanently skewed.
    """
    window = resolved[-RECORD_WINDOW_ROWS:]
    records: dict[str, dict] = {}

    for component in ensemble.COMPONENTS:
        prefix = ensemble.COLUMN_PREFIX[component]
        up_calls = up_correct = down_calls = down_correct = 0
        for row in window:
            called = row.get(f"{prefix}_direction")
            was_correct = row.get(f"{prefix}_correct")
            # NULL means the component abstained; it is not a wrong answer and
            # must not be counted as one (see predict.resolve_due_predictions).
            if called is None or was_correct is None:
                continue
            if called == "UP":
                up_calls += 1
                up_correct += int(bool(was_correct))
            else:
                down_calls += 1
                down_correct += int(bool(was_correct))
        records[component] = {"up": (up_correct, up_calls), "down": (down_correct, down_calls)}

    weights = ensemble.influence_weights(records, asset.base_rate_up)
    now_iso = datetime.now(timezone.utc).isoformat()
    for component, record in records.items():
        db.table("model_state").upsert({
            "asset": asset.key,
            "component": component,
            "up_correct": record["up"][0], "up_calls": record["up"][1],
            "down_correct": record["down"][0], "down_calls": record["down"][1],
            "weight": float(weights.get(component, 0.0)),
            "updated_at": now_iso,
        }).execute()
    return records


def report_records(asset, records: dict[str, dict], resolved: list[dict]) -> None:
    window = resolved[-RECORD_WINDOW_ROWS:]
    actual_up = [r for r in window if r.get("actual_direction") == "UP"]
    realised_base = len(actual_up) / len(window) if window else float("nan")

    print("\n" + "=" * 82)
    print("BILESEN SICILLERI  (son "
          f"{len(window)} cozulmus tahmin)")
    print("=" * 82)
    print(f"{'bilesen':<12}{'UP cagri':>10}{'UP dogru':>10}{'DOWN cagri':>12}"
          f"{'DOWN dogru':>12}{'kanit':>10}{'yorum':>16}")
    for component, record in records.items():
        up_correct, up_calls = record["up"]
        down_correct, down_calls = record["down"]
        if not up_calls and not down_calls:
            print(f"{component:<12}{'-':>10}{'-':>10}{'-':>12}{'-':>12}{'-':>10}{'gecmis yok':>16}")
            continue
        up_rate = f"%{100 * up_correct / up_calls:.1f}" if up_calls else "-"
        down_rate = f"%{100 * down_correct / down_calls:.1f}" if down_calls else "-"
        evidence = max(
            abs(ensemble.component_evidence("UP", record["up"], record["down"],
                                            asset.base_rate_up)) if up_calls else 0.0,
            abs(ensemble.component_evidence("DOWN", record["up"], record["down"],
                                            asset.base_rate_up)) if down_calls else 0.0,
        )
        total = up_calls + down_calls
        # A component that almost never takes one side isn't forecasting, it's
        # a constant -- and against a 55% base rate it will still look decent.
        skew = max(up_calls, down_calls) / total if total else 0
        note = "SABIT? tek yonlu" if skew > 0.9 and total >= 30 else ("sessiz" if evidence <= 0 else "")
        print(f"{component:<12}{up_calls:>10}{up_rate:>10}{down_calls:>12}{down_rate:>12}"
              f"{evidence:>10.3f}{note:>16}")

    print(f"\n  Gerceklesen taban oran (bu pencerede)  : %{100 * realised_base:.1f}")
    print(f"  assets.{asset.key.upper()}.base_rate_up (sabit)   : %{100 * asset.base_rate_up:.1f}")
    drift = abs(realised_base - asset.base_rate_up)
    if window and len(window) >= 200 and drift > 0.06:
        print(f"  >>> DIKKAT: {100 * drift:.1f} puan sapma. Her bilesenin 'becerisi' bu sabite")
        print("      gore olculuyor; sapma buyurse assets.py'deki taban oran yeniden")
        print("      olculmeli (research/compare.py).")


def refit_model(asset) -> None:
    panel = predict_module.load_panel(asset)
    model, metrics = ml_model.train_model(panel, drivers=asset.leading_drivers)
    ml_model.save_model(model, asset.key)
    print("\n" + "=" * 82)
    print(f"ML MODELI YENIDEN EGITILDI ({asset.label})")
    print("=" * 82)
    for key, value in metrics.items():
        print(f"  {key:<22} {value}")
    holdout = metrics.get("holdout_accuracy")
    baseline = metrics.get("always_up_baseline")
    if holdout is not None and baseline is not None:
        delta = 100 * (holdout - baseline)
        verdict = "hep-YUKARI'yi geciyor" if delta > 0 else "hep-YUKARI'nin ALTINDA"
        print(f"  >>> {verdict} ({delta:+.2f} puan)")
        if delta <= 0:
            print("      Bu beklenen sonuc, ariza degil -- research/edge.py ayni seyi")
            print("      olcmustu. Sistemin degeri yonde degil, pozisyon boyutunda.")


def refit_calibrators(asset, resolved: list[dict]) -> None:
    calibrators = calibration.load(asset.key)
    fitted = 0
    print("\n" + "=" * 82)
    print(f"KALIBRASYON ({asset.label})")
    print("=" * 82)

    for component in ("technical", "ml", "macro"):
        prefix = ensemble.COLUMN_PREFIX[component]
        confidences, corrects = [], []
        skipped_legacy = 0
        for row in resolved:
            # The RAW confidence, never the stored calibrated one. A curve
            # maps raw -> P(correct); fitting the next curve on the previous
            # curve's OUTPUT and then applying it to raw input compounds a
            # scale error every night, silently. Rows written before
            # `<c>_confidence_raw` existed are skipped rather than
            # substituted -- a mixed-scale sample is worse than a smaller one,
            # and MIN_RECORDS_TO_FIT will simply be reached a little later.
            confidence = row.get(f"{prefix}_confidence_raw")
            was_correct = row.get(f"{prefix}_correct")
            if confidence is None:
                if row.get(f"{prefix}_confidence") is not None:
                    skipped_legacy += 1
                continue
            if was_correct is None or float(confidence) <= 0:
                continue
            confidences.append(float(confidence))
            corrects.append(bool(was_correct))
        if skipped_legacy:
            print(f"  {component:<12} {skipped_legacy} eski satir atlandi "
                  f"(ham guven kolonu yoktu)")

        curve = calibration.fit(confidences, corrects, asset.base_rate_up)
        if curve is None:
            print(f"  {component:<12} fit YOK ({len(confidences)} kayit, "
                  f"gereken {calibration.MIN_RECORDS_TO_FIT}) -- kalibre edilmeden calisiyor")
            continue
        # Merge rather than replace: a component that had too few samples
        # tonight must not lose the calibrator it earned last month.
        calibrators[component] = curve
        fitted += 1
        print(f"  {component:<12} fit edildi ({len(confidences)} kayit)")

    if fitted:
        calibration.save(calibrators, asset.key)

    threshold = trading.REBALANCE_THRESHOLD
    ceilings = calibration.ceilings(calibrators, asset.base_rate_up)
    if ceilings:
        print("\n  Kalibratör tavanlari (bir bilesenin uretebilecegi EN YUKSEK guven):")
        for component, ceiling in ceilings.items():
            # A component whose ceiling cannot move exposure past the
            # rebalance band can never actually cause a trade. See the module
            # docstring -- this is the check for the silent-freeze failure.
            reach = ceiling * trading.MAX_SIGNAL_TILT
            status = "islem acabilir" if reach >= threshold else "ISLEM ACAMAZ (sessiz donmus)"
            print(f"    {component:<12} tavan={ceiling:.4f} -> pozisyon etkisi {reach:.4f} "
                  f"vs esik {threshold:.4f}   {status}")


def run_asset(db, asset) -> None:
    print(f"\n{'#' * 82}\n### {asset.label} ({asset.symbol})\n{'#' * 82}")
    resolved = fetch_resolved(db, asset.key)
    print(f"Cozulmus tahmin sayisi: {len(resolved)}")

    if not resolved:
        print("Henuz cozulmus tahmin yok -- sadece model yeniden egitilecek.")
        refit_model(asset)
        return

    records = rebuild_component_records(db, asset, resolved)
    report_records(asset, records, resolved)
    refit_model(asset)
    refit_calibrators(asset, resolved)


def main() -> int:
    db = get_client()
    for asset in assets_module.ASSETS.values():
        try:
            run_asset(db, asset)
        except Exception as exc:  # noqa: BLE001 -- one metal's maintenance
            # failing must not skip the other's; they share only the client.
            print(f"ERROR: {asset.key} yeniden egitimi basarisiz "
                  f"({type(exc).__name__}: {exc})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
