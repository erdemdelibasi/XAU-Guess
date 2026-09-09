"""Locks the fix for a real bug: `train_model()` used to fit ONE model on the
oldest TRAIN_FRACTION of the panel and both score it AND deploy it -- so the
production model permanently never trained on its own newest ~15% of
history. See ml_model.train_model's docstring for the full story.

These tests never touch the network or a real 25-year panel; a small
synthetic random-walk frame is enough to exercise the split logic itself.
"""
import datetime as dt

import numpy as np
import pandas as pd

import ml_model


def _panel(rows: int = 700) -> pd.DataFrame:
    """Same shape as fetch_data.align_on_gold's output. Random-walk prices
    with a fixed seed: the numbers are meaningless, the SHAPE (enough rows to
    clear indicators.py's warmups) is the point."""
    rng = np.random.default_rng(7)
    time = pd.to_datetime(
        [dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=i)
         for i in range(rows)], utc=True)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, rows)))
    frame = pd.DataFrame({
        "time": time, "open": close, "high": close, "low": close,
        "close": close, "volume": np.full(rows, 1000.0),
    })
    for name, start, scale in (("dxy", 100.0, 0.004), ("us10y", 4.0, 0.02),
                               ("vix", 16.0, 0.05), ("spx", 4000.0, 0.01),
                               ("tip", 110.0, 0.003), ("ief", 95.0, 0.003),
                               ("silver", 20.0, 0.015)):
        frame[name] = start * np.exp(np.cumsum(rng.normal(0.0, scale, rows)))
    return frame


def test_production_model_trains_on_every_available_row(monkeypatch):
    """The bug, stated directly: the returned/saved model must be fit on the
    FULL feature frame, not on the same 85% slice the holdout metric uses."""
    fit_row_counts = []
    real_build_estimator = ml_model.build_estimator

    def spying_build_estimator():
        estimator = real_build_estimator()
        real_fit = estimator.fit

        def spying_fit(X, y):
            fit_row_counts.append(len(X))
            return real_fit(X, y)

        estimator.fit = spying_fit
        return estimator

    monkeypatch.setattr(ml_model, "build_estimator", spying_build_estimator)

    model, metrics = ml_model.train_model(_panel())

    # Two fits happened: one disposable (holdout), one production.
    assert len(fit_row_counts) == 2
    holdout_rows, production_rows = fit_row_counts
    assert holdout_rows == metrics["train_rows"]
    assert production_rows == metrics["production_rows"]
    # The whole point: production saw strictly more rows than the holdout
    # split ever did, because it was never held back from the tail.
    assert production_rows > holdout_rows
    assert metrics["production_rows"] == metrics["train_rows"] + metrics["test_rows"]


def test_holdout_metrics_still_reported():
    """The diagnostic this replaces must keep working -- retrain.py's nightly
    console output reads these keys."""
    _, metrics = ml_model.train_model(_panel())
    assert "holdout_accuracy" in metrics
    assert "always_up_baseline" in metrics
    assert 0.0 <= metrics["holdout_accuracy"] <= 1.0
