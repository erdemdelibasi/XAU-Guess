"""A prediction has to be scored on the question it was asked.

predict.py runs at 23:00 UTC -- 19:00 New York -- so `price_at_prediction` is
a live quote from two hours INTO the session after the one the features came
from. Every component answers `close[t+5] > close[t]`, and assets.py's base
rates were measured that way, so resolving against the quote asked a
different question than the one the ensemble weighs the answer against.

Measured on 392 sessions of hourly history before the fix:

    quote vs that session's close   median 0.27% (gold), 0.77% (silver)
    labels that flip                       5.9%,          6.9%
    realised base rate, same rows   61.2% -> 59.4%,  58.2% -> 54.3%

The last line is why this is not a rounding argument: it is the same
"1.8 points of invisible bias" assets.py carries a per-asset base rate to
avoid, reintroduced inside the learning loop.
"""
import datetime as dt

import pandas as pd
import pytest

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


def _row(**kw):
    base = {
        "id": 1,
        "target_date": "2026-09-08",
        "price_at_prediction": 100.0,
        "predicted_direction": "UP",
        "tech_direction": "UP", "tech_confidence": 0.4,
        "ml_direction": "DOWN", "ml_confidence": 0.3,
        "macro_direction": "UP", "macro_confidence": 0.0,
        "news_direction": None, "news_confidence": None,
        "claude_direction": None, "claude_confidence": None,
    }
    base.update(kw)
    return base


def test_the_close_decides_not_the_live_quote():
    """The case the fix exists for: the metal rose from the session's CLOSE
    (99.0 -> 99.5) while the 19:00 quote it was called at (100.0) was above
    both. Close-to-close this is an UP day; from the quote it reads DOWN, and
    the component records would have learned the wrong lesson."""
    panel = _panel([99.0, 99.1, 99.2, 99.3, 99.4, 99.5])
    target = panel["time"].iloc[-1].date().isoformat()
    db = _Db([_row(target_date=target, price_at_prediction=100.0,
                   close_at_prediction=99.0)])

    assert predict.resolve_due_predictions(db, _GOLD, panel) == 1
    update = db.store["updates"][0]
    assert update["actual_direction"] == "UP"
    assert update["correct"] is True, "the UP call was right on its own question"


def test_a_row_without_the_column_still_resolves():
    """Rows written before the 2026-09-17 migration have no close to score
    against. They keep the old basis rather than going unresolvable: unlike
    the calibration columns, these rows are ALREADY counted in the component
    records, so dropping them would leave a hole in the very history the
    ensemble reads."""
    panel = _panel([99.0, 99.1, 99.2, 99.3, 99.4, 99.5])
    target = panel["time"].iloc[-1].date().isoformat()
    db = _Db([_row(target_date=target, price_at_prediction=100.0)])

    assert predict.resolve_due_predictions(db, _GOLD, panel) == 1
    update = db.store["updates"][0]
    assert update["actual_direction"] == "DOWN", "legacy rows keep the quote basis"


def test_an_abstaining_component_is_null_not_wrong():
    """Unchanged by the fix, and worth pinning beside it: confidence 0 means
    the component declined to speak. Scoring that as an error would punish
    exactly what macro_signal and news_signal are designed to do when the
    evidence is thin."""
    panel = _panel([99.0, 99.1, 99.2, 99.3, 99.4, 99.5])
    target = panel["time"].iloc[-1].date().isoformat()
    db = _Db([_row(target_date=target, close_at_prediction=99.0)])

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


def test_the_written_row_carries_the_close():
    """The column has to be in PENDING_MIGRATION_COLUMNS, or the first run
    against an un-migrated database loses the whole insert -- PostgREST
    rejects the entire row for one unknown key, and `unique(asset,
    target_date)` means that session never comes back."""
    assert "close_at_prediction" in predict.PENDING_MIGRATION_COLUMNS
