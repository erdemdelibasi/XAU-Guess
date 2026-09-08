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
file's whole job now is: read `kanal_finans_mentions` rows the fetcher wrote
that this project has not traded on yet (`applied_at is null`), and apply
them. It makes ZERO requests to YouTube, which is why it can keep running
on its OLD 15-minute schedule while the actual fetch moved to the fetcher's
slower, shared, 30-minute one -- this got MORE responsive to a fresh mention,
not less, because it is no longer waiting behind a possibly-blocked transcript
fetch to do the one thing it actually needs to do quickly.

Everything else about this feature is unchanged and still true: this is one
person's reported opinion, not a forecast this project stands behind
(`ensemble.COMPONENTS` still does not include it, predict.py still never
imports it), stop-loss still fires automatically while resistance never does
(see kanal_finans_trading.py), and a missing level still means "unchanged",
never "cancelled".
"""
from __future__ import annotations

from datetime import datetime, timezone

import assets as assets_module
import db as db_module
import fetch_data
import kanal_finans_trading

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


def main() -> int:
    db = db_module.get_client()
    applied = apply_pending_mentions(db)
    if applied:
        print(f"kanal_finans: applied {applied} pending mention(s).")
    else:
        print("kanal_finans: nothing pending.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
