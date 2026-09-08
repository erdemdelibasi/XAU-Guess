/* XAU-Guess frontend. No framework, no build step -- plain fetch against
   Supabase's auto-generated REST API using the public anon key (read-only,
   enforced by RLS in supabase/schema.sql).

   One display decision runs through the whole file and is worth stating
   once: each metal already rises more often than not over this horizon (gold
   55.7%, silver 53.9%), so a bare "UP" is nearly content-free. Everywhere a
   direction is shown, the model's EDGE OVER THAT ASSET'S BASE RATE is shown
   next to it. A UI that printed "UP, 62% confidence" without that context
   would systematically overstate what the system knows -- and the project's
   own research (backend/research/edge.py) measured that the direction model
   does NOT beat always-long. */

const REST = `${CONFIG.SUPABASE_URL}/rest/v1`;
const HEADERS = {
  apikey: CONFIG.SUPABASE_ANON_KEY,
  Authorization: `Bearer ${CONFIG.SUPABASE_ANON_KEY}`,
};

// Must match assets.py. Duplicated rather than fetched because display
// constants should not add a round trip; retrain.py is what watches for them
// drifting away from reality. Each prediction row also stores the rate it
// actually used (`base_rate_used`), which is what gets rendered when present.
const ASSETS = {
  gold: { label: "Altın", baseRate: 0.557, unit: "ons", digits: 2 },
  silver: { label: "Gümüş", baseRate: 0.539, unit: "ons", digits: 3 },
};

const COMPONENTS = [
  { key: "tech", label: "Teknik", weight: "weight_technical" },
  { key: "ml", label: "ML modeli", weight: "weight_ml" },
  { key: "macro", label: "Makro sürücüler", weight: "weight_macro" },
  { key: "news", label: "Haber tonu", weight: "weight_news" },
  { key: "claude", label: "Claude", weight: "weight_claude" },
];

// Order matters: buyhold renders first as the benchmark everything else is
// judged against.
const STRATEGIES = [
  { key: "buyhold", label: "Al-ve-tut", benchmark: true,
    desc: "Hiçbir şey yapma. Kıyas ölçütü: 25 yılda yıllık ~%11,8." },
  { key: "voltarget", label: "Oynaklık hedefi",
    desc: "Pozisyonu gerçekleşen oynaklığa göre ölçekler. Ölçümde işe yarayan tek mekanizma." },
  { key: "trend", label: "Trend filtresi",
    desc: "200 günlük ortalamanın altında pozisyonu kısar. Ayıda kazanır, boğada öder." },
  { key: "defensive", label: "Savunma",
    desc: "Oynaklık + trend birlikte. En düşük düşüş, en düşük getiri." },
  { key: "ensemble", label: "Harman",
    desc: "Tüm sinyaller + risk kuralları." },
  { key: "technical", label: "Sadece teknik", desc: "Yalnızca kural tabanlı teknik sinyal." },
  { key: "ml", label: "Sadece ML", desc: "Yalnızca gradient boosting modeli." },
  { key: "macro", label: "Sadece makro", desc: "Yalnızca ölçülmüş öncü sürücüler." },
  { key: "claude", label: "Sadece Claude", desc: "Yalnızca Claude'un bağımsız yargısı." },
  { key: "kanalfinans", label: "Kanal Finans TŞ", follower: true,
    desc: "Tunç Şatıroğlu ne derse onu yapar. Tam giriş/çıkış, zarar-kes takipli." },
];

const STARTING_CASH = 1000;

// Must match trading.REBALANCE_THRESHOLD. Duplicated for the same reason the
// base rates are: this only decides a label ("sonraki işlem"), never a trade.
// The backend remains the sole authority on what actually gets executed.
const REBALANCE_THRESHOLD = 0.05;

// Measured facts about the gold/silver ratio, from backend/research/ratio.py
// on the 25-year panel (2001-09-07 .. 2026-09-04). Hardcoded the same way
// indicators.py hardcodes its scale constants: a measured number with a named
// source, not a guess. Re-run ratio.py and update these if the panel is
// extended -- and note the median is NOT stable across the sample (60.3 in the
// first half against 78.7 in the second), which is itself the reason the UI
// shows a TRAILING z rather than a distance from this median.
const GS_RATIO = {
  median: 69.5,
  low: 32.0, lowYear: 2011,
  high: 125.9, highYear: 2020,
  // The one sentence that has to survive any redesign of this panel. The
  // ratio is the single most requested number here and the most inviting to
  // misread: it looks like a signal, it is displayed like a signal, and it
  // was measured not to be one.
  note: "Ölçüldü: 5 form × 3 hedef × 4 ufuk = 60 testin hiçbiri eşiği geçmedi. "
      + "Bağlam için gösteriliyor — hiçbir strateji bu orana göre işlem yapmıyor.",
};

/* Live prices, fetched straight from the browser.

   WHICH SOURCES ARE EVEN POSSIBLE HERE was measured, not assumed
   (2026-09-08), and the constraint is CORS rather than data availability:

     Yahoo          the backend's own primary feed. Sends NO
                    Access-Control-Allow-Origin, so the browser cannot call
                    it at all. Unusable here regardless of what it holds.
     goldprice.org  403 Forbidden, no CORS header. Unusable.
     Investing.com  403 Forbidden, no CORS header. Unusable.
     Binance        CORS `*`. Carries PAXGUSDT and USDTTRY -- gold and FX,
                    24/7 -- but NO silver: XAGUSDT / SLVUSDT / KAGUSDT all
                    return "Invalid symbol", the same gap fetch_data.py
                    documents server-side.
     TradingView    CORS, and it has BOTH metals plus the FX rate in one
                    call. This is the only source found that closes the
                    silver gap.

   THE TRADINGVIEW REQUEST HAS TO BE SHAPED A SPECIFIC WAY. Its preflight
   replies `Access-Control-Allow-Headers: Referer,Accept` -- `content-type`
   is absent -- so a normal `application/json` POST is rejected by the
   browser before it is ever sent. Posting the same JSON body under
   `text/plain;charset=UTF-8` makes it a CORS "simple request", which needs
   no preflight, and the response then carries the allow-origin header.
   Changing that content type back to JSON silently breaks this in browsers
   while continuing to work in curl.

   IT IS ALSO AN UNDOCUMENTED ENDPOINT and is treated as one: TradingView is
   tried first, Binance is the fallback for gold and FX, and silver falls
   back to its last COMEX close labelled as such. Nothing here throws.

   THE NUMBERS WERE CROSS-CHECKED before this was wired in, because a single
   unverified feed is just a second guess: TVC:GOLD sat 0.057% from Binance
   PAXG and FX_IDC:USDTRY 0.004% from Yahoo's USDTRY. Silver has no
   independent live source to check against, so the consistency test was
   internal -- TVC spot ran 0.99% under GC=F and 0.96% under SI=F, i.e. the
   same futures basis on both metals, which is what a genuine spot quote
   looks like. */
const BINANCE = "https://data-api.binance.vision/api/v3/ticker/price";
const TRADINGVIEW = "https://scanner.tradingview.com/global/scan";
const TV_TICKERS = { gold: "TVC:GOLD", silver: "TVC:SILVER", usdtry: "FX_IDC:USDTRY" };

/* TWO PRICE SERIES ARE NEEDED, NOT ONE, and using the wrong one for the wrong
   job is a silent 1% error.

     TVC:GOLD / TVC:SILVER   spot, `streaming` (real-time), 24/7. This is
                             "what is an ounce worth right now" -- the Anlık
                             Fiyatlar cards.
     COMEX:GC1! / SI1!       front-month COMEX futures, `delayed_streaming_600`
                             (10 minutes behind). This is the instrument the
                             BACKEND trades: price_at_prediction comes from
                             GC=F, every trade in `trades` was filled at a
                             futures price, and any future trade will be too.

   Measured 2026-09-08: stored close 4476.60, GC1! 4442.30 (-0.77%), TVC spot
   4397.34 (-1.77%). Valuing the portfolios at SPOT would therefore book an
   instant ~1% loss on every one of them that no market move caused -- it is
   the futures-spot basis (financing + storage), i.e. a change of units
   masquerading as a change of value. Portfolios are valued on GC1!/SI1! for
   that reason, and the 10-minute delay is the price paid for being on the
   right series; it is stated on screen rather than hidden. */
const TV_FUTURES = { gold: "COMEX:GC1!", silver: "COMEX:SI1!" };
const TROY_OUNCE_GRAMS = 31.1034768;

/* Live prices refresh on their own fast loop, separate from Supabase.

   The Supabase side produces ONE row per trading day, so re-fetching it every
   few seconds would just re-download identical data; it stays on the slow
   cycle. Prices are the only thing that actually moves intraday.

   BACKOFF IS NOT POLITENESS HERE. TradingView's scanner is an undocumented
   endpoint, and this is the same lesson kanal_finans.RETRY_SCHEDULE records
   in the backend: hammering an endpoint that is already refusing us is the
   surest way to turn a temporary block into a permanent one. A failing fetch
   backs off geometrically to a minute; the first success resets it.

   HOW FAST IS WORTH POLLING WAS MEASURED (2026-09-08), not guessed. Sampling
   the scanner once a second for 109 seconds, each series produced a new value
   only every 11-22 seconds:

     TVC:GOLD        8 ticks   ~13.7s apart
     TVC:SILVER     10 ticks   ~10.9s
     COMEX:GC1!      5 ticks   ~21.9s
     FX_IDC:USDTRY   9 ticks   ~12.1s

   Polling at 1s, 2s and 5s all landed on the SAME set of values: because each
   value persists far longer than the poll interval, a 5s poll already misses
   no tick. So a faster loop buys latency, not information -- at 2s the newest
   value reaches the screen up to 3 seconds sooner, and that is the whole gain.

   Two seconds is used anyway because that latency is what the page feels
   like, and it is paid for by NOT re-fetching Binance every cycle (below)
   rather than by making 2.5x the requests. */
const PRICE_REFRESH_MS = 2000;
const PRICE_BACKOFF_MAX_MS = 60000;
const DATA_REFRESH_MS = 5 * 60 * 1000;

/* Binance is only ever a FALLBACK -- gold and FX, for when TradingView is
   unreachable -- so it does not need TradingView's cadence. It used to ride
   in every cycle so the fallback was already in hand rather than costing a
   serial round trip at the worst possible moment; that reasoning still holds,
   but 30 seconds satisfies it just as well as 2.

   The arithmetic is why 2s costs nothing here. Per tab, per hour:
     before, 5s x 3 requests  = 2160
     now,    2s x 1 request + 30s x 2 = 1800 + 240 = 2040
   i.e. a faster loop that makes FEWER total requests than the slower one it
   replaces. A TradingView failure refreshes Binance immediately regardless of
   this timer, so the fallback is never stale when it is actually needed. */
const BINANCE_REFRESH_MS = 30000;

const KF_STANCE = { UP: "Olumlu", DOWN: "Olumsuz", NEUTRAL: "Nötr" };
const KF_ACTION = { BUY: "AL", SELL: "SAT", HOLD: "TUT" };
const KF_IMPACT = { POSITIVE: "olumlu", NEGATIVE: "olumsuz", NEUTRAL: "nötr" };
const KF_THEME_LABEL = {
  SAVAS: "Savaş / jeopolitik",
  ABD_POLITIKA: "ABD politikası / Fed",
  REZERV: "Merkez bankası rezervleri",
  DOLAR: "Dolar",
  ENFLASYON: "Enflasyon",
  ARZ_TALEP: "Arz / talep",
  BORSA: "Borsa / risk iştahı",
  TURKIYE: "Türkiye / gram",
};
const KF_ASSET_LABEL = { ALTIN: "Altın", GUMUS: "Gümüş", GENEL: "Genel" };

let currentAsset = "gold";
let cache = {
  predictions: {}, portfolios: [], mentions: [], themes: [],
  costBasis: new Map(),
  // Filled by the fast price loop, not by the Supabase load.
  live: null,
};
let priceFailures = 0;
let priceTimer = null;

/* ---------------------------------------------------------------- helpers */

async function api(path) {
  const response = await fetch(`${REST}/${path}`, { headers: HEADERS });
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
  return response.json();
}

// Supabase's REST API caps a response at ~1000 rows and says so by simply
// returning fewer -- silently, with no error. An average purchase price
// computed from a truncated trade log is wrong rather than missing, so this
// pages until a short page arrives. `trades` grows without bound; `predictions`
// is one row per day and does not need it.
async function apiAll(path, pageSize = 1000, maxPages = 25) {
  const rows = [];
  for (let page = 0; page < maxPages; page += 1) {
    const chunk = await api(`${path}&limit=${pageSize}&offset=${page * pageSize}`);
    rows.push(...chunk);
    if (chunk.length < pageSize) break;
  }
  return rows;
}

const fmtUsd = (v, digits = 2) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "-"
    : `$${Number(v).toLocaleString("tr-TR", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;

// Turkish writes decimals with a comma, so every number that reaches the
// screen goes through toLocaleString("tr-TR") -- toFixed() would print
// "%62.3", which is simply misspelt in this language. fmtUsd already did this
// and the percentage formatters did not, so the same page showed both
// conventions.
const fmtNumber = (v, digits = 1) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "-"
    : Number(v).toLocaleString("tr-TR", { minimumFractionDigits: digits, maximumFractionDigits: digits });

// Signed, for quantities where the direction is the point (a z-score, an
// edge over the base rate): "0,08" and "-0,08" are different claims and the
// leading + is what makes the positive case say so out loud.
const fmtSigned = (v, digits = 2) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "-"
    : `${Number(v) >= 0 ? "+" : "−"}${fmtNumber(Math.abs(Number(v)), digits)}`;

// A signed percentage, Turkish word order: the sign goes OUTSIDE the percent
// sign ("+%0,02"), unlike English's "+0.02%". Used for P&L, where the sign is
// the first thing read and must not be buried after the symbol.
const fmtSignedPct = (v, digits = 2) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "-"
    : `${Number(v) >= 0 ? "+" : "−"}%${fmtNumber(Math.abs(Number(v) * 100), digits)}`;

const fmtPct = (v, digits = 1) =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? "-" : `%${fmtNumber(Number(v) * 100, digits)}`;

const fmtPoints = (v, digits = 1) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "-"
    : `${fmtSigned(Number(v) * 100, digits)} puan`;

const fmtDate = (v) => (v ? String(v).slice(0, 10) : "-");

function showError(message) {
  const box = document.createElement("div");
  box.className = "error";
  box.textContent = `Veri yüklenemedi: ${message}`;
  document.getElementById("app").prepend(box);
}

/* ------------------------------------------------------------ rendering */

function renderPrediction(row, asset) {
  const el = (id) => document.getElementById(id);
  el("asset-name").textContent = asset.label;
  el("portfolio-asset-name").textContent = asset.label;

  if (!row) {
    el("prediction-direction").textContent = "-";
    el("prediction-horizon").textContent = "henüz tahmin yok";
    el("prediction-verdict").textContent = "Bu varlık için henüz tahmin üretilmedi.";
    return;
  }

  const isUp = row.predicted_direction === "UP";
  const direction = el("prediction-direction");
  direction.textContent = isUp ? "YÜKSELİŞ" : "DÜŞÜŞ";
  direction.className = `direction ${isUp ? "up" : "down"}`;

  el("prediction-price").textContent = `hedef ${fmtUsd(row.predicted_price, asset.digits)}`;
  el("prediction-horizon").textContent =
    `${fmtDate(row.target_date)} · ${row.horizon_days} işlem günü · giriş ${fmtUsd(row.price_at_prediction, asset.digits)}`;

  // Prefer the rate the row was actually scored against: a later change to
  // the constant must not silently rewrite how an old row reads.
  const baseRate = row.base_rate_used ?? asset.baseRate;
  const pUp = row.p_up === null || row.p_up === undefined ? null : Number(row.p_up);
  el("prediction-pup").textContent = pUp === null ? "-" : fmtPct(pUp);
  el("prediction-base").textContent = fmtPct(baseRate);

  const edge = row.edge_over_base ?? (pUp === null ? null : pUp - baseRate);
  const edgeEl = el("prediction-edge");
  edgeEl.textContent = fmtPoints(edge);
  // Near zero is the common and honest case, so it gets neutral styling
  // rather than being dressed up as a signal.
  edgeEl.className = edge === null || Math.abs(edge) < 0.01
    ? "" : (edge > 0 ? "up-text" : "down-text");

  // The same three numbers, as one sentence. A reader who does not want to do
  // arithmetic in their head still has to be able to leave this card knowing
  // what it said -- and the honest reading of a near-zero edge is "nothing
  // today", which a large "YÜKSELİŞ" label actively hides. This is the same
  // threshold the edge styling uses, so the wording and the colour can never
  // disagree with each other.
  const verdict = el("prediction-verdict");
  const dirWord = isUp ? "yükseliş" : "düşüş";
  const lede =
    `<strong>Özet:</strong> <strong>${fmtDate(row.target_date)}</strong> seansında fiyatın, ` +
    `bugünkü ${fmtUsd(row.price_at_prediction, asset.digits)} seviyesine göre ` +
    `<strong>${dirWord}</strong> yönünde olmasını bekliyor. Yükseliş ihtimalini ` +
    `${fmtPct(pUp)} görüyor; hiçbir model olmasaydı bu ihtimal ${fmtPct(baseRate)} olurdu`;

  if (edge === null || edge === undefined) {
    verdict.textContent = "-";
  } else if (Math.abs(edge) < 0.01) {
    verdict.innerHTML =
      `<strong>Özet:</strong> model bugün kayda değer bir şey söylemiyor. Yön olarak ` +
      `${dirWord} diyor, ama taban orana kattığı fark yalnızca ${fmtPoints(edge)} ` +
      `&mdash; yani &ldquo;bilmiyorum&rdquo;a çok yakın.`;
  } else if (isUp && edge < 0) {
    // The case a bare "YÜKSELİŞ" label misreports most badly. p_up above 0.5
    // but BELOW the base rate means the model is bullish and still less
    // bullish than doing nothing at all -- so the reader must not walk away
    // treating this as a buy signal. Spelling it out is the whole reason
    // edge_over_base is on this page.
    verdict.innerHTML =
      `${lede} &mdash; yani model yükseliş diyor ama <strong>taban orandan daha az ` +
      `iyimser</strong> (${fmtPoints(edge)}). Bu bir alım sinyali değildir: hiç ` +
      `bakmadan &ldquo;yükselir&rdquo; demek bugün modelden daha iyimser bir duruştur.`;
  } else {
    verdict.innerHTML = `${lede} &mdash; yani modelin kendi katkısı ${fmtPoints(edge)}.`;
  }

  el("base-rate-note").innerHTML =
    `${asset.label}, 5 işlem gününde zaten <strong>${fmtPct(baseRate)}</strong> ihtimalle ` +
    `yükseliyor. Anlamlı olan tek sayı modelin bunun <em>üzerine</em> kattığı farktır; ` +
    `sıfıra yakınsa model o gün bir şey söylemiyor demektir.`;
}

function renderContext(row, asset) {
  const grid = document.getElementById("context-grid");
  if (!row) { grid.innerHTML = ""; return; }
  const items = [
    ["Giriş fiyatı", fmtUsd(row.price_at_prediction, asset.digits)],
    ["200 seans ortalaması", fmtUsd(row.trend_average, asset.digits)],
    ["Yıllık oynaklık", fmtPct(row.realised_volatility)],
    ["Harman hedef pozisyon", fmtPct(row.target_exposure, 0)],
    ["Fiyat kaynağı", row.price_source ?? "-"],
    ["Model sürümü", String(row.model_version ?? "-").slice(0, 10)],
  ];
  grid.innerHTML = items
    .map(([label, value]) => `
      <div class="context-item">
        <span class="label">${label}</span>
        <span class="value">${value}</span>
      </div>`)
    .join("");
}

function renderRatio(goldRow, silverRow) {
  const stored = goldRow?.gs_ratio ?? silverRow?.gs_ratio;
  const goldPrice = goldRow?.price_at_prediction;
  const silverPrice = silverRow?.price_at_prediction;
  const ratio = stored ?? (goldPrice && silverPrice ? goldPrice / silverPrice : null);

  document.getElementById("gs-ratio").textContent =
    ratio === null ? "-" : fmtNumber(ratio, 1);

  // A bare "67,1" is unreadable without a scale -- high or low against what?
  // The trailing z is the honest placement: it compares the ratio to its own
  // last 250 sessions rather than to a 25-year median the series has already
  // walked away from.
  const z = goldRow?.gs_ratio_z ?? silverRow?.gs_ratio_z;
  const parts = [`25y aralık ${fmtNumber(GS_RATIO.low, 0)}–${fmtNumber(GS_RATIO.high, 0)}`];
  if (z !== null && z !== undefined) {
    parts.push(`250 seans z ${fmtSigned(z, 2)}`);
  }
  document.getElementById("gs-ratio-context").textContent = parts.join(" · ");
  document.getElementById("gs-ratio-note").textContent = GS_RATIO.note;
}

async function fetchTradingView() {
  // Both metals and the FX rate in one request. Returns null on any problem,
  // so the caller simply falls through to Binance.
  try {
    const response = await fetch(TRADINGVIEW, {
      method: "POST",
      // NOT application/json -- see the block comment above. This content
      // type is what keeps the request preflight-free and therefore allowed.
      headers: { "Content-Type": "text/plain;charset=UTF-8" },
      body: JSON.stringify({
        symbols: { tickers: [...Object.values(TV_TICKERS), ...Object.values(TV_FUTURES)] },
        columns: ["close", "update_mode", "open"],
      }),
    });
    if (!response.ok) return null;
    const rows = (await response.json()).data ?? [];
    const bySymbol = new Map(rows.map((r) => [r.s, r.d]));
    const read = (ticker) => {
      const cell = bySymbol.get(ticker);
      const value = cell ? Number(cell[0]) : NaN;
      return Number.isFinite(value) && value > 0 ? value : null;
    };
    // Column index 2: today's session open, per TradingView's own daily bar
    // (its exchange-timezone boundary, not ours). This is what "up/down
    // today" is measured against below -- deliberately NOT the previous
    // close, which is a different and more common convention but not the one
    // asked for here.
    const readOpen = (ticker) => {
      const cell = bySymbol.get(ticker);
      const value = cell ? Number(cell[2]) : NaN;
      return Number.isFinite(value) && value > 0 ? value : null;
    };
    const gold = read(TV_TICKERS.gold);
    const silver = read(TV_TICKERS.silver);
    if (gold === null && silver === null) return null;
    // The feed says whether it is real-time or delayed. Reading it means the
    // "canlı" badge stops being a hardcoded claim: if TradingView ever serves
    // this account a delayed quote, the card says "gecikmeli" instead of
    // asserting something that is no longer true.
    //
    // Only the SPOT tickers decide this flag. The futures legs are always
    // `delayed_streaming_600` by design, so folding them in would permanently
    // brand the real-time spot cards "gecikmeli" and make the badge useless.
    const modes = Object.values(TV_TICKERS)
      .map((t) => bySymbol.get(t)?.[1])
      .filter(Boolean);
    return {
      gold, silver,
      usdtry: read(TV_TICKERS.usdtry),
      // The series the portfolios are valued on -- see the TV_FUTURES note.
      futures: { gold: read(TV_FUTURES.gold), silver: read(TV_FUTURES.silver) },
      // No fallback source (Binance) has a comparable "today's open" -- its
      // 24hr ticker has a rolling-window open, a different number wearing the
      // same name -- so this stays empty rather than mixing definitions, and
      // the up/down arrow simply does not render while TradingView is down.
      open: { gold: readOpen(TV_TICKERS.gold), silver: readOpen(TV_TICKERS.silver) },
      delayed: modes.length > 0 && modes.some((m) => m !== "streaming"),
      source: "TradingView",
    };
  } catch {
    return null;
  }
}

async function fetchBinance(symbol) {
  // One dead endpoint must not blank the whole panel, so this resolves to
  // null rather than rejecting -- the renderer decides what to show instead.
  try {
    const response = await fetch(`${BINANCE}?symbol=${symbol}`);
    if (!response.ok) return null;
    const price = Number((await response.json()).price);
    return Number.isFinite(price) && price > 0 ? price : null;
  } catch {
    return null;
  }
}

function livePriceCard({ label, metal, usd, usdtry, source, live, badge, footnote, dayChangePct, flashClass }) {
  // These two cards are the only place both metals appear at once, so each
  // pins its own palette (.metal-gold / .metal-silver) instead of inheriting
  // the active tab's. Everything else on the page follows the tab.
  const skin = `live-card metal-${metal}`;
  if (usd === null || usd === undefined) {
    return `<div class="${skin}"><div class="live-label">${label}</div>
            <div class="live-usd">-</div>
            <div class="muted small">fiyat alınamadı</div></div>`;
  }
  const digits = label === "Gümüş" ? 3 : 2;
  // TL is always DERIVED, never quoted: there is no lira-denominated feed
  // here, so it is dollar price x USDTRY and nothing more.
  const tlOunce = usdtry ? usd * usdtry : null;
  const tlGram = tlOunce === null ? null : tlOunce / TROY_OUNCE_GRAMS;

  // Arrow against TODAY'S OPEN, not the previous close -- that is what was
  // asked for, and it is a different (and less common) comparison, so it is
  // never silently swapped for the more standard one. Absent whenever there
  // is no genuine same-day open to compare against (Binance fallback, or a
  // move too small to round to a visible percentage) rather than guessing.
  const arrowHtml = dayChangePct === null
    ? ""
    : `<span class="live-arrow ${dayChangePct >= 0 ? "up-text" : "down-text"}">` +
      `${dayChangePct >= 0 ? "▲" : "▼"} ${fmtSignedPct(dayChangePct)}</span>`;

  // renderLivePrices rebuilds this whole grid's innerHTML every 2s regardless
  // of whether anything changed, so every card is a brand-new DOM node on
  // every render -- which is what makes this safe rather than needing a key
  // trick to restart the CSS animation: the class is only INCLUDED on a
  // render where the price actually moved, so an unchanged tick produces a
  // fresh node with no animation class and nothing plays.
  const flash = flashClass ? ` ${flashClass}` : "";

  return `
    <div class="${skin}${live ? " is-live" : ""}${flash}">
      <div class="live-label">${label}
        <span class="live-badge">${badge ?? (live ? "canlı" : "son kapanış")}</span>
      </div>
      <div class="live-usd">${fmtUsd(usd, digits)}<span class="unit">/ons</span> ${arrowHtml}</div>
      <div class="live-tl">
        <span>${tlOunce === null ? "-" : fmtNumber(tlOunce, 0) + " ₺"}<span class="unit">/ons</span></span>
        <span>${tlGram === null ? "-" : fmtNumber(tlGram, 2) + " ₺"}<span class="unit">/gram</span></span>
      </div>
      <div class="muted small live-source">${source}</div>
      ${footnote ? `<div class="muted small live-source">${footnote}</div>` : ""}
    </div>`;
}

function renderLivePrices(live, goldRow, silverRow) {
  const comex = {
    gold: goldRow ? Number(goldRow.price_at_prediction) : null,
    silver: silverRow ? Number(silverRow.price_at_prediction) : null,
  };
  const rows = { gold: goldRow, silver: silverRow };
  const asOf = (row) => (row?.created_at ? fmtDate(row.created_at) : "-");
  const usdtry = live.usdtry;
  const badge = live.delayed ? "gecikmeli" : "canlı";

  const cards = ["gold", "silver"].map((key) => {
    const label = ASSETS[key].label;
    const spot = live[key];
    const close = comex[key];
    // Spot and the model's futures close differ by TWO things at once, and
    // the label has to say so: the futures-spot basis (financing + storage,
    // measured ~1% on both metals) AND whatever the market did since that
    // close, which can be days old. Calling the gap "basis" -- as an earlier
    // version did -- reports a stale price move as a financing cost.
    const gap = spot && close ? spot / close - 1 : null;
    const usd = spot ?? close;
    const digits = key === "silver" ? 3 : 2;

    // Arrow: today's session open, TradingView-only, and only against a
    // genuine live spot quote -- comparing a possibly days-old COMEX close to
    // TODAY's open would date-mismatch the two sides of the comparison.
    const open = live.open?.[key] ?? null;
    let dayChangePct = null;
    if (spot && open) {
      const pct = spot / open - 1;
      // Rounds to 0.00% at the precision actually shown -- an arrow claiming
      // a direction the reader cannot see the size of would overstate it.
      if (Math.abs(pct) >= 0.00005) dayChangePct = pct;
    }

    // Flash: did the number actually ON SCREEN just change, versus the last
    // render -- not the raw float, which jitters below what is displayed and
    // would flash on movement nobody can see. `null` the first time a value
    // appears, so the initial paint never flashes.
    const rounded = usd === null || usd === undefined ? null : usd.toFixed(digits);
    const prev = lastPaintedPrice[key];
    let flashClass = null;
    if (rounded !== null && prev !== null && rounded !== prev) {
      flashClass = Number(rounded) > Number(prev) ? "flash-up" : "flash-down";
    }
    if (rounded !== null) lastPaintedPrice[key] = rounded;

    return livePriceCard({
      label,
      metal: key,
      usd,
      usdtry,
      dayChangePct,
      flashClass,
      // The green "is-live" treatment tracks a REAL-TIME quote, not merely a
      // present one: a delayed feed still gets its number shown, but it must
      // not wear the styling that says "this is the price right now".
      live: Boolean(spot) && !live.delayed,
      badge: spot ? badge : "son kapanış",
      source: spot
        ? `Spot &middot; ${live.source}, 7/24`
        : `COMEX ${key === "gold" ? "GC=F" : "SI=F"} kapanışı &middot; ${asOf(rows[key])}`,
      footnote:
        spot && close
          ? `Model <strong>COMEX vadeli</strong> kapanışını kullanıyor: `
            + `${fmtUsd(close, key === "silver" ? 3 : 2)} (${asOf(rows[key])}). `
            + `Aradaki %${fmtNumber(Math.abs(gap * 100), 1)} fark iki şeyi birden içerir: `
            + `vadeli&ndash;spot bazı ve o kapanıştan bu yana olan hareket.`
          : spot
            ? ""
            : "Bu kaynaktan anlık fiyat alınamadı &mdash; gösterilen son kapanıştır.",
    });
  });
  document.getElementById("live-prices").innerHTML = cards.join("");

  // A refresh clock, and when the parity last actually MOVED.
  //
  // Without these the panel cannot distinguish "still updating" from "stuck",
  // and USDTRY makes that distinction constantly: measured 2026-09-08 it
  // produces a new value only about every 12 seconds and moves ~0.004% a
  // minute, so a correct, live page shows an unchanging parity most of the
  // time. Printing the poll time makes the loop visible; printing the last
  // change makes the stillness legible as the currency's, not the page's.
  const clock = (t) => (t ? new Date(t).toLocaleTimeString("tr-TR") : "-");
  const pulse =
    `<br />Son kontrol <strong>${clock(live.at)}</strong> `
    + `&middot; her ${Math.round(PRICE_REFRESH_MS / 1000)} saniyede bir. `
    + `Parite en son ${clock(lastChangedAt.usdtry)}'te değişti &mdash; USDTRY `
    + `ortalama 12 saniyede bir güncelleniyor, yani aynı sayıyı görmek normaldir.`;

  document.getElementById("live-note").innerHTML = usdtry
    ? `TL değerleri <strong>paritedir</strong>: dolar fiyatı × USDTRY `
      + `(${fmtNumber(usdtry, 4)}). Türkiye'de gram altın bu paritenin `
      + `<em>üzerinde</em> bir primle işlem görür, dolayısıyla bu sayı kuyumcu fiyatı değildir.`
      + pulse
    : "USDTRY alınamadı &mdash; TL karşılıkları gösterilemiyor.";
}

function renderComponents(row, asset) {
  const body = document.querySelector("#components-table tbody");
  if (!row) { body.innerHTML = ""; return; }

  body.innerHTML = COMPONENTS.map(({ key, label, weight }) => {
    const direction = row[`${key}_direction`];
    const confidence = row[`${key}_confidence`];
    if (direction === null || direction === undefined) {
      return `<tr><td>${label}</td><td colspan="4" class="silenced">veri yok</td></tr>`;
    }
    // Confidence 0 means the component abstained this cycle. That is normal,
    // designed behaviour for macro/news -- not a failure -- so it is labelled
    // rather than shown as a weak vote in some direction.
    const abstained = Number(confidence) <= 0;
    const isUp = direction === "UP";
    const influence = row[weight];
    return `
      <tr>
        <td>${label}</td>
        <td class="${abstained ? "silenced" : (isUp ? "up-text" : "down-text")}">
          ${abstained ? "sessiz" : (isUp ? "YÜKSELİŞ" : "DÜŞÜŞ")}
        </td>
        <td class="num">${abstained ? "-" : Number(confidence).toFixed(4)}</td>
        <td class="num">${abstained ? "-" : fmtUsd(row[`${key}_price`], asset.digits)}</td>
        <td class="num ${Number(influence) > 0 ? "" : "silenced"}">${fmtPct(influence, 0)}</td>
      </tr>`;
  }).join("");

  // The "Etki" column means two different things and the caption above it
  // only describes one of them. With component records, it is measured
  // influence and a component that never beat the base rate shows 0%. With
  // NO records -- every prediction until roughly a trading year of history
  // exists -- the blend runs ensemble._cold_start(), those numbers are the
  // DEFAULT weights its direction vote used, and rendering "25%" under a
  // caption about measured skill would claim a track record that does not
  // exist. `cold_start` is stored per row precisely so this can be said out
  // loud instead of inferred.
  //
  // `!== false` rather than truthy: rows written before the 2026-09-08
  // migration carry NULL here, and those are by construction the OLDEST rows
  // in the table -- i.e. exactly the cold-start period. Treating NULL as
  // "not a cold start" would suppress the warning on precisely the rows that
  // need it. Once a component earns a record, predict.py writes an explicit
  // false and the note disappears.
  const note = document.getElementById("components-note");
  if (row.cold_start !== false) {
    note.textContent =
      "Bileşenlerin henüz ölçülmüş sicili yok. Harman bu satırda taban orandan " +
      "başlayan bir yön oylaması kullandı; aşağıdaki “Etki” payları o oylamanın " +
      "varsayılan ağırlıkları, ölçülmüş katkı değil.";
    note.hidden = false;
  } else {
    note.hidden = true;
  }

  const reasoning = document.getElementById("claude-reasoning");
  reasoning.textContent = row.claude_reasoning ? `Claude: "${row.claude_reasoning}"` : "";
}

/* Weighted-average purchase price per (asset, strategy), replayed from the
   trade log.

   Average-cost method: a BUY adds ounces at its own price, a SELL removes
   ounces at the running average and therefore leaves that average unchanged.
   This is the only method that answers "what did the metal I am STILL holding
   cost me" -- FIFO would answer a different question and would disagree the
   moment a portfolio sells part of a position, which the volatility-targeted
   ones do routinely.

   Two different numbers live here and the panel keeps them apart:
     price  -- the market price on the tape. This is "kaç dolardan aldı".
     allIn  -- usd_amount / ounces, i.e. including the fee actually paid.
   The panel shows the market price (that is the question asked) and compares
   it to the current valuation price. Net-of-fee performance is already what
   the panel's total P&L reports, so showing the fee twice would double-count
   it. */
function costBasisByStrategy(trades) {
  const byKey = new Map();
  for (const trade of trades) {
    const key = `${trade.asset}|${trade.strategy}`;
    const state = byKey.get(key) ?? { ounces: 0, marketCost: 0, allInCost: 0 };
    const ounces = Number(trade.ounce_amount);
    if (!Number.isFinite(ounces) || ounces <= 0) continue;
    if (trade.side === "BUY") {
      state.marketCost += Number(trade.price) * ounces;
      state.allInCost += Number(trade.usd_amount);
      state.ounces += ounces;
    } else {
      // Reduce at the running average so the average survives the sale.
      const sold = Math.min(ounces, state.ounces);
      if (state.ounces > 0) {
        state.marketCost -= (state.marketCost / state.ounces) * sold;
        state.allInCost -= (state.allInCost / state.ounces) * sold;
      }
      state.ounces -= sold;
      // A fully closed position has no cost basis left to report.
      if (state.ounces <= 1e-9) { state.ounces = 0; state.marketCost = 0; state.allInCost = 0; }
    }
    byKey.set(key, state);
  }
  const out = new Map();
  for (const [key, s] of byKey) {
    out.set(key, s.ounces > 0
      ? { avgPrice: s.marketCost / s.ounces, avgAllIn: s.allInCost / s.ounces }
      : { avgPrice: null, avgAllIn: null });
  }
  return out;
}

// Quantity of metal, not a price -- gold positions sit around 0.2 oz and
// silver's around 15, so they need different precision to say anything. The
// gram is shown alongside because that is the unit this is bought in locally.
const fmtOunces = (v) => {
  const digits = currentAsset === "gold" ? 4 : 3;
  return `${fmtNumber(v, digits)} ons (${fmtNumber(v * TROY_OUNCE_GRAMS, 2)} g)`;
};

// What this portfolio would do on the backend's next run. Mirrors
// trading.compute_rebalance exactly, including the 5-point dead band -- the
// gap between "pozisyon" and "hedef" is otherwise a puzzle the reader has to
// solve, and the most common answer ("nothing, it is close enough") is the
// one a bare pair of percentages communicates worst.
function nextActionFor(state, price, exposure, value) {
  if (state.strategy === "kanalfinans") {
    // The follower has no target exposure at all: it is all-in or all-out on
    // a person's stated call (kanal_finans_trading.decide_on_mention), so
    // applying the drift rule here would invent a rule it does not follow.
    const stop = state.stop_loss_price
      ? ` Zarar-kes ${fmtUsd(state.stop_loss_price, ASSETS[currentAsset].digits)} altına inerse tamamen satar.`
      : "";
    return Number(state.ounces) > 0
      ? { kind: "hold", text: `Pozisyonda &mdash; sonraki video SAT diyene kadar tutar.${stop}` }
      : { kind: "hold", text: "Nakitte &mdash; sonraki video AL diyene kadar bekler." };
  }

  const target = Number(state.target_exposure);
  if (!Number.isFinite(target) || value <= 0 || price <= 0) {
    return { kind: "hold", text: "&mdash;" };
  }
  const drift = exposure - target;
  if (Math.abs(drift) <= REBALANCE_THRESHOLD) {
    // Below half a point the drift rounds to zero at one decimal, and
    // printing it anyway yields "−0,0 puan" -- a negative zero, which reads
    // as a real (downward) deviation when the portfolio is in fact exactly
    // on target.
    const detail = Math.abs(drift) < 0.005
      ? "Pozisyon hedefin tam üzerinde."
      : `Sapma ${fmtPoints(drift)}, eşik 5 puan.`;
    return { kind: "hold", text: `Dengede &mdash; işlem yok. ${detail}` };
  }
  if (drift > 0) {
    const ounces = Math.min(Number(state.ounces), (drift * value) / price);
    return {
      kind: "sell",
      text: `<strong>SATACAK</strong> &mdash; ${fmtOunces(ounces)} ≈ ${fmtUsd(ounces * price, 0)}.`,
    };
  }
  const usd = Math.min(Number(state.cash_usd), -drift * value);
  if (usd <= 0) return { kind: "hold", text: "Nakit kalmadı &mdash; alım yapamaz." };
  return {
    kind: "buy",
    text: `<strong>ALACAK</strong> &mdash; ${fmtUsd(usd, 0)} ≈ ${fmtOunces(usd / price)}.`,
  };
}

function renderStrategies(portfolios, price, asset, costBasis) {
  const mine = portfolios.filter((p) => p.asset === currentAsset);
  const byKey = new Map(mine.map((p) => [p.strategy, p]));
  const benchmark = byKey.get("buyhold");
  const benchmarkValue = benchmark
    ? Number(benchmark.cash_usd) + Number(benchmark.ounces) * price
    : null;

  document.getElementById("strategy-panels").innerHTML = STRATEGIES.map((strategy) => {
    const state = byKey.get(strategy.key);
    if (!state) {
      return `<div class="strategy-panel"><div class="name">${strategy.label}</div>
              <p class="desc">${strategy.desc}</p><div class="value">-</div></div>`;
    }
    const value = Number(state.cash_usd) + Number(state.ounces) * price;
    const pnl = value / STARTING_CASH - 1;
    const exposure = value > 0 ? (Number(state.ounces) * price) / value : 0;
    // Every panel also states how it stands against buy-and-hold, because
    // that comparison is the point and burying it elsewhere is how a reader
    // ends up not making it.
    const vsBenchmark =
      benchmarkValue && !strategy.benchmark ? value / benchmarkValue - 1 : null;

    // The follower portfolio watches a level rather than a target exposure,
    // so it shows that instead.
    const extraRow = strategy.follower
      ? `<div class="row"><span>zarar-kes</span><span>${
          state.stop_loss_price ? fmtUsd(state.stop_loss_price, asset.digits) : "yok"
        }</span></div>`
      : `<div class="row"><span>hedef</span><span>${fmtPct(state.target_exposure, 0)}</span></div>`;

    // "%17 pozisyon" is a ratio; these two are the holding itself, and they
    // are what the question "did it actually buy any gold?" is asking. A
    // dashboard that only ever prints ratios cannot answer it.
    const action = nextActionFor(state, price, exposure, value);
    // What the metal it still holds cost, and how the price has moved since.
    // This is a PRICE comparison, not net P&L: the panel's own percentage
    // above already carries the fees, and repeating them here would count
    // them twice.
    const basis = costBasis.get(`${currentAsset}|${strategy.key}`)
      ?? { avgPrice: null, avgAllIn: null };
    const sincePurchase = basis.avgPrice ? price / basis.avgPrice - 1 : null;

    return `
      <div class="strategy-panel${strategy.benchmark ? " benchmark" : ""}${strategy.follower ? " follower" : ""}">
        <div class="name">${strategy.label}${strategy.benchmark ? '<span class="badge">kıyas</span>' : ""}</div>
        <p class="desc">${strategy.desc}</p>
        <div class="value">${fmtUsd(value, 0)}</div>
        <!-- Not toFixed: this panel sat next to "%48,2" while printing
             "+0.02%", i.e. two decimal conventions on one screen. Turkish
             puts the sign OUTSIDE the percent sign -- "+%0,02", not "%+0,02". -->
        <div class="pnl ${pnl >= 0 ? "up-text" : "down-text"}">${fmtSignedPct(pnl)}</div>
        <div class="row"><span>pozisyon</span><span>${fmtPct(exposure, 0)}</span></div>
        ${extraRow}
        ${vsBenchmark === null ? "" : `
        <div class="row"><span>al-ve-tut'a göre</span>
          <span class="${vsBenchmark >= 0 ? "up-text" : "down-text"}">
            ${fmtSignedPct(vsBenchmark)}
          </span></div>`}
        <div class="exposure-bar"><div style="width:${Math.min(100, exposure * 100).toFixed(1)}%"></div></div>
        <div class="holding">
          <div class="row"><span>elindeki ${asset.label.toLowerCase()}</span>
            <span>${Number(state.ounces) > 0 ? fmtOunces(Number(state.ounces)) : "yok"}</span></div>
          <div class="row"><span>elindeki nakit</span>
            <span>${fmtUsd(state.cash_usd, 2)}</span></div>
          ${basis.avgPrice === null ? "" : `
          <div class="row"><span>aldığı fiyat</span>
            <span>${fmtUsd(basis.avgPrice, asset.digits)}</span></div>
          <div class="row"><span>o günden bu yana</span>
            <span class="${sincePurchase >= 0 ? "up-text" : "down-text"}">${fmtSignedPct(sincePurchase)}</span></div>`}
        </div>
        <div class="next-action ${action.kind}">Sonraki işlem: ${action.text}</div>
      </div>`;
  }).join("");
}

function renderHistory(rows, asset) {
  const body = document.querySelector("#history-table tbody");
  const mine = rows.filter((r) => r.asset === currentAsset);
  const resolved = mine.filter((r) => r.resolved_at);

  body.innerHTML = mine.map((row) => {
    const isUp = row.predicted_direction === "UP";
    const done = Boolean(row.resolved_at);
    // Both dates, always. With only the target date on screen, the newest row
    // -- which is normally still open -- shows a date in the FUTURE under a
    // panel about what already happened, and there is nothing to tell the
    // reader that is the target rather than the day it was made.
    return `
      <tr class="${done ? "" : "pending"}">
        <td>${fmtDate(row.created_at)}</td>
        <td>${fmtDate(row.target_date)}</td>
        <td class="num">${fmtUsd(row.price_at_prediction, asset.digits)}</td>
        <td class="${isUp ? "up-text" : "down-text"}">${isUp ? "YÜK" : "DÜŞ"}</td>
        <td class="num">${row.p_up == null ? "-" : fmtPct(row.p_up)}</td>
        <td class="num">${row.edge_over_base == null ? "-" : fmtPoints(row.edge_over_base)}</td>
        <td class="${!done ? "silenced" : (row.correct ? "up-text" : "down-text")}">
          ${!done ? "bekliyor" : (row.correct ? "doğru" : "yanlış")}
        </td>
        <td class="num">${done ? fmtUsd(row.price_at_resolution, asset.digits) : "-"}</td>
      </tr>`;
  }).join("");

  const summary = document.getElementById("history-summary");
  if (!resolved.length) {
    // "Henüz çözülmüş tahmin yok" on its own reads like a fault. It is not --
    // it is the expected state for the first five sessions of a five-day
    // horizon -- so it says WHY, and when that changes.
    const pending = mine.filter((r) => !r.resolved_at);
    summary.textContent = pending.length
      ? `${pending.length} tahmin açık, hiçbiri henüz puanlanmadı. İlk sonuç ` +
        `${fmtDate(pending[pending.length - 1].target_date)} seansı kapandığında çıkacak — ` +
        `5 işlem günlük ufuk gereği bu normaldir.`
      : "Henüz tahmin üretilmedi.";
    return;
  }
  const accuracy = resolved.filter((r) => r.correct).length / resolved.length;
  const actualUp = resolved.filter((r) => r.actual_direction === "UP").length / resolved.length;
  // The honest scoreboard: accuracy alone is meaningless against a base rate
  // this far from 50%, so the comparison is printed with it, always.
  const verdict = accuracy > actualUp
    ? "hep-YÜKSELİŞ demekten iyi"
    : "hep-YÜKSELİŞ demekten iyi DEĞİL";
  summary.textContent =
    `${resolved.length} çözülmüş tahmin · isabet ${fmtPct(accuracy)} · ` +
    `aynı dönemde fiyat ${fmtPct(actualUp)} oranında yükselmiş → model ${verdict}.`;
}

function renderKanalFinans(mentions, themes) {
  const body = document.querySelector("#kf-mentions-table tbody");
  if (!mentions.length) {
    body.innerHTML = `<tr><td colspan="8" class="silenced">Henüz işlenmiş video yok.</td></tr>`;
  } else {
    body.innerHTML = mentions.slice(0, 12).map((m) => {
      const stanceClass = m.stance === "UP" ? "up-text" : m.stance === "DOWN" ? "down-text" : "silenced";
      return `
        <tr>
          <td>${fmtDate(m.published_at)}</td>
          <td>${KF_ASSET_LABEL[m.asset] ?? m.asset}</td>
          <td class="${stanceClass}">${KF_STANCE[m.stance] ?? m.stance}</td>
          <td><span class="action action-${m.action.toLowerCase()}">${KF_ACTION[m.action] ?? m.action}</span></td>
          <td class="num">${m.ounce_target ? fmtUsd(m.ounce_target) : "-"}</td>
          <td class="num">${m.stop_loss_price ? fmtUsd(m.stop_loss_price) : "-"}</td>
          <td class="num">${m.resistance_price ? fmtUsd(m.resistance_price) : "-"}</td>
          <td class="summary-cell">${m.summary}</td>
        </tr>`;
    }).join("");
  }

  const box = document.getElementById("kf-themes");
  if (!themes.length) {
    box.innerHTML = `<p class="muted small">Henüz tema çıkarılmadı.</p>`;
    return;
  }
  // Only the most recent video's themes: an unfiltered list turns into
  // dozens of rows of stale narrative the moment a backfill runs.
  const newestVideo = themes[0].video_id;
  const latest = themes.filter((t) => t.video_id === newestVideo);
  box.innerHTML = latest.map((t) => `
    <div class="theme theme-${t.impact.toLowerCase()}">
      <div class="theme-head">
        <span class="theme-name">${KF_THEME_LABEL[t.theme] ?? t.theme}</span>
        <span class="theme-impact">madenlere etkisi: ${KF_IMPACT[t.impact] ?? t.impact}</span>
      </div>
      <div class="theme-body">${t.summary}</div>
    </div>`).join("")
    + `<p class="muted small">${fmtDate(latest[0].published_at)} tarihli videodan.</p>`;
}

/* The price the portfolios are marked at.

   Live COMEX futures when available, the stored close otherwise -- NEVER
   spot, which would inject the futures-spot basis as a phantom loss (see the
   TV_FUTURES note). Returns the provenance too, because a portfolio value
   that moves intraday and one frozen at Friday's close are different claims
   and the panel has to be able to say which it is showing. */
function valuationPrice(assetKey) {
  const stored = Number(cache.predictions[assetKey]?.[0]?.price_at_prediction);
  const futures = cache.live?.futures?.[assetKey] ?? null;
  if (futures) return { price: futures, live: true };
  return { price: Number.isFinite(stored) ? stored : 0, live: false };
}

function renderValuationNote(asset, mark) {
  const el = document.getElementById("valuation-note");
  if (!el) return;
  const row = cache.predictions[currentAsset]?.[0];
  el.innerHTML = mark.live
    ? `Değerleme fiyatı <strong>${fmtUsd(mark.price, asset.digits)}</strong> `
      + `&mdash; ${currentAsset === "gold" ? "COMEX:GC1!" : "COMEX:SI1!"} vadeli, `
      // Derived, never typed: this sentence said "5 saniyede bir" for one
      // commit after the loop moved to 2s.
      + `<strong>10 dakika gecikmeli</strong>, ${Math.round(PRICE_REFRESH_MS / 1000)} `
      + `saniyede bir yenileniyor. `
      + `Spot değil vadeli kullanılıyor: portföyler vadeli fiyattan alındı ve vadeliden `
      + `satılacak, spotla değerlemek ~%1'lik vadeli&ndash;spot bazını sahte bir zarar `
      + `gibi yazardı.`
    : `Değerleme fiyatı <strong>${fmtUsd(mark.price, asset.digits)}</strong> `
      + `&mdash; canlı vadeli alınamadı, son COMEX kapanışı kullanılıyor`
      + `${row?.created_at ? ` (${fmtDate(row.created_at)})` : ""}. `
      + `Bu değerler kapanış anında donmuştur.`;
}

function renderAll() {
  const asset = ASSETS[currentAsset];
  // Repaints every asset-scoped card in the selected metal's colour. The
  // numbers below the tab strip are mostly percentages that look identical
  // between the two assets, so this is the cue that they changed meaning.
  document.getElementById("app").dataset.asset = currentAsset;
  const row = cache.predictions[currentAsset]?.[0] ?? null;
  const mark = valuationPrice(currentAsset);

  renderPrediction(row, asset);
  renderContext(row, asset);
  renderComponents(row, asset);
  renderStrategies(cache.portfolios, mark.price, asset, cache.costBasis);
  renderValuationNote(asset, mark);
  renderHistory(cache.predictions[currentAsset] ?? [], asset);
}

/* ------------------------------------------------------------------ load */

// Declared before its use in loadData rather than after: a `const` is in the
// temporal dead zone until evaluated, so the current bottom-of-file call
// order is the only thing that makes a later declaration work.
const EMPTY_LIVE = { gold: null, silver: null, usdtry: null, futures: {}, open: {}, delayed: false, source: "" };

/* Supabase data. One row per trading day, so this stays on the slow cycle --
   polling it every few seconds would re-download identical bytes. */
async function loadData() {
  try {
    const [gold, silver, portfolios, trades, mentions, themes] = await Promise.all([
      api("predictions?select=*&asset=eq.gold&order=target_date.desc&limit=30"),
      api("predictions?select=*&asset=eq.silver&order=target_date.desc&limit=30"),
      api("portfolios?select=*"),
      // Ascending and complete: the average-cost replay has to see every fill
      // in the order it happened, so this is the one query that pages.
      apiAll("trades?select=asset,strategy,side,price,ounce_amount,usd_amount&order=created_at.asc"),
      api("kanal_finans_mentions?select=*&order=published_at.desc&limit=40"),
      api("kanal_finans_themes?select=*&order=published_at.desc&limit=40"),
    ]);

    cache.predictions = { gold, silver };
    cache.portfolios = portfolios;
    cache.mentions = mentions;
    cache.themes = themes;
    cache.costBasis = costBasisByStrategy(trades);

    // The gold/silver ratio is not per-asset, so it renders outside the
    // per-asset block. Prefer the value predict.py stored (it comes from the
    // same aligned panel the model sees) and fall back to dividing the two
    // latest prices, which is right whenever both rows are from the same day
    // and quietly wrong when one metal's row is staler than the other's.
    renderRatio(gold[0], silver[0]);
    // Renders the COMEX-close fallback if the fast loop has not landed yet,
    // so the panel is never blank while prices are in flight.
    renderLivePrices(cache.live ?? EMPTY_LIVE, gold[0], silver[0]);
    renderKanalFinans(mentions, themes);
    renderAll();
  } catch (error) {
    showError(error.message);
  }
}

// Last known Binance quotes, refreshed on their own slower timer. Kept as
// module state so a cycle that skips the fetch still has a fallback in hand.
let binanceCache = { paxg: null, usdtry: null };
// When each quoted value last actually CHANGED, as opposed to when it was
// last polled. On a series that ticks every ~12 seconds these are different
// facts, and it is the second one that tells a reader the page is alive.
let lastChangedAt = { usdtry: null };
let binanceFetchedAt = 0;

// The DISPLAYED (rounded) price last painted for each live card, used only to
// decide whether to flash on the next render. Rounded rather than raw: the
// feed sometimes jitters in a decimal the card does not even show, and
// flashing on a change nobody can see would just be noise. Separate from the
// day-open comparison below -- this is "did the number just move", not
// "is today red or green".
let lastPaintedPrice = { gold: null, silver: null };

async function refreshBinance() {
  const [paxg, usdtry] = await Promise.all([
    fetchBinance("PAXGUSDT"), fetchBinance("USDTTRY"),
  ]);
  binanceFetchedAt = Date.now();
  // A failed leg keeps its previous value rather than blanking the fallback:
  // a slightly stale backup is worth more than no backup, and this value is
  // only ever read when TradingView is already down.
  binanceCache = {
    paxg: paxg ?? binanceCache.paxg,
    usdtry: usdtry ?? binanceCache.usdtry,
  };
  return binanceCache;
}

/* Prices. Fast loop, and the only thing on the page that actually moves
   intraday: the two live cards, every portfolio's value, and the next-order
   line that depends on it. */
async function refreshPrices() {
  // A hidden tab renders to nobody. Skipping the fetch is what keeps a
  // forgotten background tab from making 720 requests an hour at an
  // undocumented endpoint.
  if (document.hidden) { schedulePrices(); return; }

  // TradingView every cycle; Binance only when its own timer is due, because
  // it is a fallback and not the feed being watched. See BINANCE_REFRESH_MS.
  const binanceDue = Date.now() - binanceFetchedAt >= BINANCE_REFRESH_MS;
  const [tv, binance] = await Promise.all([
    fetchTradingView(),
    binanceDue ? refreshBinance() : Promise.resolve(binanceCache),
  ]);
  // No "refetch immediately because TradingView failed" branch, deliberately.
  // `!binanceDue` already means the cache is younger than BINANCE_REFRESH_MS,
  // so there is nothing fresher to fetch -- and an outage is exactly when the
  // condition holds on every single cycle. A simulated 60s TradingView outage
  // with that branch in place made 3720 Binance requests an hour instead of
  // 360: the backoff never engages, because Binance is still answering.
  // The first cycle needs no special case either; binanceFetchedAt starts at
  // 0, so binanceDue is true and the fallback is fetched before it is read.
  const paxg = binance.paxg;
  const binanceFx = binance.usdtry;

  if (!tv && paxg === null && binanceFx === null) {
    // Everything failed. Keep the last good prices on screen rather than
    // blanking them, and back off before trying again.
    priceFailures += 1;
    schedulePrices();
    return;
  }
  priceFailures = 0;

  // TradingView first because it is the only source that carries silver.
  // Binance fills whatever it left null -- gold and FX only, since it has no
  // silver at all -- and silver then falls through to its last COMEX close,
  // labelled as such by the renderer.
  const usdtry = tv?.usdtry ?? binanceFx;
  // Record the moment the parity actually moved, not merely the moment it was
  // polled -- the two are far apart on a series that ticks every ~12 seconds.
  if (usdtry !== null && usdtry !== cache.live?.usdtry) {
    lastChangedAt.usdtry = Date.now();
  }

  cache.live = {
    gold: tv?.gold ?? paxg,
    silver: tv?.silver ?? null,
    usdtry,
    futures: tv?.futures ?? {},
    open: tv?.open ?? {},
    delayed: tv?.delayed ?? false,
    source: tv?.gold ? tv.source : "Binance",
    at: Date.now(),
  };

  const gold = cache.predictions.gold?.[0];
  const silver = cache.predictions.silver?.[0];
  renderLivePrices(cache.live, gold, silver);

  // Portfolio value is ounces x price, so it moves on this tick too -- along
  // with the exposure it implies and therefore the next order.
  if (cache.portfolios.length) {
    const asset = ASSETS[currentAsset];
    const mark = valuationPrice(currentAsset);
    renderStrategies(cache.portfolios, mark.price, asset, cache.costBasis);
    renderValuationNote(asset, mark);
  }
  schedulePrices();
}

function schedulePrices() {
  clearTimeout(priceTimer);
  const delay = priceFailures === 0
    ? PRICE_REFRESH_MS
    : Math.min(PRICE_BACKOFF_MAX_MS, PRICE_REFRESH_MS * 2 ** priceFailures);
  priceTimer = setTimeout(refreshPrices, delay);
}

document.getElementById("asset-tabs").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-asset]");
  if (!button) return;
  currentAsset = button.dataset.asset;
  document.querySelectorAll("#asset-tabs button")
    .forEach((b) => b.classList.toggle("active", b === button));
  // Re-render from cache rather than re-fetching: both assets were loaded in
  // the same round trip, so switching tabs should be instant.
  renderAll();
});

loadData();
refreshPrices();
// The backend produces one row per trading day, so polling faster than this
// would just re-fetch identical data. Five minutes keeps a left-open tab
// current without hammering Supabase. Prices run their own loop.
setInterval(loadData, DATA_REFRESH_MS);

// Coming back to a backgrounded tab should not show a price up to five
// seconds -- or, after a backoff, a minute -- old. Refreshing on the way in
// also resets any backoff that accumulated while nobody was looking.
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) { priceFailures = 0; refreshPrices(); }
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}
