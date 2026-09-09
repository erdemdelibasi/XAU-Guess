"""Tests for the daily mail's interpretation layer.

Nothing here touches Supabase, SMTP or the network -- what is covered is the
part that decides what the mail SAYS, which is where a digest goes wrong: not
by crashing, but by quietly reporting a system as better than it is every
morning for months.

Each test pins a rule the UI already follows, so the page and the mail cannot
drift into disagreeing about whether the model is working.
"""
import datetime as dt

import pytest

import assets
import daily_report as report
import trading


def _prediction(**overrides) -> dict:
    row = {
        "asset": "gold", "target_date": "2026-09-15", "horizon_days": 5,
        "price_at_prediction": 4400.0, "price_source": "GC=F",
        "predicted_direction": "UP", "confidence": 0.1,
        "p_up": 0.60, "edge_over_base": 0.60 - 0.557,
        "base_rate_used": 0.557, "cold_start": False,
    }
    row.update(overrides)
    return row


# --------------------------------------------------------------------------
# The verdict sentence -- the same three cases frontend/app.js separates
# --------------------------------------------------------------------------

def test_a_near_zero_edge_says_the_model_is_quiet():
    """Confidence is high whenever the prior is, so a direction label alone
    overstates this system every single morning. Near-zero edge is the common
    and honest case and has to read as one."""
    text = report.verdict_sentence(
        _prediction(p_up=0.560, edge_over_base=0.003), assets.GOLD)
    assert "kayda değer bir şey söylemiyor" in text


def test_bullish_below_the_base_rate_is_flagged_as_not_a_buy_signal():
    """The case a bare "YÜKSELİŞ" misreports worst, and it is not
    hypothetical -- measured live on silver: p_up=0.514 against a 0.539 base.
    The model is bullish AND less bullish than doing nothing."""
    text = report.verdict_sentence(
        _prediction(p_up=0.514, edge_over_base=0.514 - 0.539,
                    base_rate_used=0.539), assets.SILVER)
    assert "alım sinyali değildir" in text
    assert "DAHA AZ iyimser" in text


def test_a_real_edge_is_reported_plainly():
    text = report.verdict_sentence(_prediction(), assets.GOLD)
    assert "alım sinyali değildir" not in text
    assert "kendi katkısı" in text


def test_edge_is_recomputed_from_the_rows_own_base_rate_when_missing():
    """`base_rate_used` is stored per row precisely so a later change to the
    constant cannot rewrite how an old row reads. A fallback that reached for
    the current constant instead would do exactly that."""
    row = _prediction(p_up=0.55, edge_over_base=None, base_rate_used=0.50)
    # Against the STORED 0.50 this is a +5 point edge, so it must not trip the
    # "less bullish than the base rate" branch that gold's 0.557 would.
    assert "alım sinyali değildir" not in report.verdict_sentence(row, assets.GOLD)


def test_no_prediction_yet_is_stated_not_faked():
    assert "henüz tahmin üretilmedi" in report.verdict_sentence(None, assets.GOLD)


# --------------------------------------------------------------------------
# The track-record verdict -- power before ranking
# --------------------------------------------------------------------------

def test_no_resolved_rows_explains_why_instead_of_reading_as_a_fault():
    text = report.record_verdict(0, None, None)
    assert "5 işlem günlük ufkun doğal sonucu" in text


def test_a_thin_record_refuses_to_rank():
    """This resolves ONE row per asset per trading day. "Model
    hep-YÜKSELİŞ'ten iyi" over eight rows is a coin flip wearing a
    measurement's clothes -- the same floor frontend/app.js applies."""
    text = report.record_verdict(8, 0.75, 0.50)
    assert "çok az satır" in text
    assert "iyi" not in text.split("→")[1]


def test_a_near_tie_is_not_a_ranking_even_with_enough_rows():
    text = report.record_verdict(200, 0.560, 0.550)
    assert "ayırt edilebilir değil" in text


def test_a_clear_win_and_a_clear_loss_are_both_printable():
    """The project's value is in reporting negative results honestly, so the
    losing branch has to exist and say so plainly."""
    assert "iyi." in report.record_verdict(200, 0.62, 0.55)
    assert "iyi DEĞİL." in report.record_verdict(200, 0.50, 0.56)


def test_the_mail_and_the_ui_share_one_threshold():
    """A page and a mail that disagree about whether the model works would be
    worse than either alone. The UI's constant lives in frontend/app.js as
    MIN_ROWS_FOR_VERDICT; if one moves, this is the reminder to move both."""
    assert report.MIN_ROWS_FOR_VERDICT == 60
    assert report.VERDICT_MIN_GAP == pytest.approx(0.02)


# --------------------------------------------------------------------------
# Window
# --------------------------------------------------------------------------

def test_window_is_anchored_not_relative_to_now():
    """A cron a few minutes late and a manual run at lunchtime must report the
    SAME window, or two runs on one day disagree about that day."""
    late_cron = dt.datetime(2026, 9, 9, 9, 4, tzinfo=report.TIMEZONE)
    lunchtime = dt.datetime(2026, 9, 9, 13, 30, tzinfo=report.TIMEZONE)
    assert report.window_bounds(late_cron) == report.window_bounds(lunchtime)


def test_a_run_before_the_anchor_reports_the_previous_day():
    start, end = report.window_bounds(dt.datetime(2026, 9, 9, 7, 0, tzinfo=report.TIMEZONE))
    assert end.day == 8 and start.day == 7
    assert (end - start) == dt.timedelta(days=1)


# --------------------------------------------------------------------------
# Coverage of the portfolios
# --------------------------------------------------------------------------

def test_every_portfolio_that_exists_is_reported():
    """Ten books per metal. A strategy added to trading.STRATEGIES but not to
    the mail would silently stop being watched -- and the follower, which is
    NOT in that tuple, has to be carried explicitly."""
    assert set(report.REPORT_STRATEGIES) == set(trading.STRATEGIES) | {report.FOLLOWER}
    assert len(report.REPORT_STRATEGIES) == len(set(report.REPORT_STRATEGIES))
    assert all(s in report.STRATEGY_LABELS for s in report.REPORT_STRATEGIES)


def test_buyhold_is_the_benchmark_and_is_reported_first():
    """It is the comparison the whole project reports against, so it must be
    the first row rather than one entry in a ranking."""
    assert report.BENCHMARK == "buyhold"
    assert report.REPORT_STRATEGIES[0] == "buyhold"


# --------------------------------------------------------------------------
# Turkish number formatting -- decimal comma, sign outside the percent sign
# --------------------------------------------------------------------------

def test_numbers_use_turkish_conventions():
    assert report.fmt_num(4476.6, 2) == "4.476,60"
    # Not a .xxx5 tie: those land on float representation and banker's
    # rounding rather than on anything this formatter decides.
    assert report.fmt_usd(66.2107, 3) == "$66,211"
    assert report.fmt_signed_pct(0.0123) == "+%1,23"
    assert report.fmt_signed_pct(-0.0123) == "−%1,23"


def test_an_edge_is_reported_in_points_not_percent():
    """It is the difference of two probabilities. Calling it a percentage
    invites reading it as a relative change, which is a different and much
    larger-sounding claim."""
    assert report.fmt_points(-0.052) == "−5,2 puan"
    assert report.fmt_points(0.052) == "+5,2 puan"


def test_missing_values_render_as_a_dash_not_a_crash():
    for fn in (report.fmt_usd, report.fmt_pct, report.fmt_signed_pct, report.fmt_points):
        assert fn(None) == "-"
