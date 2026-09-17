"""Daily email digest, one run a morning from GitHub Actions.

Ported from XRP-Guess's daily_report.py, and the differences are not cosmetic
-- three of them come straight from what this project measured.

WHY THE HEADLINE NUMBER IS `edge_over_base`, NOT ACCURACY
---------------------------------------------------------
Gold closes higher over five trading days 55.7% of the time and silver 53.9%.
A mail that opened with "YÜKSELİŞ, %62 güven" would overstate the system every
single morning, because confidence is high whenever the prior is. The one
number that answers "did the model add anything last night" is how far its
p_up sits from THAT ASSET's base rate, so that is what leads -- and the
awkward case gets its own sentence: p_up above 0.5 but BELOW the base rate is
a bullish label that is still less bullish than doing nothing (measured live:
silver p_up=0.514 against a 0.539 base). frontend/app.js says the same thing
in the same three cases; this is the same rule, not a second opinion.

WHY buyhold HAS ITS OWN COLUMN
------------------------------
It is the benchmark, it is genuinely hard to beat (~11.8%/yr over 25 years),
and research/edge.py measured the direction model losing to it. XRP-Guess's
mail ranked strategies against each other and printed "bugün en çok kazanan",
which quietly answers a different, easier question. Here every portfolio is
reported against buy-and-hold and "HİÇBİRİ" is a real, expected answer that
the mail is willing to print.

WHY A VERDICT NEEDS A SAMPLE SIZE
---------------------------------
XRP-Guess resolved 96 predictions a day; this resolves ONE per asset per
trading day, five days later. "Model hep-YÜKSELİŞ'ten iyi" over eight rows is
a coin flip wearing a measurement's clothes, so the same 60-row floor the UI
uses applies here (see MIN_ROWS_FOR_VERDICT).

VALUATION IS THE FUTURES PRICE, NEVER SPOT. fetch_data.get_live_price returns
GC=F / SI=F, which is the instrument every fill in `trades` actually happened
at. Marking these books to spot would book an instant ~1% loss no market move
produced -- that is the futures-spot basis, a change of units. The frontend
carries the same rule and the same warning.

Fails loudly only on the mail itself: every section that depends on an
optional subsystem (Kanal Finans) degrades to "absent" so the rest still goes
out. No new tables and no schema change -- everything here is read from
`predictions`, `portfolios`, `trades` and `kanal_finans_mentions`.
"""
from __future__ import annotations

import os
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# Windows defaults a REDIRECTED stdout to cp1252, which cannot encode the
# Turkish this file prints. Same guard as predict.py, same reason.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import assets as assets_module  # noqa: E402
import ensemble  # noqa: E402
import fetch_data  # noqa: E402
import health  # noqa: E402
import trading  # noqa: E402
from db import get_client  # noqa: E402

TIMEZONE = timezone(timedelta(hours=3))  # Turkey: fixed UTC+3, no DST
TR_MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz",
             "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]

# The window closes at this hour, Turkey time, and covers the 24h before it.
# It is an ANCHOR rather than "the last 24 hours from now" so that a cron a
# few minutes late, or a manual test run at lunchtime, both report the exact
# same window -- otherwise two runs on one day would disagree about the same
# day and neither would be wrong.
#
# 09:00 TRT is 06:00 UTC, which is seven hours after predict.py's 23:00 UTC
# cron. The night's prediction is written, resolved and traded on well before
# the mail is built.
REPORT_HOUR_TRT = 9

# Resolved rows needed before this mail is willing to rank the model against
# "always UP". One trading quarter. Mirrors frontend/app.js's
# MIN_ROWS_FOR_VERDICT -- a page and a mail that disagree about whether the
# model is working would be worse than either alone.
MIN_ROWS_FOR_VERDICT = 60
# ...and even above it, a gap this small is not a ranking.
VERDICT_MIN_GAP = 0.02

COMPONENT_LABELS = {"technical": "Teknik", "ml": "ML modeli", "macro": "Makro",
                    "news": "Haber", "claude": "Claude"}
STRATEGY_LABELS = {
    "buyhold": "Al-ve-tut", "voltarget": "Oynaklık hedefi", "trend": "Trend filtresi",
    "defensive": "Savunma", "ensemble": "Harman", "technical": "Sadece teknik",
    "ml": "Sadece ML", "macro": "Sadece makro", "claude": "Sadece Claude",
    "miners": "Madenciler", "kanalfinans": "Kanal Finans TŞ",
    "breakout": "Kırılım kuralı",
}
# trading.STRATEGIES plus the follower, which is a real $1000 book keyed into
# the same table but driven by a different engine (kanal_finans_trading.py).
# It is comparable on exactly one axis -- what $1000 became -- and has no
# directional calls to score, which the table says rather than leaving blank.
FOLLOWER = "kanalfinans"
# The breakout rule's own $1000 book (backend/breakout_trading.py). Like the
# follower it is keyed into the same table and driven by a different engine,
# so it is comparable on exactly one axis: what $1000 became.
#
# It was deliberately ABSENT from this mail while it traded nothing -- there
# was no result to report. That reason expired on 2026-09-16 when the book
# opened. It is a ROW rather than a section of its own, and it carries a
# caveat line like `miners` does, because the rule FAILED its pre-registered
# bar: a full section would print a measured-losing rule at the same weight
# as the books that were measured to work, which is the opposite of why its
# card sits in the page's narrow column.
BREAKOUT_BOOK = "breakout"
REPORT_STRATEGIES = (*trading.STRATEGIES, FOLLOWER, BREAKOUT_BOOK)
BENCHMARK = "buyhold"

# Kanal Finans stance/action wording is deliberately Turkish and different
# from the model's own YÜKSELİŞ/DÜŞÜŞ labels: it is a person's opinion being
# reported, not a forecast this project stands behind. Same separation the UI
# makes.
KF_ASSET = {"gold": "ALTIN", "silver": "GUMUS"}
STANCE_LABELS = {"UP": "Olumlu", "DOWN": "Olumsuz", "NEUTRAL": "Nötr"}
ACTION_LABELS = {"BUY": "AL", "SELL": "SAT", "HOLD": "TUT"}


# --------------------------------------------------------------------------
# Formatting helpers. Turkish writes decimals with a comma and puts the sign
# OUTSIDE the percent sign ("+%0,02"), which is the same convention app.js
# had to be corrected into.
# --------------------------------------------------------------------------

def fmt_tr_date(when: datetime) -> str:
    return f"{when.day:02d} {TR_MONTHS[when.month - 1]} {when.year}"


def fmt_num(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def fmt_usd(value, digits: int = 2) -> str:
    return "-" if value is None else f"${fmt_num(float(value), digits)}"


def fmt_pct(value, digits: int = 1) -> str:
    return "-" if value is None else f"%{fmt_num(100 * float(value), digits)}"


def fmt_signed_pct(value, digits: int = 2) -> str:
    if value is None:
        return "-"
    sign = "+" if float(value) >= 0 else "−"
    return f"{sign}%{fmt_num(abs(100 * float(value)), digits)}"


def fmt_points(value, digits: int = 1) -> str:
    """An edge over the base rate, in percentage POINTS. It is a difference of
    two probabilities, so calling it a percentage would invite reading it as a
    relative change."""
    if value is None:
        return "-"
    sign = "+" if float(value) >= 0 else "−"
    return f"{sign}{fmt_num(abs(100 * float(value)), digits)} puan"


def window_bounds(now_trt: datetime) -> tuple[datetime, datetime]:
    """The most recent past REPORT_HOUR_TRT mark, and the 24h before it."""
    anchor = now_trt.replace(hour=REPORT_HOUR_TRT, minute=0, second=0, microsecond=0)
    if now_trt < anchor:
        anchor -= timedelta(days=1)
    return anchor - timedelta(days=1), anchor


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------

def latest_prediction(db, asset_key: str) -> dict | None:
    rows = (db.table("predictions").select("*")
            .eq("asset", asset_key).order("target_date", desc=True)
            .limit(1).execute().data)
    return rows[0] if rows else None


def resolved_predictions(db, asset_key: str) -> list[dict]:
    """Every scored row for one asset, newest last.

    Paged, because Supabase's REST API silently caps a response at ~1000 rows
    and a truncated history would quietly understate the track record rather
    than fail (the same reason retrain.fetch_resolved pages).
    """
    rows: list[dict] = []
    start, page_size = 0, 1000
    while True:
        page = (db.table("predictions")
                .select("target_date,resolved_at,correct,actual_direction,created_at")
                .eq("asset", asset_key).not_.is_("resolved_at", "null")
                .order("target_date").range(start, start + page_size - 1)
                .execute().data)
        rows.extend(page)
        if len(page) < page_size:
            return rows
        start += page_size


def portfolio_states(db, asset_key: str) -> dict[str, dict]:
    rows = db.table("portfolios").select("*").eq("asset", asset_key).execute().data
    return {r["strategy"]: r for r in rows}


def trades_in_window(db, asset_key: str, start: datetime, end: datetime) -> list[dict]:
    return (db.table("trades").select("strategy,side,created_at")
            .eq("asset", asset_key)
            .gte("created_at", start.isoformat())
            .lt("created_at", end.isoformat())
            .execute().data)


def holdings_as_of(db, asset_key: str, strategy: str, cutoff: datetime) -> tuple[float, float]:
    """(cash, ounces) at `cutoff`, from the last fill at or before it.

    A portfolio with no trade yet is still sitting on its full starting cash,
    which is the honest reconstruction rather than a gap.
    """
    rows = (db.table("trades").select("cash_after,ounces_after,created_at")
            .eq("asset", asset_key).eq("strategy", strategy)
            .lte("created_at", cutoff.isoformat())
            .order("created_at", desc=True).limit(1).execute().data)
    if rows:
        return float(rows[0]["cash_after"]), float(rows[0]["ounces_after"])
    return trading.STARTING_CASH, 0.0


def cost_basis(db, asset_key: str) -> dict[str, dict]:
    """Average purchase price and last fill date, per strategy.

    AVERAGE COST, the same method frontend/app.js uses: a buy adds units at
    its own price, a sale removes them at the running average and leaves that
    average alone. FIFO answers a different question and the two diverge the
    moment a volatility-targeted book takes partial profits -- the mail and
    the page disagreeing on what a position cost would be worse than either.

    Unpaginated on purpose: these books trade about eight times a year, so the
    whole ledger is a few dozen rows. The metals' books would need
    retrain.fetch_resolved's paging.
    """
    rows = (db.table("trades").select("strategy,side,price,ounce_amount,created_at")
            .eq("asset", asset_key).order("created_at").execute().data)
    state: dict[str, dict] = {}
    for row in rows:
        book = state.setdefault(row["strategy"], {"units": 0.0, "cost": 0.0, "last": None})
        units = float(row["ounce_amount"])
        if units <= 0:
            continue
        book["last"] = row["created_at"]
        if row["side"] == "BUY":
            book["cost"] += float(row["price"]) * units
            book["units"] += units
        else:
            sold = min(units, book["units"])
            if book["units"] > 0:
                book["cost"] -= (book["cost"] / book["units"]) * sold
            book["units"] -= sold
            if book["units"] <= 1e-9:
                book["units"], book["cost"] = 0.0, 0.0
    return {name: {"avg_price": (b["cost"] / b["units"]) if b["units"] > 0 else None,
                   "last": b["last"]}
            for name, b in state.items()}


def price_as_of(db, asset_key: str, cutoff: datetime) -> float | None:
    """The futures price this system itself recorded at or before `cutoff`.

    `price_at_prediction` rather than a fresh quote for a past moment: it is
    the number every portfolio actually traded at that day, so valuing the
    start of the window with it compares like with like. None when the system
    had not run yet.
    """
    rows = (db.table("predictions").select("price_at_prediction,created_at")
            .eq("asset", asset_key)
            .lte("created_at", cutoff.isoformat())
            .order("created_at", desc=True).limit(1).execute().data)
    return float(rows[0]["price_at_prediction"]) if rows else None


def kanal_finans_view(db, asset_key: str) -> dict | None:
    """His latest call on this metal, and the levels the follower is watching.

    The latest mention REGARDLESS of date, not "what arrived in the window":
    the channel does not post daily and the local fetcher is currently
    blocked, so a window-only query would print "nothing" on almost every run
    while the portfolio is still acting on a call from weeks ago. What the
    book is doing is the thing worth reporting.
    """
    rows = (db.table("kanal_finans_mentions")
            .select("stance,action,summary,video_title,published_at,"
                    "ounce_target,stop_loss_price,resistance_price")
            .eq("asset", KF_ASSET[asset_key])
            .order("published_at", desc=True).limit(1).execute().data)
    return rows[0] if rows else None


# --------------------------------------------------------------------------
# Interpretation -- pure, so tests can pin it without a database
# --------------------------------------------------------------------------

def verdict_sentence(row: dict, asset) -> str:
    """One sentence saying what last night's call actually means.

    Three cases, the same three frontend/app.js separates, because a direction
    label on its own misreports this system in a specific and repeatable way.
    """
    if not row:
        return "Bu varlık için henüz tahmin üretilmedi."

    base = float(row.get("base_rate_used") or asset.base_rate_up)
    p_up = row.get("p_up")
    edge = row.get("edge_over_base")
    if edge is None and p_up is not None:
        edge = float(p_up) - base
    is_up = row.get("predicted_direction") == "UP"
    word = "yükseliş" if is_up else "düşüş"

    if edge is None:
        return f"Model {word} diyor; taban orana kattığı fark hesaplanamadı."

    edge = float(edge)
    if abs(edge) < 0.01:
        return (f"Model bugün kayda değer bir şey söylemiyor: yön olarak {word} diyor, "
                f"ama taban orana kattığı fark yalnızca {fmt_points(edge)} — "
                f"yani “bilmiyorum”a çok yakın.")
    if is_up and edge < 0:
        # The case a bare "YÜKSELİŞ" misreports worst: bullish, and still less
        # bullish than doing nothing at all.
        return (f"Model yükseliş diyor ama taban orandan DAHA AZ iyimser "
                f"({fmt_points(edge)}). Bu bir alım sinyali değildir — hiç bakmadan "
                f"“yükselir” demek bugün modelden daha iyimser bir duruştur.")
    return (f"Model {word} diyor; yükseliş ihtimalini {fmt_pct(p_up)} görüyor, "
            f"taban oran {fmt_pct(base)} — kendi katkısı {fmt_points(edge)}.")


def record_verdict(resolved: int, accuracy: float | None, actual_up: float | None) -> str:
    """Whether the record is allowed to rank the model against always-UP yet."""
    if not resolved or accuracy is None or actual_up is None:
        return "Henüz puanlanmış tahmin yok — 5 işlem günlük ufkun doğal sonucu."
    scoreboard = (f"{resolved} çözülmüş tahmin · isabet {fmt_pct(accuracy)} · "
                  f"aynı dönemde fiyat {fmt_pct(actual_up)} oranında yükselmiş")
    if resolved < MIN_ROWS_FOR_VERDICT:
        return (f"{scoreboard} → hüküm için çok az satır "
                f"({resolved}/{MIN_ROWS_FOR_VERDICT}); bu boyutta iki sayı rahatlıkla "
                f"yer değiştirir.")
    if abs(accuracy - actual_up) < VERDICT_MIN_GAP:
        return f"{scoreboard} → aradaki fark 2 puandan küçük, ayırt edilebilir değil."
    better = accuracy > actual_up
    return (f"{scoreboard} → model hep-YÜKSELİŞ demekten "
            f"{'iyi' if better else 'iyi DEĞİL'}.")


def build_asset_report(db, asset, start: datetime, end: datetime) -> dict:
    row = latest_prediction(db, asset.key)
    price_now, price_source = fetch_data.get_live_price(asset.symbol)
    price_start = price_as_of(db, asset.key, start)

    resolved = resolved_predictions(db, asset.key)
    scored = [r for r in resolved if r.get("correct") is not None]
    accuracy = (sum(1 for r in scored if r["correct"]) / len(scored)) if scored else None
    actual_up = (sum(1 for r in scored if r.get("actual_direction") == "UP") / len(scored)
                 if scored else None)
    # Rows that got their answer inside this window -- the "what happened
    # overnight" half, as opposed to the cumulative record above.
    just_resolved = [r for r in resolved
                     if r.get("resolved_at") and start.isoformat() <= r["resolved_at"] < end.isoformat()]

    states = portfolio_states(db, asset.key)
    window_trades = trades_in_window(db, asset.key, start, end)

    books = {}
    for strategy in REPORT_STRATEGIES:
        state = states.get(strategy)
        if not state:
            continue
        cash_start, ounces_start = holdings_as_of(db, asset.key, strategy, start)
        value_start = cash_start + ounces_start * (price_start if price_start else price_now)
        value_now = float(state["cash_usd"]) + float(state["ounces"]) * price_now
        mine = [t for t in window_trades if t["strategy"] == strategy]
        books[strategy] = {
            "value_start": value_start, "value_now": value_now,
            "ounces": float(state["ounces"]),
            "exposure": (float(state["ounces"]) * price_now / value_now) if value_now > 0 else 0.0,
            "target_exposure": state.get("target_exposure"),
            "stop_loss_price": state.get("stop_loss_price"),
            "buys": sum(1 for t in mine if t["side"] == "BUY"),
            "sells": sum(1 for t in mine if t["side"] == "SELL"),
        }

    benchmark_value = books.get(BENCHMARK, {}).get("value_now")
    for book in books.values():
        book["today"] = ((book["value_now"] - book["value_start"]) / book["value_start"]
                         if book["value_start"] else 0.0)
        book["total"] = book["value_now"] / trading.STARTING_CASH - 1.0
        book["vs_benchmark"] = (book["value_now"] / benchmark_value - 1.0
                                if benchmark_value else None)

    beat = [s for s in books
            if s != BENCHMARK and (books[s]["vs_benchmark"] or 0) > 0]

    return {
        "asset": asset,
        "row": row,
        "verdict": verdict_sentence(row, asset),
        "price_now": price_now, "price_source": price_source, "price_start": price_start,
        # TWO changes, against TWO different reference prices, and they must
        # never appear as one number. `price_start` is the last price the
        # system recorded before the window opened -- which on a normal
        # morning is the PREVIOUS session's prediction, not last night's,
        # because last night's was written after the window closed. So the
        # entry price on the card and the 24h reference are genuinely
        # different prices, and printing one percentage beside the other
        # price produced a rise labelled as a fall (gold, 2026-09-09:
        # 4395.90 -> 4442.50 shown as -0.76%).
        "price_change_24h": ((price_now - price_start) / price_start) if price_start else None,
        "price_change_entry": ((price_now - float(row["price_at_prediction"]))
                               / float(row["price_at_prediction"])) if row else None,
        "resolved_total": len(scored), "accuracy": accuracy, "actual_up": actual_up,
        "record_verdict": record_verdict(len(scored), accuracy, actual_up),
        "just_resolved": just_resolved,
        "books": books, "beat_benchmark": beat,
        "kanal_finans": kanal_finans_view(db, asset.key),
        # Silent-failure signals (health.py): predict.py's or retrain.py's
        # cron having simply stopped, with nothing else here able to notice
        # since this mail is the one channel that reaches a person daily.
        "health": health.check(asset, health.fetch_recent(db, asset.key),
                                health.fetch_model_state_updates(db, asset.key)),
    }


# The tradeable-ETF books (assets.TRACKED, written by track_etf.py). Their
# strategies are trading.MECHANICAL, and the labels are deliberately the same
# words the futures books use -- they are the same rules on a different
# instrument, and renaming them would invite reading them as different ones.
ETF_STRATEGIES = ("buyhold", "voltarget", "trend", "defensive")

# One line, carried into both renderers, because these books are the ones most
# likely to be misread. research/README.md section 17 measured that on money
# rather than Calmar nothing here beats doing nothing.
ETF_NOTE = ("COMEX vadeli değil, gerçekten alınabilen ETF · işlem başına $1,50 · "
            "iddia getiri değil, DÜŞÜŞ azalması")

# Each book's OWN measured drawdown reduction, keyed by assets.TRACKED. Not one
# shared string: silver's buy-and-hold drawdown is 76.3% against gold's 45.6%,
# so printing gold's pair beside a silver book would misstate both the starting
# wound and the size of the cut. research/README.md section 17.
ETF_CLAIM = {
    "gld": "ölçümde %45,6 → %39,2 (16,1 yıl, $10.000 hesap)",
    "slv": "ölçümde %76,3 → %70,8 (16,1 yıl, $10.000 hesap)",
}


def build_etf_report(db) -> list[dict]:
    """Value every tracked-ETF book at its own live price.

    No 24-hour column, unlike the metals'. That one is reconstructed from
    `predictions.price_at_prediction` -- the price the books actually traded
    at that day -- and these books have no predictions rows at all, by design.
    Inventing the number from a fresh quote would compare a live price against
    a live price and call the difference a day's move.
    """
    sections = []
    for asset in assets_module.TRACKED.values():
        try:
            price, source = fetch_data.get_live_price(asset.symbol)
        except Exception as exc:  # noqa: BLE001 -- a dead quote must not kill the mail
            print(f"WARNING: {asset.key} price failed ({type(exc).__name__}: {exc})")
            continue
        states = portfolio_states(db, asset.key)
        if not states:
            continue
        basis = cost_basis(db, asset.key)

        books = {}
        for strategy in ETF_STRATEGIES:
            row = states.get(strategy)
            if not row:
                continue
            value = float(row["cash_usd"]) + float(row["ounces"]) * price
            paid = basis.get(strategy, {})
            books[strategy] = {
                "value_now": value,
                "total": value / trading.STARTING_CASH - 1.0,
                "target": float(row.get("target_exposure") or 0.0),
                "exposure": (float(row["ounces"]) * price / value) if value > 0 else 0.0,
                # SHARES, not ounces. The DB column is named `ounces` because
                # one table serves both kinds of book, but a GLD share is about
                # a tenth of an ounce of gold and an SLV share about nine
                # tenths of an ounce of silver -- printing this under an
                # "ons" heading would overstate the gold holding elevenfold.
                "shares": float(row["ounces"]),
                # Cash is half of what the book is, and an exposure percentage
                # hides it: 35% invested is also $650 sitting idle, which is
                # the number a person checks against their own account.
                "cash": float(row["cash_usd"]),
                "avg_price": paid.get("avg_price"),
                "last_trade": paid.get("last"),
            }
        bench = books.get(BENCHMARK)
        for strategy, book in books.items():
            book["vs_benchmark"] = (None if bench is None or strategy == BENCHMARK
                                    else book["total"] - bench["total"])
        beat = [s for s, b in books.items()
                if s != BENCHMARK and b.get("vs_benchmark") is not None
                and b["vs_benchmark"] > 0]
        sections.append({"asset": asset, "price": price, "source": source,
                         "books": books, "beat_benchmark": beat})
    return sections


def build_report(db) -> dict:
    start, end = window_bounds(datetime.now(TIMEZONE))
    per_asset = []
    for asset in assets_module.ASSETS.values():
        try:
            per_asset.append(build_asset_report(db, asset, start, end))
        except Exception as exc:  # noqa: BLE001 -- one metal must not take the
            # other's section down with it; they share only the DB client.
            print(f"WARNING: {asset.key} section failed ({type(exc).__name__}: {exc})")
    ratio_row = next((a["row"] for a in per_asset if a["row"] and a["row"].get("gs_ratio")), None)
    health_warnings = [line for a in per_asset for line in a.get("health", [])]
    try:
        etfs = build_etf_report(db)
    except Exception as exc:  # noqa: BLE001 -- the metals' report must survive it
        print(f"WARNING: ETF section failed ({type(exc).__name__}: {exc})")
        etfs = []
    return {"start": start, "end": end, "assets": per_asset, "ratio_row": ratio_row,
            "etfs": etfs, "health_warnings": health_warnings}


# --------------------------------------------------------------------------
# Plain-text body
# --------------------------------------------------------------------------

RATIO_NOTE = ("Ölçüldü: 5 form × 3 hedef × 4 ufuk = 60 testin hiçbiri eşiği geçmedi. "
              "Bağlam için gösteriliyor — hiçbir strateji bu orana göre işlem yapmıyor.")


def _component_lines(row: dict) -> list[str]:
    if not row:
        return []
    out = []
    for component, label in COMPONENT_LABELS.items():
        prefix = ensemble.COLUMN_PREFIX[component]
        direction = row.get(f"{prefix}_direction")
        confidence = row.get(f"{prefix}_confidence")
        if direction is None:
            continue
        # Confidence 0 means the component abstained this cycle. That is
        # designed behaviour for macro/news, not a failure, and it is scored
        # as NULL rather than wrong -- so the mail must not print it as a
        # weak vote in some direction.
        if confidence is None or float(confidence) <= 0:
            out.append(f"    {label:<12} sessiz")
        else:
            word = "YÜKSELİŞ" if direction == "UP" else "DÜŞÜŞ"
            out.append(f"    {label:<12} {word:<9} güven {fmt_num(float(confidence), 4)}")
    return out


def render_text(report: dict) -> str:
    lines = ["Merhaba Erdem,", "",
             f"{report['start'].strftime('%d.%m %H:%M')} – "
             f"{report['end'].strftime('%d.%m %H:%M')} arası:"]

    for section in report["assets"]:
        asset = section["asset"]
        row = section["row"]
        digits = 3 if asset.key == "silver" else 2
        lines += ["", "=" * 66, f"{asset.label.upper()} ({asset.symbol})", "=" * 66]

        if row:
            word = "YÜKSELİŞ" if row["predicted_direction"] == "UP" else "DÜŞÜŞ"
            lines.append(f"  Tahmin  : {word} — hedef seans {row['target_date']} "
                         f"({row.get('horizon_days', 5)} işlem günü)")
            lines.append(f"  Giriş   : {fmt_usd(row['price_at_prediction'], digits)} "
                         f"(kaynak {row.get('price_source') or '-'})")
        lines.append(f"  Şu an   : {fmt_usd(section['price_now'], digits)} "
                     f"({fmt_signed_pct(section['price_change_entry'])} girişe göre)")
        if section["price_start"]:
            lines.append(f"  Son 24s : {fmt_usd(section['price_start'], digits)} → "
                         f"{fmt_usd(section['price_now'], digits)} "
                         f"({fmt_signed_pct(section['price_change_24h'])})")
        lines.append(f"  Özet    : {section['verdict']}")
        if row and row.get("cold_start") is not False:
            lines.append("  NOT     : bileşenlerin ölçülmüş sicili yok; harman taban orandan "
                         "başlayan bir yön oylaması kullandı.")

        component_lines = _component_lines(row)
        if component_lines:
            lines += ["", "  Bileşenler:"] + component_lines

        lines += ["", f"  Sicil   : {section['record_verdict']}"]
        for done in section["just_resolved"]:
            lines.append(f"    · {done['target_date']} puanlandı: "
                         f"{'doğru' if done.get('correct') else 'yanlış'}")

        lines += ["", "  PORTFÖYLER (her biri kendi $1000'ı ile, al-ve-tut kıyas ölçütü)"]
        lines.append(f"    {'strateji':<18}{'değer':>10}{'24s':>10}{'toplam':>10}"
                     f"{'vs al-tut':>11}  işlem")
        for strategy in REPORT_STRATEGIES:
            book = section["books"].get(strategy)
            if not book:
                continue
            versus = ("kıyas" if strategy == BENCHMARK
                      else fmt_signed_pct(book["vs_benchmark"]))
            moves = book["buys"] + book["sells"]
            lines.append(
                f"    {STRATEGY_LABELS[strategy]:<18}{fmt_usd(book['value_now'], 2):>10}"
                f"{fmt_signed_pct(book['today']):>10}{fmt_signed_pct(book['total']):>10}"
                f"{versus:>11}  {moves} ({book['buys']} AL, {book['sells']} SAT)")
        beat = section["beat_benchmark"]
        lines.append("    Al-ve-tut'u geçen: "
                     + (", ".join(STRATEGY_LABELS[s] for s in beat) if beat else "HİÇBİRİ"))
        # `miners` is the one book here whose measured edge is specific to the
        # instrument it is valued in. research/README.md section 16: the lead
        # is largely a futures session-boundary effect (GC=F settles 17:00,
        # GDX 16:00) and it collapses on the ETFs a retail account can hold
        # -- +0.150 to +0.040. Without this line the mail would rank it first
        # every good week and invite exactly the wrong conclusion.
        if "miners" in beat:
            lines.append("    (Madenciler: kazanç VADELİ kontrata özgü, "
                         "GLD/IAU/SLV'de kayboluyor — satın alınabilir değil)")
        # Printed whether or not it is ahead this week, unlike the miners
        # caveat: this one is not a caveat about a win, it is the rule's
        # measured result, and a week in which it happens to lead is exactly
        # when a reader most needs it.
        if section["books"].get(BREAKOUT_BOOK):
            lines.append("    (Kırılım kuralı: ön-kayıtlı barajı iki ayrı veri "
                         "kaynağında geçemedi; defterin koştuğu varyant on yıllık "
                         "testte al-ve-tut'un altında kaldı — altında %51,2, "
                         "gümüşte %59,3. Bu defter COMEX kontratında $/ons işlem "
                         "görüyor, ölçüm ise alınabilir bacakta (GLD/SLV). "
                         "Defter kaybı canlı göstermek için var)")

        kf = section["kanal_finans"]
        if kf:
            stance = STANCE_LABELS.get(kf["stance"], kf["stance"])
            action = ACTION_LABELS.get(kf.get("action"), "—")
            lines += ["", f"  Kanal Finans TŞ: {stance} / {action} — {kf['summary']}"]
            book = section["books"].get(FOLLOWER, {})
            lines.append(f"    İzlenen zarar-kes: "
                         f"{fmt_usd(book.get('stop_loss_price'), digits) if book.get('stop_loss_price') else 'yok'}"
                         "  (direnç bilerek otomatik satış tetiklemez)")

    ratio_row = report.get("ratio_row")
    if ratio_row:
        lines += ["", "ALTIN/GÜMÜŞ ORANI",
                  f"  {fmt_num(float(ratio_row['gs_ratio']), 1)}"
                  + (f" · 250 seans z {fmt_num(float(ratio_row['gs_ratio_z']), 2)}"
                     if ratio_row.get("gs_ratio_z") is not None else ""),
                  f"  {RATIO_NOTE}"]

    for etf in report.get("etfs", []):
        claim = ETF_CLAIM.get(etf["asset"].key, "")
        lines += ["", f"ALINABİLİR ENSTRÜMAN — {etf['asset'].label} "
                      f"({fmt_usd(etf['price'], 2)})",
                  f"  {ETF_NOTE} · {claim}" if claim else f"  {ETF_NOTE}"]
        for strategy in ETF_STRATEGIES:
            book = etf["books"].get(strategy)
            if not book:
                continue
            versus = ("kıyas" if strategy == BENCHMARK
                      else fmt_signed_pct(book["vs_benchmark"]))
            lines.append(f"    {STRATEGY_LABELS[strategy]:<18}"
                         f"{fmt_usd(book['value_now'], 2):>10}"
                         f"{fmt_signed_pct(book['total']):>10}"
                         f"{versus:>11}  pozisyon %{100 * book['exposure']:.0f}"
                         f" (hedef %{100 * book['target']:.0f})")
            held = _holding_line(book)
            if held:
                lines.append(f"      {held}")
        beat = etf["beat_benchmark"]
        lines.append("    Al-ve-tut'u geçen: "
                     + (", ".join(STRATEGY_LABELS[s] for s in beat) if beat else "HİÇBİRİ"))

    health_warnings = report.get("health_warnings")
    if health_warnings:
        lines += ["", "SİSTEM SAĞLIĞI"] + [f"  {w}" for w in health_warnings]

    lines += ["", "Bu bir yatırım tavsiyesi değildir. Tüm portföyler sanaldır."]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# HTML body. Same palette as frontend/style.css so the mail reads as the same
# product, including the per-metal accent -- gold's $4.476 and silver's $66
# cannot be confused, but "%17 pozisyon" and "+%2,4" can, and most of what
# follows is that kind of number.
# --------------------------------------------------------------------------

BG, CARD, CARD_HEAD, BORDER = "#0b0906", "#15120d", "#1d1913", "#2c2519"
TEXT, MUTED, UP, DOWN, BENCH = "#f2ede4", "#9a8f7d", "#4ec98a", "#e2635c", "#7fa8d8"
METAL = {"gold": "#e8bd5e", "silver": "#d3dbe6"}


def _pct_html(value) -> str:
    if value is None:
        return f'<span style="color:{MUTED};">—</span>'
    color = UP if float(value) >= 0 else DOWN
    return f'<span style="color:{color};font-weight:600;">{fmt_signed_pct(value)}</span>'


def _row_html(label: str, value: str) -> str:
    return (f'<tr><td style="padding:8px 16px;font-size:13px;color:{MUTED};'
            f'border-top:1px solid {BORDER};">{label}</td>'
            f'<td style="padding:8px 16px;font-size:13px;text-align:right;'
            f'border-top:1px solid {BORDER};">{value}</td></tr>')


def _books_table_html(section: dict) -> str:
    accent = METAL[section["asset"].key]
    headers = ("Strateji", "Değer", "24s", "Toplam", "vs al-tut", "İşlem")
    head = "".join(
        f'<th style="padding:7px 9px;font-size:11px;color:{MUTED};text-align:left;'
        f'border-bottom:1px solid {BORDER};white-space:nowrap;">{h}</th>' for h in headers)

    body = []
    for strategy in REPORT_STRATEGIES:
        book = section["books"].get(strategy)
        if not book:
            continue
        is_bench = strategy == BENCHMARK
        name = (f'<span style="color:{BENCH};font-weight:700;">{STRATEGY_LABELS[strategy]}</span>'
                f' <span style="color:{MUTED};font-size:10px;">kıyas</span>'
                if is_bench else STRATEGY_LABELS[strategy])
        versus = (f'<span style="color:{MUTED};">—</span>' if is_bench
                  else _pct_html(book["vs_benchmark"]))
        cells = [name, fmt_usd(book["value_now"], 2), _pct_html(book["today"]),
                 _pct_html(book["total"]), versus,
                 f'<span style="color:{MUTED};">{book["buys"] + book["sells"]}</span>']
        body.append("<tr>" + "".join(
            f'<td style="padding:7px 9px;font-size:12px;border-top:1px solid {BORDER};'
            f'white-space:nowrap;">{c}</td>' for c in cells) + "</tr>")

    beat = section["beat_benchmark"]
    # "HİÇBİRİ" is printed in the benchmark's own colour rather than red: it
    # is not a failure, it is the result this project measured and expects.
    verdict = (", ".join(STRATEGY_LABELS[s] for s in beat) if beat
               else '<span style="color:%s;">HİÇBİRİ</span>' % BENCH)
    # The breakout book's caveat, printed whether or not it is ahead this
    # week -- unlike a caveat about a win, this is the rule's own measured
    # result, and a week in which it happens to lead is exactly when a reader
    # most needs it. Same job as the miners line in the text report.
    caveat = ("" if not section["books"].get(BREAKOUT_BOOK) else
              f'<br><span style="color:{MUTED};">Kırılım kuralı: ön-kayıtlı barajı '
              f'iki ayrı veri kaynağında geçemedi; defterin koştuğu varyant on '
              f"yıllık testte al-ve-tut'un %51,2 (gümüşte %59,3) altında kaldı. "
              f'Defter COMEX kontratında $/ons işlem görüyor, ölçüm alınabilir '
              f'bacakta (GLD/SLV) okunuyor. Defter kaybı canlı göstermek için '
              f'var.</span>')
    note = (f'<tr><td colspan="6" style="padding:6px 9px 10px;font-size:11px;color:{MUTED};'
            f'line-height:1.45;">'
            f'Al-ve-tut\'u geçen: {verdict}{caveat}</td></tr>')

    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="background:{CARD};border-radius:10px;overflow:hidden;margin:0 0 14px;'
            f'border:1px solid {BORDER};">'
            f'<tr><td colspan="6" style="padding:9px 16px;background:{CARD_HEAD};font-size:12px;'
            f'font-weight:700;letter-spacing:.04em;color:{accent};">PORTFÖYLER '
            f'<span style="font-weight:400;color:{MUTED};">(her biri kendi $1000 ile)</span>'
            f'</td></tr><tr>{head}</tr>{"".join(body)}{note}</table>')


def _asset_card_html(section: dict) -> str:
    asset = section["asset"]
    accent = METAL[asset.key]
    row = section["row"]
    digits = 3 if asset.key == "silver" else 2

    rows = []
    if row:
        is_up = row["predicted_direction"] == "UP"
        word = "YÜKSELİŞ" if is_up else "DÜŞÜŞ"
        base = float(row.get("base_rate_used") or asset.base_rate_up)
        rows.append(_row_html(
            f'Tahmin <span style="color:{MUTED};">({row["target_date"]} seansı)</span>',
            f'<span style="color:{UP if is_up else DOWN};font-weight:700;">{word}</span>'))
        rows.append(_row_html("P(yükseliş) / taban oran",
                              f'{fmt_pct(row.get("p_up"))} <span style="color:{MUTED};">/ '
                              f'{fmt_pct(base)}</span>'))
        # The headline number. Everything above it is context.
        rows.append(_row_html("Modelin kattığı fark",
                              _pct_html(None) if row.get("edge_over_base") is None else
                              f'<span style="color:{UP if float(row["edge_over_base"]) >= 0 else DOWN};'
                              f'font-weight:700;">{fmt_points(row["edge_over_base"])}</span>'))
        rows.append(_row_html("Giriş fiyatı", fmt_usd(row["price_at_prediction"], digits)))
    rows.append(_row_html(
        f'Şu anki fiyat <span style="color:{MUTED};">({section["price_source"]})</span>',
        f'{fmt_usd(section["price_now"], digits)} &nbsp;'
        f'{_pct_html(section["price_change_entry"])} '
        f'<span style="color:{MUTED};font-size:11px;">girişe göre</span>'))
    if section["price_start"]:
        rows.append(_row_html(
            f'Son 24 saat <span style="color:{MUTED};">'
            f'({fmt_usd(section["price_start"], digits)} idi)</span>',
            _pct_html(section["price_change_24h"])))

    verdict = (f'<tr><td colspan="2" style="padding:10px 16px;font-size:12px;color:{TEXT};'
               f'line-height:1.5;border-top:1px solid {BORDER};background:{CARD_HEAD};">'
               f'{section["verdict"]}</td></tr>')
    record = (f'<tr><td colspan="2" style="padding:8px 16px 12px;font-size:11px;color:{MUTED};'
              f'line-height:1.45;">Sicil: {section["record_verdict"]}</td></tr>')

    card = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="background:{CARD};border-radius:10px;overflow:hidden;margin:0 0 14px;'
            f'border:1px solid {BORDER};border-left:3px solid {accent};">'
            f'<tr><td colspan="2" style="padding:10px 16px;background:{CARD_HEAD};font-size:13px;'
            f'font-weight:700;color:{accent};">{asset.label} '
            f'<span style="font-weight:400;color:{MUTED};font-size:11px;">{asset.symbol}</span>'
            f'</td></tr>{"".join(rows)}{verdict}{record}</table>')

    kf = section["kanal_finans"]
    kf_html = ""
    if kf:
        stance_color = {"UP": UP, "DOWN": DOWN}.get(kf["stance"], MUTED)
        book = section["books"].get(FOLLOWER, {})
        stop = book.get("stop_loss_price")
        kf_html = (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="background:{CARD};border-radius:10px;overflow:hidden;margin:0 0 14px;'
            f'border:1px solid {BORDER};border-left:3px solid {BENCH};">'
            f'<tr><td colspan="2" style="padding:9px 16px;background:{CARD_HEAD};font-size:12px;'
            f'font-weight:700;color:{TEXT};">KANAL FİNANS TŞ '
            f'<span style="font-weight:400;color:{MUTED};">— söylediği, bizim tahminimiz değil</span>'
            f'</td></tr>'
            + _row_html("Görüş",
                        f'<span style="color:{stance_color};font-weight:600;">'
                        f'{STANCE_LABELS.get(kf["stance"], kf["stance"])}</span> '
                        f'<span style="color:{MUTED};">/ '
                        f'{ACTION_LABELS.get(kf.get("action"), "—")}</span>')
            + f'<tr><td colspan="2" style="padding:2px 16px 10px;font-size:12px;color:{TEXT};'
              f'line-height:1.45;">{kf["summary"]}</td></tr>'
            + _row_html("İzlenen zarar-kes",
                        fmt_usd(stop, digits) if stop else
                        f'<span style="color:{MUTED};">yok</span>')
            + f'<tr><td colspan="2" style="padding:2px 16px 10px;font-size:11px;color:{MUTED};">'
              f'Direnç bilerek otomatik satış tetiklemez.</td></tr></table>')

    return card + _books_table_html(section) + kf_html


def _holding_line(book: dict) -> str:
    """What the book holds and what it paid -- shares, price, date.

    A value and an exposure describe the strategy; they do not say how many
    shares are held, at what price or when it last moved, and a portfolio row
    looks identical whether the position was set yesterday or a month ago.
    No gram figure here: converting shares to metal needs a SPOT quote this
    report never fetches (it values books in futures, deliberately), and
    dividing by a futures price would bake the ~1% basis into the number. The
    page does that conversion, where the spot quote is already on hand.
    """
    shares = book.get("shares") or 0.0
    cash = book.get("cash")
    if shares <= 1e-9:
        return ("tamamen nakitte" if cash is None
                else f"tamamen nakitte — {fmt_usd(cash, 2)}")
    # fmt_num, not an f-string format spec: the rest of the mail writes
    # decimals with a comma and mixing both conventions on one line is the
    # same defect fmtNumber fixed on the page.
    parts = [f"{fmt_num(shares, 4)} pay"]
    if cash is not None:
        parts.append(f"{fmt_usd(cash, 2)} nakit")
    if book.get("avg_price"):
        parts.append(f"ort. {fmt_usd(book['avg_price'], 2)}/pay")
    if book.get("last_trade"):
        stamp = book["last_trade"]
        parts.append(f"son işlem {stamp[8:10]}.{stamp[5:7]}.{stamp[0:4]}")
    return " · ".join(parts)


def _etf_table_html(etf: dict) -> str:
    """The tradeable-ETF books. Same shape as _books_table_html, minus the 24h
    column these books cannot honestly fill (see build_etf_report)."""
    headers = ("Strateji", "Değer", "Pozisyon", "Toplam", "vs al-tut")
    head = "".join(
        f'<th style="padding:7px 9px;font-size:11px;color:{MUTED};text-align:left;'
        f'border-bottom:1px solid {BORDER};white-space:nowrap;">{h}</th>' for h in headers)

    body = []
    for strategy in ETF_STRATEGIES:
        book = etf["books"].get(strategy)
        if not book:
            continue
        is_bench = strategy == BENCHMARK
        name = (f'<span style="color:{BENCH};font-weight:700;">{STRATEGY_LABELS[strategy]}</span>'
                f' <span style="color:{MUTED};font-size:10px;">kıyas</span>'
                if is_bench else STRATEGY_LABELS[strategy])
        versus = (f'<span style="color:{MUTED};">—</span>' if is_bench
                  else _pct_html(book["vs_benchmark"]))
        held = _holding_line(book)
        if held:
            name += (f'<br><span style="color:{MUTED};font-size:10px;">{held}</span>')
        cells = [name, fmt_usd(book["value_now"], 2),
                 f'<span style="color:{MUTED};">%{100 * book["exposure"]:.0f}</span>',
                 _pct_html(book["total"]), versus]
        body.append("<tr>" + "".join(
            f'<td style="padding:7px 9px;font-size:12px;border-top:1px solid {BORDER};'
            f'white-space:nowrap;">{c}</td>' for c in cells) + "</tr>")

    beat = etf["beat_benchmark"]
    verdict = (", ".join(STRATEGY_LABELS[s] for s in beat) if beat
               else '<span style="color:%s;">HİÇBİRİ</span>' % BENCH)
    claim = ETF_CLAIM.get(etf["asset"].key, "")
    tail = f" · {claim}" if claim else ""
    note = ('<tr><td colspan="5" style="padding:6px 9px 10px;font-size:11px;'
            f'color:{MUTED};line-height:1.45;">'
            f"Al-ve-tut'u geçen: {verdict}<br>{ETF_NOTE}{tail}</td></tr>")

    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="background:{CARD};border-radius:10px;overflow:hidden;margin:0 0 14px;'
            f'border:1px solid {BORDER};">'
            f'<tr><td colspan="5" style="padding:9px 16px;background:{CARD_HEAD};font-size:12px;'
            f'font-weight:700;color:{TEXT};">ALINABİLİR ENSTRÜMAN &mdash; '
            f'{etf["asset"].label} {fmt_usd(etf["price"], 2)}</td></tr>'
            f'<tr>{head}</tr>' + "".join(body) + note + '</table>')


def render_html(report: dict) -> str:
    body = "".join(_asset_card_html(s) for s in report["assets"])
    body += "".join(_etf_table_html(e) for e in report.get("etfs", []))

    ratio_row = report.get("ratio_row")
    if ratio_row:
        z = ratio_row.get("gs_ratio_z")
        body += (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="background:{CARD};border-radius:10px;overflow:hidden;margin:0 0 14px;'
            f'border:1px solid {BORDER};">'
            f'<tr><td colspan="2" style="padding:9px 16px;background:{CARD_HEAD};font-size:12px;'
            f'font-weight:700;color:{TEXT};">ALTIN / GÜMÜŞ ORANI</td></tr>'
            + _row_html("Oran", f'{fmt_num(float(ratio_row["gs_ratio"]), 1)}'
                        + (f' <span style="color:{MUTED};">· 250 seans z '
                           f'{fmt_num(float(z), 2)}</span>' if z is not None else ""))
            + f'<tr><td colspan="2" style="padding:6px 16px 12px;font-size:11px;color:{MUTED};'
              f'line-height:1.45;">{RATIO_NOTE}</td></tr></table>')

    health_warnings = report.get("health_warnings")
    if health_warnings:
        health_rows = "".join(
            f'<tr><td style="padding:6px 16px;font-size:12px;color:{DOWN};line-height:1.45;'
            f'border-top:1px solid {BORDER};">{w}</td></tr>' for w in health_warnings)
        body += (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="background:{CARD};border-radius:10px;overflow:hidden;margin:0 0 14px;'
            f'border:1px solid {BORDER};border-left:3px solid {DOWN};">'
            f'<tr><td style="padding:9px 16px;background:{CARD_HEAD};font-size:12px;'
            f'font-weight:700;color:{TEXT};">SİSTEM SAĞLIĞI</td></tr>{health_rows}</table>')

    return f"""\
<!doctype html>
<html><body style="margin:0;padding:0;background:{BG};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{BG};padding:24px 0;">
<tr><td align="center">
<table role="presentation" width="620" cellpadding="0" cellspacing="0"
       style="width:620px;max-width:100%;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:{TEXT};">
<tr><td style="padding:0 20px 6px;">
  <div style="font-size:20px;font-weight:700;">
    <span style="color:{METAL['gold']};">ALTIN</span>
    <span style="color:{MUTED};">&amp;</span>
    <span style="color:{METAL['silver']};">GÜMÜŞ</span>
  </div>
  <div style="font-size:13px;color:{MUTED};margin-top:2px;">Günlük Özet &mdash; {fmt_tr_date(report['end'])}</div>
</td></tr>
<tr><td style="padding:12px 20px 4px;font-size:14px;">Merhaba Erdem,</td></tr>
<tr><td style="padding:0 20px 14px;font-size:13px;color:{MUTED};">
  {report['start'].strftime('%d.%m %H:%M')} &ndash; {report['end'].strftime('%d.%m %H:%M')} arası.
  Anlamlı olan tek sayı modelin taban orana <em>kattığı farktır</em>; sıfıra yakınsa
  o gün bir şey söylemiyor demektir.
</td></tr>
<tr><td style="padding:0 20px;">{body}</td></tr>
<tr><td style="padding:4px 20px 0;font-size:11px;color:{MUTED};">
  Bu bir yatırım tavsiyesi değildir. Tüm portföyler sanaldır; hiçbir gerçek emir verilmez.
</td></tr>
</table>
</td></tr>
</table>
</body></html>
"""


# --------------------------------------------------------------------------
# Sending
# --------------------------------------------------------------------------

def render_email(report: dict) -> tuple[str, str, str]:
    lead = next((a for a in report["assets"] if a["row"]), None)
    tag = ""
    if lead and lead["row"].get("edge_over_base") is not None:
        tag = f" · {lead['asset'].label} {fmt_points(lead['row']['edge_over_base'])}"
    return (f"XAU-Guess — Günlük Özet ({fmt_tr_date(report['end'])}){tag}",
            render_text(report), render_html(report))


def send_email(subject: str, text_body: str, html_body: str) -> None:
    address = os.environ["GMAIL_ADDRESS"]
    app_password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ.get("REPORT_RECIPIENT", address)

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = address
    message["To"] = recipient
    # Plain text first: a client that can render both picks the LAST part, so
    # this order is what makes the HTML the one that shows.
    message.attach(MIMEText(text_body, "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(address, app_password)
        server.sendmail(address, [recipient], message.as_string())


def main() -> int:
    db = get_client()
    report = build_report(db)
    subject, text_body, html_body = render_email(report)
    print(text_body)
    if not os.environ.get("GMAIL_ADDRESS"):
        # Nothing to send with. Printing the report and exiting 0 keeps this
        # usable as a local preview (`python daily_report.py`) without turning
        # a missing optional secret into a failed workflow.
        print("\nNOT: GMAIL_ADDRESS tanımlı değil — rapor basıldı, mail gönderilmedi.")
        return 0
    send_email(subject, text_body, html_body)
    print("\nGunluk rapor maili gonderildi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
