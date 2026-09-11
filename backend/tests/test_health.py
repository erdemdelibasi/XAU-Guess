"""Tests for health.check() -- the silent-failure detector.

No network, no DB: rows are handed in directly, exactly the shape
health.fetch_recent()/fetch_model_state_updates() return. Timestamps are
built relative to the real current time (not frozen) -- check() also calls
datetime.now() internally, and the day-scale thresholds here are far larger
than the sub-second gap between building a fixture and calling check().

Each test locks one specific "this fails with no exception anywhere" scenario
from the module docstring.
"""
import datetime as dt

import assets
import health


def _iso(days_ago: float) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)).isoformat()


def _row(days_ago: float, price_source: str = "GC=F",
         news_confidence: float = 0.3, macro_confidence: float = 0.2) -> dict:
    return {"created_at": _iso(days_ago), "price_source": price_source,
            "news_confidence": news_confidence, "macro_confidence": macro_confidence}


def _check(recent, model_state_rows):
    return health.check(assets.GOLD, recent, model_state_rows)


def _state(days_ago, up_calls=40, down_calls=20):
    """A model_state row that has actually scored predictions.

    The counters are load-bearing, not decoration: check() reads them to tell
    a stalled retrain from one that has never had a resolved prediction to
    work with. Defaults describe the ordinary case so each test says only
    what it is actually about.
    """
    return {"updated_at": _iso(days_ago), "up_calls": up_calls, "down_calls": down_calls}


def test_healthy_pipeline_is_silent():
    """The common case: nothing should be said when nothing is wrong -- a
    section that prints "all clear" every morning trains the reader to
    ignore it, exactly the failure mode this module exists to avoid."""
    recent = [_row(days_ago=d) for d in (0.3, 1.3, 2.3)]
    model_state = [_state(0.3)]
    assert _check(recent, model_state) == []


def test_no_recent_prediction_flags_predict_cron():
    """predict.py's cron silently stopped -- the newest row is old."""
    recent = [_row(days_ago=5.0)]
    warnings = _check(recent, [_state(0.3)])
    assert any("predict.py" in w for w in warnings)


def test_a_single_stale_price_is_not_alarming():
    """One stale read is ordinary noise, not a persisting problem."""
    recent = [_row(days_ago=0.3, price_source="GC=F(stale)"),
              _row(days_ago=1.3, price_source="GC=F"),
              _row(days_ago=2.3, price_source="GC=F")]
    assert _check(recent, [_state(0.3)]) == []


def test_three_consecutive_stale_prices_is_flagged():
    """Three weekday runs in a row on a proxy is a live source that stopped
    updating, not a weekend gap -- predict.py never runs on weekends."""
    recent = [_row(days_ago=d, price_source="GC=F(stale)") for d in (0.3, 1.3, 2.3)]
    warnings = _check(recent, [_state(0.3)])
    assert any("stale" in w for w in warnings)


def test_a_single_abstain_is_normal_but_a_long_streak_is_flagged():
    quiet = [_row(days_ago=d, news_confidence=0.0) for d in range(6)]
    warnings = _check(quiet, [_state(0.3)])
    assert any("haber" in w for w in warnings)

    one_off = [_row(days_ago=0.3, news_confidence=0.0)] + [_row(days_ago=d) for d in (1.3, 2.3)]
    assert _check(one_off, [_state(0.3)]) == []


def test_stale_model_state_flags_retrain_cron():
    """retrain.py's cron silently stopped -- model_state was not touched
    recently, even though predict.py itself is still running fine."""
    recent = [_row(days_ago=d) for d in (0.3, 1.3, 2.3)]
    warnings = _check(recent, [_state(10.0)])
    assert any("retrain.py" in w for w in warnings)


def test_records_that_never_scored_anything_cannot_be_stale():
    """The system's first week, and the check used to cry wolf through it.

    The horizon is five trading days, so nothing resolves until a week after
    the first prediction -- and retrain.run_asset skips
    rebuild_component_records entirely while there is nothing resolved, so
    `updated_at` sits at the seed value and drifts further from today every
    night the cron runs PERFECTLY. Measured live on 2026-09-11: eight
    predictions written, zero resolved, every cron green, and both metals'
    reports carried ">>> DIKKAT ... retrain.py'nin cron'u sessizce durmus
    olabilir". A warning that fires when nothing is wrong is worse than no
    warning, because it is the one the reader learns to skip.
    """
    recent = [_row(days_ago=d) for d in (0.3, 1.3, 2.3)]
    cold = [_state(10.0, up_calls=0, down_calls=0) for _ in range(5)]
    assert not any("retrain.py" in w for w in _check(recent, cold))
    # One scored component is enough to put the check back on duty: that is
    # the moment the record became something that CAN go stale.
    warm = cold[:-1] + [_state(10.0, up_calls=1, down_calls=0)]
    assert any("retrain.py" in w for w in _check(recent, warm))


def test_no_history_at_all_is_silent_not_broken():
    """A brand-new asset with nothing in either table yet must not raise or
    warn -- that is cold start, not a failure."""
    assert _check([], []) == []
