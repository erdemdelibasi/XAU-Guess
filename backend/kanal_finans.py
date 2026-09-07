"""Kanal Finans TŞ (YouTube @KanalFinans, Tunç Şatıroğlu) as an independent
opinion feed for the metals.

Watches the channel's public RSS for new videos, pulls each Turkish
transcript, and asks Claude to extract two different things:

  MENTIONS -- per asset (ALTIN / GUMUS / GENEL): a faithful one-line summary,
      the SPEAKER's stance, a buy/hold/sell reading, and any ounce target,
      stop-loss or resistance level he actually named. This is what the
      `kanalfinans` paper portfolio acts on.

  THEMES   -- the macro story behind those calls: war, US policy and the Fed,
      central-bank reserve buying, the dollar, inflation, physical supply.
      Deliberately NOT tradeable. It exists so a bare "UP" can be read in
      context, and so the reasoning can be compared against what actually
      happened later.

This is explicitly NOT an ensemble component (see ensemble.COMPONENTS).
predict.py never imports it. We are not forming a view here; we are reporting
one person's, and the UI labels it that way.

WHY THIS RUNS ON THE USER'S OWN MACHINE, NOT GITHUB ACTIONS
-----------------------------------------------------------
Verified live in XRP-Guess (2026-09-02, two separate manual runs, 15 of 15
videos each): transcript requests from GitHub Actions' Azure IP range are
refused by YouTube with RequestBlocked, every time. That is the same class of
problem this project already routes around for Binance -- except there an
alternate public host existed and here there is not one. The library's own
recommended fix is a residential proxy, which `_build_api()` still supports
via WEBSHARE_PROXY_* if those ever become reachable.

A 2026-09-03 follow-up matters just as much: the local machine got IpBlocked
too, on both a scheduled and a manual run. Moving off the cloud reduced the
problem, it did not solve it. That is why RETRY_SCHEDULE below is not a
politeness feature -- hammering an endpoint that is already refusing us is
the surest way to turn a temporary block into a lasting one.
"""
from __future__ import annotations

import json
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import anthropic
import requests
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import CouldNotRetrieveTranscript
from youtube_transcript_api.proxies import WebshareProxyConfig

import assets as assets_module
import db as db_module
import fetch_data
import kanal_finans_trading

# Every video title this module prints is Turkish, and on Windows a redirected
# stdout defaults to cp1252 -- which cannot encode 'ı' or 'ş', so a single
# print() of a title killed the whole run with UnicodeEncodeError. That was
# not theoretical: in XRP-Guess the scheduled task exited 1 on every run, the
# log cut off mid-video, and record_failure() never got to run, so the retry
# backoff silently recorded nothing at all. Forcing UTF-8 here (rather than
# only in run_kanal_finans.ps1) keeps the script correct however it is invoked.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

CHANNEL_ID = "UCGBytjbMXiF1nbe6HD7iORQ"  # resolved once from the channel's canonical link; stable even if the handle changes
RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id=" + CHANNEL_ID
TIMEOUT = 15
MAX_VIDEOS_PER_RUN = 15  # the RSS feed itself only ever returns ~15 entries

MODEL = "claude-opus-5"

# What the extraction may talk about. GENEL covers "kıymetli madenler" /
# "emtia" comments that name neither metal specifically.
MENTION_ASSETS = ("ALTIN", "GUMUS", "GENEL")
# Only these two map onto real paper portfolios.
PORTFOLIO_ASSET = {"ALTIN": "gold", "GUMUS": "silver"}

# The macro narrative vocabulary. Fixed and small on purpose: an open-ended
# "what did he talk about" field produces a different taxonomy every video and
# nothing can be counted across time. These are the themes that actually move
# metals and that this channel actually discusses.
THEMES = (
    "SAVAS",          # war, geopolitical escalation, sanctions
    "ABD_POLITIKA",   # the Fed, US rates, US politics, elections
    "REZERV",         # central-bank reserve buying, de-dollarisation
    "DOLAR",          # dollar strength/weakness, DXY
    "ENFLASYON",      # inflation, cost of living, real rates
    "ARZ_TALEP",      # mining supply, physical demand, jewellery, industry
    "BORSA",          # equities, risk appetite, crypto competition
    "TURKIYE",        # TL, domestic gram price, local premium
)

# Retry backoff for a video that failed to process. The scheduled task runs
# every 15 minutes, so without this a video whose transcript is IP-blocked
# would be retried 96 times a day against the endpoint already refusing us.
# Attempts are cheap and useful early (a blip clears on the next run) and
# near-worthless late, so the interval widens with the failure count: a
# permanently stuck video settles at ~2 attempts/day, while a genuinely new
# video is never delayed (it has no failure record, so it is always due).
# There is deliberately no give-up threshold -- the widening interval already
# bounds the cost, and a video falls out of the RSS window eventually.
RETRY_SCHEDULE = ((3, 0), (6, 60), (10, 240))  # (failures below this, minutes to wait)
RETRY_MAX_DELAY_MINUTES = 720

_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}

SYSTEM_PROMPT = (
    "Sana Kanal Finans YouTube kanalindaki bir video icin Turkce transkript "
    "verilecek. Kanalin sunucusu Tunc Satiroglu'nun ALTIN ve GUMUS hakkinda "
    "soyledigi seyleri sadakatle raporlamani istiyorum -- KENDI GORUSUNU "
    "KATMA, sadece konusmacinin ne dedigini ozetle.\n\n"
    "IKI AYRI SEY cikaracaksin:\n\n"
    "1) mentions -- varlik bazinda gorus. Sadece net bir goruse/beklentiye "
    "isaret eden yerleri yakala; bir varligin ismini gecici olarak anmasi "
    "yeterli DEGIL. Video hic kiymetli madenlere deginmiyorsa bos liste "
    "dondur. Her bahis icin:\n"
    "   - asset: ALTIN (ons altin, XAU, gram altin dahil), GUMUS (ons gumus, "
    "XAG dahil), ya da ikisini de ismen ayirmadan 'kiymetli madenler/emtia' "
    "diye konustuysa GENEL.\n"
    "   - summary: tek cumle, Turkce, konusmacinin dedigi.\n"
    "   - stance: UP (yukselis bekliyor), DOWN (dusus bekliyor), NEUTRAL "
    "(kararsiz ya da net yon yok).\n"
    "   - action: net bir 'al/pozisyona gir' onerisi mi (BUY), 'sat/cik/kar "
    "al' onerisi mi (SELL), yoksa 'tut/bekle/degisiklik yok' mu (HOLD).\n"
    "   - ounce_target: ONS BASINA DOLAR cinsinden hedef fiyat verdiyse o "
    "sayi. Gram/TL cinsinden bir rakam verdiyse ONU KULLANMA, 0 ver -- bu "
    "alan sadece ons/dolar icindir.\n"
    "   - stop_loss_price ve resistance_price: ons/dolar cinsinden zarar-kes "
    "(destek) ve direnc seviyeleri.\n\n"
    "   Birden fazla seviye ya da bir aralik verilmisse HER IKISINDE DE "
    "'once tetiklenecek olani' sec -- ama bu ikisi icin TERS yonlerdir, "
    "dikkat et: stop_loss_price'ta EN YUKSEK degeri al (fiyat DUSERKEN oraya "
    "once deger; orn. '4300/4250 altina duserse zarar kes' -> 4300 ver, 4250 "
    "DEGIL), resistance_price'ta EN DUSUK degeri al (fiyat YUKSELIRKEN oraya "
    "once deger; orn. '4500-4600 direnc bolgesi' -> 4500 ver, 4600 DEGIL). "
    "Belirtilmemisse 0 kullan (0 = 'bahsedilmedi', gercek bir fiyat degil).\n\n"
    "2) themes -- konusmacinin altin/gumus gorusunu dayandirdigi MAKRO "
    "GEREKCELER. Sadece gercekten deginilenleri listele, zorlama. Her biri "
    "icin theme (asagidaki listeden), tek cumlelik Turkce summary, ve "
    "konusmaciya gore bu temanin kiymetli madenlere etkisi: POSITIVE "
    "(yukselis yonlu), NEGATIVE (dusus yonlu), NEUTRAL.\n"
    "   Tema listesi: SAVAS (savas, jeopolitik gerilim, yaptirimlar), "
    "ABD_POLITIKA (Fed, ABD faizleri, ABD siyaseti/secim), REZERV (merkez "
    "bankalari altin alimi, rezervler, dolarsizlasma), DOLAR (dolar endeksi, "
    "dolarin gucu), ENFLASYON (enflasyon, reel faiz), ARZ_TALEP (madencilik "
    "arzi, fiziki talep, takı, sanayi), BORSA (hisse senetleri, risk istahi, "
    "kripto rekabeti), TURKIYE (TL, gram altin, yurtici prim).\n\n"
    "Sadece verilen sema ile cevap ver."
)

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "mentions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "asset": {"type": "string", "enum": list(MENTION_ASSETS)},
                    "summary": {"type": "string"},
                    "stance": {"type": "string", "enum": ["UP", "DOWN", "NEUTRAL"]},
                    "action": {"type": "string", "enum": ["BUY", "SELL", "HOLD"]},
                    # json_schema here rejects "minimum"/"maximum" on a number
                    # with a 400, so 0 is the "not mentioned" sentinel and the
                    # conversion to NULL happens in save_video_data().
                    "ounce_target": {"type": "number"},
                    "stop_loss_price": {"type": "number"},
                    "resistance_price": {"type": "number"},
                },
                "required": ["asset", "summary", "stance", "action",
                             "ounce_target", "stop_loss_price", "resistance_price"],
                "additionalProperties": False,
            },
        },
        "themes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "theme": {"type": "string", "enum": list(THEMES)},
                    "summary": {"type": "string"},
                    "impact": {"type": "string", "enum": ["POSITIVE", "NEGATIVE", "NEUTRAL"]},
                },
                "required": ["theme", "summary", "impact"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["mentions", "themes"],
    "additionalProperties": False,
}


# --------------------------------------------------------------------------
# RSS + bookkeeping
# --------------------------------------------------------------------------

def get_recent_videos() -> list[dict]:
    """[{"video_id", "title", "published"}] from the public RSS feed, newest
    first. Empty list on any network/parse failure -- a fetch hiccup must
    never crash the run."""
    try:
        resp = requests.get(RSS_URL, timeout=TIMEOUT)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except (requests.RequestException, ET.ParseError) as exc:
        print(f"kanal_finans: RSS unavailable ({exc}).")
        return []

    videos = []
    for entry in root.findall("atom:entry", _ATOM_NS)[:MAX_VIDEOS_PER_RUN]:
        video_id = entry.findtext("yt:videoId", default="", namespaces=_ATOM_NS)
        if not video_id:
            continue
        videos.append({
            "video_id": video_id,
            "title": entry.findtext("atom:title", default="", namespaces=_ATOM_NS),
            "published": entry.findtext("atom:published", default="", namespaces=_ATOM_NS),
        })
    return videos


def get_processed_ids(db) -> set[str]:
    return {row["video_id"] for row in
            db.table("kanal_finans_videos").select("video_id").execute().data}


def get_fetch_attempts(db) -> dict[str, dict]:
    """Failure record per video, for the retry backoff.

    Fails soft: if the table is missing (migration not applied) or Supabase
    hiccups, the backoff is lost and behaviour falls back to retry-every-run.
    The warning is loud because that fallback is exactly the hammering this
    table exists to prevent.
    """
    try:
        rows = (db.table("kanal_finans_fetch_attempts")
                .select("video_id,attempts,last_attempt_at").execute().data)
    except Exception as exc:  # noqa: BLE001 -- see docstring
        print(f"WARNING: kanal_finans retry-backoff table unreadable ({exc}); "
              "every failed video will be retried every run until this is fixed.")
        return {}
    return {row["video_id"]: row for row in rows}


def _retry_delay_minutes(attempts: int) -> int:
    for threshold, minutes in RETRY_SCHEDULE:
        if attempts < threshold:
            return minutes
    return RETRY_MAX_DELAY_MINUTES


def is_retry_due(record: dict | None, now: datetime) -> bool:
    """Whether a previously-failed video should be attempted again. A video
    with no failure record (i.e. a new one) is always due."""
    if not record:
        return True
    delay = _retry_delay_minutes(int(record.get("attempts") or 0))
    if delay <= 0:
        return True
    last = record.get("last_attempt_at")
    if not last:
        return True
    return now - datetime.fromisoformat(last.replace("Z", "+00:00")) >= timedelta(minutes=delay)


def record_failure(db, video_id: str, previous: dict | None, reason: str) -> None:
    """Bump a video's failure counter so the next run waits longer.

    Read-then-write is safe: one scheduled task is the only writer, and a lost
    increment would cost at most one extra early retry.
    """
    attempts = int((previous or {}).get("attempts") or 0) + 1
    try:
        db.table("kanal_finans_fetch_attempts").upsert({
            "video_id": video_id,
            "attempts": attempts,
            "last_attempt_at": datetime.now(timezone.utc).isoformat(),
            "last_error": reason[:500],
        }).execute()
    except Exception as exc:  # noqa: BLE001 -- bookkeeping must never sink the run
        print(f"WARNING: couldn't record failure for {video_id} ({exc}).")
        return
    print(f"kanal_finans: {video_id} failed {attempts}x, "
          f"next attempt in >= {_retry_delay_minutes(attempts)} min.")


def clear_failures(db, video_id: str) -> None:
    """Drop a video's failure record once it processes. Best-effort: a
    leftover row only delays a retry that is no longer needed, since the
    video is now in kanal_finans_videos and filtered out."""
    try:
        db.table("kanal_finans_fetch_attempts").delete().eq("video_id", video_id).execute()
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: couldn't clear failure record for {video_id} ({exc}).")


# --------------------------------------------------------------------------
# Transcript + extraction
# --------------------------------------------------------------------------

def _build_api() -> YouTubeTranscriptApi:
    """Routes through a Webshare residential proxy when configured.

    See the module docstring: cloud runners are blocked outright and the local
    machine is blocked intermittently. A residential proxy is the library's
    own recommended fix; without the secrets this falls back to a direct
    connection, which is what actually runs today.
    """
    username = os.environ.get("WEBSHARE_PROXY_USERNAME")
    password = os.environ.get("WEBSHARE_PROXY_PASSWORD")
    if username and password:
        return YouTubeTranscriptApi(proxy_config=WebshareProxyConfig(username, password))
    return YouTubeTranscriptApi()


def fetch_transcript(video_id: str) -> str | None:
    """Turkish transcript text, or None if unavailable/blocked.

    Tries Turkish first (the channel is Turkish-language), then falls back to
    whatever track the video does carry -- some only have an auto-translation.
    """
    api = _build_api()
    try:
        fetched = api.fetch(video_id, languages=["tr", "tr-TR"])
    except CouldNotRetrieveTranscript as exc:
        print(f"kanal_finans: tr transcript failed for {video_id} ({type(exc).__name__}); trying any track.")
        try:
            fetched = next(iter(api.list(video_id))).fetch()
        except (CouldNotRetrieveTranscript, StopIteration) as exc2:
            print(f"kanal_finans: fallback transcript also failed for {video_id} ({type(exc2).__name__}: {exc2})")
            return None
    except Exception as exc:  # noqa: BLE001 -- covers network-level blocks that
        # aren't a CouldNotRetrieveTranscript subclass (an IP-blocked runner).
        print(f"kanal_finans: transcript network error for {video_id} ({type(exc).__name__}: {exc})")
        return None

    text = " ".join(snippet.text for snippet in fetched)
    return text or None


def extract(video_title: str, transcript: str) -> dict | None:
    """{"mentions": [...], "themes": [...]}, or None on any failure.

    None rather than an empty result on purpose: main() must be able to tell
    "he said nothing about metals" (a valid, recordable outcome) from "we
    could not ask" (retry later).
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user",
                       "content": f"Video basligi: {video_title}\n\nTranskript:\n{transcript}"}],
            output_config={
                # Faithful extraction from a long transcript, not analysis --
                # but long enough that the model has to hold a lot at once, so
                # not the lowest setting either.
                "effort": "medium",
                "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA},
            },
        )
        if response.stop_reason == "refusal":
            print(f"WARNING: kanal_finans extraction refused for '{video_title}'.")
            return None
        text = next(b.text for b in response.content if b.type == "text")
        parsed = json.loads(text)
        return {"mentions": parsed["mentions"], "themes": parsed["themes"]}
    except (anthropic.APIStatusError, anthropic.APIConnectionError, StopIteration,
            KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f"WARNING: kanal_finans extraction failed for '{video_title}' ({exc}).")
        return None


def _level(value) -> float | None:
    """0 is the schema's "not mentioned" sentinel -- store NULL, so a stored
    number is always a level he actually named."""
    try:
        return float(value) or None
    except (TypeError, ValueError):
        return None


def save_video_data(db, video: dict, mentions: list[dict], themes: list[dict]) -> list[dict]:
    """Write the video, its mentions and its themes. Returns the inserted
    mention rows WITH their database ids -- kanal_finans_trading needs an id
    for trades.triggered_by_mention_id."""
    db.table("kanal_finans_videos").insert({
        "video_id": video["video_id"],
        "video_title": video["title"],
        "published_at": video["published"] or None,
        "transcript_found": True,
    }).execute()

    if themes:
        db.table("kanal_finans_themes").insert([
            {
                "video_id": video["video_id"],
                "published_at": video["published"] or None,
                "theme": t["theme"], "summary": t["summary"], "impact": t["impact"],
            }
            for t in themes
        ]).execute()

    if not mentions:
        return []

    rows = [
        {
            "video_id": video["video_id"],
            "video_title": video["title"],
            "published_at": video["published"] or None,
            "asset": m["asset"],
            "summary": m["summary"],
            "stance": m["stance"],
            "action": m["action"],
            "ounce_target": _level(m.get("ounce_target")),
            "stop_loss_price": _level(m.get("stop_loss_price")),
            "resistance_price": _level(m.get("resistance_price")),
        }
        for m in mentions
    ]
    return db.table("kanal_finans_mentions").insert(rows).execute().data


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        # No point fetching transcripts -- each is an extra request against a
        # host known to block us -- when extract() would fail anyway.
        print("kanal_finans: ANTHROPIC_API_KEY not set, skipping this run.")
        return 0

    db = db_module.get_client()

    videos = get_recent_videos()
    if not videos:
        print("kanal_finans: RSS empty or unavailable, nothing to do.")
        return 0

    processed = get_processed_ids(db)
    pending = [v for v in videos if v["video_id"] not in processed]
    if not pending:
        print("kanal_finans: no new videos since last run.")
        return 0

    attempts = get_fetch_attempts(db)
    now = datetime.now(timezone.utc)

    for video in pending:
        video_id = video["video_id"]
        previous = attempts.get(video_id)
        if not is_retry_due(previous, now):
            # Backing off, not giving up. Skipping one video never holds up
            # the others: a newly published video has no failure record and
            # so is always attempted immediately.
            print(f"kanal_finans: backing off '{video['title']}' ({video_id}), "
                  f"{previous['attempts']} failure(s) so far.")
            continue

        transcript = fetch_transcript(video_id)
        if transcript is None:
            record_failure(db, video_id, previous, "transcript unavailable")
            continue

        result = extract(video["title"], transcript)
        if result is None:
            record_failure(db, video_id, previous, "claude extraction failed")
            continue

        # A video is recorded only once BOTH the transcript and the extraction
        # succeeded, so a partial failure leaves it unrecorded and the next
        # run retries it. A stuck video is delayed, never lost.
        saved = save_video_data(db, video, result["mentions"], result["themes"])
        clear_failures(db, video_id)
        print(f"kanal_finans: processed '{video['title']}' -- "
              f"{len(result['mentions'])} mention(s), {len(result['themes'])} theme(s).")
        for theme in result["themes"]:
            print(f"    [{theme['theme']:<13} {theme['impact']:<8}] {theme['summary']}")

        for mention in saved:
            asset_key = PORTFOLIO_ASSET.get(mention["asset"])
            if not asset_key:
                continue  # GENEL is informational; there is no "general metal" to trade
            try:
                asset = assets_module.get(asset_key)
                price, source = fetch_data.get_live_price(asset.symbol)
                kanal_finans_trading.apply_mention(db, asset, mention, price)
                print(f"    [{mention['asset']}] {mention['action']} @ {price:,.2f} ({source})")
            except Exception as exc:  # noqa: BLE001 -- one asset's hiccup must not
                # stop the other, nor stop the remaining videos from processing.
                print(f"WARNING: kanal_finans portfolio update failed for "
                      f"{mention['asset']} ({exc})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
