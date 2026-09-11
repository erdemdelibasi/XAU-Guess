"""Locks the contract between export_backtest.py and the chart that draws it.

The frontend reads frontend/data/backtest.json across a process, a language
and a deploy boundary. Nothing connects the two at runtime: rename a field in
the exporter and the page does not crash, it silently renders an empty card
under a heading that promises 19.5 years of measurement -- which is worse than
the missing chart, because the caption still makes the claim.

That is the same failure shape as
test_track_etf.test_every_tracked_book_is_reachable_on_the_page, and it gets
the same treatment: the mirrors are asserted here rather than trusted.

Nothing here needs the network. The committed payload is the fixture, which
is the point -- these assertions are about the file that actually ships.
"""
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import export_backtest  # noqa: E402
import trading  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PAYLOAD_PATH = os.path.join(ROOT, "frontend", "data", "backtest.json")
APP_JS = os.path.join(ROOT, "frontend", "app.js")
CHART_JS = os.path.join(ROOT, "frontend", "chart.js")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


@pytest.fixture(scope="module")
def payload():
    if not os.path.exists(PAYLOAD_PATH):
        pytest.skip("backtest.json not exported yet -- run python export_backtest.py")
    return json.loads(read(PAYLOAD_PATH))


# ---------------------------------------------------------------------------
# The sampling grid
# ---------------------------------------------------------------------------

def test_sampling_always_keeps_the_last_session():
    """The card prints the final equity value out of the sampled array.

    Without the explicit tail, a panel whose length is not a multiple of
    SAMPLE_EVERY ends on whatever the grid last happened to land on -- up to
    a week short. The number would be plausible, close, and wrong, and it is
    the one number in the card a reader is most likely to quote.
    """
    for n in range(1, 40):
        assert export_backtest.sample_indices(n)[-1] == n - 1


def test_dates_and_equity_share_one_sampling_grid(payload):
    """x and y sampled apart is a curve shifted by up to a week, drawn without
    complaint. One index list is built and reused; this checks it stayed that
    way."""
    for key, asset in payload["assets"].items():
        for name, strategy in asset["strategies"].items():
            assert len(strategy["equity"]) == len(asset["dates"]), \
                f"{key}/{name}: {len(strategy['equity'])} points against {len(asset['dates'])} dates"


# ---------------------------------------------------------------------------
# The cross-language mirrors
# ---------------------------------------------------------------------------

def test_schema_version_matches_the_frontend(payload):
    """app.js refuses a payload whose schema it does not know. Bumping one
    side only means the card hides itself on every load -- quietly, because
    hiding is the correct behaviour for a payload it cannot read."""
    declared = re.search(r"const BACKTEST_SCHEMA = (\d+);", read(APP_JS))
    assert declared, "BACKTEST_SCHEMA not found in app.js"
    assert int(declared.group(1)) == export_backtest.SCHEMA == payload["schema"]


def test_every_exported_strategy_is_drawable(payload):
    """A strategy in the payload that the chart has no colour for would be
    drawn in the benchmark's muted grey -- indistinguishable from the
    reference line it is supposed to be measured against."""
    colours = set(re.findall(r"^\s{2}(\w+):\s*\"#", read(CHART_JS), re.M))
    for key, asset in payload["assets"].items():
        for name in asset["strategies"]:
            if name == "buyhold":
                continue  # deliberately not a categorical slot
            assert name in colours, f"{key}/{name} has no series colour in chart.js"


def test_every_drawable_strategy_is_listed_in_the_legend_order():
    """chart.js's palette was validated pair-by-pair in BACKTEST_SERIES' order.

    A strategy with a colour but no place in that list gets a hue and never a
    chip, so it can never be turned on -- and the adjacency the colorblind
    check scored would no longer be the adjacency on screen.
    """
    colours = set(re.findall(r"^\s{2}(\w+):\s*\"#", read(CHART_JS), re.M))
    listed = re.search(r"const BACKTEST_SERIES = \[(.*?)\];", read(APP_JS), re.S)
    assert listed
    order = set(re.findall(r'"(\w+)"', listed.group(1)))
    assert colours == order, f"colours {colours ^ order} are in one list and not the other"


def test_short_labels_exist_for_every_drawn_series():
    """The direct label on the plot falls back to the raw key without one --
    a line labelled "voltarget" on a page that is otherwise entirely Turkish."""
    shorts = re.search(r"const BACKTEST_SHORT = \{(.*?)\};", read(APP_JS), re.S)
    assert shorts
    named = set(re.findall(r"(\w+):", shorts.group(1)))
    listed = re.search(r"const BACKTEST_SERIES = \[(.*?)\];", read(APP_JS), re.S)
    assert set(re.findall(r'"(\w+)"', listed.group(1))) | {"buyhold"} <= named


# ---------------------------------------------------------------------------
# What the card is allowed to claim
# ---------------------------------------------------------------------------

def test_benchmark_is_present_for_every_asset(payload):
    """Every comparison on the card is against buy-and-hold. Without the row
    the summary line has no reference and silently reports "HİÇBİRİ"."""
    for key, asset in payload["assets"].items():
        assert "buyhold" in asset["strategies"], f"{key} has no benchmark"


def test_untestable_strategies_are_excluded_and_say_so(payload):
    """`claude` and `kanalfinans` cannot be backtested at all.

    They must be absent AND named in `excluded`: a card that quietly drops two
    of the eleven portfolios shown further up the page, with no note, reads as
    a complete scoreboard.
    """
    for key, asset in payload["assets"].items():
        assert "claude" not in asset["strategies"]
        assert "kanalfinans" not in asset["strategies"]
    assert {"claude", "kanalfinans"} <= set(payload["excluded"])

    exported = set(next(iter(payload["assets"].values()))["strategies"])
    missing = set(trading.STRATEGIES) - exported - set(payload["excluded"])
    assert not missing, f"{missing} runs live but is neither charted nor explained"


def test_each_asset_is_charted_at_its_own_cost_rung(payload):
    """The chart must assume the cost that asset's live books actually pay.

    Silver pays twice gold's spread. Charting both at one rung would put a
    strategy's silver curve on the page under a commission it never paid --
    and turnover is precisely what separates these curves.
    """
    import assets as assets_module
    for key, asset in payload["assets"].items():
        expected = assets_module.get(key).fee_rate * 10_000
        assert abs(asset["fee_bps"] - expected) < 0.01, \
            f"{key} charted at {asset['fee_bps']} bp, live books pay {expected} bp"


def test_payload_stays_small_enough_to_precache(payload):
    """sw.js precaches this file with the app shell, so it is downloaded by
    every visitor before anything renders. SAMPLE_EVERY is the dial."""
    assert os.path.getsize(PAYLOAD_PATH) < 400 * 1024
