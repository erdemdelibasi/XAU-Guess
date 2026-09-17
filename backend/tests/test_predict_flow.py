"""Tests for run_asset()'s plumbing -- the wiring between components, not the
components themselves.

Everything that touches the network or Supabase is stubbed, so this runs in CI
with no secrets, like the rest of the suite. What it covers is the class of bug
that has no other guard here: a value handed to the wrong consumer. Those raise
nothing, read correctly in review, and in one case below would have taken 180
resolved rows to become visible at all.
"""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

import assets
import ensemble
import miners_signal
import ml_model
import predict


# --------------------------------------------------------------------------
# A synthetic panel and a Supabase stub
# --------------------------------------------------------------------------

def _panel(rows: int = 700) -> pd.DataFrame:
    """A frame shaped exactly like fetch_data.align_on_gold's output.

    Random-walk prices with a fixed seed: the numbers are meaningless, the
    SHAPE is the point -- enough rows to clear the 250-session warmups so
    build_features produces a fully populated final row.
    """
    rng = np.random.default_rng(7)
    time = pd.to_datetime(
        [dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=i)
         for i in range(rows)], utc=True)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, rows)))
    frame = pd.DataFrame({
        "time": time, "open": close, "high": close, "low": close,
        "close": close, "volume": np.full(rows, 1000.0),
    })
    # Both metals are present here; assets.macro_symbols_for is what removes
    # the asset's own series in production, and the feature builder simply
    # skips a column it does not find. Carrying both keeps this fixture usable
    # for gold and silver without two versions of it.
    for name, start, scale in (("dxy", 100.0, 0.004), ("us10y", 4.0, 0.02),
                               ("vix", 16.0, 0.05), ("spx", 4000.0, 0.01),
                               ("tip", 110.0, 0.003), ("ief", 95.0, 0.003),
                               ("silver", 25.0, 0.015), ("gold", 1800.0, 0.01)):
        frame[name] = start * np.exp(np.cumsum(rng.normal(0.0, scale, rows)))
    # gdx gets a DETERMINISTIC final move rather than a random one, because a
    # test that asserts on the miners signal needs a value it can name. The
    # last bar rises exactly 2%, so miners_signal must produce
    # 0.02 * GDX_SCALE = 0.5.
    gdx = 30.0 * np.exp(np.cumsum(rng.normal(0.0, 0.02, rows)))
    gdx[-1] = gdx[-2] * 1.02
    frame["gdx"] = gdx
    return frame


class _Table:
    """Just enough of the supabase-py chain for run_asset's four queries."""

    def __init__(self, name, db):
        self.name, self.db, self.inserted = name, db, False
        self.filters = {}

    def select(self, *a, **k): return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def is_(self, column, _value):
        self.filters[column] = "null"
        return self

    def order(self, *a, **k): return self
    def range(self, *a): return self
    def single(self): return self
    def update(self, _patch): return self

    def insert(self, row):
        self.db.rows.append((self.name, row))
        self.inserted = True
        return self

    def execute(self):
        if self.name == "portfolios" and not self.inserted:
            return type("R", (), {"data": {"cash_usd": 1000.0, "ounces": 0.0,
                                           "stop_loss_price": None,
                                           "resistance_price": None}})()
        if self.inserted:
            return type("R", (), {"data": [{"id": 1}]})()
        return type("R", (), {"data": []})()


class _Db:
    def __init__(self):
        self.rows = []

    def table(self, name):
        return _Table(name, self)


class _ShrinkingCalibrator:
    """Stands in for a fitted isotonic curve. Maps any raw confidence to a
    sliver of EXCESS over the call's no-information rate, so
    calibration.apply() shrinks it hard -- and that contrast is what makes
    "raw or calibrated?" observable.

    The stub used to return `base_rate + 0.01` because the curve used to
    predict P(correct). It predicts excess since 2026-09-17, and a stub still
    speaking the old scale turned a 0.01 sliver into a 0.567 landslide --
    which is why this test failed loudly on that change instead of quietly
    passing. The `base` argument is kept so the fixtures read unchanged.
    """

    def __init__(self, base):
        self.base = base

    def predict(self, xs):
        return np.asarray([0.01 for _ in xs])


@pytest.fixture
def wired(monkeypatch):
    """run_asset with every external dependency replaced. Returns a recorder."""
    seen = {"traded": [], "told": {}}

    monkeypatch.setattr(predict, "load_panel", lambda asset: _panel())
    monkeypatch.setattr(predict.fetch_data, "get_live_price",
                        lambda symbol: (100.0, symbol))
    monkeypatch.setattr(predict.news_module, "news_signal",
                        lambda asset: {"direction": "UP", "confidence": 0.0, "score": 0.0})
    def _record_trade(db, asset, strategy, prediction_id, price, trend, vol,
                      direction, confidence):
        seen["traded"].append(strategy)
        seen["told"][strategy] = {"direction": direction, "confidence": confidence}

    monkeypatch.setattr(predict.trading, "maybe_trade", _record_trade)
    monkeypatch.setattr(predict.kanal_finans_trading, "maybe_check_stop_loss",
                        lambda *a, **k: None)

    def _load_model(asset_key):
        """A model whose feature names match whatever the panel produced, so
        the staleness guard passes and no bootstrap fit is triggered."""
        model = type("M", (), {})()
        model.feature_names_in_ = np.asarray(
            ml_model.available_features(
                predict.build_features(_panel(), assets.get(asset_key).leading_drivers)),
            dtype=object)
        return model

    monkeypatch.setattr(predict.ml_model, "load_model", _load_model)
    monkeypatch.setattr(predict.ml_model, "ml_signal",
                        lambda model, features: {"direction": "UP", "confidence": 0.30,
                                                 "score": 0.30, "proba_up": 0.65})
    monkeypatch.setattr(predict.ml_model, "train_model",
                        lambda *a, **k: pytest.fail("the model guard should not have fired"))

    def _capture(asset, price, tech, macro, context):
        seen["claude_args"] = {"tech": dict(tech), "macro": dict(macro),
                               "context": dict(context), "price": price}
        return {"direction": "UP", "confidence": 0.0, "score": 0.0}

    monkeypatch.setattr(predict.claude_module, "claude_signal", _capture)
    return seen


def _prediction_row(db):
    return next(row for name, row in db.rows if name == "predictions")


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

def test_claude_sees_raw_confidences_not_calibrated_ones(wired, monkeypatch):
    """`tech` and `macro` are REBOUND to their calibrated selves a few lines
    before the Claude call, so passing those names handed the prompt
    confidences shrunk against the base rate -- "everything is neutral", which
    is a display convention rather than information about the market.

    Nothing raised and nothing looked wrong, because the first calibrator does
    not exist until calibration.MIN_RECORDS_TO_FIT (180) rows have resolved:
    this would have started misreporting roughly nine months after it shipped,
    long after anyone would connect the two.
    """
    asset = assets.GOLD
    monkeypatch.setattr(predict.calibration, "load", lambda key: {
        "technical": _ShrinkingCalibrator(asset.base_rate_up),
        "ml": _ShrinkingCalibrator(asset.base_rate_up),
        "macro": _ShrinkingCalibrator(asset.base_rate_up),
    })
    db = _Db()
    assert predict.run_asset(db, asset) == 1
    row = _prediction_row(db)

    # The calibrator really did bite on this run...
    assert row["tech_confidence"] < row["tech_confidence_raw"]
    assert row["macro_confidence"] < row["macro_confidence_raw"]
    # ...and Claude was still handed the number from before it bit.
    sent = wired["claude_args"]
    assert sent["tech"]["confidence"] == pytest.approx(row["tech_confidence_raw"])
    assert sent["macro"]["confidence"] == pytest.approx(row["macro_confidence_raw"])


def test_claude_context_carries_the_counterpart_metal(wired, monkeypatch):
    """Silver's panel holds gold's close, not silver's. A context built from a
    hardcoded "silver" key left the silver prompt with no counterpart price in
    it while still quoting the gold/silver ratio -- a ratio with neither leg
    on screen."""
    monkeypatch.setattr(predict.calibration, "load", lambda key: {})
    predict.run_asset(_Db(), assets.SILVER)
    context = wired["claude_args"]["context"]
    assert context["gold"] is not None, "silver's prompt needs gold's level"
    assert context["gold_silver_ratio"] is not None


def test_every_portfolio_runs_exactly_once_per_prediction(wired, monkeypatch):
    """predict.py iterates trading.STRATEGIES once and nothing else. It used to
    iterate ("ensemble", *STRATEGIES), which rebalanced the ensemble twice a
    day and looked like nothing from the outside."""
    monkeypatch.setattr(predict.calibration, "load", lambda key: {})
    predict.run_asset(_Db(), assets.GOLD)
    assert wired["traded"] == list(predict.trading.STRATEGIES)


def test_the_miners_portfolio_is_actually_wired_to_the_miners_signal(wired, monkeypatch):
    """The `miners` book must receive miners_signal's call, not the abstain default.

    This is the single mis-wiring that no other test in the suite can see.
    predict.py picks a portfolio's signal with

        strategy_signal.get(name, {"direction": "UP", "confidence": 0.0})

    so a strategy present in trading.STRATEGIES but MISSING from that dict
    silently falls through to a permanent abstain: no exception, no warning,
    a portfolio that simply sits at SIGNAL_BASE_EXPOSURE forever while the
    dashboard shows it as a working strategy. `test_every_portfolio_runs_
    exactly_once_per_prediction` would still pass, because the book does run.

    The fixture panel's last gdx bar rises exactly 2%, so the expected
    confidence is 0.02 * GDX_SCALE = 0.5 -- a number this test can name, which
    is what separates "the right value arrived" from "some value arrived".
    """
    db = _Db()
    predict.run_asset(db, assets.GOLD)

    told = wired["told"]["miners"]
    assert told["direction"] == "UP"
    assert told["confidence"] == pytest.approx(0.02 * miners_signal.GDX_SCALE)
    # And it must be a DIFFERENT number from the ml component's, or the
    # assertion above could be satisfied by the wrong signal arriving.
    assert told["confidence"] != wired["told"]["ml"]["confidence"]


def test_miners_abstains_rather_than_selling_when_gdx_is_missing(wired, monkeypatch):
    """A dead GDX feed must leave the book flat, never short it.

    fetch_data.get_macro_daily is fail-soft per series, so this is a real
    Tuesday, not a hypothetical. An abstain returns direction "UP" with
    confidence 0.0, which compute_target_exposure reads as "no tilt".
    """
    monkeypatch.setattr(predict, "load_panel",
                        lambda asset: _panel().drop(columns=["gdx"]))
    db = _Db()
    predict.run_asset(db, assets.GOLD)

    assert wired["told"]["miners"]["confidence"] == 0.0
    # Every other portfolio still got its own signal -- one dead series must
    # not take the run down with it.
    assert wired["told"]["ml"]["confidence"] > 0


def test_no_written_number_is_nan(wired, monkeypatch):
    """Postgres `numeric` has no NaN and PostgREST serialises one as the
    invalid JSON token `NaN`, which fails the WHOLE insert -- and
    `unique (asset, target_date)` means that session can never be written
    again. A warmup gap in a display-only column must not cost a prediction."""
    monkeypatch.setattr(predict.calibration, "load", lambda key: {})
    db = _Db()
    predict.run_asset(db, assets.GOLD)
    bad = [k for k, v in _prediction_row(db).items()
           if isinstance(v, float) and not np.isfinite(v)]
    assert not bad, f"non-finite values would lose the whole row: {bad}"


def test_a_missing_counterpart_series_does_not_lose_the_prediction(wired, monkeypatch):
    """gs_ratio needs the counterpart metal, and load_panel fetches macro
    series fail-soft -- one dead Yahoo symbol leaves the column absent. Losing
    the day's prediction over a display-only number would be the expensive
    half of a cheap outage."""
    monkeypatch.setattr(predict.calibration, "load", lambda key: {})
    thin = _panel().drop(columns=["silver", "gold"])
    monkeypatch.setattr(predict, "load_panel", lambda asset: thin)
    # Losing the counterpart also drops `counterpart_chg` from the feature set,
    # so the saved model legitimately reads as stale and predict.py retrains --
    # which is the designed response, and is stubbed here rather than run.
    monkeypatch.setattr(predict.ml_model, "load_model", lambda key: None)
    monkeypatch.setattr(predict.ml_model, "train_model",
                        lambda *a, **k: (object(), {"train_rows": 0}))
    monkeypatch.setattr(predict.ml_model, "save_model", lambda *a, **k: None)
    db = _Db()
    assert predict.run_asset(db, assets.GOLD) == 1
    row = _prediction_row(db)
    assert row["gs_ratio"] is None and row["gs_ratio_z"] is None


def test_a_second_run_for_the_same_session_is_skipped(monkeypatch):
    """Idempotency: a manual re-run overlapping the cron would double-count the
    row in every component record AND fire all nine portfolios twice for one
    signal. The check has to happen before any expensive work."""
    monkeypatch.setattr(predict, "load_panel", lambda asset: _panel())
    monkeypatch.setattr(predict.fetch_data, "get_live_price",
                        lambda s: pytest.fail("must skip before fetching a price"))

    class _Existing(_Db):
        """Answers the IDEMPOTENCY query (filtered on target_date) with a hit,
        while leaving the resolver's query (filtered on resolved_at) empty --
        the two are different questions against the same table."""

        def table(self, name):
            table = _Table(name, self)
            original = table.execute
            table.execute = lambda: (
                type("R", (), {"data": [{"id": 42}]})()
                if name == "predictions" and "target_date" in table.filters
                else original())
            return table

    assert predict.run_asset(_Existing(), assets.GOLD) == 0


def test_stored_base_rate_is_the_assets_own(wired, monkeypatch):
    """Stored per row so a later change to the constant cannot silently rewrite
    how past rows should be read."""
    monkeypatch.setattr(predict.calibration, "load", lambda key: {})
    for asset in (assets.GOLD, assets.SILVER):
        db = _Db()
        predict.run_asset(db, asset)
        row = _prediction_row(db)
        assert row["base_rate_used"] == pytest.approx(asset.base_rate_up)
        assert row["asset"] == asset.key
        assert {f"weight_{c}" for c in ensemble.COMPONENTS} <= set(row)
