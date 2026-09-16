"""The `breakout` paper portfolio: one $1,000 book per metal, running the
breakout rule from flow_signal.py.

WHY THIS BOOK EXISTS EVEN THOUGH THE RULE FAILED ITS BAR
--------------------------------------------------------
research/flow.py scored this rule against a bar declared before any result
was looked at, twice, on two vendors and two instruments. It failed both
times: gold wins on Calmar and finishes 34-42% behind buy-and-hold in money,
silver loses on both counts. research/README.md section 18 has the tables.

The book was opened anyway, deliberately and with that result printed beside
it, because the question it answers is not "should I trade this" -- that was
measured and the answer is no -- but "what does a measured-losing rule
actually DO to a thousand dollars, day by day, in public". This repo's whole
claim is that it reports negative results honestly, and a negative result you
can watch cost money is a stronger form of that than a table.

So: the card carries the measurement, the README says there is no reason to
copy it, and the money is fake.

A DIFFERENT ENGINE, WHICH IS WHY IT IS NOT IN trading.STRATEGIES
----------------------------------------------------------------
Same shape as kanal_finans_trading.py, and for the same structural reason:

  Every strategy in trading.STRATEGIES runs compute_target_exposure(), which
  scales a position by a confidence number and a volatility budget, re-aimed
  every trading day.

  This one has no confidence number and no target exposure. It has a discrete
  in/out state from a stateful walk (flow_signal.breakout_path), so it is
  all-in or all-out. Sizing it by anything would contradict the rule: "hold
  until the trend breaks" is not compatible with trimming 3% every morning.

That is also why trading.REBALANCE_THRESHOLD does not apply to it, and why
the page draws its panel inside the breakout card rather than in the grid of
measured rules. tests/test_flow_signal.py locks those boundaries.

THE BOOK MIRRORS THE RULE'S STATE, IT DOES NOT RE-DERIVE IT
------------------------------------------------------------
The only input is `state` on the newest published row of `breakout_state`.
That makes the book self-correcting: a missed cron run does not desynchronise
it, because the next run compares holdings against the state again rather
than replaying a queue of events. The cost is that a position opened AND
closed between two runs is missed entirely -- acceptable on daily bars with a
daily cron, and the alternative (an event queue) fails in the worse
direction, by acting on a signal whose exit has already happened.

One consequence to know when the book is first opened or reset: if the rule
is already long at that moment, the book buys in mid-trend at today's price
rather than at the rule's original entry. Both metals were flat when these
books opened (2026-09-16), so this did not arise -- but it is the honest
behaviour rather than a bug. The book runs the rule from the day it starts.

FILLS ARE AT THE SIGNAL'S OWN SERIES
-------------------------------------
The fill price is the TradingView COMEX close the decision was made on, NOT
fetch_data.get_live_price()'s GC=F. Those two are different continuous-
contract stitchings of the same contract and differ by a median 0.88% on
closes (research/README.md, phase 2), so deciding on one and filling at the
other would book that seam as P&L. The frontend already marks every portfolio
at COMEX:GC1!/SI1!, which is this series -- so for this book the decision
price, the fill price and the mark are finally all one series.
"""
from __future__ import annotations

from datetime import datetime, timezone

STRATEGY = "breakout"

# Why each exit happened, for the trade's `reason` column. The keys are
# flow_signal.breakout_path's own exit_reason values; an unknown one falls
# back to the raw string rather than to silence.
EXIT_REASON = {
    "stop": "Stop seviyesi kirildi",
    "trend": "Trend kirildi (iki seans AVWAP alti)",
}


def decide(signal_state: int, units: float, cash: float, price: float,
           fee_rate: float, exit_reason: str = "",
           entry_level: float | None = None) -> dict:
    """What the book should do, given the rule's state today. Pure.

    All-in / all-out: there is no exposure to scale. Returns the same shape
    kanal_finans_trading.decide_on_mention does, so _apply() below reads like
    that module's twin and the two cannot drift in what a decision dict means.
    """
    if not price or price <= 0:
        return {"action": "HOLD", "usd_amount": 0.0, "unit_amount": 0.0,
                "fee_usd": 0.0, "reason": ""}

    if signal_state and units == 0 and cash > 0:
        fee = cash * fee_rate
        level = f" (VAH ${entry_level:,.2f})" if entry_level else ""
        return {
            "action": "BUY", "usd_amount": cash, "unit_amount": (cash - fee) / price,
            "fee_usd": fee,
            "reason": f"Kirilim: deger alani ustu kapanis{level}",
        }

    if not signal_state and units > 0:
        gross = units * price
        return {
            "action": "SELL", "usd_amount": gross, "unit_amount": units,
            "fee_usd": gross * fee_rate,
            "reason": EXIT_REASON.get(exit_reason, exit_reason or "Kural cikti"),
        }

    return {"action": "HOLD", "usd_amount": 0.0, "unit_amount": 0.0,
            "fee_usd": 0.0, "reason": ""}


# --------------------------------------------------------------------------
# Live path
# --------------------------------------------------------------------------

def get_state(db, asset_key: str) -> dict | None:
    """The book's row, or None when it has not been seeded.

    None rather than an exception: the seed ships in a migration the user
    applies by hand, so between a deploy and that migration this must degrade
    to "no book yet" and leave the panel -- which is the thing that actually
    matters here -- writing normally.
    """
    rows = (db.table("portfolios").select("*")
            .eq("asset", asset_key).eq("strategy", STRATEGY).execute().data)
    return rows[0] if rows else None


def _apply(db, asset, decision: dict, price: float, cash: float,
           units: float) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()

    if decision["action"] == "BUY":
        new_cash = cash - decision["usd_amount"]
        new_units = units + decision["unit_amount"]
    else:
        new_cash = cash + (decision["usd_amount"] - decision["fee_usd"])
        new_units = units - decision["unit_amount"]

    db.table("portfolios").update({
        "cash_usd": new_cash, "ounces": new_units,
        "position": "LONG" if new_units > 0 else "CASH",
        # Deliberately NOT written: `target_exposure` stays 0 because this
        # rule has none, and `stop_loss_price` stays null because the live
        # stop already lives on breakout_state, recomputed from price history
        # on every run. A second copy here could only ever disagree with it --
        # the same reason the Fibonacci levels are derived in the browser
        # rather than stored.
        "updated_at": now_iso,
    }).eq("asset", asset.key).eq("strategy", STRATEGY).execute()

    db.table("trades").insert({
        "asset": asset.key, "strategy": STRATEGY,
        "side": decision["action"], "price": price,
        "ounce_amount": decision["unit_amount"], "usd_amount": decision["usd_amount"],
        "fee_usd": decision["fee_usd"], "cash_after": new_cash,
        "ounces_after": new_units, "reason": decision["reason"],
    }).execute()

    print(f"TRADE [{asset.key}/{STRATEGY}]: {decision['action']} "
          f"{decision['unit_amount']:.4f} oz @ {price:,.2f} -- {decision['reason']}")


def apply_state(db, asset, last_row: dict) -> str:
    """Bring the book in line with the newest published breakout state.

    `last_row` is track_breakout.build_rows()'s final entry, so the price is
    the close the decision was actually made on. Returns a short status for
    the console: "BUY" / "SELL" / "HOLD" / "no-book".
    """
    state = get_state(db, asset.key)
    if state is None:
        return "no-book"

    cash, units = float(state["cash_usd"]), float(state["ounces"])
    decision = decide(
        int(last_row["state"]), units, cash, float(last_row["close"]),
        asset.fee_rate, str(last_row.get("exit_reason") or ""),
        last_row.get("vah"),
    )
    if decision["action"] == "HOLD":
        return "HOLD"
    _apply(db, asset, decision, float(last_row["close"]), cash, units)
    return decision["action"]
