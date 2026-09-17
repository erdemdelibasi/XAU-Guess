"""Tests for the data-hygiene rules that decide what counts as a real session.

These lock in a bug that shipped and survived a review because the code
looked right: the "is this bar finished?" rule read the SHAPE of Yahoo's
timestamp, and Yahoo stamps a half-traded session exactly like a closed one.
The result was a guard that removed nothing, in two files at once.
"""
import datetime as dt

import pandas as pd
import pytest

import fetch_data

ET = fetch_data.EXCHANGE_TZ


def _bar(date_str: str) -> pd.Timestamp:
    """A daily bar as Yahoo actually stamps one: 00:00 New York, in UTC."""
    return (pd.Timestamp(f"{date_str} 00:00", tz=ET)).tz_convert("UTC")


def _now(date_str: str, hour: int) -> dt.datetime:
    return dt.datetime.fromisoformat(f"{date_str}T{hour:02d}:00").replace(tzinfo=ET)


def test_midsession_bar_is_not_complete():
    """The bug. At 04:00 New York the 2026-09-08 session has hours left to
    run, and Yahoo serves it stamped 00:00 -- identical to a closed bar.
    Measured live on 2026-09-08 07:58 UTC before this rule existed."""
    assert not fetch_data.bar_is_complete(_bar("2026-09-08"), _now("2026-09-08", 4))


def test_bar_is_complete_after_the_close():
    """23:00 UTC, when the cron runs, is 19:00 New York -- two hours past the
    17:00 close, so the day's bar is final and must be kept. A rule that
    dropped it here would push every prediction a session into the past."""
    assert fetch_data.bar_is_complete(_bar("2026-09-08"), _now("2026-09-08", 19))


def test_yesterdays_bar_is_always_complete():
    assert fetch_data.bar_is_complete(_bar("2026-09-04"), _now("2026-09-08", 4))


def test_early_close_session_is_kept():
    """Yahoo stamped the half-day session after Thanksgiving (2025-11-28) at
    09:30 New York rather than 00:00. The old shape-based rule read that as
    "not a clean session open" and threw away a REAL session. The clock rule
    keeps it, because what matters is the date, not the stamp."""
    odd = pd.Timestamp("2025-11-28 09:30", tz=ET).tz_convert("UTC")
    assert fetch_data.bar_is_complete(odd, _now("2025-11-28", 19))


def test_drop_forming_bar_removes_only_the_last_row():
    frame = pd.DataFrame({
        "time": [_bar("2026-09-03"), _bar("2026-09-04"), _bar("2026-09-08")],
        "close": [1.0, 2.0, 3.0],
    })
    trimmed = fetch_data.drop_forming_bar(frame, _now("2026-09-08", 4))
    assert len(trimmed) == 2
    assert trimmed["close"].iloc[-1] == 2.0
    # And nothing is dropped once that session has closed.
    assert len(fetch_data.drop_forming_bar(frame, _now("2026-09-08", 19))) == 3


def test_drop_forming_bar_handles_an_empty_frame():
    empty = pd.DataFrame(columns=["time", "close"])
    assert fetch_data.drop_forming_bar(empty).empty


def test_dst_is_handled_both_ways():
    """The close is 17:00 New York, which is 21:00 UTC in summer and 22:00 in
    winter. A hardcoded UTC hour would be right for half the year -- and
    wrong in the direction that predicts from an unfinished session."""
    summer = _bar("2026-07-15")
    winter = _bar("2026-01-15")
    assert summer.hour == 4 and winter.hour == 5, "Yahoo stamps 00:00 New York"
    for bar, day in ((summer, "2026-07-15"), (winter, "2026-01-15")):
        assert not fetch_data.bar_is_complete(bar, _now(day, 16))
        assert fetch_data.bar_is_complete(bar, _now(day, 18))


# --------------------------------------------------------------------------
# The Fed target splice
# --------------------------------------------------------------------------

def test_fed_target_uses_the_range_midpoint_not_the_upper_bound():
    """The FOMC switched from a single target to a range on 2008-12-16.
    Splicing the pre-2008 single target onto the range's UPPER bound would
    print a policy move on the changeover date that never happened, and
    research/fedcycle.py reads exactly those change dates as its event list.

    The splice is exercised through a stub rather than the network: what is
    being tested is the arithmetic, and a test that needs FRED to be up is a
    test that fails for reasons unrelated to the code (see fetch_data.FRED_CSV
    on why this host is not dependable).
    """
    single = pd.DataFrame({
        "time": pd.to_datetime(["2008-12-14", "2008-12-15"], utc=True),
        "value": [1.0, 1.0],
    })
    lower = pd.DataFrame({
        "time": pd.to_datetime(["2008-12-16", "2008-12-17"], utc=True),
        "value": [0.0, 0.0],
    })
    upper = pd.DataFrame({
        "time": pd.to_datetime(["2008-12-16", "2008-12-17"], utc=True),
        "value": [0.25, 0.25],
    })
    stub = {"DFEDTAR": single, "DFEDTARL": lower, "DFEDTARU": upper}
    original = fetch_data.get_fred_series
    fetch_data.get_fred_series = lambda series_id: stub.get(series_id)
    try:
        spliced = fetch_data.get_fed_target_rate()
    finally:
        fetch_data.get_fred_series = original

    assert list(spliced["value"]) == [1.0, 1.0, 0.125, 0.125]
    # One genuine cut on the changeover, not two, and not a phantom 0.75 step.
    changes = spliced["value"].diff().abs() > 1e-9
    assert int(changes.sum()) == 1


def test_fed_target_falls_back_when_the_range_series_are_missing():
    """FRED going half-dark must not produce a silently truncated series."""
    single = pd.DataFrame({
        "time": pd.to_datetime(["2005-01-03"], utc=True), "value": [2.25],
    })
    original = fetch_data.get_fred_series
    fetch_data.get_fred_series = lambda series_id: single if series_id == "DFEDTAR" else None
    try:
        assert len(fetch_data.get_fed_target_rate()) == 1
    finally:
        fetch_data.get_fred_series = original


# --------------------------------------------------------------------------
# Pending-migration tolerance
# --------------------------------------------------------------------------

class _FakeTable:
    def __init__(self, known_columns, seen):
        self.known = known_columns
        self.seen = seen

    def insert(self, row):
        self.seen.append(dict(row))
        unknown = [c for c in row if c not in self.known]
        if unknown:
            raise RuntimeError(
                f"{{'code': 'PGRST204', 'message': \"Could not find the "
                f"'{unknown[0]}' column of 'predictions' in the schema cache\"}}")
        self._row = row
        return self

    def execute(self):
        return type("R", (), {"data": [{"id": 1}]})()


class _FakeDb:
    def __init__(self, known_columns):
        self.known = known_columns
        self.seen = []

    def table(self, _name):
        return _FakeTable(self.known, self.seen)


def test_insert_survives_a_pending_migration():
    """A column that exists only in schema.sql must not cost the whole row.

    PostgREST rejects an insert outright when any key has no column, and
    `unique (asset, target_date)` means a lost row can never be backfilled --
    that session is simply gone. So an unapplied ALTER TABLE has to degrade
    to "one feature dormant", never to "no prediction today".
    """
    import predict

    known = {"asset", "target_date", "confidence"}
    db = _FakeDb(known)
    row = {"asset": "gold", "target_date": "2026-09-15", "confidence": 0.1,
           "tech_confidence_raw": 0.42}
    result = predict.insert_prediction(db, row)

    assert result.data[0]["id"] == 1
    assert len(db.seen) == 2, "should retry once, not give up and not loop"
    assert "tech_confidence_raw" not in db.seen[1]
    assert db.seen[1]["confidence"] == 0.1, "everything else must survive"


def test_insert_does_not_swallow_unrelated_errors():
    """Only the known-pending columns justify a retry. Anything else is a real
    failure and must surface -- a blanket retry would hide a genuine outage
    behind a reassuring warning."""
    import predict

    class _Boom:
        def table(self, _name):
            return self

        def insert(self, _row):
            raise RuntimeError("connection refused")

        def execute(self):
            raise AssertionError("unreachable")

    with pytest.raises(RuntimeError, match="connection refused"):
        predict.insert_prediction(_Boom(), {"asset": "gold"})


# ---------------------------------------------------------------------------
# The same bug, through the second vendor's door (2026-09-17)
# ---------------------------------------------------------------------------
# TradingView stamps a daily futures bar with the moment the session OPENED
# (18:00 New York); Yahoo and CME label it with the trade date it closes on.
# tv_history.daily() promised "columns match fetch_data.get_daily exactly" and
# the columns did -- the dates did not, and the guard above reads a date. It
# therefore removed nothing from a TradingView frame, and track_breakout.py
# published a one-hour-old forming bar as the newest closed session every
# night. Measured live: the published 2026-09-16 row carried 4,309.1 against
# that session's real close of 4,408.2.


def _tv_bar(date_str: str, hour: int) -> pd.Timestamp:
    """A bar as TradingView stamps one: the session's OPEN, in UTC."""
    return pd.Timestamp(f"{date_str} {hour:02d}:00", tz=ET).tz_convert("UTC")


def _trade_dates(*bars: pd.Timestamp) -> list[dt.date]:
    import tv_history

    stamped = tv_history.to_trade_dates(pd.Series(list(bars)))
    return [t.tz_convert(ET).date() for t in stamped]


def test_evening_stamp_rolls_to_the_next_trade_date():
    """The Sunday-evening open is Monday's session. Getting this wrong is not
    a cosmetic label: it is a full session of misalignment against every
    Yahoo-derived series in the project."""
    assert _trade_dates(_tv_bar("2026-09-13", 18)) == [dt.date(2026, 9, 14)]
    assert _trade_dates(_tv_bar("2026-09-16", 18)) == [dt.date(2026, 9, 17)]


def test_daytime_stamp_is_left_alone():
    """An equity-style bar stamped at midnight exchange time is already
    labelled by its own trade date. The rule is CME's definition, not a
    per-symbol constant, so it has to pass those through untouched."""
    assert _trade_dates(_tv_bar("2026-09-16", 0)) == [dt.date(2026, 9, 16)]


def test_the_roll_survives_a_dst_boundary():
    """2026-11-01 is the day EDT ends. Adding a tz-aware 24 hours to midnight
    here lands on 23:00 of the SAME day -- a different calendar date, which is
    the only thing this function produces. Naive arithmetic, then localise."""
    stamped = _trade_dates(_tv_bar("2026-11-01", 18))
    assert stamped == [dt.date(2026, 11, 2)]


def test_a_tradingview_bar_is_stamped_like_a_yahoo_one():
    """Midnight New York, exactly as fetch_data stamps a completed daily bar.
    The two vendors have to be indistinguishable to everything downstream --
    that is what lets research/flow.py score one rule on both."""
    import tv_history

    stamped = tv_history.to_trade_dates(pd.Series([_tv_bar("2026-09-16", 18)]))
    assert stamped.iloc[0].tz_convert(ET).hour == 0


def test_forming_tradingview_bar_is_dropped():
    """The invariant that actually broke. At 19:00 New York -- when the cron
    runs -- the session that opened an hour ago has not closed, so its bar
    must not be published as a session, and the previous one must survive."""
    import tv_history

    times = tv_history.to_trade_dates(pd.Series([
        _tv_bar("2026-09-15", 18), _tv_bar("2026-09-16", 18)]))
    frame = pd.DataFrame({"time": times, "close": [4387.5, 4309.1]})

    kept = fetch_data.drop_forming_bar(frame, _now("2026-09-16", 19))
    assert len(kept) == 1, "the bar that opened at 18:00 is still trading"
    assert kept["close"].iloc[0] == 4387.5

    done = fetch_data.drop_forming_bar(frame, _now("2026-09-17", 19))
    assert len(done) == 2, "after its own 17:00 close it is a real session"
