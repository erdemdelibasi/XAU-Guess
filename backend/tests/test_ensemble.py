"""Tests for the log-odds pooling in ensemble.py.

The property tested first is the one the whole project turns on: on an asset
that rises 55.2% of the time, a component that always says UP has NO skill,
and any scheme that scores it against a coin flip will believe it does.
research/edge.py measured exactly that trap -- the ML model beats chance at
every horizon and loses to always-long at every horizon.
"""
import math

import pytest

import ensemble


BASE = ensemble.BASE_RATE_UP


def test_always_up_component_contributes_nothing():
    """THE central invariant. A component whose UP calls are right exactly at
    the base rate knows nothing beyond "gold usually rises", which the prior
    already supplies. Scored against 0.5 it would look like a 55% forecaster."""
    record_up = (int(round(BASE * 2000)), 2000)
    evidence = ensemble.component_evidence("UP", record_up, (0, 0))
    assert evidence == pytest.approx(0.0, abs=1e-3)


def test_always_down_component_contributes_nothing():
    """The mirror case, and the one that shipped broken here once: DOWN calls
    have a no-information rate of 1 - BASE_RATE_UP, not BASE_RATE_UP.
    Shrinking both sides toward the same number gave a zero-skill component
    positive evidence and an unearned share of ensemble influence."""
    down_calls = 2000
    down_correct = int(round((1 - BASE) * down_calls))
    evidence = ensemble.component_evidence("DOWN", (0, 0), (down_correct, down_calls))
    assert evidence == pytest.approx(0.0, abs=1e-3)


def test_genuinely_skilled_component_gets_positive_evidence():
    skilled = (int(0.65 * 2000), 2000)
    assert ensemble.component_evidence("UP", skilled, (0, 0)) > 0.2


def test_below_base_rate_component_is_silenced_not_inverted():
    """Reading an anti-predictive component backwards is left off: XRP-Guess
    measured inversion inside the noise and it produces behaviour that cannot
    be explained to someone looking at the UI (all components UP, blend DOWN)."""
    assert not ensemble.ALLOW_INVERSION
    poor = (int(0.40 * 2000), 2000)
    assert ensemble.component_evidence("UP", poor, (0, 0)) == 0.0


def test_thin_evidence_is_shrunk_toward_silence():
    """Five perfect calls must not outvote a long record. SHRINK_ALPHA is what
    makes a component earn its voice rather than be handed one."""
    thin = ensemble.component_evidence("UP", (5, 5), (0, 0))
    thick = ensemble.component_evidence("UP", (int(0.65 * 2000), 2000), (0, 0))
    assert thin < thick
    assert thin < 0.25


def test_evidence_is_capped():
    absurd = ensemble.component_evidence("UP", (5000, 5000), (0, 0))
    assert abs(absurd) <= ensemble.LOGODDS_CAP + 1e-9


def test_cold_start_lands_on_the_base_rate():
    """With no history and no opinions, the honest answer for gold is the
    base rate -- not 50/50."""
    signals = {c: {"direction": "UP", "confidence": 0.0} for c in ensemble.COMPONENTS}
    result = ensemble.combine(signals)
    assert result["cold_start"] is True
    assert result["p_up"] == pytest.approx(BASE, abs=1e-6)


def test_abstaining_component_is_ignored():
    """confidence 0 means "no opinion this cycle". It must not be read as a
    vote for whatever `direction` happens to hold."""
    skilled = {"up": (int(0.70 * 2000), 2000), "down": (int(0.70 * 2000), 2000)}
    records = {"technical": skilled, "ml": skilled}

    speaking = {"technical": {"direction": "UP", "confidence": 0.3},
                "ml": {"direction": "DOWN", "confidence": 0.0}}
    alone = {"technical": {"direction": "UP", "confidence": 0.3}}
    assert (ensemble.combine(speaking, records=records)["p_up"]
            == pytest.approx(ensemble.combine(alone, records=records)["p_up"]))


def test_edge_over_base_is_zero_for_uninformative_components():
    """`confidence` is high whenever the prior is; `edge_over_base` is the
    number that answers "did the model add anything today"."""
    flat = {"up": (int(round(BASE * 2000)), 2000),
            "down": (int(round((1 - BASE) * 2000)), 2000)}
    signals = {c: {"direction": "UP", "confidence": 0.5} for c in ensemble.COMPONENTS}
    records = {c: flat for c in ensemble.COMPONENTS}
    result = ensemble.combine(signals, records=records)
    assert result["edge_over_base"] == pytest.approx(0.0, abs=1e-3)
    # ...while raw confidence stays clearly non-zero, which is exactly why
    # reading confidence alone would mislead.
    assert result["confidence"] > 0.08


def test_influence_weights_give_the_credit_to_the_skilled_component():
    records = {
        "technical": {"up": (int(0.65 * 2000), 2000), "down": (int(0.65 * 1400), 1400)},
        "ml": {"up": (int(round(BASE * 2000)), 2000),
               "down": (int(round((1 - BASE) * 2000)), 2000)},
    }
    weights = ensemble.influence_weights(records)
    assert weights["technical"] == pytest.approx(1.0, abs=1e-6)
    assert weights["ml"] == pytest.approx(0.0, abs=1e-6)


def test_damping_reduces_confidence_but_never_flips_direction():
    """CORRELATION_DAMPING is a bet-sizing correction, not a directional one --
    the components all read the same market, so a naive sum is overconfident."""
    skilled = {"up": (int(0.65 * 2000), 2000), "down": (int(0.65 * 2000), 2000)}
    signals = {c: {"direction": "DOWN", "confidence": 0.4} for c in ensemble.COMPONENTS}
    records = {c: skilled for c in ensemble.COMPONENTS}

    damped = ensemble.combine(signals, records=records)
    saved = ensemble.CORRELATION_DAMPING
    try:
        ensemble.CORRELATION_DAMPING = 1.0
        undamped = ensemble.combine(signals, records=records)
    finally:
        ensemble.CORRELATION_DAMPING = saved

    assert damped["direction"] == undamped["direction"]
    assert damped["confidence"] < undamped["confidence"]


def test_base_rate_matches_the_measured_value():
    """research/wall.py measured 55.2% over 6272 sessions. If this drifts,
    every component's measured skill is silently rebased -- retrain.py prints
    the realised rate next to it every night for the same reason."""
    assert 0.50 < BASE < 0.60
    assert ensemble.BASE_LOGODDS == pytest.approx(math.log(BASE / (1 - BASE)))


def test_cold_start_ignores_incomparable_confidence_scales():
    """The components' stated confidences are not on one scale. Measured live
    2026-09-07: news reported 0.6923 while technical/ml/macro reported 0.1006,
    0.0984 and 0.0525. A confidence-weighted cold start would hand a 7x louder
    voice to the one component that is neither calibrated nor backtestable --
    XRP-Guess's original bug exactly. Only the SIGN may count here."""
    loud = {"technical": {"direction": "UP", "confidence": 0.10},
            "news": {"direction": "DOWN", "confidence": 0.95}}
    quiet = {"technical": {"direction": "UP", "confidence": 0.10},
             "news": {"direction": "DOWN", "confidence": 0.02}}
    assert (ensemble.combine(loud)["p_up"] == pytest.approx(ensemble.combine(quiet)["p_up"]))


def test_cold_start_stays_near_the_prior():
    """With no track record the prior should dominate: even unanimity may only
    nudge the blend, because 'every component agrees' says nothing yet about
    whether any of them is any good."""
    unanimous = {c: {"direction": "DOWN", "confidence": 0.9} for c in ensemble.COMPONENTS}
    result = ensemble.combine(unanimous)
    assert abs(result["p_up"] - BASE) < 0.10


def test_cold_start_reports_edge_over_base():
    """predict.py writes this straight to the predictions row and the UI reads
    it as the headline number; a None here means the column silently never
    gets populated during the system's entire cold-start period."""
    signals = {c: {"direction": "UP", "confidence": 0.2} for c in ensemble.COMPONENTS}
    assert ensemble.combine(signals)["edge_over_base"] is not None


def test_cold_start_ignores_abstaining_components():
    speaking = {"technical": {"direction": "UP", "confidence": 0.2},
                "news": {"direction": "DOWN", "confidence": 0.0}}
    alone = {"technical": {"direction": "UP", "confidence": 0.2}}
    assert (ensemble.combine(speaking)["p_up"] == pytest.approx(ensemble.combine(alone)["p_up"]))


# --------------------------------------------------------------------------
# Per-asset base rate
# --------------------------------------------------------------------------

def test_base_rate_is_a_parameter_not_a_global():
    """Gold rises 55.7% of the time over this horizon, silver 53.9%. Both the
    prior AND the reference every component is scored against come from it, so
    using gold's number on silver biases the pool twice over -- silently, with
    no error anywhere."""
    import assets

    signals = {c: {"direction": "UP", "confidence": 0.0} for c in ensemble.COMPONENTS}
    gold = ensemble.combine(signals, base_rate=assets.GOLD.base_rate_up)
    silver = ensemble.combine(signals, base_rate=assets.SILVER.base_rate_up)
    assert gold["p_up"] == pytest.approx(assets.GOLD.base_rate_up, abs=1e-6)
    assert silver["p_up"] == pytest.approx(assets.SILVER.base_rate_up, abs=1e-6)
    assert gold["p_up"] > silver["p_up"]


def test_always_up_contributes_nothing_at_silvers_base_rate_too():
    """The central invariant has to hold for every asset, not just the one the
    module constant happens to name."""
    import assets

    rate = assets.SILVER.base_rate_up
    record_up = (int(round(rate * 2000)), 2000)
    evidence = ensemble.component_evidence("UP", record_up, (0, 0), rate)
    assert evidence == pytest.approx(0.0, abs=1e-3)

    # ...and the SAME record scored against gold's higher rate must NOT read
    # as skill either -- it should read as a deficit, i.e. silenced.
    mis_scored = ensemble.component_evidence("UP", record_up, (0, 0), assets.GOLD.base_rate_up)
    assert mis_scored == 0.0, "a below-reference component must be silenced, not credited"


def test_combine_reports_the_base_rate_it_used():
    """predict.py stores this on the prediction row, so a later change to the
    constant cannot silently rewrite how past rows should be read."""
    import assets

    signals = {c: {"direction": "UP", "confidence": 0.1} for c in ensemble.COMPONENTS}
    result = ensemble.combine(signals, base_rate=assets.SILVER.base_rate_up)
    assert result["base_rate"] == pytest.approx(assets.SILVER.base_rate_up)
