"""Tests for the DB-free decision functions in the Kanal Finans pipeline, plus
apply_pending_mentions()'s bookkeeping.

The YouTube-facing half (RSS, transcripts, retry backoff, the Claude call) no
longer lives in this project -- it moved to ../Kanal-Finans-Fetcher, a sibling
repo shared with XRP-Guess (see kanal_finans.py's module docstring for why).
Its tests moved with it, into Kanal-Finans-Fetcher/tests/test_fetcher.py.
What's tested here is everything that stayed: a stop-loss that quietly
disarms, a level read from the wrong end of a range, and a pending mention
that must retry (never get marked applied) if trading on it fails.
"""
import pytest

import kanal_finans
import kanal_finans_trading as kft


class FakeAsset:
    key = "gold"
    label = "Altın"
    symbol = "GC=F"
    fee_rate = 0.0005


ASSET = FakeAsset()


# --------------------------------------------------------------------------
# Mention decisions
# --------------------------------------------------------------------------

def test_buy_enters_full_position():
    """All-in / all-out on purpose: there is no confidence number to scale by,
    and the specification is "do what he says"."""
    d = kft.decide_on_mention(1000.0, 0.0, None, None, "BUY", None, None,
                              price=4000.0, fee_rate=ASSET.fee_rate)
    assert d["action"] == "BUY"
    assert d["usd_amount"] == 1000.0
    assert d["unit_amount"] == pytest.approx((1000.0 - 0.5) / 4000.0)


def test_buy_while_already_long_does_nothing():
    d = kft.decide_on_mention(0.0, 0.25, 3900.0, None, "BUY", None, None,
                              4000.0, ASSET.fee_rate)
    assert d["action"] == "HOLD"


def test_sell_exits_fully():
    d = kft.decide_on_mention(0.0, 0.25, 3900.0, 4200.0, "SELL", None, None,
                              4000.0, ASSET.fee_rate)
    assert d["action"] == "SELL"
    assert d["unit_amount"] == 0.25


def test_missing_level_keeps_the_previous_one():
    """He does not repeat the level in every video, so "no level given" means
    UNCHANGED, not cancelled. Reading it the other way would silently disarm
    the stop-loss on every video that happened not to restate it."""
    d = kft.decide_on_mention(0.0, 0.25, 3900.0, 4200.0, "HOLD", None, None,
                              4000.0, ASSET.fee_rate)
    assert d["new_stop"] == 3900.0
    assert d["new_resistance"] == 4200.0


def test_new_level_replaces_the_old_one():
    d = kft.decide_on_mention(0.0, 0.25, 3900.0, 4200.0, "HOLD", 3950.0, 4300.0,
                              4000.0, ASSET.fee_rate)
    assert d["new_stop"] == 3950.0
    assert d["new_resistance"] == 4300.0


def test_selling_clears_the_stop_but_keeps_resistance():
    """Flat again: nothing left to protect until the next BUY sets a fresh
    level. Carrying the old stop forward would arm it against a position that
    no longer exists."""
    d = kft.decide_on_mention(0.0, 0.25, 3900.0, 4200.0, "SELL", None, None,
                              4000.0, ASSET.fee_rate)
    assert d["new_stop"] is None
    assert d["new_resistance"] == 4200.0


# --------------------------------------------------------------------------
# Stop-loss
# --------------------------------------------------------------------------

def test_stop_loss_fires_below_the_level():
    d = kft.check_stop_loss(0.25, 3900.0, price=3850.0, fee_rate=ASSET.fee_rate)
    assert d["action"] == "SELL"
    assert d["unit_amount"] == 0.25


def test_stop_loss_does_not_fire_above_the_level():
    assert kft.check_stop_loss(0.25, 3900.0, 3950.0, ASSET.fee_rate)["action"] == "HOLD"


def test_stop_loss_needs_both_a_position_and_a_level():
    assert kft.check_stop_loss(0.0, 3900.0, 100.0, ASSET.fee_rate)["action"] == "HOLD"
    assert kft.check_stop_loss(0.25, None, 100.0, ASSET.fee_rate)["action"] == "HOLD"


def test_resistance_never_triggers_a_sale():
    """Measured in XRP-Guess: the speaker sometimes calls a resistance BREAK
    bullish ("geçilirse alım fırsatı olabilir"), so a fixed
    resistance -> take-profit rule would invert him on exactly the videos
    where he was most specific. Only the stop-loss is automatic."""
    far_above = kft.check_stop_loss(0.25, 3900.0, price=99999.0, fee_rate=ASSET.fee_rate)
    assert far_above["action"] == "HOLD"


# --------------------------------------------------------------------------
# apply_pending_mentions -- the bookkeeping half that stayed here
# --------------------------------------------------------------------------

class _FakeTable:
    def __init__(self, name, store):
        self.name = name
        self.store = store
        self._filter_null = None
        self._eq = None

    def select(self, _cols):
        return self

    def is_(self, column, value):
        assert value == "null"
        self._filter_null = column
        return self

    def order(self, _col):
        return self

    def update(self, patch):
        self._patch = patch
        return self

    def eq(self, column, value):
        self._eq = (column, value)
        return self

    def execute(self):
        if self._filter_null:
            rows = [r for r in self.store if r.get(self._filter_null) is None]
            return type("R", (), {"data": rows})()
        if self._eq:
            column, value = self._eq
            for row in self.store:
                if row[column] == value:
                    row.update(self._patch)
            return type("R", (), {"data": None})()
        return type("R", (), {"data": self.store})()


class FakeDb:
    """Mimics just enough of the supabase-py chain for kanal_finans_mentions:
    .select().is_(col, "null").order().execute().data and
    .update(patch).eq(col, val).execute()."""
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        assert name == "kanal_finans_mentions"
        return _FakeTable(name, self.rows)


def test_get_pending_mentions_only_returns_unapplied_rows():
    rows = [
        {"id": 1, "asset": "ALTIN", "applied_at": None},
        {"id": 2, "asset": "GUMUS", "applied_at": "2026-09-08T00:00:00+00:00"},
    ]
    pending = kanal_finans.get_pending_mentions(FakeDb(rows))
    assert [r["id"] for r in pending] == [1]


def test_apply_pending_mentions_stamps_genel_without_trading(monkeypatch):
    """GENEL has no portfolio to trade, but must still be marked applied --
    otherwise it is read as "pending" on every run forever."""
    rows = [{"id": 1, "asset": "GENEL", "applied_at": None}]
    db = FakeDb(rows)

    def boom(*_a, **_kw):
        raise AssertionError("GENEL must never reach the trading engine")
    monkeypatch.setattr(kanal_finans.kanal_finans_trading, "apply_mention", boom)

    applied = kanal_finans.apply_pending_mentions(db)
    assert applied == 0
    assert rows[0]["applied_at"] is not None


def test_apply_pending_mentions_trades_real_metals(monkeypatch):
    rows = [{"id": 1, "asset": "ALTIN", "action": "BUY", "applied_at": None}]
    db = FakeDb(rows)
    calls = []

    monkeypatch.setattr(kanal_finans.fetch_data, "get_live_price",
                         lambda symbol: (4400.0, "GC=F"))
    monkeypatch.setattr(kanal_finans.kanal_finans_trading, "apply_mention",
                         lambda db, asset, mention, price: calls.append((asset.key, price)))

    applied = kanal_finans.apply_pending_mentions(db)
    assert applied == 1
    assert calls == [("gold", 4400.0)]
    assert rows[0]["applied_at"] is not None


def test_a_failed_trade_is_not_marked_applied(monkeypatch):
    """The retry contract: leaving applied_at NULL is what makes the next run
    try again. Marking it applied here would silently drop a real mention."""
    rows = [{"id": 1, "asset": "ALTIN", "action": "BUY", "applied_at": None}]
    db = FakeDb(rows)

    def boom(_symbol):
        raise RuntimeError("Yahoo hiccup")
    monkeypatch.setattr(kanal_finans.fetch_data, "get_live_price", boom)

    applied = kanal_finans.apply_pending_mentions(db)
    assert applied == 0
    assert rows[0]["applied_at"] is None


# --------------------------------------------------------------------------
# What still maps mentions to portfolios
# --------------------------------------------------------------------------

def test_only_real_metals_map_to_portfolios():
    """GENEL ("kıymetli madenler" with neither metal named) is informational:
    there is no "general metal" position to take."""
    assert set(kanal_finans.PORTFOLIO_ASSET) == {"ALTIN", "GUMUS"}
