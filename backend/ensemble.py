"""Pools the signal components into one directional call, in log-odds space.

The pooling machinery is ported from XRP-Guess's ensemble.py, which arrived at
it by fixing a real and instructive bug. Its original rule weighted each
component by `weight x stated confidence`, but the stated confidences were
never on a comparable scale -- calibration was applied to two components and
not the rest, so the uncalibrated ones kept confidences 5-10x larger.
Measured over 242 live rows, effective influence was whale 26.5%, news 22.3%,
claude 18.1%, orderbook 15.6%, ml 11.5% and technical just 6.0% -- the only
component with an edge had the smallest voice and the worst had the largest.
Log-odds pooling fixes that structurally: every component enters on ONE scale,
P(correct), and a component's demonstrated reliability simply IS its weight.
That change took the blend from 41.1% to 54.0% out of sample there.

THE CORRECTION GOLD FORCES
--------------------------
XRP over 15 minutes was a ~50/50 coin. Gold is not: it closes higher over 5
trading days 55.7% of the time, and has drifted up 11.8% a year for 25 years
(research/wall.py, research/compare.py). Silver's own rate is different again
(53.9%), which is why the number lives in assets.py rather than here. On an asset with drift, "P(this component is correct)" is
the wrong quantity to pool, because a component that says UP every single day
scores 55% and would enter the pool looking skilled. It has no skill; it has
the base rate.

research/edge.py made this concrete and it is the central finding of the
project: the ML model beats chance at every horizon (z=+4.56 at 5 days) and
loses to always-UP at every horizon. Scored against 50% it looks good.
Scored against the honest baseline it adds nothing. An ensemble that pools
against 50% would inherit exactly that illusion.

So every component's evidence here is measured as a LIKELIHOOD RATIO against
the base rate, not against a coin flip:

    evidence(said UP)   = logit(P(up | said UP))   - logit(base_rate)
    evidence(said DOWN) = logit(base_rate) - logit(P(up | said DOWN))

A component that always says UP has P(up | said UP) = base_rate, so its
evidence is exactly zero -- which is the truth about it. The prior itself
enters once, as logit(base_rate), so the blend starts from "gold usually
rises" and components only move it from there.

This needs the record kept SEPARATELY for a component's UP and DOWN calls
(four counters, not two). That is why `model_state` carries up_calls /
up_correct / down_calls / down_correct rather than one accuracy figure.
"""
from __future__ import annotations

import math

import assets

COMPONENTS = ["technical", "ml", "macro", "news", "claude"]
DEFAULT_WEIGHTS = {"technical": 0.25, "ml": 0.25, "macro": 0.25, "news": 0.10, "claude": 0.15}

# predictions-table column prefix per component. "technical" is shortened to
# "tech" there to keep column names compact.
COLUMN_PREFIX = {"technical": "tech", "ml": "ml", "macro": "macro",
                 "news": "news", "claude": "claude"}

# P(the metal closes higher over HORIZON_DAYS): the prior the pool starts
# from and the reference every component's evidence is measured against.
#
# Sourced from assets.py, which holds the per-asset measured value (gold
# 0.557, silver 0.539 -- research/compare.py). This module-level name is
# gold's, kept for the single-asset call path and the tests; anything
# predicting silver must pass that asset's rate through explicitly, because
# applying gold's number to silver rebases silver's entire scoreboard.
#
# It is a constant rather than a rolling estimate on purpose: computed from a
# recent window it would drift with whatever the last year did, and a prior
# that tracks recent returns is a momentum signal wearing a prior's clothes.
# retrain.py prints the realised rate next to it so a genuine regime change
# would be visible rather than silently absorbed.
BASE_RATE_UP = assets.GOLD.base_rate_up

# Pseudo-observations pulling a thin record toward the base rate, so a
# component with little history is automatically silent and earns a voice
# only as evidence accumulates. Higher than XRP-Guess's 30 because this
# system resolves ONE prediction per trading day rather than 96 -- 30
# pseudo-observations would be overwhelmed within six weeks here.
SHRINK_ALPHA = 60.0

# Per-component ceiling on evidence, so no single record can capture the pool.
LOGODDS_CAP = 1.0

# The components are not conditionally independent -- technical, ml and macro
# all read the same market -- so a naive Bayes sum double-counts evidence and
# comes out overconfident. XRP-Guess measured its undamped pool claiming 58.0%
# while delivering 55.6%, and 0.7 bringing claim and delivery into line. The
# value is inherited rather than re-measured: this project has no live history
# yet. Re-measure it once a few hundred rows have resolved -- damping changes
# only confidence magnitude (and therefore position size), never direction.
CORRELATION_DAMPING = 0.7

# A component measured worse than the base rate carries information read
# backwards. Exploiting that is left OFF, following XRP-Guess, where inverting
# scored 55.8% against 55.4% for simply silencing such a component -- inside
# the noise at that sample size, unproven, and it produces behaviour that
# cannot be defended to someone looking at the UI ("every component says UP,
# the blend says DOWN"). Revisit only with a few hundred resolved rows.
ALLOW_INVERSION = False


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


BASE_LOGODDS = _logit(BASE_RATE_UP)


def directional_reliability(correct: int, total: int, no_information_rate: float,
                            shrink_alpha: float | None = None) -> float:  # noqa: D401
    """P(the outcome matched | this component made this call), shrunk toward
    `no_information_rate` by `shrink_alpha` pseudo-observations (module
    constant SHRINK_ALPHA, read at CALL time, when None -- the parameter
    exists so research/ensemble_weights.py can score a candidate value
    through this exact function rather than a copy).

    Shrinking toward the no-information rate rather than 0.5 is what makes
    thin evidence land on "says nothing" instead of on "coin flip" -- on an
    asset that rises 55% of the time those are different statements.

    The no-information rate is NOT the same on both sides, and getting that
    wrong is subtle enough to have shipped here once already. For an UP call
    it is BASE_RATE_UP (0.557 for gold): a component that always says UP is
    right that often by construction. For a DOWN call it is 1 - BASE_RATE_UP
    (0.443), because a component that always says DOWN is right only when the
    metal falls. Shrinking both toward 0.557 gave a component with zero skill on
    its DOWN calls a small POSITIVE evidence score (+0.024) and a 4.9% share
    of ensemble influence it had not earned.
    """
    if shrink_alpha is None:
        shrink_alpha = SHRINK_ALPHA
    return (correct + shrink_alpha * no_information_rate) / (total + shrink_alpha)


def component_evidence(direction: str, up_record: tuple[int, int],
                       down_record: tuple[int, int],
                       base_rate: float = BASE_RATE_UP,
                       shrink_alpha: float | None = None) -> float:
    """Log-odds this component's current call is worth, above the base rate.

    `up_record` is (times it said UP and the metal rose, times it said UP).
    `down_record` is (times it said DOWN and it fell, times it said DOWN).
    Returns 0.0 when the call carries no more information than the prior --
    the correct reading for a component that just tracks the drift.

    `base_rate` is THIS ASSET's rate (gold 0.557, silver 0.539). Passing the
    wrong one does not raise; it just rebases every component's measured
    skill by the difference, which for these two metals is 1.8 points of
    pure, invisible bias.
    """
    base_logodds = _logit(base_rate)
    if direction == "UP":
        correct, total = up_record
        if total <= 0:
            return 0.0
        p_up_given_call = directional_reliability(correct, total, base_rate, shrink_alpha)
        evidence = _logit(p_up_given_call) - base_logodds
    else:
        correct, total = down_record
        if total <= 0:
            return 0.0
        # For a DOWN call, `correct` counts times the metal actually fell, so
        # the no-information rate is 1 - base_rate and P(up | said DOWN) is
        # one minus the resulting reliability.
        p_down_given_call = directional_reliability(correct, total, 1.0 - base_rate, shrink_alpha)
        evidence = base_logodds - _logit(1.0 - p_down_given_call)

    evidence = max(-LOGODDS_CAP, min(LOGODDS_CAP, evidence))
    if not ALLOW_INVERSION:
        # Negative evidence means the component is anti-predictive on this
        # side. Silence it rather than read it backwards -- see ALLOW_INVERSION.
        evidence = max(evidence, 0.0)
    return evidence if direction == "UP" else -evidence


# How far the components may move the cold-start blend off the base rate, in
# log-odds, when every component votes the same way. Small on purpose: with
# no track record the honest position is "we don't know", so the prior should
# dominate until real evidence exists.
COLD_START_STRENGTH = 0.30


def _cold_start(signals: dict[str, dict], weights: dict[str, float],
                base_rate: float = BASE_RATE_UP) -> dict:
    """Direction-only weighted vote, used before any component has a record.

    Counts each component's SIGN, not its stated confidence, and that is the
    whole point. The confidences are not on a comparable scale and never were:
    measured live on 2026-09-07, `news` reported 0.6923 while `technical`,
    `ml` and `macro` reported 0.1006, 0.0984 and 0.0525. A confidence-weighted
    vote hands a 7x louder voice to the one component that is neither
    calibrated nor backtestable -- which is precisely the bug XRP-Guess found
    in its own ensemble (effective influence: whale 26.5%, technical 6.0%,
    with technical the only component that had an edge).

    combine() avoids this by pooling measured records instead. This path has
    no records by definition, so it falls back to the one thing that IS
    comparable across components: which way each of them points.

    Still anchored on the base rate -- with no history the honest default for
    gold is a mild UP lean, not 50/50.
    """
    vote = 0.0
    total_weight = 0.0
    for name, signal in signals.items():
        # confidence 0 means the component abstained this cycle; a sign-based
        # vote would otherwise read its placeholder direction as an opinion.
        if signal["confidence"] <= 0:
            continue
        w = weights.get(name, 0.0)
        vote += w * (1.0 if signal["direction"] == "UP" else -1.0)
        total_weight += w

    if total_weight > 0:
        vote /= total_weight  # -1..1 regardless of how many components spoke

    logodds = _logit(base_rate) + COLD_START_STRENGTH * vote
    p_up = 1.0 / (1.0 + math.exp(-logodds))
    score = 2.0 * p_up - 1.0
    return {"direction": "UP" if score >= 0 else "DOWN", "confidence": abs(score),
            "score": score, "p_up": p_up, "edge_over_base": p_up - base_rate,
            "base_rate": base_rate, "weights_used": dict(weights), "cold_start": True}


def combine(signals: dict[str, dict], weights: dict[str, float] | None = None,
            records: dict[str, dict] | None = None,
            base_rate: float = BASE_RATE_UP,
            correlation_damping: float | None = None,
            shrink_alpha: float | None = None) -> dict:
    """Pool the components into one call.

    `records` maps a component to
    {"up": (correct, total), "down": (correct, total)} from its live history.
    Without it (cold start) this falls back to a base-rate-anchored vote.

    `base_rate` must be THIS ASSET's measured rate -- assets.Asset.
    base_rate_up. It is the prior the pool starts from AND the reference every
    component's evidence is measured against, so a gold number used on silver
    biases both at once.

    `correlation_damping` and `shrink_alpha` default to the module constants
    (read at CALL time, when None). They are parameters only so
    research/ensemble_weights.py can score a candidate pair through this
    exact function -- production never passes them explicitly.
    """
    if correlation_damping is None:
        correlation_damping = CORRELATION_DAMPING
    weights = weights or DEFAULT_WEIGHTS
    usable = {c: r for c, r in (records or {}).items()
              if c in signals and (r.get("up", (0, 0))[1] > 0 or r.get("down", (0, 0))[1] > 0)}
    if not usable:
        return _cold_start(signals, weights, base_rate)

    evidence_total = 0.0
    for name, signal in signals.items():
        if name not in usable:
            continue
        if signal["confidence"] <= 0:
            continue  # abstaining this cycle -- contributes nothing
        record = usable[name]
        evidence_total += component_evidence(
            signal["direction"], record.get("up", (0, 0)), record.get("down", (0, 0)),
            base_rate, shrink_alpha,
        )

    logodds = _logit(base_rate) + evidence_total * correlation_damping
    p_up = 1.0 / (1.0 + math.exp(-logodds))
    # Signed edge in -1..1, which is what indicators.estimate_pct_change and
    # trading.compute_target_exposure both expect.
    score = 2.0 * p_up - 1.0

    return {
        "direction": "UP" if score >= 0 else "DOWN",
        "confidence": abs(score),
        "score": score,
        "p_up": p_up,
        # How far the components moved the call away from simply knowing the
        # base rate. This, not `confidence`, is the number that answers "did
        # the model add anything today" -- confidence is high whenever the
        # prior is, all on its own.
        "edge_over_base": p_up - base_rate,
        "base_rate": base_rate,
        "weights_used": dict(weights),
        "cold_start": False,
    }


def influence_weights(records: dict[str, dict], base_rate: float = BASE_RATE_UP) -> dict:
    """Each component's share of the evidence actually in play, for display
    only -- combine() pools the records directly and never consumes these.

    A component that has not beaten the base rate shows 0%, which is the
    honest reading: it is not influencing the call.

    The exception is a total cold start. When NO component has evidence there
    is no share to compute, so DEFAULT_WEIGHTS comes back -- and those are
    genuinely what _cold_start() weights its direction vote by, so the number
    is true. It is just not a measurement, which is why predict.py stores
    `cold_start` alongside it and the UI says so instead of printing "25%"
    under a caption about measured skill.
    """
    signed: dict[str, float] = {}
    for component in COMPONENTS:
        record = records.get(component)
        if not record:
            continue
        strength = 0.0
        for direction, key in (("UP", "up"), ("DOWN", "down")):
            counts = record.get(key, (0, 0))
            if counts[1] > 0:
                strength = max(strength, abs(component_evidence(
                    direction, record.get("up", (0, 0)), record.get("down", (0, 0)), base_rate)))
        if strength > 0:
            signed[component] = strength
    total = sum(signed.values())
    if not signed or total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {c: signed.get(c, 0.0) / total for c in COMPONENTS}
