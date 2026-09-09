"""Gradient-boosted classifier: will gold close higher `HORIZON_DAYS` from now?

Trains on Yahoo's own GC=F history plus the macro panel, so there is no
cold-start dependency on this project's own prediction log.

Two things here differ from XRP-Guess's equivalent and both matter.

**The label is not "next bar up".** It is "up over HORIZON_DAYS", because
research/wall.py measured that a one-day call on gold has to be right 56.2%
of the time just to pay ETF-level costs, while a five-day call needs 52.7%
and a twenty-day call 51.3%. The horizon is a parameter of the problem, not
an incidental consequence of how often the cron happens to run -- which is
exactly the mistake that trapped XRP-Guess at 15 minutes.

**Every feature is scale-free.** Gold went from $270 to $4400 across this
panel, so any feature carrying a price level would let the model split on
"which decade is this" and score brilliantly in-sample while learning
nothing. Trend state is therefore expressed as ratios (close/sma200 - 1),
never as levels -- see indicators.py.

The model trains on the full available history rather than a recent slice.
Restricting it to the post-2008 regime is a reasonable-sounding idea that
has NOT been measured, so it is not done: research/edge.py's walk-forward is
what would have to settle it, and until it does, a shorter window is just a
smaller sample.
"""
from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

import assets as assets_module
from indicators import LEADING_DRIVERS, build_features

MODELS_DIR = Path(__file__).parent / "models"


def model_path(asset_key: str = "gold") -> Path:
    """Each asset gets its own file. They are NOT interchangeable: silver's
    model is fitted on a different driver set (no `ief`) and therefore a
    different feature count, so loading one for the other would either raise
    or -- worse, if the counts happened to match -- score silver against
    gold's learned relationships."""
    return MODELS_DIR / assets_module.get(asset_key).model_filename

# Prediction horizon in trading days. See research/wall.py: the break-even
# accuracy wall falls steeply from 1d to 5d and then flattens, so 5 buys most
# of the available relief while still producing a decision often enough to be
# a live system rather than a buy-and-hold with extra steps.
HORIZON_DAYS = 5

FEATURE_COLUMNS = [
    # price-derived
    "rsi14", "macd_hist", "bb_pct",
    "ema9_21", "px_sma200", "px_ema50",
    "return_1d", "return_5d", "return_20d", "return_60d",
    "vol_20d", "vol_ratio", "donchian_pct",
    # macro: the measured leads (research/drivers.py, research/lags.py)
    "tip_chg", "tip_chg5", "ief_chg", "ief_chg5", "vix_chg", "vix_chg5",
    # macro: regime context -- weak on their own, useful as split conditions
    "dxy_chg", "dxy_chg5", "us10y_chg", "us10y_chg5", "counterpart_chg", "spx_chg",
    "gs_ratio_z", "real_yield_chg",
]

TRAIN_FRACTION = 0.85


def build_estimator() -> HistGradientBoostingClassifier:
    """The one place the estimator is configured.

    research/edge.py imports this rather than defining its own, so a
    hyperparameter can never be changed in production while research keeps
    measuring the old one -- the same reason trading.compute_rebalance() is
    shared between the live path and the backtest.

    Histogram-based, not the classic GradientBoostingClassifier: measured on
    this panel, an identical-capacity fit takes 0.66s here against 12.6s
    there (5000 rows x 27 features). The walk-forward in research/edge.py
    refits ~80 times per horizon, so that difference is ~30 minutes versus
    ~1 minute -- which is the difference between a study that gets re-run
    whenever an assumption changes and one that quietly never does.
    """
    return HistGradientBoostingClassifier(
        max_iter=200,
        max_depth=3,
        learning_rate=0.03,
        # Gold's daily direction is close to noise, so the danger is a model
        # confidently memorising it. Both of these push the other way.
        min_samples_leaf=40,
        l2_regularization=1.0,
        early_stopping=False,  # deterministic across refits; the walk-forward
                               # is the validation, an internal split would
                               # just shrink the training set unpredictably
        random_state=0,
    )


def build_feature_frame(panel: pd.DataFrame, horizon: int = HORIZON_DAYS,
                        drivers: tuple[str, ...] = LEADING_DRIVERS) -> pd.DataFrame:
    """Features + a forward-looking label, with warmup and unlabelable rows dropped.

    The label uses shift(-horizon), so the final `horizon` rows have no known
    outcome. np.where makes those explicitly NaN rather than letting the
    comparison quietly produce False: in pandas `NaN > x` is False, not NaN,
    so without this the last rows would each receive a fabricated DOWN label
    and the model would train on invented outcomes. (XRP-Guess hit exactly
    this bug and the fix is the same shape.)
    """
    df = build_features(panel, drivers)
    future_close = df["close"].shift(-horizon)
    df["label_up"] = np.where(
        future_close.notna(), (future_close > df["close"]).astype(float), np.nan
    )
    available = [c for c in FEATURE_COLUMNS if c in df.columns]
    return df.dropna(subset=available + ["label_up"]).reset_index(drop=True)


def available_features(df: pd.DataFrame) -> list[str]:
    """FEATURE_COLUMNS actually present -- a macro series can be missing."""
    return [c for c in FEATURE_COLUMNS if c in df.columns]


def train_model(panel: pd.DataFrame, horizon: int = HORIZON_DAYS,
                drivers: tuple[str, ...] = LEADING_DRIVERS) -> tuple[HistGradientBoostingClassifier, dict]:
    """Fits the production classifier on the FULL panel, plus a disposable
    holdout fit purely to print a smoke-test metric.

    These used to be the same fit: one model, trained on the first
    TRAIN_FRACTION of the panel, both scored on the last slice AND saved as
    the live model. That meant the deployed model permanently never saw its
    own most recent ~15% of history -- for a 25-year panel, the newest 3-4
    years, every single night, forever. The real out-of-sample validation
    for this model lives in research/edge.py's walk-forward (refit on an
    expanding window, scored strictly out of sample); a single static 85/15
    split here was a *weaker* second validation that was quietly winning by
    also controlling what got deployed.

    So the two jobs are split. `holdout_model` is fit on the older
    TRAIN_FRACTION and scored on the newer slice purely to print
    `holdout_accuracy` -- a cheap smoke test retrain.py can eyeball for a
    sudden regression, not the real measurement. The returned/saved `model`
    is a separate fit on every row available. Fitting twice costs nothing
    here (~0.66s each, see build_estimator's docstring).
    """
    df = build_feature_frame(panel, horizon=horizon, drivers=drivers)
    features = available_features(df)
    if len(df) < 300:
        raise ValueError(f"Not enough labelled rows to train: {len(df)}")

    split = int(len(df) * TRAIN_FRACTION)
    train_df, test_df = df.iloc[:split], df.iloc[split:]

    metrics = {
        "train_rows": len(train_df),
        "test_rows": len(test_df),
        "features": len(features),
        "horizon_days": horizon,
    }
    if len(test_df) > 0:
        holdout_model = build_estimator()
        holdout_model.fit(train_df[features], train_df["label_up"])
        preds = holdout_model.predict(test_df[features])
        metrics["holdout_accuracy"] = float((preds == test_df["label_up"]).mean())
        # The bar a directional model has to clear is not 50% -- both metals
        # rise more often than they fall, so "always UP" is a free baseline.
        # Reporting accuracy without it would flatter every model here.
        metrics["always_up_baseline"] = float(test_df["label_up"].mean())

    model = build_estimator()
    model.fit(df[features], df["label_up"])
    metrics["production_rows"] = len(df)
    return model, metrics


def save_model(model: HistGradientBoostingClassifier, asset_key: str = "gold") -> None:
    path = model_path(asset_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)


def load_model(asset_key: str = "gold") -> HistGradientBoostingClassifier | None:
    path = model_path(asset_key)
    if not path.exists():
        return None
    return joblib.load(path)


def ml_signal(model: HistGradientBoostingClassifier, features: pd.DataFrame) -> dict:
    """Directional call for the latest row of `features`."""
    last = features.iloc[-1]
    columns = available_features(features)
    values = last[columns]
    if values.isna().any():
        return {"direction": "UP", "confidence": 0.0, "score": 0.0}

    x = pd.DataFrame([values.to_numpy()], columns=columns)
    proba_up = float(model.predict_proba(x)[0][1])
    score = float(np.clip((proba_up - 0.5) * 2, -1, 1))
    return {
        "direction": "UP" if proba_up >= 0.5 else "DOWN",
        "confidence": abs(proba_up - 0.5) * 2,
        "score": score,
        "proba_up": proba_up,
    }
