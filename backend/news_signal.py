"""Headline sentiment for gold, from Google News' keyless RSS search.

Ported from XRP-Guess's news_signal.py, but the keyword design is genuinely
different because gold's news vocabulary is macro, not promotional. Both of
that module's hard-won lessons are carried over intact:

  1. **Word-boundary matching, never substring.** Live proof from that
     project: a neutral headline was scored strongly bearish because "ban"
     matched inside "banking". The cost of the fix is that every inflected
     form has to be listed explicitly -- "cuts" does not come free with "cut".

  2. **One vote per headline, normalised, with abstention.** Scoring by the
     SUM of keyword hits made signal strength scale with news VOLUME, so one
     keyword-stuffed headline counted three times. Measured there: the
     component said UP in 121 of 127 rows -- a constant wearing a signal's
     clothes.

WHAT IS DIFFERENT FOR GOLD
--------------------------
XRP's lists were bullish/bearish words. That works when the vocabulary is
promotional. Gold's drivers are macro variables whose *direction* carries the
meaning, and the mapping is frequently inverted relative to how the sentence
sounds:

    "Fed cuts rates"          sounds like bad news, is BULLISH for gold
    "strong jobs report"      sounds like good news, is BEARISH for gold
    "dollar rallies"          sounds positive, is BEARISH for gold
    "inflation accelerates"   sounds bad, is BULLISH for gold

So the lists below are organised by EFFECT ON GOLD, not by tone, and a
plain-English sentiment model would get several of these backwards. Each
entry is a phrase, checked with word boundaries.

Because gold is a haven, media coverage also spikes when gold rises -- more
articles, more superlatives -- which is a recency bias, not information.
Normalising by matched weight is what keeps that out.

Fails soft to neutral on any network or parsing problem: a hiccup here must
never block a prediction run.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
# One query per metal. Silver's news is genuinely different -- it carries an
# industrial-demand story gold does not have (solar, electronics), and a
# shared "precious metals" query would drown silver's own drivers in gold
# headlines, which outnumber them heavily.
QUERIES = {
    "gold": "gold price OR XAU OR bullion OR \"Federal Reserve\" gold",
    "silver": "silver price OR XAG OR \"silver market\" OR \"silver demand\"",
}
TIMEOUT = 15
LOOKBACK_HOURS = 24  # gold is a daily-horizon asset here, unlike XRP's 6h

# Same guards as XRP-Guess, same reasoning. These are initial estimates:
# there is no historical headline archive to fit them against, so they must
# be validated on live `predictions` rows. Check the UP/DOWN split before
# declaring this component healthy.
MIN_MATCHED_HEADLINES = 3
MIN_IMBALANCE = 0.4

# Phrases whose occurrence implies HIGHER gold, whatever their tone.
BULLISH_PHRASES = [
    # monetary easing -- lowers the opportunity cost of a zero-yield asset
    "rate cut", "rate cuts", "cuts rates", "cut rates", "cutting rates",
    "dovish", "easing", "stimulus", "quantitative easing",
    # inflation -- gold's classic hedge case
    "inflation rises", "inflation accelerates", "inflation surges",
    "hot inflation", "price pressures",
    # dollar weakness
    "dollar falls", "dollar weakens", "weaker dollar", "dollar slides",
    # haven demand
    "safe haven", "haven demand", "geopolitical", "war", "conflict",
    "escalation", "sanctions", "crisis", "uncertainty",
    # official-sector buying, a genuine multi-year gold driver
    "central bank buying", "central banks buy", "reserve diversification",
    # outright
    "record high", "all-time high", "gold rallies", "gold surges", "gold climbs",
    "silver rallies", "silver surges", "silver climbs",
    # Silver-specific: it is half an industrial metal, so a demand story that
    # is irrelevant to gold moves silver.
    "industrial demand", "solar demand", "supply deficit",
]
# Phrases whose occurrence implies LOWER gold.
BEARISH_PHRASES = [
    # tightening
    "rate hike", "rate hikes", "hikes rates", "hike rates", "raising rates",
    "hawkish", "tightening", "higher for longer",
    # strong economy -- raises real yields, the main thing gold competes with
    "strong jobs", "jobs beat", "robust growth", "economy accelerates",
    "yields rise", "yields climb", "yields surge", "real yields",
    # dollar strength
    "dollar rallies", "dollar strengthens", "stronger dollar", "dollar surges",
    # risk-on rotation out of metal
    "risk appetite", "risk-on", "equities rally", "record stocks",
    # outright
    "gold falls", "gold slides", "gold tumbles", "gold retreats", "profit taking",
    "silver falls", "silver slides", "silver tumbles", "silver retreats",
    "demand slowdown", "surplus",
]
# Headlines about the policy setter itself move gold hardest, so they count
# double -- as a HEADLINE, not per keyword (that was XRP-Guess's bug).
HIGH_IMPACT_PHRASES = [
    "federal reserve", "fed chair", "fomc", "powell", "central bank",
    "cpi", "inflation data", "payrolls", "jobs report", "interest rate",
]

NEUTRAL = {"direction": "UP", "confidence": 0.0, "score": 0.0}

_PATTERN_CACHE: dict[str, re.Pattern] = {}


def _phrase_hits(title: str, phrases: list[str]) -> list[str]:
    """Word-boundary phrase matching. See the module docstring for why this
    is not a substring search."""
    hits = []
    for phrase in phrases:
        pattern = _PATTERN_CACHE.get(phrase)
        if pattern is None:
            # \b at both ends; internal spaces match any whitespace run so
            # "rate  cut" and "rate\ncut" behave like "rate cut".
            body = r"\s+".join(re.escape(word) for word in phrase.split())
            pattern = re.compile(rf"\b{body}\b")
            _PATTERN_CACHE[phrase] = pattern
        if pattern.search(title):
            hits.append(phrase)
    return hits


def _fetch_headlines(query: str) -> list[dict]:
    params = {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    resp = requests.get(GOOGLE_NEWS_RSS_URL, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    return [
        {"title": item.findtext("title") or "", "pubDate": item.findtext("pubDate") or ""}
        for item in root.iter("item")
    ]


def recent_headlines(asset_key: str = "gold") -> list[dict]:
    """Raw headlines from the last LOOKBACK_HOURS for this metal.

    Shared with claude_signal.py, which wants the actual text to reason over
    rather than this module's keyword tally. Empty list on any failure --
    same fail-soft contract as news_signal() itself.
    """
    try:
        items = _fetch_headlines(QUERIES.get(asset_key, QUERIES["gold"]))
    except (requests.RequestException, ET.ParseError) as exc:
        print(f"WARNING: news feed unavailable ({exc}); no headlines.")
        return []

    since = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    recent = []
    for item in items:
        try:
            when = parsedate_to_datetime(item["pubDate"])
        except (TypeError, ValueError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when >= since:
            recent.append({"title": item["title"], "published": when.isoformat()})
    return recent


def news_signal(asset=None) -> dict:
    """Directional call from this metal's recent headlines, or neutral.

    `asset` is an assets.Asset (or None for gold). Being SILENT most of the
    time is the correct behaviour for this component, not a malfunction --
    retrain.py excludes zero-confidence rows from its accuracy, so abstaining
    costs it nothing and guessing does.
    """
    asset_key = getattr(asset, "key", asset) or "gold"
    headlines = recent_headlines(asset_key)

    bullish_weight = 0.0
    bearish_weight = 0.0
    matched = 0

    for item in headlines:
        title = item["title"].lower()
        up_hits = len(_phrase_hits(title, BULLISH_PHRASES))
        down_hits = len(_phrase_hits(title, BEARISH_PHRASES))
        if up_hits == down_hits:
            # Either nothing matched, or the two cancel inside one headline.
            continue

        weight = 2.0 if _phrase_hits(title, HIGH_IMPACT_PHRASES) else 1.0
        matched += 1
        if up_hits > down_hits:
            bullish_weight += weight
        else:
            bearish_weight += weight

    total = bullish_weight + bearish_weight
    if matched < MIN_MATCHED_HEADLINES or total == 0:
        return dict(NEUTRAL)

    balance = (bullish_weight - bearish_weight) / total
    if abs(balance) < MIN_IMBALANCE:
        return dict(NEUTRAL)

    score = max(-1.0, min(1.0, balance))
    return {
        "direction": "UP" if score >= 0 else "DOWN",
        "confidence": abs(score),
        "score": score,
        "matched_headlines": matched,
    }
