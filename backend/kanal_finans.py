"""Kanal Finans TS (YouTube @KanalFinans, Tunc Satiroglu) as an independent
opinion feed for the metals -- the TRADE-APPLICATION half only.

WHERE THE OTHER HALF WENT, AND WHY
-----------------------------------
Until 2026-09-08 this module also polled the channel's RSS feed, fetched each
video's transcript, and asked Claude to extract mentions/themes -- all of it
inline, then immediately applied any ALTIN/GUMUS mention to this project's own
paper portfolio. XRP-Guess ran an independent, near-identical copy of that
same pipeline against the SAME YouTube channel, from the SAME machine (same
residential IP), on its own 15-minute schedule.

That meant every pending video's transcript was fetched from YouTube TWICE
per cycle for no reason -- doubling the load against an endpoint that was
already blocking us intermittently (see the FRED-style note this project
already carries: an intermittent block is not "fixed", it is "not blocked
right now"). Measured that day: this project had NEVER once succeeded (zero
rows in kanal_finans_videos) while XRP-Guess had 23 historical successes, the
most recent less than 24 hours earlier -- so doubling an already-struggling
IP's request volume was making a real problem worse, not a theoretical one.

The fix moved everything that talks to YOUTUBE into ../Kanal-Finans-Fetcher,
a small sibling repo that fetches each transcript ONCE and writes into BOTH
projects' Supabase with each project's own extraction prompt/schema (they are
genuinely different questions -- this project reports ALTIN/GUMUS mentions
plus macro themes, XRP-Guess reports XRP/BTC/ETH/KRIPTO mentions with no
themes at all, so there was never a single shared schema to converge on).

What is LEFT here is everything that needs THIS project's own dependencies
and cannot be shared: `assets`, `fetch_data`, `kanal_finans_trading`. This
file's job is now TWO things, both every 15 minutes: read
`kanal_finans_mentions` rows the fetcher wrote that this project has not
traded on yet (`applied_at is null`) and apply them, THEN watch every
portfolio's stop-loss against a fresh quote. Neither makes a request to
YouTube, which is why it can keep running on its OLD 15-minute schedule while
the actual fetch moved to the fetcher's slower, shared, 30-minute one -- this
got MORE responsive to a fresh mention, not less, because it is no longer
waiting behind a possibly-blocked transcript fetch to do the things it
actually needs to do quickly.

STOP-LOSS MOVED HERE ON 2026-09-28, AND THE INCIDENT THAT FORCED IT IS WORTH
KEEPING. Gold closed Friday 2026-09-25 at $4,321. Nothing was watching it
between then and the reopen: not this file (mentions only, back then), not
predict.py (once a day, 23:00 UTC). By the Sunday 22:00 UTC reopen it had
already gapped to $4,294 -- through the standing $4,285 stop -- and kept
falling overnight to $4,177 by Monday morning. The first check to actually
see it was a manual one hours into Monday's session, and it filled at
$4,182.90 against a $4,300 stop: 2.7% below the level the stop-loss exists to
protect. `check_stop_loss()` was never broken -- it sells at the live price
the moment it is CALLED, not at the stop level -- the gap was entirely in how
rarely it got called. This entry point is already awake every 15 minutes for
the mention poll and touches no paid, rate-limited, or YouTube-adjacent
endpoint to do it, so there is no real cost to checking here too: two Yahoo
quotes and two Supabase reads. predict.py keeps calling
`maybe_check_stop_loss()` as well, on purpose -- it is the fallback for
whenever this machine is asleep at a 15-minute trigger (see
run_kanal_finans.ps1's docstring), and the function only acts when price is
actually through the level, so two callers checking the same thing is
harmless, not a double-sell risk.

Everything else about this feature is unchanged and still true: this is one
person's reported opinion, not a forecast this project stands behind
(`ensemble.COMPONENTS` still does not include it, predict.py still never
imports it), resistance never fires an automatic sale (see
kanal_finans_trading.py), and a missing level still means "unchanged", never
"cancelled".
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

# Windows defaults a REDIRECTED stdout to cp1252. Same guard as predict.py,
# same reason -- but THIS is the entry point where it actually bit, and the
# asymmetry is why it was missed: the other seven run on Actions, where stdout
# is UTF-8 already, while Task Scheduler runs this one on Windows. On
# 2026-09-21 kanal_finans_trading._apply printed a `reason` of
# "Tunc Satiroglu: al" -- with the real Turkish letters -- AFTER inserting the
# trade row and BEFORE mark_applied() below could run. The fill succeeded and
# the log said "apply failed for mention 10" over it. A ledger and the line
# describing it must not be able to disagree; see the guard in _apply too.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import assets as assets_module  # noqa: E402
import db as db_module  # noqa: E402
import fetch_data  # noqa: E402
import kanal_finans_trading  # noqa: E402

# Only these two map onto real paper portfolios. GENEL ("kiymetli
# madenler/emtia" without naming one) is informational only -- there is no
# "general metal" portfolio to trade -- but it still has to be marked applied
# so it is not re-read forever.
PORTFOLIO_ASSET = {"ALTIN": "gold", "GUMUS": "silver"}


def get_pending_mentions(db) -> list[dict]:
    """Mentions Kanal-Finans-Fetcher wrote that this project has not traded
    on yet, oldest first so they apply in the order they were actually said."""
    return (db.table("kanal_finans_mentions")
            .select("*")
            .is_("applied_at", "null")
            .order("published_at")
            .execute().data)


def mark_applied(db, mention_id: int) -> None:
    db.table("kanal_finans_mentions").update(
        {"applied_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", mention_id).execute()


def apply_pending_mentions(db) -> int:
    """Applies every not-yet-traded mention to its portfolio. Returns how
    many resulted in a real trade (GENEL mentions are marked applied but
    don't count, same as a HOLD reading counts but moves no money)."""
    mentions = get_pending_mentions(db)
    applied = 0
    for mention in mentions:
        asset_key = PORTFOLIO_ASSET.get(mention["asset"])
        if not asset_key:
            mark_applied(db, mention["id"])
            continue
        try:
            asset = assets_module.get(asset_key)
            price, source = fetch_data.get_live_price(asset.symbol)
            kanal_finans_trading.apply_mention(db, asset, mention, price)
            mark_applied(db, mention["id"])
            applied += 1
            print(f"kanal_finans: [{mention['asset']}] {mention['action']} "
                  f"@ {price:,.2f} ({source})")
        except Exception as exc:  # noqa: BLE001 -- one mention's hiccup must
            # not stop the rest, and must NOT be marked applied: leaving
            # applied_at null is what makes the next run retry it.
            print(f"WARNING: kanal_finans apply failed for mention "
                  f"{mention['id']} ({exc})")
    return applied


def check_stop_losses(db) -> None:
    """Watches every portfolio's stop-loss on THIS entry point's 15-minute
    cadence -- see the module docstring for the 2026-09-28 gap that made a
    once-a-day check (predict.py) too slow to fill anywhere near the level.

    Each asset is independent: gold failing to quote must not skip silver's
    check, and either failing must not stop the mention loop that already ran
    above it in main().
    """
    for asset_key in PORTFOLIO_ASSET.values():
        try:
            asset = assets_module.get(asset_key)
            price, _source = fetch_data.get_live_price(asset.symbol)
            kanal_finans_trading.maybe_check_stop_loss(db, asset, price)
        except Exception as exc:  # noqa: BLE001 -- one asset's hiccup must
            # not stop the other, and there is always another run 15 minutes
            # from now to retry -- this never touches applied_at, so nothing
            # here needs the failed-trade retry contract apply_mention does.
            print(f"WARNING: kanal_finans stop-loss check failed for "
                  f"{asset_key} ({exc})")


def main() -> int:
    db = db_module.get_client()
    applied = apply_pending_mentions(db)
    check_stop_losses(db)
    if applied:
        print(f"kanal_finans: applied {applied} pending mention(s).")
    else:
        print("kanal_finans: nothing pending.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
