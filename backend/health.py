"""Catches the pipeline having gone SILENT, not the pipeline being wrong.

retrain.py's own module docstring already covers the second kind (calibrator
ceilings, base-rate drift, a component gone one-sided) -- those are printed
to a GitHub Actions log nobody reads every morning. This module is about a
different failure mode: predict.py or retrain.py's cron simply not running
for days, with no exception anywhere because nothing ever got the chance to
raise one.

`check()` is pure over already-fetched rows so retrain.py (writes, runs
right after predict.py every night) and daily_report.py (read-only, its OWN
independent cron ~7 hours later) can both call the exact same logic without
either depending on the other having actually run. That independence is the
whole point: daily_report must still notice if predict.py AND retrain.py
both went silent, which is exactly the scenario in which retrain.py never
gets a chance to print anything at all.

Model-file mtime was considered for "when was this model last retrained"
and rejected: GitHub Actions checks out the repo fresh on every run (see
predict.yml / daily_retrain.yml), so a file's mtime is always "just now"
regardless of when it was actually last retrained, and the default shallow
checkout cannot reliably answer "which commit last touched this path"
either. `model_state.updated_at` is used instead -- retrain.py already
writes it every night it successfully rebuilds a component's record
(retrain.rebuild_component_records), so it is a free, already-persisted
"did retrain.py actually complete last night" signal with no schema change.
"""
from __future__ import annotations

from datetime import datetime, timezone

# How many of the newest prediction rows to look at. Small on purpose: this
# is meant to catch a PERSISTING problem across several trading-day runs, not
# a one-off -- a single stale price or a single abstain is normal, documented
# behaviour elsewhere (e.g. SI=F(stale) has no weekend proxy, and abstaining
# is the correct call for macro/news with no lead that day).
LOOKBACK_ROWS = 10

# A genuinely new prediction (or component-record rebuild) should land every
# trading day. Three calendar days covers a long weekend without tripping on
# it, but nothing longer -- picked the same way XRP-Guess picked its
# cooldown/backoff constants: small and defensible, not measured, because
# "how many days of silence is abnormal" is an operational judgement call,
# not a performance statistic.
STALE_RUN_ALERT_DAYS = 3.0

# Three consecutive trading-day runs with a "(stale)" price source is not a
# weekend proxy -- predict.py only runs weekdays (see predict.yml's cron), so
# there is no weekend row to begin with. Three in a row means the live price
# source has stopped updating, not that a market was briefly closed.
STALE_PRICE_STREAK_ALERT = 3

# A component going quiet for a day is normal and already measured elsewhere
# (retrain.py's "SABIT? tek yonlu" catches the opposite failure -- never
# abstaining). Five weekdays running without a single opinion is long enough
# to be worth a line, short enough not to fire on ordinary quiet stretches.
ABSTAIN_STREAK_ALERT = 5


def fetch_recent(db, asset_key: str, limit: int = LOOKBACK_ROWS) -> list[dict]:
    """Newest-first prediction rows for one asset, INCLUDING unresolved ones
    -- a live problem shows up first in the last few days, still pending."""
    return (db.table("predictions")
            .select("created_at,price_source,news_confidence,macro_confidence")
            .eq("asset", asset_key).order("target_date", desc=True)
            .limit(limit).execute().data)


def fetch_model_state_updates(db, asset_key: str) -> list[dict]:
    """Every component's `model_state.updated_at` for one asset -- see the
    module docstring for why this stands in for "was retrain.py run"."""
    return (db.table("model_state").select("updated_at")
            .eq("asset", asset_key).execute().data)


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def check(asset, recent: list[dict], model_state_rows: list[dict]) -> list[str]:
    """Turkish warning lines for anything that looks silently broken.

    Empty list means nothing looks wrong -- callers should print/mail
    nothing in that case rather than a reassuring "all clear" section, the
    same "stay quiet unless there is something to say" rule daily_report.py's
    verdict_sentence already follows.
    """
    warnings: list[str] = []
    now = datetime.now(timezone.utc)

    if recent:
        newest_age_days = (now - _parse(recent[0]["created_at"])).total_seconds() / 86400
        if newest_age_days > STALE_RUN_ALERT_DAYS:
            warnings.append(
                f">>> DIKKAT ({asset.label}): son tahmin {newest_age_days:.1f} gun once "
                "yazildi -- predict.py'nin cron'u sessizce durmus olabilir.")

        stale_streak = 0
        for row in recent:
            if row.get("price_source") and "(stale)" in row["price_source"]:
                stale_streak += 1
            else:
                break
        if stale_streak >= STALE_PRICE_STREAK_ALERT:
            warnings.append(
                f">>> DIKKAT ({asset.label}): son {stale_streak} tahmin '(stale)' fiyat "
                "kaynagiyla yazildi -- canli fiyat kalici olarak bayat olabilir.")

        for label, column in (("haber", "news_confidence"), ("makro", "macro_confidence")):
            streak = 0
            for row in recent:
                value = row.get(column)
                if value is not None and float(value) > 0:
                    break
                streak += 1
            if streak >= ABSTAIN_STREAK_ALERT:
                warnings.append(
                    f">>> DIKKAT ({asset.label}): {label} bileseni son {streak} tahminde "
                    "hep sessiz kaldi -- beklenenden uzun bir sessizlik.")

    updates = [r["updated_at"] for r in model_state_rows if r.get("updated_at")]
    if updates:
        newest_update = max(_parse(ts) for ts in updates)
        retrain_age_days = (now - newest_update).total_seconds() / 86400
        if retrain_age_days > STALE_RUN_ALERT_DAYS:
            warnings.append(
                f">>> DIKKAT ({asset.label}): bilesen sicilleri {retrain_age_days:.1f} gundur "
                "guncellenmemis -- retrain.py'nin cron'u sessizce durmus olabilir.")

    return warnings
