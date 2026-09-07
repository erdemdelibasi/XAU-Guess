"""The `kanalfinans` paper portfolio: mirrors, as literally as possible, what
Tunç Şatıroğlu says to do with gold and silver.

One portfolio per metal, both keyed into the same `portfolios` table as every
other strategy -- but driven by a different engine, and the difference is the
point:

  Every other strategy runs trading.compute_target_exposure(), which scales
  position size by a numeric confidence and a volatility budget, re-aimed
  once per trading day.

  This one has no confidence number at all. It has a discrete BUY/HOLD/SELL
  from an irregular, per-video event stream. So position sizing is all-in /
  all-out rather than the others' partial sizing: there is nothing to scale
  by, and "do what he says" is the whole specification.

RESISTANCE LEVELS ARE STORED BUT NEVER AUTO-SELL
------------------------------------------------
XRP-Guess learned this from live data: the speaker sometimes calls a
resistance BREAK bullish -- "1.41 direncinin geçilmesi bekleniyor, geçilirse
alım fırsatı olabilir" -- so a fixed "price reached resistance -> take profit"
rule would have actively inverted him on exactly the videos where he was most
specific. Only the stop-loss is a hard automatic trigger.

The stop-loss is watched CONTINUOUSLY, not just when a new video lands --
predict.py calls maybe_check_stop_loss() on every daily cycle. That call
touches only Supabase and an already-fetched price, never YouTube, so unlike
kanal_finans.py itself it runs fine on GitHub Actions.
"""
from __future__ import annotations

from datetime import datetime, timezone

STRATEGY = "kanalfinans"


# --------------------------------------------------------------------------
# Pure decision functions -- no DB, so tests and any future replay can use them
# --------------------------------------------------------------------------

def decide_on_mention(cash: float, units: float,
                      held_stop: float | None, held_resistance: float | None,
                      action: str, mention_stop: float | None,
                      mention_resistance: float | None,
                      price: float, fee_rate: float) -> dict:
    """What a new mention should do to the portfolio.

    A mention's stop/resistance only REPLACES the currently watched level when
    it actually supplies a new one -- he does not repeat the level in every
    video, so a missing level means "unchanged", not "cancelled". Getting that
    backwards would silently disarm the stop-loss on every video that happened
    not to restate it.
    """
    new_stop = mention_stop if mention_stop else held_stop
    new_resistance = mention_resistance if mention_resistance else held_resistance

    if action == "BUY" and units == 0 and cash > 0:
        fee = cash * fee_rate
        return {
            "action": "BUY", "usd_amount": cash, "unit_amount": (cash - fee) / price,
            "fee_usd": fee, "new_stop": new_stop, "new_resistance": new_resistance,
            "reason": "Tunç Şatıroğlu: al",
        }

    if action == "SELL" and units > 0:
        gross = units * price
        return {
            "action": "SELL", "usd_amount": gross, "unit_amount": units,
            "fee_usd": gross * fee_rate,
            # Flat again: nothing left to protect until the next BUY sets a
            # fresh level. Carrying the old stop forward would arm it against
            # a position that no longer exists.
            "new_stop": None, "new_resistance": new_resistance,
            "reason": "Tunç Şatıroğlu: sat",
        }

    return {"action": "HOLD", "usd_amount": 0.0, "unit_amount": 0.0, "fee_usd": 0.0,
            "new_stop": new_stop, "new_resistance": new_resistance, "reason": ""}


def check_stop_loss(units: float, stop_price: float | None, price: float,
                    fee_rate: float) -> dict:
    """Continuous monitoring, independent of new mentions. Only fires while
    actually long and only below a level he actually gave."""
    if units > 0 and stop_price and price <= stop_price:
        gross = units * price
        return {
            "action": "SELL", "usd_amount": gross, "unit_amount": units,
            "fee_usd": gross * fee_rate, "new_stop": None,
            "reason": f"Zarar-kes tetiklendi (${stop_price:,.2f})",
        }
    return {"action": "HOLD"}


# --------------------------------------------------------------------------
# Live path
# --------------------------------------------------------------------------

def get_state(db, asset_key: str) -> dict:
    return (db.table("portfolios").select("*")
            .eq("asset", asset_key).eq("strategy", STRATEGY)
            .single().execute().data)


def _apply(db, asset, decision: dict, price: float, cash: float, units: float,
           mention_id: int | None) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()

    if decision["action"] == "HOLD":
        db.table("portfolios").update({
            "stop_loss_price": decision.get("new_stop"),
            "resistance_price": decision.get("new_resistance"),
            "updated_at": now_iso,
        }).eq("asset", asset.key).eq("strategy", STRATEGY).execute()
        return

    if decision["action"] == "BUY":
        new_cash = cash - decision["usd_amount"]
        new_units = units + decision["unit_amount"]
    else:
        new_cash = cash + (decision["usd_amount"] - decision["fee_usd"])
        new_units = units - decision["unit_amount"]

    db.table("portfolios").update({
        "cash_usd": new_cash, "ounces": new_units,
        "position": "LONG" if new_units > 0 else "CASH",
        "stop_loss_price": decision.get("new_stop"),
        "resistance_price": decision.get("new_resistance"),
        "updated_at": now_iso,
    }).eq("asset", asset.key).eq("strategy", STRATEGY).execute()

    db.table("trades").insert({
        "asset": asset.key, "strategy": STRATEGY,
        "side": decision["action"], "price": price,
        "ounce_amount": decision["unit_amount"], "usd_amount": decision["usd_amount"],
        "fee_usd": decision["fee_usd"], "cash_after": new_cash, "ounces_after": new_units,
        "triggered_by_mention_id": mention_id, "reason": decision["reason"],
    }).execute()

    print(f"TRADE [{asset.key}/{STRATEGY}]: {decision['action']} "
          f"{decision['unit_amount']:.4f} oz @ {price:,.2f} -- {decision['reason']}")


def apply_mention(db, asset, mention: dict, price: float) -> None:
    """Called from kanal_finans.py right after a new mention is saved."""
    state = get_state(db, asset.key)
    cash, units = float(state["cash_usd"]), float(state["ounces"])
    decision = decide_on_mention(
        cash, units, state.get("stop_loss_price"), state.get("resistance_price"),
        mention["action"], mention.get("stop_loss_price"),
        mention.get("resistance_price"), price, asset.fee_rate,
    )
    _apply(db, asset, decision, price, cash, units, mention["id"])


def maybe_check_stop_loss(db, asset, price: float) -> None:
    """Called every cycle from predict.py. Never touches YouTube, so unlike
    kanal_finans.py itself this runs fine on GitHub Actions."""
    state = get_state(db, asset.key)
    cash, units = float(state["cash_usd"]), float(state["ounces"])
    decision = check_stop_loss(units, state.get("stop_loss_price"), price, asset.fee_rate)
    if decision["action"] == "HOLD":
        return
    decision["new_resistance"] = state.get("resistance_price")
    _apply(db, asset, decision, price, cash, units, mention_id=None)
