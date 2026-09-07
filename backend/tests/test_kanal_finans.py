"""Tests for the DB-free decision functions in the Kanal Finans pipeline.

The network parts (RSS, transcripts, the Claude call) have no tests -- they
are validated by watching live rows, exactly as in XRP-Guess. What IS tested
here is every rule that would fail silently: a stop-loss that quietly
disarms, a retry that stops backing off, a level read from the wrong end of a
range.
"""
from datetime import datetime, timedelta, timezone

import pytest

import kanal_finans
import kanal_finans_trading as kft


class FakeAsset:
    key = "gold"
    label = "Altın"
    symbol = "GC=F"
    fee_rate = 0.0005


ASSET = FakeAsset()
NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# Retry backoff
# --------------------------------------------------------------------------

def test_new_video_is_always_due():
    """A newly published video has no failure record, so it must never be
    delayed by the backoff meant for stuck ones."""
    assert kanal_finans.is_retry_due(None, NOW) is True


def test_early_failures_retry_immediately():
    """The first few attempts are cheap and often succeed -- a transient blip
    clears on the very next run."""
    record = {"attempts": 1, "last_attempt_at": (NOW - timedelta(minutes=1)).isoformat()}
    assert kanal_finans.is_retry_due(record, NOW) is True


def test_backoff_widens_with_failures():
    """Without this, a video whose transcript is IP-blocked would be retried
    96 times a day against the endpoint already refusing us -- the surest way
    to turn a temporary block into a lasting one."""
    stuck = {"attempts": 5, "last_attempt_at": (NOW - timedelta(minutes=10)).isoformat()}
    assert kanal_finans.is_retry_due(stuck, NOW) is False
    later = {"attempts": 5, "last_attempt_at": (NOW - timedelta(hours=2)).isoformat()}
    assert kanal_finans.is_retry_due(later, NOW) is True


def test_backoff_is_monotonic_and_capped():
    delays = [kanal_finans._retry_delay_minutes(n) for n in (0, 3, 6, 10, 50)]
    assert delays == sorted(delays), "a later failure must never retry sooner"
    assert delays[-1] == kanal_finans.RETRY_MAX_DELAY_MINUTES


def test_permanently_stuck_video_settles_at_about_two_attempts_a_day():
    """The stated design goal, asserted rather than assumed."""
    per_day = 24 * 60 / kanal_finans.RETRY_MAX_DELAY_MINUTES
    assert 1 <= per_day <= 3


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
# Extraction contract
# --------------------------------------------------------------------------

def test_zero_is_the_not_mentioned_sentinel():
    """The response schema cannot express "null number", so 0 means "he did
    not give a level" and must never be stored as a real price."""
    assert kanal_finans._level(0) is None
    assert kanal_finans._level(None) is None
    assert kanal_finans._level(4300.5) == 4300.5


def test_only_real_metals_map_to_portfolios():
    """GENEL ("kıymetli madenler" with neither metal named) is informational:
    there is no "general metal" position to take."""
    assert set(kanal_finans.PORTFOLIO_ASSET) == {"ALTIN", "GUMUS"}
    assert "GENEL" in kanal_finans.MENTION_ASSETS
    assert "GENEL" not in kanal_finans.PORTFOLIO_ASSET


def test_theme_vocabulary_is_closed():
    """An open-ended "what did he talk about" field produces a different
    taxonomy every video and nothing can be counted across time."""
    schema = kanal_finans.RESPONSE_SCHEMA["properties"]["themes"]["items"]
    assert schema["properties"]["theme"]["enum"] == list(kanal_finans.THEMES)
    assert schema["additionalProperties"] is False


def test_prompt_states_both_level_directions_explicitly():
    """XRP-Guess only said "pick the more cautious end", and the model got it
    backwards: for a stop-loss the cautious end is the HIGHEST value, for a
    resistance the LOWEST. Worth ~1.8% of extra loss on a real position."""
    prompt = kanal_finans.SYSTEM_PROMPT
    assert "EN YUKSEK" in prompt and "EN DUSUK" in prompt
    assert "stop_loss_price" in prompt and "resistance_price" in prompt
