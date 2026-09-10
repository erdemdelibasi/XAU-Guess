"""Locks the leak guard on edge.walk_forward's pooled-training parameter.

`extra_training_frames` lets research/pooled.py train on a second metal's rows
without predicting them. That is the single easiest place in this project to
leak the future: the loop already cuts the TARGET's training set `horizon` rows
short (edge.py calls that out in a comment), and an extra frame that did not
get the same cut would hand the model another asset's already-resolved
outcomes for days the target has not lived through yet.

Nothing else guards this. The pooled result would simply look better, and the
better it looked the more likely it would be believed.

Synthetic frames throughout -- walk_forward takes an explicit feature list, so
none of indicators.py's warmups are needed and the numbers are irrelevant. The
row bookkeeping is the whole subject.
"""
import datetime as dt
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

import edge  # noqa: E402

HORIZON = 5


def _frame(rows: int, seed: int, src: int, start_day: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    time = pd.to_datetime(
        [dt.datetime(2015, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=start_day + i)
         for i in range(rows)], utc=True)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, rows)))
    return pd.DataFrame({
        "time": time,
        "close": close,
        "f1": rng.normal(0.0, 1.0, rows),
        "src": np.full(rows, src),
    })


@pytest.fixture
def small_schedule(monkeypatch):
    """A refit schedule short enough to run in a test, same shape as production."""
    monkeypatch.setattr(edge, "MIN_TRAIN_ROWS", 60)
    monkeypatch.setattr(edge, "REFIT_EVERY", 40)


def test_extra_training_frames_none_is_the_old_behaviour(small_schedule):
    """The parameter must be inert when unused.

    Every existing caller (ablation, ratio, hyperparams, tilt, vixterm...)
    relies on this: a pooling parameter that quietly changed the single-asset
    path would silently invalidate every study already recorded in
    research/README.md.
    """
    df = _frame(240, seed=1, src=0)
    plain = edge.walk_forward(df, HORIZON, features=["f1"])
    explicit_none = edge.walk_forward(df, HORIZON, features=["f1"],
                                      extra_training_frames=None)
    pd.testing.assert_frame_equal(plain, explicit_none)
    assert len(plain) > 0


def test_pooled_arm_predicts_exactly_the_same_rows(small_schedule):
    """Pooling may add training rows and must not touch predicted ones.

    This is what makes "did pooling help" a paired question. If the pooled arm
    scored a different set of days, any IC difference between the arms would be
    partly a difference of sample, and research/pooled.py's whole three-arm
    design would be measuring the wrong thing.
    """
    target = _frame(240, seed=1, src=0)
    other = _frame(240, seed=2, src=1)

    single = edge.walk_forward(target, HORIZON, features=["f1"])
    pooled = edge.walk_forward(target, HORIZON, features=["f1"],
                               extra_training_frames=[other])

    assert list(single["time"]) == list(pooled["time"])
    assert list(single["close"]) == list(pooled["close"])


def test_extra_frames_are_cut_at_the_same_moment_as_the_target(small_schedule, monkeypatch):
    """No extra row may be newer than the target's own training cutoff.

    The target's training set stops `horizon` rows behind the block being
    predicted, because the outcome of those last rows has not happened yet.
    An extra frame carried up to the prediction date instead would be telling
    the model what the other metal did during exactly the window the target is
    being asked about.
    """
    target = _frame(240, seed=1, src=0)
    other = _frame(240, seed=2, src=1)

    seen = []
    real_fit = edge._fit

    def spy(train, features, label, factory):
        seen.append(train[["time", "src"]].copy())
        return real_fit(train, features, label, factory)

    monkeypatch.setattr(edge, "_fit", spy)
    edge.walk_forward(target, HORIZON, features=["f1"], extra_training_frames=[other])

    assert seen, "walk_forward never refitted -- the schedule fixture is wrong"
    pooled_rows = 0
    for train in seen:
        target_rows = train[train["src"] == 0]
        extra_rows = train[train["src"] == 1]
        pooled_rows += len(extra_rows)
        assert extra_rows["time"].max() <= target_rows["time"].max()

    # Without this the assertion above would pass on an empty extra set, which
    # is precisely the bug a leak guard is most likely to regress into.
    assert pooled_rows > 0, "extra frame contributed no training rows at all"
