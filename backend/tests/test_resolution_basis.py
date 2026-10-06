"""A prediction has to be scored on the question it was asked.

predict.py runs at 23:00 UTC -- 19:00 New York -- so `price_at_prediction` is
a live quote from two hours INTO the session after the one the features came
from. Every component answers `close[t+5] > close[t]`, and assets.py's base
rates were measured that way, so resolving against the quote asked a
different question than the one the ensemble weighs the answer against.

Measured on 392 sessions of hourly history before the 2026-09-17 fix:

    quote vs that session's close   median 0.27% (gold), 0.77% (silver)
    labels that flip                       5.9%,          6.9%
    realised base rate, same rows   61.2% -> 59.4%,  58.2% -> 54.3%

And measured again on 2026-10-06, because that fix stored the panel's last
close and the panel's last close WAS the live quote: Yahoo keeps folding the
18:00 reopen's trades into the newest daily bar until it settles overnight.
All 24 rows written with `close_at_prediction` missed their session's settled
close (median 0.39% at 23:00 UTC, 0.57% at the late runs, none within 0.01%).
So both ends of the score now come from settled bars, read at resolution
time, and the newest bar is never one of them.
"""
import pandas as pd

import predict


def _panel(closes, start="2026-09-01"):
    """A minimal panel: the resolver only reads `time` and `close`."""
    days = pd.bdate_range(start, periods=len(closes), tz="UTC")
    return pd.DataFrame({"time": days, "close": [float(c) for c in closes]})


class _Table:
    def __init__(self, store):
        self.store = store
        self._filters = {}

    def select(self, *_a, **_k):
        return self

    def eq(self, key, value):
        self._filters[key] = value
        return self

    def is_(self, *_a):
        return self

    def update(self, values):
        self._pending = values
        return self

    def execute(self):
        if hasattr(self, "_pending"):
            self.store["updates"].append({**self._pending, "id": self._filters.get("id")})
            del self._pending
            return type("R", (), {"data": []})()
        return type("R", (), {"data": self.store["rows"]})()


class _Db:
    def __init__(self, rows):
        self.store = {"rows": rows, "updates": []}

    def table(self, _name):
        return _Table(self.store)


# 2026-09-01 is a Tuesday; 23:00 UTC is 19:00 New York, two hours after the
# 09-01 session closed -- the moment the cron writes the row.
WRITTEN = "2026-09-01T23:00:00+00:00"
SESSIONS = ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04",
            "2026-09-07", "2026-09-08", "2026-09-09"]


def _row(**kw):
    base = {
        "id": 1,
        "created_at": WRITTEN,
        "target_date": "2026-09-08",
        "price_at_prediction": 100.0,
        "predicted_direction": "UP",
        "tech_direction": "UP", "tech_confidence": 0.4,
        "ml_direction": "DOWN", "ml_confidence": 0.3,
        "macro_direction": "UP", "macro_confidence": 0.0,
        "news_direction": None, "news_confidence": None,
    }
    base.update(kw)
    return base


def test_the_settled_close_decides_not_the_live_quote():
    """The case both fixes exist for: the metal rose from the session's
    settled close (99.0 -> 99.5) while the 19:00 quote -- which is ALSO what
    the panel's last close read when the row was written, so it is what
    `close_at_prediction` holds -- was above both. Settled-to-settled this is
    an UP move; from either stored value it reads DOWN."""
    panel = _panel([99.0, 99.1, 99.2, 99.3, 99.4, 99.5, 99.6])
    db = _Db([_row(price_at_prediction=100.0, close_at_prediction=100.0)])

    assert predict.resolve_due_predictions(db, _GOLD, panel) == 1
    update = db.store["updates"][0]
    assert update["price_at_resolution"] == 99.5
    assert update["actual_direction"] == "UP"
    assert update["correct"] is True, "the UP call was right on its own question"


def test_the_newest_bar_is_never_a_resolution_price():
    """Measured 2026-10-05: at 23:01 UTC gold's 10-05 bar read 4168.50, the
    live quote; settled, it was 4156.80. A target that lands on the newest
    bar waits one session, until a successor proves the bar final."""
    panel = _panel([99.0, 99.1, 99.2, 99.3, 99.4, 99.5])
    db = _Db([_row()])
    assert predict.resolve_due_predictions(db, _GOLD, panel) == 0
    assert db.store["updates"] == []

    panel = _panel([99.0, 99.1, 99.2, 99.3, 99.4, 99.5, 99.6])
    assert predict.resolve_due_predictions(db, _GOLD, panel) == 1


def test_a_late_row_is_scored_from_the_session_closed_when_it_was_written():
    """The 2026-10-02 01:57 UTC run (21:57 New York) took a four-hour-old
    10-02 bar for a closed session and wrote a target one day too late. The
    basis must come from when the row was written -- the 10-01 close -- not
    from the row's own date arithmetic."""
    panel = _panel([99.0, 99.1, 99.2, 99.3, 99.4, 99.5, 99.6])
    db = _Db([_row(created_at="2026-09-02T01:57:00+00:00", target_date="2026-09-08",
                   close_at_prediction=99.15)])

    predict.resolve_due_predictions(db, _GOLD, panel)
    update = db.store["updates"][0]
    # 09-01 21:57 New York: the last closed session is 09-01 (99.0), not 09-02.
    _, base, match = predict.score_row(db.store["rows"][0], SESSIONS_AS_DATES, CLOSES)
    assert str(base) == "2026-09-01" and str(match) == "2026-09-08"
    assert update["actual_direction"] == "UP"


def test_a_row_from_before_the_column_is_scored_the_same_way():
    """Rows written before the 2026-09-17 migration have no stored close, and
    they no longer need one: the basis comes from `created_at` and the panel,
    so old and new rows answer one question instead of two."""
    panel = _panel([99.0, 99.1, 99.2, 99.3, 99.4, 99.5, 99.6])
    db = _Db([_row(price_at_prediction=100.0)])

    assert predict.resolve_due_predictions(db, _GOLD, panel) == 1
    assert db.store["updates"][0]["actual_direction"] == "UP"


def test_without_a_write_time_the_stored_close_is_the_fallback():
    row = _row(close_at_prediction=99.6, price_at_prediction=100.0)
    del row["created_at"]
    update, base, _ = predict.score_row(row, SESSIONS_AS_DATES, CLOSES)
    assert base is None
    assert update["actual_direction"] == "DOWN", "99.5 is below the stored 99.6"


def test_an_abstaining_component_is_null_not_wrong():
    """Unchanged by either fix, and worth pinning beside them: confidence 0
    means the component declined to speak. Scoring that as an error would
    punish exactly what macro_signal and news_signal are designed to do when
    the evidence is thin."""
    panel = _panel([99.0, 99.1, 99.2, 99.3, 99.4, 99.5, 99.6])
    db = _Db([_row()])

    predict.resolve_due_predictions(db, _GOLD, panel)
    update = db.store["updates"][0]
    assert update["tech_correct"] is True      # said UP, it rose
    assert update["ml_correct"] is False       # said DOWN, it rose
    assert update["macro_correct"] is None     # abstained
    assert update["news_correct"] is None      # never spoke at all


def test_a_target_that_has_not_closed_is_left_pending():
    """The panel ends before the target session, so there is nothing to score
    yet -- and a row scored early would be scored against the wrong horizon,
    which is the bug XRP-Guess shipped and measured at 33.5% of its rows."""
    panel = _panel([99.0, 99.1, 99.2])
    db = _Db([_row(target_date="2026-12-31", close_at_prediction=99.0)])

    assert predict.resolve_due_predictions(db, _GOLD, panel) == 0
    assert db.store["updates"] == []


class _GoldStub:
    key = "gold"
    label = "Altın"


_GOLD = _GoldStub()
_FULL = _panel([99.0, 99.1, 99.2, 99.3, 99.4, 99.5, 99.6])
SESSIONS_AS_DATES = _FULL["time"].dt.date.tolist()
CLOSES = dict(zip(SESSIONS_AS_DATES, _FULL["close"]))
assert [str(d) for d in SESSIONS_AS_DATES] == SESSIONS


def test_the_written_row_carries_the_close():
    """The column has to be in PENDING_MIGRATION_COLUMNS, or the first run
    against an un-migrated database loses the whole insert -- PostgREST
    rejects the entire row for one unknown key, and `unique(asset,
    target_date)` means that session never comes back."""
    assert "close_at_prediction" in predict.PENDING_MIGRATION_COLUMNS
