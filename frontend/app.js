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
// `feeBps` is assets.Asset.fee_rate in basis points, ONE WAY. Display only --
// the backend charges the real thing -- but it is the number that decides
// whether a strategy could have kept what it earned, so the trade log prints
// it next to the commission actually paid.
const ASSETS = {
  gold: { label: "Altın", baseRate: 0.557, unit: "ons", digits: 2, feeBps: 5 },
  silver: { label: "Gümüş", baseRate: 0.539, unit: "ons", digits: 3, feeBps: 10 },
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
  { key: "buyhold", label: "Al-ve-tut", benchmark: true, mechanical: true,
    desc: "Hiçbir şey yapma. Kıyas ölçütü: 25 yılda yıllık ~%11,8." },
  { key: "voltarget", mechanical: true, label: "Oynaklık hedefi",
    desc: "Pozisyonu gerçekleşen oynaklığa göre ölçekler. Ölçümde işe yarayan tek mekanizma." },
  { key: "trend", mechanical: true, label: "Trend filtresi",
    desc: "200 günlük ortalamanın altında pozisyonu kısar. Ayıda kazanır, boğada öder." },
  { key: "defensive", mechanical: true, label: "Savunma",
    desc: "Oynaklık + trend birlikte. En düşük düşüş, en düşük getiri." },
  { key: "ensemble", label: "Harman",
    desc: "Tüm sinyaller + risk kuralları." },
  { key: "technical", label: "Sadece teknik", desc: "Yalnızca kural tabanlı teknik sinyal." },
  { key: "ml", label: "Sadece ML", desc: "Yalnızca gradient boosting modeli." },
  { key: "macro", label: "Sadece makro", desc: "Yalnızca ölçülmüş öncü sürücüler." },
  { key: "claude", label: "Sadece Claude", desc: "Yalnızca Claude'un bağımsız yargısı." },
  { key: "miners", label: "Madenciler", desc:
    "GDX (altın madencileri ETF'i) bugün yükseldiyse yarın pozisyonu artırır. " +
    "Tek günlük ufuk. Kazancı VADELİ kontrat üzerinde ölçüldü ve büyük ölçüde " +
    "seans saatlerinden geliyor: GC=F 17:00'da, GDX 16:00'da kapanıyor. " +
    "GLD/IAU/SLV gibi ETF'lerde bu saat farkı yok ve kazanç kayboluyor " +
    "(öncü korelasyon +0,150 → +0,040). Satın alınabilir bir strateji DEĞİL." },
  { key: "kanalfinans", label: "Kanal Finans TŞ", follower: true,
    desc: "Tunç Şatıroğlu ne derse onu yapar. Tam giriş/çıkış, zarar-kes takipli." },
  // Like `follower`: all-in/all-out on a discrete state, not a target
  // exposure, so it is drawn in its OWN card (Kırılım Takibi) beside the
  // measurement that says it loses -- not in the grid of measured rules.
  { key: "breakout", label: "Kırılım kuralı", breakoutBook: true,
    desc: "Değer alanı kırılınca tam girer, stop ya da trend kırılınca tam çıkar. "
        + "Ölçümde al-ve-tut'u geçemedi; defter bunu canlı göstermek için var." },
];

// Order is the legend order AND the order chart.js's palette was validated
// in, adjacent pair by adjacent pair. Reordering this list silently changes
// which hues sit next to each other and invalidates that check.
const BACKTEST_SERIES = ["voltarget", "trend", "defensive", "ensemble",
                         "technical", "ml", "macro", "miners"];

// What the line is called ON the plot, where the label has to fit inside the
// right margin rather than a legend row. "Oynaklık hedefi" clipped to
// "Oynaklık h" at the first render, which is worse than no label.
const BACKTEST_SHORT = {
  buyhold: "Al-ve-tut", voltarget: "Oynaklık", trend: "Trend", defensive: "Savunma",
  ensemble: "Harman", technical: "Teknik", ml: "ML", macro: "Makro", miners: "Madenci",
  claude: "Claude", kanalfinans: "Kanal F.", breakout: "Kırılım",
};

const STARTING_CASH = 1000;

// Resolved rows needed before the track-record panel is willing to rank the
// model against "always UP". One trading quarter. Below that the two rates
// swap places on noise alone, and printing a winner would be exactly the
// overstatement backend/research/ablation.py exists to prevent.
const MIN_ROWS_FOR_VERDICT = 60;

// Fills shown inside one book's panel. The user's number, and it fits the
// question: "did this rule do anything lately", not "what is its history".
// Every book on the page carries its own log now, so this is a per-panel cap
// rather than a cap on one interleaved ledger -- eleven metal books plus four
// ETF books at six lines each, instead of fifteen lines shared by all of them.
const BOOK_LOG_ROWS = 6;

// Mirrors ensemble.SHRINK_ALPHA. Below this many calls on one side, the
// backend's own pooling still shrinks that side hard toward its
// no-information rate, so the measured percentage is not yet a track record
// -- the table prints it, and pointedly does not colour it.
const THIN_RECORD_CALLS = 60;

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

// The tradeable ETFs (backend/assets.TRACKED). Their books are valued on
// these, and they ride in the SAME request as everything else -- one more
// ticker in the existing POST, not a second round trip.
//
// Kept out of TV_TICKERS on purpose, for the same reason TV_FUTURES is: only
// the SPOT tickers decide the "gecikmeli" badge. An ETF quote folded into
// that calculation would let a delayed listing permanently brand the
// real-time spot cards as delayed.
const TV_ETFS = { gld: "AMEX:GLD", slv: "AMEX:SLV" };
// Measured 2026-09-11, BOTH legs: AMEX:GLD and AMEX:SLV each come back
// `delayed_streaming_900`, i.e. 15 minutes behind, against the futures legs'
// 600. Printed on the card for the same reason the futures delay is -- a value
// that lags by a quarter hour and one that does not are different claims, and
// the panel has to say which. Checked for silver rather than assumed from
// gold: a shared constant covering an unmeasured listing is how a delay claim
// goes quietly wrong.
const ETF_DELAY_MINUTES = 15;
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
  trades: [], records: [],
  costBasis: new Map(),
  // Filled by the fast price loop, not by the Supabase load.
  live: null,
  // The measured history. A static file written by backend/export_backtest.py
  // and fetched ONCE per session -- it changes only when someone deliberately
  // re-runs the backtest, so re-downloading 160 KB on every five-minute cycle
  // would be the same mistake polling Supabase every two seconds would be.
  backtest: null,
  // The breakout panel's window. `null` means "not loaded or unavailable",
  // which renderBreakout says out loud rather than drawing an empty chart
  // under a heading that keeps promising one.
  breakout: null,
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

// A drawdown, already in percentage points and always <= 0. Turkish puts the
// sign OUTSIDE the percent sign, so this is "−%12" and never "-12%" -- the
// same rule the chart's own y-axis labels follow.
const fmtDrawdown = (v) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "-"
    : `${Number(v) < 0 ? "−%" : "%"}${fmtNumber(Math.abs(Number(v)), 0)}`;

const fmtPoints = (v, digits = 1) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "-"
    : `${fmtSigned(Number(v) * 100, digits)} puan`;

const fmtDate = (v) => (v ? String(v).slice(0, 10) : "-");

// DD.MM, for a book's own log. The combined log needed the clock because nine
// portfolios rebalance off one signal and printed as nine same-day rows; a
// single book fills at most once on most days, so the time was noise in a
// column that has to fit a panel.
const fmtDayMonth = (v) => {
  const when = new Date(v);
  if (Number.isNaN(when.getTime())) return fmtDate(v);
  return `${String(when.getDate()).padStart(2, "0")}.`
    + String(when.getMonth() + 1).padStart(2, "0");
};

const fmtDateTime = (v) => {
  if (!v) return "-";
  const when = new Date(v);
  return Number.isNaN(when.getTime())
    ? fmtDate(v)
    : `${fmtDate(v)} ${when.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })}`;
};

/* Every string that reaches innerHTML and did NOT come from this file.

   Most text on this page is written by the backend and safe, but three fields
   are not: kanal_finans_mentions.summary, kanal_finans_themes.summary and the
   video title are Claude's transcription of whatever a YouTube video said,
   stored verbatim. A `<` in a spoken price range ("<4400") already breaks the
   markup, and an `<img onerror=...>` in that text would execute -- innerHTML
   does not run <script>, which is exactly why people assume it is safe and
   then use an attribute handler instead.

   textContent would also be safe but costs the per-cell markup these tables
   are built from, so the escape happens at the value instead. */
const esc = (v) =>
  String(v ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");

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
        symbols: { tickers: [...Object.values(TV_TICKERS), ...Object.values(TV_FUTURES),
                              ...Object.values(TV_ETFS)] },
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
      // What the tracked-ETF books are marked to.
      etfs: { gld: read(TV_ETFS.gld), slv: read(TV_ETFS.slv) },
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

/* The condensed quote pair in the sticky header.

   Deliberately a SUMMARY of the Anlık Fiyatlar card and never a second source:
   it is handed the same `live` object and the same COMEX fallback, so the two
   can disagree only if one of them is not rendered. What it drops is exactly
   the provenance -- the TL parity, the source line, the futures-spot gap --
   because those are claims that need room to be stated correctly, and a strip
   in a header does not have it. So the strip never wears the "canlı" badge or
   the live styling either: the card above is where a price gets qualified.

   Each metal keeps its OWN palette (.metal-gold / .metal-silver) rather than
   following the active tab, for the same reason the price cards do -- both are
   on screen at once, so a shared accent would say they are the same number. */
function renderTopbarQuotes(live, comex) {
  const strip = document.getElementById("topbar-quotes");
  if (!strip) return;
  strip.innerHTML = ["gold", "silver"].map((key) => {
    const spot = live[key];
    const usd = spot ?? comex[key];
    if (usd === null || usd === undefined) return "";
    const open = live.open?.[key] ?? null;
    const pct = spot && open ? spot / open - 1 : null;
    // Same visibility floor as the card's arrow: below half a basis point the
    // move is smaller than the digits on screen, and an arrow the reader
    // cannot size is an overstatement.
    const show = pct !== null && Math.abs(pct) >= 0.00005;
    return `<div class="topbar-quote metal-${key}">
      <span class="tq-label">${key === "gold" ? "XAU" : "XAG"}</span>
      <span class="tq-value">${fmtUsd(usd, key === "silver" ? 3 : 2)}</span>
      ${show ? `<span class="tq-chg ${pct >= 0 ? "up-text" : "down-text"}">
        ${pct >= 0 ? "▲" : "▼"} ${fmtSignedPct(pct)}</span>` : ""}
    </div>`;
  }).join("");
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
  renderTopbarQuotes(live, comex);

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

/* Each component's measured track record, per asset (`model_state`).

   This is the evidence the "Etki" column above is derived from, and until now
   it existed only in retrain.py's nightly console output -- i.e. nowhere a
   person actually looks. It is the project's own named example of a failure
   that produces no error: "a component that has said UP on 121 of 127
   opportunities is not a signal, it is a constant, and on an asset that rises
   54-56% of the time it will still post a respectable-looking accuracy."

   WHAT IS DELIBERATELY NOT DONE HERE: recomputing the log-odds evidence.
   ensemble.component_evidence() shrinks each side toward its own
   no-information rate and caps the result, and a second copy of that
   arithmetic in JavaScript would be a decision rule maintained in two places
   -- the exact thing backend/backtest.py refuses to do by calling the live
   functions directly. So this table shows the four RAW counters plus the rate
   each side has to beat, and leaves the pooling to the backend. */
function renderRecords(records, asset, row) {
  const body = document.querySelector("#record-table tbody");
  const note = document.getElementById("record-note");
  const mine = new Map(
    records.filter((r) => r.asset === currentAsset).map((r) => [r.component, r]));

  const baseUp = Number(row?.base_rate_used ?? asset.baseRate);
  let anyHistory = false;

  body.innerHTML = COMPONENTS.map(({ key, label }) => {
    // model_state keys components by their long name; the predictions table
    // shortens "technical" to "tech". COMPONENTS carries the short one.
    const component = key === "tech" ? "technical" : key;
    const record = mine.get(component);
    const upCalls = Number(record?.up_calls ?? 0);
    const downCalls = Number(record?.down_calls ?? 0);
    const total = upCalls + downCalls;
    if (!total) {
      return `<tr><td>${label}</td><td colspan="5" class="silenced">henüz çağrı yok</td></tr>`;
    }
    anyHistory = true;
    const upRate = upCalls ? Number(record.up_correct) / upCalls : null;
    const downRate = downCalls ? Number(record.down_correct) / downCalls : null;

    // Each side beats a DIFFERENT bar. A component that always says UP is
    // right at the base rate by construction; one that always says DOWN is
    // right only when the metal falls, i.e. 1 - base rate. Shrinking both
    // toward the same number is a bug this project already shipped once.
    //
    // A thin record is shown but NOT coloured. ensemble.SHRINK_ALPHA pulls a
    // short history toward its no-information rate, so a component with five
    // calls contributes essentially nothing to the blend no matter what those
    // five did -- and painting "100%" green over one lucky call would say the
    // opposite of what the backend is actually doing with it.
    const cell = (rate, calls, bar) => {
      if (rate === null) return `<td class="num silenced">-</td>`;
      const thin = calls < THIN_RECORD_CALLS;
      const tone = thin ? "silenced" : (rate > bar ? "up-text" : "silenced");
      return `<td class="num ${tone}">${fmtPct(rate)}`
        + `<span class="muted small"> / ${fmtPct(bar)}${thin ? " · az" : ""}</span></td>`;
    };

    // >90% on one side, with enough calls to mean it: a constant, not a
    // forecast. retrain.py prints the same warning nightly.
    const skew = Math.max(upCalls, downCalls) / total;
    const oneSided = skew > 0.9 && total >= 30
      ? `<td class="down-text">EVET &mdash; sabit gibi</td>`
      : `<td class="silenced">hayır</td>`;

    return `
      <tr>
        <td>${label}</td>
        <td class="num">${upCalls}</td>
        ${cell(upRate, upCalls, baseUp)}
        <td class="num">${downCalls}</td>
        ${cell(downRate, downCalls, 1 - baseUp)}
        ${oneSided}
      </tr>`;
  }).join("");

  // No suffix on a number whose reading changes with its value: "%55,7'yi"
  // and "%44,3'ü" take different Turkish endings, and the numbers here come
  // from the row. Phrased so the percentage is never inflected.
  note.innerHTML = anyHistory
    ? `İsabetin yanındaki ikinci sayı o tarafın <strong>bilgisizlik noktasıdır</strong> `
      + `&mdash; YÜKSELİŞ çağrıları için ${fmtPct(baseUp)}, DÜŞÜŞ çağrıları için `
      + `${fmtPct(1 - baseUp)}. Bu eşiğin altında kalan bir bileşen harmanda otomatik `
      + `olarak susturulur ve yukarıda &ldquo;Etki %0&rdquo; görünür. `
      + `&ldquo;az&rdquo; işareti ${THIN_RECORD_CALLS} çağrıdan az olan tarafı gösterir: `
      + `harman böyle bir sicili zaten bilgisizlik noktasına doğru büzer, o yüzden `
      + `oran ne olursa olsun karara katkısı yok denecek kadar azdır.`
    : `Henüz hiçbir bileşenin çözülmüş çağrısı yok. Sicil, tahminlerin hedef seansı `
      + `geldikçe (5 işlem günü) dolmaya başlar.`;
}

/* The fill price at READING precision, about five significant digits.
 *
 * Not the asset's own `digits`: that is the precision a price is QUOTED at,
 * and the log is not the place it is needed -- the same panel prints the
 * book's average purchase price two rows above, in full. What the log needs
 * is a number that fits beside a date, a side and an amount inside a panel
 * that is ~170px wide in the narrowest two-column layout. "$4.476,60" wraps
 * to its own line there; "$4.477" does not, and says the same thing about a
 * fill. Silver keeps its cents, because "$66" would not.
 */
function logPriceDigits(price) {
  const p = Math.abs(Number(price));
  if (!Number.isFinite(p)) return 2;
  return p >= 1000 ? 0 : p >= 100 ? 1 : 2;
}

/* EACH BOOK'S OWN LAST FEW FILLS, drawn inside that book's own panel.
 *
 * This replaced two combined trade logs -- one under the metals' portfolios,
 * one at the foot of the ETF card -- and the change is not cosmetic. A single
 * log sorted by time interleaves eleven books, so the question a reader
 * actually has ("what did THIS rule do") was answered by scanning a strategy
 * column across fifteen rows, and any book quiet for a fortnight vanished
 * from the log entirely while looking perfectly healthy in its panel. Six
 * fills per book answers it per book, and a book with nothing to show says so.
 *
 * What it deliberately does NOT carry: the reason string (a sentence of prose
 * cannot share a 220px panel with four numbers) and the per-fill commission
 * (rolled into the header, where the total is the number that decides whether
 * any of this was worth doing). The full history is a query away, and the
 * page is not the place to hold it.
 *
 * No <table>: below 700px every table on this page turns into label/value
 * blocks, which for a four-column log would be twenty-four lines per book.
 * This is a list, so it reads the same at every width.
 *
 * Newest first; the cost-basis replay needs the opposite order and gets its
 * own copy, so neither reverses the other's array in place. */
function bookLogHtml(assetKey, strategyKey) {
  const mine = (cache.trades ?? []).filter(
    (t) => t.asset === assetKey && t.strategy === strategyKey);
  if (!mine.length) {
    // Said out loud rather than left blank: "this book has not traded" is a
    // fact about the rule (buy-and-hold fills once, ever), and an empty space
    // there reads as a panel that failed to load.
    return `<div class="book-log"><div class="book-log-head">`
      + `<span>işlemler</span><span class="muted">henüz yok</span></div></div>`;
  }
  const fees = mine.reduce((sum, t) => sum + (Number(t.fee_usd) || 0), 0);
  const rows = [...mine].reverse().slice(0, BOOK_LOG_ROWS).map((t) => {
    const buy = t.side === "BUY";
    return `<li><span class="when">${fmtDayMonth(t.created_at)}</span>`
      + `<span class="action action-${buy ? "buy" : "sell"}">${buy ? "AL" : "SAT"}</span>`
      + `<span class="amt">${fmtUsd(t.usd_amount, 0)}</span>`
      + `<span class="at">${fmtUsd(t.price, logPriceDigits(t.price))}</span></li>`;
  }).join("");
  return `<div class="book-log">
      <div class="book-log-head">
        <span>${mine.length} işlem${mine.length > BOOK_LOG_ROWS
          ? ` · son ${BOOK_LOG_ROWS}` : ""}</span>
        <span class="muted">${fmtUsd(fees, 2)} komisyon</span>
      </div>
      <ul>${rows}</ul>
    </div>`;
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
    const state = byKey.get(key) ?? { ounces: 0, marketCost: 0, allInCost: 0, lastAt: null };
    const ounces = Number(trade.ounce_amount);
    if (!Number.isFinite(ounces) || ounces <= 0) continue;
    // The rows arrive ordered by created_at ascending, so the last one seen is
    // the most recent. Carried because "what did it pay" and "when did it last
    // do anything" are different questions and a portfolio box answers neither
    // on its own -- it looks identical whether the position was set yesterday
    // or three weeks ago.
    state.lastAt = trade.created_at ?? state.lastAt;
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
      ? { avgPrice: s.marketCost / s.ounces, avgAllIn: s.allInCost / s.ounces,
          lastAt: s.lastAt }
      : { avgPrice: null, avgAllIn: null, lastAt: s.lastAt });
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
/* The newest published breakout row for the selected metal, or null.

   Shared by the book panel's "next action" line and the card itself, so the
   two cannot say different things about the same level -- which they would
   the first time one of them was edited. */
function breakoutLatest() {
  const mine = (cache.breakout ?? []).filter((r) => r.asset === currentAsset);
  if (!mine.length) return null;
  return mine.reduce((newest, r) =>
    String(r.session_date) > String(newest.session_date) ? r : newest);
}

function nextActionFor(state, price, exposure, value) {
  if (state.strategy === "breakout") {
    // No target exposure at all, so the drift rule below would invent a
    // rule this book does not follow -- same reason `kanalfinans` branches
    // out here. What it DOES have is a pair of named levels, and those are
    // the answer to "what is it waiting for".
    const row = breakoutLatest();
    const asset = ASSETS[currentAsset];
    const usd = (v) => fmtUsd(v, asset.digits);
    if (Number(state.ounces) > 0) {
      const stop = row?.stop ? ` Stop ${usd(row.stop)} altına inerse` : " Stop kırılırsa";
      const avwap = row?.avwap ? ` ya da iki seans ${usd(row.avwap)} altında kapanırsa` : "";
      return { kind: "hold",
               text: `Pozisyonda &mdash; trend kırılana kadar tutar.${stop}${avwap} tamamen satar.` };
    }
    if (!row?.vah) {
      return { kind: "hold", text: "Nakitte &mdash; kırılım bekliyor." };
    }
    const away = price > 0 ? row.vah / price - 1 : null;
    const gap = away === null ? "" : ` (${fmtSignedPct(away)})`;
    return { kind: "hold",
             text: `Nakitte &mdash; ${usd(row.vah)} üzeri kapanış${gap} bekliyor; `
                 + `ayrıca AVWAP üstü, pozitif akış ve en az `
                 + `${BREAKOUT_VERDICT[currentAsset].minConfirmations} onay şart.` };
  }

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

/* ------------------------------------------------- the live books, charted */

// Legend order for the live chart. The first eight are BACKTEST_SERIES, in
// the same order and the same colours, so "blue is voltarget" survives
// between the two charts. `claude` and `kanalfinans` only exist here -- the
// first cannot be backtested at all, the second follows a person rather than
// a rule -- and they are APPENDED rather than slotted in beside their
// neighbours in STRATEGIES: with `claude` sitting between macro and miners,
// the tan and the red became adjacent and that pair failed the palette's
// normal-vision floor. See chart.js.
const LIVE_SERIES = [...BACKTEST_SERIES, "claude", "kanalfinans", "breakout"];

let liveSelection = new Set(["voltarget", "ensemble"]);

/* When each book OPENED, for books that did not start with the others.
 *
 * Without this the replay below starts every curve at $1,000 on the first
 * day of the window, so a book opened last week draws a flat $1,000 line
 * back through a month it did not exist for -- and a flat line is not a
 * neutral mark here, it is the claim "this book was open and in cash". It
 * would also enter the "N of N are ahead of buy-and-hold" arithmetic on days
 * it could not have traded.
 *
 * Everything not listed opened with the project, which is where the window
 * itself starts, so an absent key means "no clipping needed" rather than
 * "unknown". Dates are the book's first day, ISO, compared as strings
 * against the point's own `date` -- both are YYYY-MM-DD. */
const BOOK_OPENED = { breakout: "2026-09-16" };

/* Replays `trades` into a daily equity curve per strategy.

   The books hold ounces, so their value only exists against a price, and the
   price series this uses is `predictions.price_at_prediction` -- one row per
   trading day, written by the same run that placed the day's trades, at the
   same moment, from the same feed. Marking the books with anything else (a
   spot quote, a close from another series) would price a position in a
   currency it was never bought in; it is the same futures-vs-spot mistake
   the valuation note warns about, a day at a time.

   Trades are cut off at the END of each point's day: predict.py writes the
   prediction first and trades a second later, so a cutoff at the prediction's
   own timestamp would show every book one day behind its own fills. */
function liveEquitySeries(assetKey, markPrice) {
  const days = (cache.predictions[assetKey] ?? [])
    .filter((r) => r.created_at && r.price_at_prediction)
    .slice().reverse();                       // fetched newest-first
  if (!days.length) return null;

  const trades = (cache.trades ?? [])
    .filter((t) => t.asset === assetKey)
    .map((t) => ({ ...t, at: new Date(t.created_at).getTime() }))
    .sort((a, b) => a.at - b.at);

  const points = days.map((row) => ({
    date: String(row.created_at).slice(0, 10),
    cutoff: new Date(String(row.created_at).slice(0, 10) + "T23:59:59.999Z").getTime(),
    price: Number(row.price_at_prediction),
  }));
  // "Now", at the price every other panel on this card is marked at, so the
  // last point of the chart and the number in the box below it agree.
  if (markPrice > 0) {
    points.push({ date: "şimdi", cutoff: Date.now(), price: markPrice });
  }

  const series = LIVE_SERIES.concat("buyhold").map((key) => {
    let cash = STARTING_CASH, ounces = 0, i = 0;
    const mine = trades.filter((t) => t.strategy === key);
    const opened = BOOK_OPENED[key] ?? null;
    const equity = points.map((pt) => {
      while (i < mine.length && mine[i].at <= pt.cutoff) {
        const t = mine[i++];
        const gross = Number(t.usd_amount) || 0;
        const qty = Number(t.ounce_amount) || 0;
        if (t.side === "BUY") { cash -= gross; ounces += qty; }
        else { cash += gross - (Number(t.fee_usd) || 0); ounces -= qty; }
      }
      // null, not $1,000: timeSeriesPanel lifts the pen on a null, so the
      // line simply begins where the book does. "şimdi" is always after any
      // opening date, so the live point is never clipped.
      if (opened && pt.date !== "şimdi" && pt.date < opened) return null;
      return cash + ounces * pt.price;
    });
    return { key, label: backtestLabel(key), short: BACKTEST_SHORT[key] ?? key, equity };
  });

  return { dates: points.map((p) => p.date), series };
}

function renderLiveChart(asset, price) {
  const root = document.getElementById("live-chart");
  const toggle = document.getElementById("live-toggle");
  const note = document.getElementById("live-chart-note");
  if (!root) return;

  const built = liveEquitySeries(currentAsset, price);
  if (!built || built.dates.length < 2) {
    root.innerHTML = "";
    toggle.innerHTML = "";
    note.textContent = "Defterler yeni açıldı — eğri için en az iki seans gerekiyor.";
    return;
  }

  toggle.innerHTML = LIVE_SERIES.map((key) => {
    const on = liveSelection.has(key);
    return `<button class="chip${on ? " on" : ""}" data-live-series="${key}"`
      + ` style="--chip:${Viz.colourFor(key)}" aria-pressed="${on}">`
      + `${esc(backtestLabel(key))}</button>`;
  }).join("");

  const shown = ["buyhold", ...LIVE_SERIES.filter((k) => liveSelection.has(k))];
  const series = shown
    .map((key) => built.series.find((s) => s.key === key))
    .filter(Boolean);

  // FIXED caption, same rule as the measured chart: the last point of every
  // drawn book, which on this chart is the "şimdi" mark -- i.e. the same
  // valuation the panels below use, at the same mark price.
  const last = built.dates.length - 1;
  note.innerHTML = `<span class="readout-date">şimdi</span> ` + series.map((s) =>
      `<span class="readout-item"><i style="background:${Viz.colourFor(s.key)}"></i>`
      + `${esc(s.label)} <strong>${fmtUsd(s.equity[last], 2)}</strong></span>`).join(" ")
    // Derived, not typed: this line said "her defter aynı gün başladı" for as
    // long as that was true, and a book opened later would have made it
    // quietly false -- the sentence is the only thing on the card that could
    // have told the reader why one line starts in the middle of the plot.
    + ` <span class="muted">&mdash; her defter <strong>$1.000</strong> ile başladı;`
    + ` kesikli gri çizgi al-ve-tut.` + (() => {
        const late = series.filter((s) => BOOK_OPENED[s.key])
          .map((s) => `${esc(s.label)} (${fmtDate(BOOK_OPENED[s.key])})`);
        return late.length
          ? ` ${late.join(", ")} sonradan açıldı, o yüzden çizgisi daha geç başlıyor.`
          : "";
      })()
    + `</span>`;

  Viz.renderBacktestCharts(root, { dates: built.dates, series, panels: ["equity"] });
}

document.addEventListener("click", (event) => {
  const chip = event.target.closest("#live-toggle .chip");
  if (!chip) return;
  const key = chip.dataset.liveSeries;
  if (liveSelection.has(key)) liveSelection.delete(key);
  else liveSelection.add(key);
  renderLiveChart(ASSETS[currentAsset], valuationPrice(currentAsset).price);
});

/* What every book panel needs to price itself: the books for the selected
 * metal, the mark price they are all valued at, and the benchmark they are all
 * compared against. Built once per render and shared, so the ten panels in one
 * card and the one in another cannot disagree about the benchmark. */
function bookContext(portfolios, price, asset, costBasis) {
  const mine = portfolios.filter((p) => p.asset === currentAsset);
  const byKey = new Map(mine.map((p) => [p.strategy, p]));
  const benchmark = byKey.get("buyhold");
  return {
    byKey, price, asset, costBasis, assetKey: currentAsset,
    benchmarkValue: benchmark
      ? Number(benchmark.cash_usd) + Number(benchmark.ounces) * price
      : null,
  };
}

/* One paper book, as a panel.
 *
 * Top-level rather than a closure inside renderStrategies because two cards
 * draw these now: the portfolios card draws ten of them, and the Kanal Finans
 * card draws the eleventh beside the words it follows. A second copy of this
 * markup would drift at the first row added to either one -- the same reason
 * the two trade logs were one function before they became per-book.
 */
function bookPanelHtml(strategy, ctx) {
  const { byKey, price, asset, costBasis, benchmarkValue, assetKey } = ctx;
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

  // Two of this metal's books watch a LEVEL rather than a target exposure, so
  // they show that instead. Printing "hedef %0" for an all-in/all-out book
  // states a target it does not have and that it will never move toward.
  let extraRow;
  if (strategy.follower) {
    extraRow = `<div class="row"><span>zarar-kes</span><span>${
      state.stop_loss_price ? fmtUsd(state.stop_loss_price, asset.digits) : "yok"
    }</span></div>`;
  } else if (strategy.breakoutBook) {
    // Read off breakout_state, not off portfolios: the live stop is
    // recomputed from price history every run and this book deliberately
    // keeps no second copy of it.
    const row = breakoutLatest();
    extraRow = Number(state.ounces) > 0
      ? `<div class="row"><span>stop</span><span>${
          row?.stop ? fmtUsd(row.stop, asset.digits) : "-"}</span></div>`
      : `<div class="row"><span>giriş eşiği</span><span>${
          row?.vah ? fmtUsd(row.vah, asset.digits) : "-"}</span></div>`;
  } else {
    extraRow = `<div class="row"><span>hedef</span><span>${fmtPct(state.target_exposure, 0)}</span></div>`;
  }

  // "%17 pozisyon" is a ratio; these two are the holding itself, and they
  // are what the question "did it actually buy any gold?" is asking. A
  // dashboard that only ever prints ratios cannot answer it.
  const action = nextActionFor(state, price, exposure, value);
  // What the metal it still holds cost, and how the price has moved since.
  // This is a PRICE comparison, not net P&L: the panel's own percentage
  // above already carries the fees, and repeating them here would count
  // them twice.
  const basis = costBasis.get(`${assetKey}|${strategy.key}`)
    ?? { avgPrice: null, avgAllIn: null };
  const sincePurchase = basis.avgPrice ? price / basis.avgPrice - 1 : null;

  return `
    <div class="strategy-panel${strategy.benchmark ? " benchmark" : ""}${strategy.follower ? " follower" : ""}${strategy.breakoutBook ? " breakout-book" : ""}">
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
      ${bookLogHtml(assetKey, strategy.key)}
    </div>`;
}

function renderStrategies(portfolios, price, asset, costBasis) {
  const ctx = bookContext(portfolios, price, asset, costBasis);
  const { byKey, benchmarkValue } = ctx;
  const panelFor = (strategy) => bookPanelHtml(strategy, ctx);

  // TWO GROUPS, and the line between them is trading.MECHANICAL -- the same
  // constant the backend uses to decide which rules may run on the tracked
  // ETFs. It is not a layout preference:
  //
  //   * The four mechanical books forecast NOTHING. They react to realised
  //     volatility and to price against its own long average, and
  //     research/instrument.py measured that on the BUYABLE instrument every
  //     strategy but one that beat buy-and-hold is in this set.
  //   * The other seven act on a direction call that research/edge.py measured
  //     as losing to "always long" at every horizon, and that research/tilt.py
  //     measured as worth a position tilt of exactly zero.
  //
  // Eleven equal boxes said those two groups were equally supported. They are
  // not, and this page's entire job is to not say that.
  //
  // Nothing is hidden: the summary carries the live count of how many of them
  // are currently ahead of buy-and-hold, which is the fact a reader would open
  // the group to find. Collapsing a measured-null result behind a summary that
  // states the result is not the same as omitting it.
  // `follower` is the THIRD kind and it is drawn somewhere else entirely --
  // in the Kanal Finans card, beside the words it copies. It is not a rule and
  // not a signal book: `predict.py` does not produce it, `ensemble.COMPONENTS`
  // does not contain it, `trading.compute_target_exposure` never sizes it, and
  // `trading.REBALANCE_THRESHOLD` does not apply to it -- it is all-in or
  // all-out on one person's stated call
  // (`kanal_finans_trading.decide_on_mention`). Standing in a grid of rules it
  // read as an eleventh rule. Its curve stays on the live chart, where the
  // comparison it CAN make -- against the same benchmark, on the same days --
  // is the honest one.
  const measured = STRATEGIES.filter((s) => s.mechanical);
  const signalled = STRATEGIES.filter(
    (s) => !s.mechanical && !s.follower && !s.breakoutBook);
  const ahead = signalled.filter((s) => {
    const state = byKey.get(s.key);
    if (!state || benchmarkValue === null) return false;
    return Number(state.cash_usd) + Number(state.ounces) * price > benchmarkValue;
  }).length;

  // The live standing gets its AGE printed next to it, and that is not a
  // decoration. These books opened in September 2026; over a fortnight in
  // which gold happened to fall, every book holding less than 100% is ahead
  // of buy-and-hold by construction, and "7 of 7 are winning" is a sentence
  // about the last two weeks wearing the clothes of a result.
  //
  // Same discipline as MIN_ROWS_FOR_VERDICT in renderHistory, which refuses
  // to rank the model against always-UP under 60 resolved rows, and as
  // research/ablation.py printing a test's power beside its finding. The
  // ranking that IS a measurement is the one in the chart above.
  const days = bookAgeDays();
  const age = days === null ? "" :
    ` &mdash; ama defterler <strong>${days} gün</strong>lük, yani bu sıralama henüz `
    + `bir ölçüm değil. Ölçülmüş sıralama yukarıdaki 19,5 yıllık grafikte.`;

  const ledger = (cache.trades ?? []).filter((t) => t.asset === currentAsset);
  const totalTrades = ledger.length;
  const totalFees = ledger.reduce((sum, t) => sum + (Number(t.fee_usd) || 0), 0);

  // Which books are drawn somewhere else, DERIVED rather than typed. The
  // sentence below used to name `kanalfinans` as "the eleventh" and say
  // "eleven books" -- and the moment `breakout` opened a twelfth book, the
  // count was wrong while `totalTrades` beside it, which counts every fill on
  // this metal, had already started including it. A number that is computed
  // standing next to a number that is asserted is how a page starts
  // contradicting itself. Same fix as the live chart's caption.
  const elsewhere = STRATEGIES.filter((s) => s.follower || s.breakoutBook);
  const elsewhereText = elsewhere.map((s) => esc(s.label)).join(" ve ")
    + (elsewhere.length > 1 ? " kendi kartlarında" : " kendi kartında");

  // Two labelled groups, BOTH fully visible. An earlier version folded the
  // signalled seven into a <details>; nothing on this page is hidden behind a
  // click except the "what does this mean" explainers, because a panel that
  // must be opened is a panel read once.
  //
  // The separation still carries the finding -- it is a heading and a
  // sentence rather than a fold.
  document.getElementById("strategy-panels").innerHTML = `
    <h3 class="sub">Ölçülen risk kuralları</h3>
    <p class="muted small group-note">
      Hiçbiri tahmin yapmaz &mdash; gerçekleşen oynaklığa ve fiyatın kendi uzun
      ortalamasına tepki verirler. Alınabilir ETF üzerinde al-ve-tut'u geçenlerin
      biri hariç hepsi bu gruptan çıktı.
    </p>
    <div class="strategy-grid measured">${measured.map(panelFor).join("")}</div>

    <h3 class="sub">Sinyal defterleri</h3>
    <p class="muted small group-note">
      Yön tahminine göre pozisyon alanlar. Şu an <strong>${ahead}</strong>/${signalled.length}
      tanesi al-ve-tut'un üzerinde${age}
    </p>
    <div class="strategy-grid signalled">${signalled.map(panelFor).join("")}</div>

    <!-- The one number the combined trade log carried that a per-book log
         cannot: what every book on this metal has paid between them, and the
         rate they pay it at. backend/backtest.py's whole cost ladder exists
         because the same strategy beats buy-and-hold at 2 bp and loses badly
         at 150, so this is not a footnote. -->
    <p class="muted small">
      Her defterin kendi son işlemleri kutusunun içinde; ${elsewhereText}.
      Bu metalin <strong>${STRATEGIES.length}</strong> defteri bugüne
      kadar toplam <strong>${totalTrades}</strong> işlem yaptı ve
      <strong>${fmtUsd(totalFees, 2)}</strong> komisyon ödedi; oran bu metal için
      tek yönde ${fmtNumber(asset.feeBps, 0)} baz puandır &mdash; bir stratejinin
      al-ve-tut'u geçip geçmediğini çoğu zaman sinyal değil bu sayı belirler.
    </p>`;
}

/* The follower's book, drawn in the Kanal Finans card rather than among the
 * rules.
 *
 * It answers "what did his call actually cost or earn", and that question
 * belongs next to the call, not in a grid of measured strategies -- eleven
 * equal boxes said a person's opinion and a measured risk rule were the same
 * kind of thing. Same panel function as the other ten (`bookPanelHtml`), so
 * the two cards cannot drift apart, and same benchmark: `bookContext` builds
 * the buy-and-hold value once.
 *
 * Its curve stays on `Defterlerin seyri` above. Moving the panel is about
 * where the book is EXPLAINED; the chart is where it is compared, and a line
 * missing from that chart would quietly drop the one comparison that treats
 * every book alike. */
function renderKanalFinansBook(portfolios, price, asset, costBasis) {
  const host = document.getElementById("kf-book");
  if (!host) return;
  const follower = STRATEGIES.find((s) => s.follower);
  const ctx = bookContext(portfolios, price, asset, costBasis);
  host.innerHTML = `<div class="strategy-grid follower-grid">`
    + bookPanelHtml(follower, ctx) + `</div>`;
}

/* The breakout rule's own $1,000 book, inside the Kırılım Takibi card.
 *
 * Same function as the other eleven panels (`bookPanelHtml`) and the same
 * benchmark (`bookContext` computes buy-and-hold once), for the reason the
 * follower's panel is drawn that way: two cards drawing the same box from two
 * copies of the markup drift at the first row added to either.
 *
 * It sits HERE rather than in the grid of measured rules because it is the
 * same third kind as the follower -- all-in/all-out on a discrete state
 * (`breakout_trading.decide`), never sized by `compute_target_exposure`, and
 * `REBALANCE_THRESHOLD` does not apply to it. Standing among the rules it
 * would read as a twelfth rule; standing here it reads as what it is, a book
 * on the rule this card measures. Its curve stays on `Defterlerin seyri`,
 * where every book is compared on the same days against the same benchmark.
 */
function renderBreakoutBook(portfolios, price, asset, costBasis) {
  const host = document.getElementById("breakout-book");
  if (!host) return;
  const strategy = STRATEGIES.find((s) => s.breakoutBook);
  const ctx = bookContext(portfolios, price, asset, costBasis);
  // No book row yet means the 2026-09-16 migration has not been applied. Say
  // so rather than drawing an empty box -- the panel would otherwise print
  // "-" with no way for a reader to learn why.
  if (!ctx.byKey.get(strategy.key)) {
    host.innerHTML = `<p class="muted small">Bu kuralın kağıt defteri henüz `
      + `açılmamış. <code>supabase/schema.sql</code>'in <strong>2026-09-16</strong> `
      + `migration'ı uygulandığında burada $1.000'lik defter belirir.</p>`;
    return;
  }
  // Until this book has traded once, its "al-ve-tut'a göre" row is not about
  // this book at all: it sits at exactly $1,000 while the benchmark has been
  // running since early September, so the number is a report on buy-and-hold's
  // own fortnight. Same discipline as renderStrategies printing the books' age
  // beside "N of N are ahead", and as MIN_ROWS_FOR_VERDICT in renderHistory.
  const fills = (cache.trades ?? []).filter(
    (t) => t.asset === currentAsset && t.strategy === strategy.key).length;
  const caveat = fills === 0
    ? `<p class="muted small">Bu defter <strong>henüz hiç işlem yapmadı</strong> &mdash; `
      + `kural boştaydı. Panelin &ldquo;al-ve-tut'a göre&rdquo; satırı bu yüzden bu `
      + `defteri değil, al-ve-tut'un açılıştan bu yana ne yaptığını ölçüyor; `
      + `karşılaştırma ilk dolumdan sonra anlam kazanır.</p>`
    : "";

  // The card's verdict sentence above measures the configuration the sweep
  // CHOSE; this book runs a different one, and saying so is not a footnote.
  // The sweep keeps 35% of the book invested while the rule is flat, and an
  // all-in/all-out engine cannot hold that -- so the book is the hard-exit
  // sibling, and it is measured on the same test half rather than assumed to
  // behave like its twin. It does not: 11 points of Calmar and 15 points of
  // money worse, in gold. Quoting the verdict's numbers beside this box would
  // be the one thing this card exists not to do.
  const v = BREAKOUT_VERDICT[currentAsset];
  const bookGap = 1 - v.bookFinal / v.benchFinal;
  const variant = `<p class="muted small">Bu defter, kartın ölçtüğü `
    + `konfigürasyonun <strong>tam giriş/tam çıkış</strong> kardeşini koşuyor: `
    + `süpürme kural boştayken %35 yatırımda kalmayı seçti, bu motorun ise `
    + `hedef pozisyonu yok. Aynı test yarısında, aynı alınabilir bacakta `
    + `(${esc(BREAKOUT_VERDICT[currentAsset].etf)}) o varyant Calmar `
    + `<strong>${fmtNumber(v.bookCalmar, 3)}</strong> (al-ve-tut `
    + `${fmtNumber(v.benchCalmar, 3)}) ve $10.000'lik hesapta `
    + `<strong>${fmtUsd(v.bookFinal, 0)}</strong> &mdash; al-ve-tut'un `
    + `%${fmtNumber(100 * bookGap, 1)} altında. Yani defter, yukarıdaki ölçümün `
    + `bile gerisinde bir varyantı taşıyor.</p>`;

  host.innerHTML = `<div class="strategy-grid follower-grid">`
    + bookPanelHtml(strategy, ctx) + `</div>` + caveat + variant;
}

// How long the paper books have been running, from the first fill on record.
// Read off `trades` rather than a hardcoded start date so it stays true if the
// books are ever reset, and returns null rather than 0 when nothing has traded
// yet -- "0 gün" would read as a measurement of zero rather than as no data.
function bookAgeDays() {
  const first = cache.trades.find((t) => t.created_at);
  if (!first) return null;
  const started = new Date(first.created_at).getTime();
  if (!Number.isFinite(started)) return null;
  return Math.max(1, Math.round((Date.now() - started) / 86400000));
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
  const scoreboard =
    `${resolved.length} çözülmüş tahmin · isabet ${fmtPct(accuracy)} · ` +
    `aynı dönemde fiyat ${fmtPct(actualUp)} oranında yükselmiş`;

  // A VERDICT needs enough rows to be one. At ~250 resolved rows a year, the
  // first months of this table are a handful of coin flips, and "model
  // hep-YÜKSELİŞ demekten iyi" printed over eight of them is the same
  // overstatement this project spends its research bench refusing to make --
  // research/ablation.py's whole discipline is reporting a test's POWER
  // alongside its result. The two rates also differ by a point or two for a
  // long time, so even at a decent sample a near-tie is not a ranking.
  const GAP = Math.abs(accuracy - actualUp);
  let verdict;
  if (resolved.length < MIN_ROWS_FOR_VERDICT) {
    verdict = ` → henüz hüküm vermek için çok az satır var (${resolved.length}/`
      + `${MIN_ROWS_FOR_VERDICT}); bu iki sayı bu boyutta rahatlıkla yer değiştirir.`;
  } else if (GAP < 0.02) {
    verdict = " → ikisi arasındaki fark 2 puandan küçük, yani ayırt edilebilir değil.";
  } else {
    verdict = accuracy > actualUp
      ? " → model hep-YÜKSELİŞ demekten iyi."
      : " → model hep-YÜKSELİŞ demekten iyi DEĞİL.";
  }
  summary.textContent = scoreboard + verdict;
}

/* A CARD LIST, not a table -- and that is a form correction rather than a
   layout workaround.

   The eight columns (date, asset, stance, action, target, stop, resistance,
   summary) were never eight comparable measures. Seven are short labels and
   levels, and the eighth is a paragraph of transcribed speech; a table makes
   the paragraph fight six numeric columns for width and loses. In the 444px
   sidebar this card now lives in, no amount of tightening fits it, and the
   previous answer -- scroll it sideways -- hid whichever columns happened to
   come last behind a gesture most readers never make.
   
   As cards the levels become chips that wrap, the summary gets the full width
   it needs, and nothing is off screen at any viewport. */
/* ------------------------------------------------------- breakout panel */

/* Display metadata for the six confirmations. Deliberately NOT the rule:
   `threshold` is a printed LABEL and nothing here recomputes a vote. The vote
   arrives in `votes_detail`, decided by flow_signal.confirmation_votes() --
   the same function the backend's own state machine calls.

   This is the component-record table's rule applied again. That table shows
   raw counters and refuses to redo the log-odds pooling in JavaScript,
   because a decision rule kept in two languages drifts the first time one
   side is edited, and the drift produces a page that is confidently wrong
   rather than visibly broken. A threshold comparison is a smaller rule than
   log-odds pooling, and exactly as easy to edit on one side only. */
// `signed` picks the formatter, and the distinction is the one fmtSigned's
// own comment draws: three of these oscillate around zero, where the sign IS
// the reading ("MACD −3,14" and "MACD +3,14" are opposite claims), and three
// are levels on a fixed scale, where a leading "+" on an RSI of 43,7 would be
// noise. It also gets the typographic minus the rest of the page uses.
const BREAKOUT_INDICATORS = [
  { key: "rsi14", label: "RSI (14)", threshold: "50", digits: 1 },
  { key: "macd_hist", label: "MACD histogram", threshold: "0", digits: 2, signed: true },
  { key: "cci20", label: "CCI (20)", threshold: "±100", digits: 0, signed: true },
  { key: "mom10", label: "Momentum (10)", threshold: "0", digits: 2, signed: true, suffix: "%" },
  { key: "stoch_k", label: "Stokastik %K", threshold: "50", digits: 1 },
  { key: "fib_pos", label: "Fibonacci konumu", threshold: "0,382", digits: 3 },
];

/* The out-of-sample result, from backend/research/flow.py, second half of the
   window (2016-2026), on the BUYABLE instrument at the $10,000 rung with the
   $1.50 flat commission. Hardcoded with a named source, the same way GS_RATIO
   and indicators.py's scale constants are.

   Both metals are here and both lines are losses, which is the point: gold
   beats buy-and-hold on Calmar and finishes a third behind it in money, and
   printing only the first number would be exactly the overstatement
   research/README.md section 17 exists to correct. */
/* research/flow.py part 5, RE-MEASURED 2026-09-17.
 *
 * The first phase-2 numbers (gold Calmar 0.520 vs 0.463, silver 0.154 vs
 * 0.236) were produced by a construction that claimed a one-session lag on
 * the buyable leg and did not have one: TradingView stamps a daily bar with
 * the session's OPEN, so the ETF join landed a day early and the lag
 * cancelled it back out into an hour of look-ahead. Fixed in
 * tv_history.to_trade_dates(); these are the re-run's figures, and gold no
 * longer wins Calmar either.
 *
 * `book*` is the variant the $1,000 paper book actually runs. The sweep now
 * picks a 0.35 floor for both metals and breakout_trading.py is all-in /
 * all-out, so the book is the hard-exit sibling of the rule the bar judged --
 * measured on the same test half rather than assumed to be the same. */
const BREAKOUT_VERDICT = {
  gold: {
    etf: "GLD", years: 10.9, calmar: 0.452, benchCalmar: 0.460,
    final: 22151, benchFinal: 35012, entries: 62, inPosition: 0.29,
    bookCalmar: 0.341, bookFinal: 17072,
    // assets.GOLD.breakout -- mirrored for a caption, never for a decision.
    minConfirmations: 2, stopSigmas: 2.0,
    // The WHOLE phrase, not a metal name a template glues a suffix onto:
    // Turkish inflects it ("altının" / "gümüşün"), so a shared sentence with
    // ${label}'in in it is wrong for one of the two metals. Same reason the
    // card's percentage sentences avoid a trailing suffix entirely.
    spotNote: "Spot altının (XAU/USD)",
  },
  silver: {
    etf: "SLV", years: 10.2, calmar: 0.146, benchCalmar: 0.230,
    final: 18811, benchFinal: 31935, entries: 53, inPosition: 0.22,
    bookCalmar: 0.053, bookFinal: 12995,
    minConfirmations: 4, stopSigmas: 2.0,
    spotNote: "Spot gümüşün (XAG/USD)",
  },
};

/* How the verdict sentence ENDS, and it changed on 2026-09-16.
 *
 * It used to read "Bu yüzden buna bağlı bir portföy yok" -- true until the
 * book was opened, and the kind of sentence that stays on screen sounding
 * reasonable long after it stops being true. The measurement did not change;
 * the decision did, and the card has to say which. */
const BREAKOUT_BOOK_NOTE =
  "Defter yine de açıldı &mdash; bu kaybı bir tabloda değil, canlı ve "
  + "al-ve-tut'un yanında görmek için. Kopyalanacak bir kural değil.";

function breakoutStateHtml(last, asset) {
  if (!last) return "";
  // asset.digits, not a hardcoded 2. Silver quotes to three places everywhere
  // else on this page, and the book panel below this card already used
  // asset.digits -- so the same $69.83 level was printed two different ways
  // inside one card. The parameter was always here and always ignored.
  const price = (v) => (v == null ? "-" : fmtUsd(v, asset.digits));
  if (last.state) {
    const gain = last.entry_price ? last.close / last.entry_price - 1 : null;
    const room = last.stop ? last.close / last.stop - 1 : null;
    return `<div class="breakout-status in">`
      + `<div class="breakout-badge up">POZİSYONDA</div>`
      + `<div class="breakout-status-grid">`
      + `<div><span class="muted small">Giriş</span><strong>${fmtDate(last.entry_date)}`
      + ` &middot; ${price(last.entry_price)}</strong></div>`
      + `<div><span class="muted small">O günden bu yana</span>`
      + `<strong class="${gain >= 0 ? "up-text" : "down-text"}">${fmtSignedPct(gain)}</strong></div>`
      + `<div><span class="muted small">Stop</span><strong>${price(last.stop)}</strong></div>`
      + `<div><span class="muted small">Stop ne kadar uzakta</span>`
      + `<strong>${room == null ? "-" : fmtPct(room, 1)}</strong></div>`
      + `</div></div>`;
  }
  const why = { stop: "stop seviyesi kırıldı", trend: "trend kırıldı (AVWAP altı)" };
  return `<div class="breakout-status out">`
    + `<div class="breakout-badge flat">POZİSYON YOK</div>`
    + `<div class="breakout-status-grid">`
    + `<div><span class="muted small">Son çıkış sebebi</span>`
    + `<strong>${esc(why[last.exit_reason] ?? "henüz giriş olmadı")}</strong></div>`
    + `<div><span class="muted small">Giriş için gereken</span>`
    + `<strong>${price(last.vah)} üzeri kapanış</strong></div>`
    + `</div></div>`;
}

/* The levels, with the distance from today's close beside each one.

   The distance is the half a reader would otherwise compute in their head,
   and it is the half that decides anything: "VAH $404,96" is a fact about the
   last quarter, "%3,1 yukarıda" is the reason nothing has triggered. */
function breakoutLevelsHtml(last, asset) {
  if (!last) return "";
  // The two Fibonacci levels are arithmetic on `fib_low`/`fib_high`, which
  // are both stored. Derived here rather than shipped for the reason the
  // drawdown panel is: a pure function of data already in the payload, so a
  // stored copy could only ever disagree with its own source. Neither level
  // triggers anything -- flow_signal.py is explicit that a profit target
  // that closes a winning trend is the opposite of "hold until it breaks".
  const span = (last.fib_high != null && last.fib_low != null)
    ? Number(last.fib_high) - Number(last.fib_low) : null;
  const fibSupport = span == null ? null : Number(last.fib_low) + 0.382 * span;
  const fibTarget = span == null ? null : Number(last.fib_high) + 0.618 * span;
  const rows = [
    { label: "Kapanış", value: last.close, note: `${esc(last.source_symbol)} — $/ons`, bare: true },
    { label: "Değer alanı üstü (VAH)", value: last.vah, note: "kırılım eşiği" },
    { label: "En çok işlem gören fiyat (POC)", value: last.poc, note: "hacim profilinin tepesi" },
    { label: "Değer alanı altı (VAL)", value: last.val, note: "ilk stop buradan" },
    { label: "Çapalı VWAP", value: last.avwap,
      note: last.avwap_anchor ? `çapa: ${fmtUsd(last.avwap_anchor, asset.digits)} (yıllık dip)` : "" },
    { label: "Fibonacci %38,2 desteği", value: fibSupport, note: "gösterilir, işlem üretmez" },
    { label: "Fibonacci %61,8 uzantısı", value: fibTarget, note: "gösterilir, işlem üretmez" },
  ];
  return `<div class="breakout-levels">` + rows.filter((r) => r.value != null).map((r) => {
    const away = r.bare ? "" : `<span class="muted small">${fmtSignedPct(r.value / last.close - 1)}</span>`;
    return `<div class="breakout-level">`
      + `<span class="breakout-level-label">${esc(r.label)}`
      + (r.note ? `<em class="muted small">${esc(r.note)}</em>` : "") + `</span>`
      + `<span class="breakout-level-value"><strong>${fmtUsd(r.value, asset.digits)}</strong>${away}</span>`
      + `</div>`;
  }).join("") + `</div>`;
}

function renderBreakout(rows, asset) {
  const card = document.getElementById("breakout-card");
  if (!card) return;
  const mine = (rows ?? []).filter((r) => r.asset === currentAsset);
  const chartRoot = document.getElementById("breakout-chart");
  const verdict = BREAKOUT_VERDICT[currentAsset];

  document.getElementById("breakout-asset-name").textContent = asset.label;
  document.getElementById("breakout-minconf").textContent =
    String(verdict.minConfirmations);

  // Rows from BEFORE the 2026-09-15b migration are not "slightly old", they
  // describe a different instrument in a different unit: `close` was a GLD
  // share price and `source_symbol` did not exist. Rendering them would print
  // "Seviyeler undefined üzerindedir" over $394 levels on a card whose whole
  // point is that the levels are $/ounce -- wrong, and plausible enough to be
  // believed. A schema check is the same guard loadBacktest() applies to
  // backtest.json, for the same reason.
  const stale = mine.length > 0 && mine.every((r) => r.source_symbol == null);

  // No usable rows is not an empty chart, it is a missing migration or a
  // tracker that has never run. Saying which is the whole job -- a heading
  // that promises a breakout state over a blank panel keeps making the claim.
  if (!mine.length || stale) {
    card.classList.add("awaiting");
    document.getElementById("breakout-updated").textContent = "-";
    document.getElementById("breakout-state").innerHTML = stale
      ? `<p class="muted small">Kayıtlı satırlar <strong>eski şemadan</strong> `
        + `(seviyeler GLD/SLV payı cinsinden). <code>supabase/schema.sql</code>'in `
        + `<strong>2026-09-15b</strong> migration'ı henüz uygulanmamış &mdash; `
        + `uygulanınca <code>track_breakout.py</code> pencereyi $/ons olarak `
        + `yeniden yazar.</p>`
      : `<p class="muted small">Bu metal için henüz kırılım durumu yazılmamış. `
        + `<code>track_breakout.py</code> ilk kez çalıştığında (ya da `
        + `<code>breakout_state</code> migration'ı uygulandığında) burası dolar.</p>`;
    chartRoot.innerHTML = "";
    document.getElementById("breakout-readout").textContent = "-";
    document.getElementById("breakout-levels").innerHTML = "";
    document.querySelector("#breakout-votes-table tbody").innerHTML =
      `<tr><td colspan="4" class="muted">Veri yok.</td></tr>`;
    document.getElementById("breakout-verdict").textContent = "-";
    document.getElementById("breakout-note").textContent = "-";
    return;
  }
  card.classList.remove("awaiting");

  // Supabase returns newest-first; the chart reads oldest-first.
  const ordered = [...mine].sort((a, b) => String(a.session_date).localeCompare(b.session_date));
  const last = ordered[ordered.length - 1];
  const numeric = (r) => ({
    close: Number(r.close), avwap: r.avwap == null ? null : Number(r.avwap),
    vah: r.vah == null ? null : Number(r.vah), val: r.val == null ? null : Number(r.val),
    poc: r.poc == null ? null : Number(r.poc), stop: r.stop == null ? null : Number(r.stop),
    state: Number(r.state),
  });

  document.getElementById("breakout-updated").textContent =
    `son seans ${fmtDate(last.session_date)}`;
  document.getElementById("breakout-state").innerHTML = breakoutStateHtml(last, asset);

  Viz.renderBreakoutChart(chartRoot, {
    dates: ordered.map((r) => String(r.session_date)),
    rows: ordered.map(numeric),
    yFormat: (v) => fmtUsd(v, 0),
  });

  // FIXED caption, same rule as every other chart here: where each drawn line
  // ENDS. No crosshair, so the numbers a reader just read stay put.
  const ink = Viz.BREAKOUT_INK;
  const item = (colour, label, value) =>
    `<span class="readout-item"><i style="background:${colour}"></i>${esc(label)} `
    + `<strong>${value == null ? "-" : fmtUsd(Number(value), asset.digits)}</strong></span>`;
  const held = ordered.filter((r) => Number(r.state)).length;
  document.getElementById("breakout-readout").innerHTML =
    `<span class="readout-date">${fmtDate(last.session_date)}</span> `
    + item(ink.price, "fiyat", last.close)
    + item(ink.avwap, "AVWAP", last.avwap)
    + item(ink.area, "VAH", last.vah)
    + (last.state ? item(ink.stop, "stop", last.stop) : "")
    + ` <span class="muted">&mdash; gösterilen ${ordered.length} seansın `
    + `<strong>${held}</strong> tanesinde (%${Math.round(100 * held / ordered.length)}) `
    + `kural pozisyondaydı.</span>`;

  document.getElementById("breakout-levels").innerHTML = breakoutLevelsHtml(last, asset);

  // The book's fill series, named in the book's own intro. Read off the row
  // rather than typed, so it cannot disagree with the levels above it.
  const symbolEl = document.getElementById("breakout-book-symbol");
  if (symbolEl) symbolEl.textContent = last.source_symbol ?? "-";

  // The votes come from the backend. `votes_detail` is missing only on rows
  // written before that column existed, and a dash is the honest cell there
  // -- recomputing it here would be the drift this table is arranged to
  // avoid, and it would silently disagree with the `votes` total beside it.
  const detail = last.votes_detail ?? {};
  const voteLabel = { "1": "olumlu", "-1": "olumsuz", "0": "nötr" };
  document.querySelector("#breakout-votes-table tbody").innerHTML =
    BREAKOUT_INDICATORS.map((ind) => {
      const raw = last[ind.key];
      const vote = detail[ind.key];
      const cls = vote > 0 ? "up-text" : vote < 0 ? "down-text" : "muted";
      return `<tr><td>${esc(ind.label)}</td>`
        + `<td>${raw == null ? "-"
              : (ind.signed ? fmtSigned(Number(raw), ind.digits)
                            : fmtNumber(Number(raw), ind.digits)) + (ind.suffix ?? "")}</td>`
        + `<td class="muted">${esc(ind.threshold)}</td>`
        + `<td class="${cls}">${vote == null ? "-" : esc(voteLabel[String(vote)])}</td></tr>`;
    }).join("");

  // The measurement, on the card. It is a loss and it is printed as one.
  //
  // AND IT NAMES BOTH INSTRUMENTS, because they are deliberately different
  // and the card had stopped saying so. Everything above this line speaks
  // COMEX and $/ounce -- the levels, the chart, the book's fills -- and then
  // this sentence said "GLD üzerinde" with no explanation, which reads as a
  // leftover from phase 1 (when the whole panel really was in GLD dollars)
  // rather than as the deliberate split it is: the rule is BUILT on the
  // futures contract because that is the only series with real volume, and
  // the verdict is READ on the ETF because no retail account can hold a COMEX
  // contract. Two instruments, one rule, and a reader should not have to
  // infer that from a three-word parenthesis.
  const shortfall = 1 - verdict.final / verdict.benchFinal;
  const calmarWon = verdict.calmar > verdict.benchCalmar;
  const measuredOn =
    `<strong>Ölçüm iki ayrı enstrümanda duruyor</strong> ve bu bilerek böyle: `
    + `kural <strong>${esc(last.source_symbol)}</strong> üzerinde kuruluyor `
    + `(yukarıdaki her seviye orada, <strong>$/ons</strong>), hüküm ise `
    + `<strong>${esc(verdict.etf)}</strong> üzerinde okunuyor &mdash; alınabilir `
    + `bacak, sinyal 1 seans gecikmeli &mdash; çünkü perakende bir hesap COMEX `
    + `kontratı tutamaz. `;
  document.getElementById("breakout-verdict").innerHTML = measuredOn + (calmarWon
    ? `${fmtNumber(verdict.years, 1)} yıl örneklem dışı o bacakta `
      + `<strong>düşüşü azaltıyor</strong> (Calmar ${fmtNumber(verdict.calmar, 3)} — `
      + `al-ve-tut ${fmtNumber(verdict.benchCalmar, 3)}) ama <strong>parada geride kalıyor</strong>: `
      + `$10.000'lik hesapta ${fmtUsd(verdict.final, 0)}, al-ve-tut ${fmtUsd(verdict.benchFinal, 0)} `
      + `(%${fmtNumber(100 * shortfall, 1)} daha az). ${BREAKOUT_BOOK_NOTE}`
    : `${fmtNumber(verdict.years, 1)} yıl örneklem dışı o bacakta `
      + `<strong>her iki ölçüde de al-ve-tut'un gerisinde</strong>: Calmar `
      + `${fmtNumber(verdict.calmar, 3)} — ${fmtNumber(verdict.benchCalmar, 3)}, ve `
      + `$10.000'lik hesapta ${fmtUsd(verdict.final, 0)} — ${fmtUsd(verdict.benchFinal, 0)} `
      + `(%${fmtNumber(100 * shortfall, 1)} daha az). ${BREAKOUT_BOOK_NOTE}`);

  // No "the levels are in GLD dollars, convert them yourself" sentence any
  // more, and that absence is the point of the phase-2 source change: the
  // COMEX contract is quoted per troy ounce, so the card speaks the unit the
  // reader watches. What replaces it is the caveat that is actually left --
  // where the volume comes from, and that spot has none at all.
  document.getElementById("breakout-note").innerHTML =
    `${verdict.entries} giriş; pozisyonda geçen süre %${Math.round(100 * verdict.inPosition)}. `
    + `Baraj sonuçlara bakılmadan ilan edildi ve geçilemedi &mdash; `
    // The "levels are in <symbol>, i.e. $/ounce" sentence used to live here.
    // It moved into the verdict paragraph above, which now has to name both
    // instruments anyway; leaving a copy here printed the same fact twice
    // two lines apart. What stays is this note's own point, which nothing
    // else on the card makes: spot has no volume at all.
    + `<code>backend/research/flow.py</code>. ${verdict.spotNote} `
    + `hacmi <strong>hiçbir kaynakta yok</strong> &mdash; tezgâh üstü piyasa, konsolide `
    + `tape yok &mdash; o yüzden hacim profili COMEX kontratından okunuyor.`;
}

function renderKanalFinans(mentions, themes) {
  const box0 = document.getElementById("kf-mentions");
  // GENEL ("kıymetli madenler", neither metal named) applies to both tabs;
  // ALTIN/GUMUS belong on their own tab only. Without this filter every tab
  // showed the same mixed list and the asset label did the sorting a reader
  // expects the tab strip itself to do.
  const wanted = currentAsset === "gold" ? "ALTIN" : "GUMUS";
  const filtered = mentions.filter((m) => m.asset === wanted || m.asset === "GENEL");

  if (!filtered.length) {
    box0.innerHTML = `<p class="muted small">Henüz işlenmiş video yok.</p>`;
  } else {
    box0.innerHTML = filtered.slice(0, 12).map((m) => {
      const stanceClass = m.stance === "UP" ? "up-text" : m.stance === "DOWN" ? "down-text" : "silenced";
      // Every field that is not one of this file's own constants goes through
      // esc(): `summary` is Claude's transcription of speech and can contain
      // anything a person said out loud, angle brackets included.
      const action = String(m.action ?? "").toLowerCase();
      // Only the levels the speaker actually gave. An always-present row of
      // dashes says "he mentioned a stop and it was empty", which is the
      // opposite of what a missing level means here -- see the "eksik =
      // değişmedi" rule in kanal_finans_trading.
      const levels = [
        ["hedef", m.ounce_target],
        ["zarar-kes", m.stop_loss_price],
        ["direnç", m.resistance_price],
      ].filter(([, v]) => v)
       .map(([label, v]) => `<span class="kf-level"><i>${label}</i>${fmtUsd(v)}</span>`)
       .join("");

      return `
        <article class="kf-mention">
          <div class="kf-head">
            <span class="kf-date">${fmtDate(m.published_at)}</span>
            <span class="kf-asset">${KF_ASSET_LABEL[m.asset] ?? esc(m.asset)}</span>
            <span class="${stanceClass} kf-stance">${KF_STANCE[m.stance] ?? esc(m.stance)}</span>
            <span class="action action-${esc(action)}">${KF_ACTION[m.action] ?? esc(m.action)}</span>
          </div>
          ${levels ? `<div class="kf-levels">${levels}</div>` : ""}
          <p class="kf-summary">${esc(m.summary)}</p>
        </article>`;
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
    <div class="theme theme-${esc(String(t.impact ?? "").toLowerCase())}">
      <div class="theme-head">
        <span class="theme-name">${KF_THEME_LABEL[t.theme] ?? esc(t.theme)}</span>
        <span class="theme-impact">madenlere etkisi: ${KF_IMPACT[t.impact] ?? esc(t.impact)}</span>
      </div>
      <div class="theme-body">${esc(t.summary)}</div>
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

// Labels for the tracked-ETF books. Deliberately the SAME wording as the
// futures panels above -- these are the same rules, and giving them different
// names would invite reading them as different strategies.
const ETF_STRATEGIES = [
  { key: "buyhold", label: "Al-ve-tut", benchmark: true },
  { key: "voltarget", label: "Oynaklık hedefi" },
  { key: "trend", label: "Trend filtresi" },
  { key: "defensive", label: "Savunma" },
];

// backend/assets.TRACKED, in the same order. `metal` is the ASSETS key whose
// tab this fund belongs under -- the card follows the tab strip, so GLD shows
// on the gold tab and SLV on the silver one.
//
// `claim` is each book's OWN measured result from research/README.md section
// 17. Gold's numbers are not reused for silver, because the two are not the
// same claim: silver's buy-and-hold drawdown is 76.3% against gold's 45.6%,
// so the five points cut here sit on a much larger wound than gold's six.
const TRACKED_ETFS = [
  { key: "gld", label: "GLD", metal: "gold", metalLabel: "altın", tv: "AMEX:GLD",
    claim: "16,1 yılda $10.000'lik bir hesapta oynaklık hedefi $36.257, al-ve-tut $34.844 bitirdi; "
         + "maksimum düşüş %45,6 → %39,2, Sharpe 0,48 → 0,59." },
  { key: "slv", label: "SLV", metal: "silver", metalLabel: "gümüş", tv: "AMEX:SLV",
    claim: "16,1 yılda $10.000'lik bir hesapta oynaklık hedefi $35.023, al-ve-tut $33.286 bitirdi; "
         + "maksimum düşüş %76,3 → %70,8, Sharpe 0,24 → 0,32." },
];

/* Renders the tracked-ETF books for the SELECTED metal.
 *
 * Asset-scoped, like every other panel below the tab strip. It was not, while
 * GLD was the only tracked fund: filtering on `currentAsset` would then have
 * blanked the card on the silver tab. Adding SLV removed that hazard and with
 * it the reason -- each metal now has exactly one tradeable proxy, so showing
 * both at once put a silver book under the gold tab, which is precisely the
 * confusion the per-asset colouring exists to prevent.
 *
 * The LIVE PRICE cards stay unscoped, and that difference is deliberate: they
 * are two quotes of two different things shown side by side on purpose. These
 * are books, and a book belongs to the metal whose page it is on.
 *
 * Built from TRACKED_ETFS rather than from fixed markup, so a fund is a data
 * change -- including a metal that has two proxies, which would simply render
 * two tables on that metal's tab. */
function renderEtfBooks(portfolios, live) {
  const host = document.getElementById("etf-books");
  if (!host) return;
  const mine = TRACKED_ETFS.filter((etf) => etf.metal === currentAsset);
  const title = document.getElementById("etf-card-title");
  if (title) {
    title.textContent = mine.length
      ? `Alınabilir Enstrüman — ${mine.map((e) => e.label).join(" / ")}`
      : "Alınabilir Enstrüman";
  }
  // A metal with no tracked fund is a real state (a third metal added to
  // ASSETS before its ETF is picked), so it gets a sentence rather than an
  // empty card that reads as a loading failure.
  host.innerHTML = mine.length
    ? mine.map((etf) => renderOneEtfBook(
        etf, portfolios ?? [], live?.etfs?.[etf.key] ?? null, live,
        cache.costBasis)).join("")
    : `<p class="muted small">Bu metal için izlenen bir ETF yok.</p>`;
}

/* How much metal one ETF share actually represents, in troy ounces.
 *
 * Derived from the price ratio rather than from the sponsor's NAV file: the
 * fund holds bullion and almost nothing else, so its share price tracks
 * `metal per share x metal price` closely, and the ratio recovers the first
 * factor without adding a data source. Measured 2026-09-11: GLD 0.0913 oz and
 * SLV 0.8989 oz per share, both within a percent of the sponsors' published
 * figures.
 *
 * SPOT is the right denominator here and FUTURES would be wrong, which is the
 * exact opposite of the rule for portfolio valuation (see the TV_FUTURES
 * note). The books are valued in futures because that is the series they
 * traded at; metal CONTENT is a different question -- a fund's bullion is
 * marked to the spot market, and dividing by a futures price would quietly
 * bake the ~1% basis into the gram figure.
 *
 * Two honest limits, both stated on screen: this is an approximation, and
 * while the US market is closed the ETF's last close is compared against a
 * live spot price, so the figure drifts with the overnight move. */
function metalOuncesPerShare(etf, etfPrice, live) {
  const spot = live?.[etf.metal] ?? null;
  if (!Number.isFinite(spot) || spot <= 0 || !Number.isFinite(etfPrice)) return null;
  return etfPrice / spot;
}

/* The line that answers "what do I actually hold, and what did I pay".
 *
 * A portfolio box shows value and exposure, which is what the strategy cares
 * about -- but not the three things a person holding the position asks: how
 * many shares, how much metal that is, and at what price and when it was
 * bought. Those live in `trades`, which the page already downloads in full
 * for the cost basis, so this costs no extra request. */
function etfHoldingLine(etf, row, price, live, basis) {
  const shares = Number(row.ounces);
  if (!Number.isFinite(shares) || shares <= 1e-9) {
    return `tamamen nakitte &mdash; ${fmtUsd(Number(row.cash_usd))}`;
  }
  const parts = [`${fmtNumber(shares, 4)} pay`];

  const perShare = metalOuncesPerShare(etf, price, live);
  if (perShare !== null) {
    const grams = shares * perShare * TROY_OUNCE_GRAMS;
    parts.push(`≈ ${fmtNumber(grams, 2)} g ${etf.metalLabel}`);
  }
  // Cash is half of what the book IS, and a percentage exposure hides it: a
  // book at 35% is also a book sitting on 650 dollars, and that number is the
  // one a person checks against their own account. Printed even when zero --
  // "fully invested" is a fact, not a missing value.
  parts.push(`${fmtUsd(Number(row.cash_usd))} nakit`);
  const cost = basis?.get(`${etf.key}|${row.strategy}`) ?? null;
  if (cost?.avgPrice) parts.push(`ort. ${fmtUsd(cost.avgPrice)}/pay`);
  if (cost?.lastAt) parts.push(`son işlem ${fmtShortDate(cost.lastAt)}`);
  return parts.join(" · ");
}

const fmtShortDate = (iso) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—"
    : d.toLocaleDateString("tr-TR", { day: "numeric", month: "short", year: "numeric" });
};

function renderOneEtfBook(etf, portfolios, price, live, basis) {
  // h3.sub, the same heading style the other in-card sections use.
  const head = `<h3 class="sub">${etf.label} &mdash; ${etf.metalLabel} ETF</h3>`;
  const mine = portfolios.filter((p) => p.asset === etf.key);

  if (!mine.length) {
    return head + `<p class="muted small">Defterler henüz kurulmadı &mdash;`
      + ` <code>supabase/schema.sql</code>'deki <code>${etf.key}</code> portföy`
      + ` migration'ı çalıştırılmamış.</p>`;
  }
  // A missing quote must not silently value the books at zero. Showing the
  // last known cash+units without a mark would be a number with no defined
  // meaning, so the row says so instead.
  if (price === null) {
    return head + `<p class="muted small">${etf.tv} fiyatı alınamadı &mdash;`
      + ` canlı fiyat gelmeden defterler değerlenemez.</p>`;
  }

  const byKey = new Map(mine.map((p) => [p.strategy, p]));
  const valueOf = (row) => Number(row.cash_usd) + Number(row.ounces) * price;
  const benchmark = byKey.get("buyhold");

  // PANELS, not table rows, and not because four rows were too wide: each book
  // now carries its own last fills, and a log cannot live in a table cell. The
  // form is deliberately the SAME as the metals' books above -- these are the
  // same four rules, and two shapes for one rule set says they are two kinds
  // of thing.
  //
  // "al-ve-tut'a göre" is computed the same way as in renderStrategies
  // (value / benchmarkValue - 1) rather than as the difference of the two
  // total returns the table used. The two agree to a rounding error because
  // every book starts at exactly $1,000, but identical-looking panels must not
  // mean two different things.
  const benchmarkValue = benchmark ? valueOf(benchmark) : null;
  const panels = ETF_STRATEGIES.map(({ key, label, benchmark: isBench }) => {
    const row = byKey.get(key);
    if (!row) {
      return `<div class="strategy-panel"><div class="name">${label}</div>
              <div class="value">-</div>
              <p class="muted tiny">Bu defter kurulmamış.</p></div>`;
    }
    const value = valueOf(row);
    const total = value / STARTING_CASH - 1;
    const exposure = value > 0 ? (Number(row.ounces) * price) / value : 0;
    const versus = isBench || !benchmarkValue ? null : value / benchmarkValue - 1;
    return `
      <div class="strategy-panel${isBench ? " benchmark" : ""}">
        <div class="name">${label}${isBench ? ' <span class="badge">kıyas</span>' : ""}</div>
        <div class="value">${fmtUsd(value)}</div>
        <div class="pnl ${total >= 0 ? "up-text" : "down-text"}">${fmtSignedPct(total)}</div>
        <div class="row"><span>pozisyon</span><span>${fmtPct(exposure)}</span></div>
        <div class="row"><span>hedef</span><span>${fmtPct(Number(row.target_exposure))}</span></div>
        ${versus === null ? "" : `
        <div class="row"><span>al-ve-tut'a göre</span>
          <span class="${versus >= 0 ? "up-text" : "down-text"}">${fmtSignedPct(versus)}</span></div>`}
        <div class="exposure-bar"><div style="width:${Math.min(100, exposure * 100).toFixed(1)}%"></div></div>
        <p class="muted tiny holding-line">${etfHoldingLine(etf, row, price, live, basis)}</p>
        ${bookLogHtml(etf.key, key)}
      </div>`;
  }).join("");

  const shown = price.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return head
    + `<div class="strategy-grid measured">${panels}</div>`
    + `<p class="muted small">${etf.tv} $${shown}`
    + ` <span class="muted">(${ETF_DELAY_MINUTES} dk gecikmeli)</span>`
    + ` &mdash; her defter $${STARTING_CASH.toLocaleString("tr-TR")} ile başladı.`
    + ` Komisyon bir oran değil, işlem başına <strong>sabit $1,50</strong>&#39;dır`
    + `${effectiveFeeText(etf)}. Küçük işlemlerde bu oran yükselir, büyük`
    + ` işlemlerde düşer; hesap büyüdükçe de düşer.`
    + `<br>Defterler <strong>pay</strong> tutuyor, külçe değil. Gram karşılığı`
    + ` ETF fiyatının spot fiyata oranından türetilmiş bir <strong>yaklaşıktır</strong>`
    + ` (bugün 1 ${etf.label} ≈ ${gramsPerShareText(etf, price, live)});`
    + ` ABD borsası kapalıyken ETF'in son kapanışı canlı spotla karşılaştırıldığı`
    + ` için bir-iki puan sapabilir.`
    + `<br>Ölçülen: ${etf.claim}</p>`;
}

/* What the flat fee has actually COST these four books, as a rate.
 *
 * The MEASURED effective rate, never an assumed one -- backend/backtest.py's
 * flat_fee_ladder prints the same number for the same reason: dividing $1.50
 * by the smallest possible trade gives 60 bp on a $5,000 account while the
 * measured figure is 11.7, because trades do not stay at that floor and the
 * book compounds. A flat fee has no basis-point value until it is divided by
 * the trades that actually happened.
 *
 * This sentence used to live under the ETF card's combined trade log. That log
 * is gone -- each book now shows its own fills, and each shows its own fee
 * total -- but the RATE is a property of all four together and had to survive
 * the change: it is the number that decides whether a $1,000 book can carry
 * this rule at all. */
function effectiveFeeText(etf) {
  const trades = (cache.trades ?? []).filter((t) => t.asset === etf.key);
  const fees = trades.reduce((sum, t) => sum + (Number(t.fee_usd) || 0), 0);
  const gross = trades.reduce((sum, t) => sum + (Number(t.usd_amount) || 0), 0);
  if (!(gross > 0)) return "";
  return ` &mdash; bugüne kadarki ${trades.length} işlemde tek yönde`
    + ` <strong>${fmtNumber((fees / gross) * 10_000, 1)} baz puana</strong> denk geldi`;
}

function gramsPerShareText(etf, price, live) {
  const perShare = metalOuncesPerShare(etf, price, live);
  return perShare === null ? "—"
    : `${fmtNumber(perShare * TROY_OUNCE_GRAMS, 3)} g`;
}

/* ------------------------------------------------------------ the answer */

// Which rule the headline speaks for. `voltarget` rather than the blend, and
// that is a measurement rather than a preference: research/instrument.py ran
// the whole scoreboard on GC=F, SI=F, GLD, IAU and SLV and volatility
// targeting is the ONLY strategy that beats buy-and-hold on Calmar in every
// column. The blend does it on the ETFs and not on the futures. Putting the
// blend here would headline a rule that fails in half the columns it was
// measured in.
const HEADLINE_STRATEGY = "voltarget";

function renderToday(portfolios, price, asset, row) {
  const mine = portfolios.filter((p) => p.asset === currentAsset);
  const state = mine.find((p) => p.strategy === HEADLINE_STRATEGY);
  const target = document.getElementById("today-target");
  const rows = document.getElementById("today-rows");
  const verdict = document.getElementById("today-verdict");

  document.getElementById("today-asset-name").textContent = asset.label;

  if (!state || !Number.isFinite(Number(state.target_exposure)) || !(price > 0)) {
    target.textContent = "-";
    rows.innerHTML = "";
    verdict.textContent = "Portföy durumu henüz yüklenmedi.";
    document.getElementById("today-note").textContent = "-";
    return;
  }

  const wanted = Number(state.target_exposure);
  const value = Number(state.cash_usd) + Number(state.ounces) * price;
  const now = value > 0 ? (Number(state.ounces) * price) / value : 0;
  const action = nextActionFor(state, price, now, value);

  target.textContent = fmtPct(wanted, 0);
  // Two marks, not one: the bar is the TARGET, the notch is where the book
  // actually sits. A single bar would answer "what should I hold" and hide
  // the only question that produces an action -- "how far off am I".
  document.getElementById("today-bar-fill").style.width =
    `${Math.min(100, Math.max(0, wanted * 100)).toFixed(1)}%`;
  document.getElementById("today-bar-now").style.left =
    `${Math.min(100, Math.max(0, now * 100)).toFixed(1)}%`;

  const direction = row?.predicted_direction;
  const edge = row?.edge_over_base;

  // Labels are short and NOWRAP (see style.css): in the hero this card is
  // ~660px wide, and a label allowed to shrink broke "Sonraki işlem" onto two
  // lines and "5 günlük yön çağrısı" onto three, turning a four-row list into
  // a paragraph.
  //
  // The blend's target is NOT repeated here. Piyasa Durumu prints it from the
  // prediction row (`target_exposure`) directly alongside this card in the
  // hero, and this one would have come from the portfolios table -- the same
  // quantity down two different paths, side by side, where any future
  // divergence would read as a bug in the page rather than in the data.
  rows.innerHTML = [
    ["Şu anki pozisyon", fmtPct(now, 0)],
    ["Sonraki işlem", action.text],
    // Kept, and kept SMALL. The direction call is genuine output and hiding
    // it would be its own dishonesty; giving it the headline was the problem.
    //
    // The label alone is not enough, and the worst case is "YÜKSELİŞ with a
    // negative edge": p_up is above 0.5 so the model says up, while sitting
    // BELOW the base rate -- i.e. less optimistic than knowing nothing at all.
    // renderPrediction spells this out in its own card; a compact row that
    // printed the two values side by side without saying so would let the
    // reader take "YÜKSELİŞ" at face value on exactly the days it is
    // misleading.
    ["Yön çağrısı (5 gün)", direction
      ? `${direction === "UP" ? "YÜKSELİŞ" : "DÜŞÜŞ"} · taban orana fark ${fmtPoints(edge)}`
        + (direction === "UP" && Number(edge) < 0
           ? ` <span class="silenced">(taban oranın altında — alım sinyali değil)</span>`
           : "")
      : "-"],
  ].map(([label, text]) =>
    `<div class="row"><span>${label}</span><span>${text}</span></div>`).join("");

  // One sentence, because a reader who does not want to read a bar chart
  // still has to be able to leave this card knowing what it said.
  const drift = now - wanted;
  if (Math.abs(drift) <= REBALANCE_THRESHOLD) {
    verdict.innerHTML = `Bugün <strong>yapılacak bir şey yok</strong> &mdash; pozisyon `
      + `zaten hedefin ${Math.abs(drift) < 0.005 ? "tam üzerinde" : "5 puanlık bandı içinde"}.`;
  } else if (drift > 0) {
    verdict.innerHTML = `Kural bugün <strong>pozisyon azaltmayı</strong> söylüyor: `
      + `elde %${fmtNumber(now * 100, 0)}, hedef %${fmtNumber(wanted * 100, 0)}. `
      + `Sebep yön tahmini değil, <strong>oynaklığın yükselmesi</strong>.`;
  } else {
    verdict.innerHTML = `Kural bugün <strong>pozisyon artırmayı</strong> söylüyor: `
      + `elde %${fmtNumber(now * 100, 0)}, hedef %${fmtNumber(wanted * 100, 0)}. `
      + `Sebep yön tahmini değil, <strong>oynaklığın yatışması</strong>.`;
  }

  document.getElementById("today-note").textContent =
    `Bu kural yılda yaklaşık 8 işlem yapar; çoğu gün doğru cevap "hiçbir şey yapma"dır. `
    + `Yüzde, defterin metalde tutulan kısmıdır — kalanı nakittir.`;
  document.getElementById("today-updated").textContent =
    state.updated_at ? `son güncelleme ${fmtDateTime(state.updated_at)}` : "";
}

/* --------------------------------------------------- the measured sample */

// Which curves are drawn. `buyhold` is always on and is not in this set: it
// is the benchmark, not a selection. Default pairs the headline rule with the
// full blend -- two lines plus the reference, which is what a first read can
// actually hold. Everything else is one click away.
let backtestSelection = new Set([HEADLINE_STRATEGY, "ensemble"]);


function backtestLabel(key) {
  return STRATEGIES.find((s) => s.key === key)?.label ?? key;
}


function renderBacktest(asset) {
  const card = document.getElementById("backtest-card");
  const payload = cache.backtest?.assets?.[currentAsset];
  const root = document.getElementById("backtest-charts");
  const body = document.querySelector("#backtest-table tbody");

  if (!payload) {
    card.hidden = true;
    return;
  }
  card.hidden = false;
  document.getElementById("backtest-asset-name").textContent = asset.label;
  document.getElementById("backtest-window").textContent =
    `${payload.start} → ${payload.end} · ${fmtNumber(payload.years, 1)} yıl · `
    + `${payload.sessions.toLocaleString("tr-TR")} seans · komisyon tek yön ${payload.fee_bps} bp`;

  document.getElementById("backtest-toggle").innerHTML = BACKTEST_SERIES
    .filter((key) => payload.strategies[key])
    .map((key) => {
      const on = backtestSelection.has(key);
      return `<button class="chip${on ? " on" : ""}" data-series="${key}"`
        + ` style="--chip:${Viz.colourFor(key)}" aria-pressed="${on}">`
        + `${esc(backtestLabel(key))}</button>`;
    }).join("");

  const keys = ["buyhold", ...BACKTEST_SERIES.filter((k) =>
    backtestSelection.has(k) && payload.strategies[k])];
  const series = keys.map((key) => {
    const equity = payload.strategies[key].equity;
    return { key, label: backtestLabel(key), short: BACKTEST_SHORT[key] ?? key,
             equity, drawdown: Viz.drawdownOf(equity) };
  });

  // A FIXED caption, not a hover readout. It used to follow a crosshair and
  // rewrite itself on every pointer move; the numbers moved out from under the
  // reader, and nothing on the card could be quoted or compared. It now states
  // where each drawn curve ENDED -- the value and how far below its own peak
  // that value sits, which is the pair this project's claim is about and the
  // second number is not in the table below (that column is the WORST
  // drawdown, not today's).
  const last = payload.dates.length - 1;
  document.getElementById("backtest-readout").innerHTML =
    `<span class="muted">son seans</span> `
    + `<span class="readout-date">${payload.dates[last]}</span>`
    + series.map((s) =>
      `<span class="readout-item"><i style="background:${Viz.colourFor(s.key)}"></i>`
      + `${esc(s.label)} <strong>${fmtUsd(s.equity[last], 0)}</strong>`
      + ` <em>${fmtDrawdown(s.drawdown[last])}</em></span>`).join("");

  Viz.renderBacktestCharts(root, { dates: payload.dates, series });

  // The table view. Required rather than optional: it is the non-visual path
  // to the same numbers, and it is also the only place the trade COUNT shows
  // up -- which is what decides whether a curve survives a real commission.
  const bench = payload.strategies.buyhold;
  body.innerHTML = ["buyhold", ...BACKTEST_SERIES]
    .filter((key) => payload.strategies[key])
    .sort((a, b) => payload.strategies[b].calmar - payload.strategies[a].calmar)
    .map((key) => {
      const m = payload.strategies[key];
      const isBench = key === "buyhold";
      const better = !isBench && m.calmar > bench.calmar;
      return `<tr class="${isBench ? "benchmark-row" : ""}">
        <td><i class="swatch" style="background:${Viz.colourFor(key)}"></i>
            ${esc(backtestLabel(key))}${isBench ? ' <span class="badge">kıyas</span>' : ""}</td>
        <td class="num">${fmtUsd(m.final, 0)}</td>
        <td class="num">${fmtPct(m.cagr, 1)}</td>
        <td class="num down-text">${fmtPct(m.max_dd, 1)}</td>
        <td class="num ${better ? "up-text" : ""}">${fmtNumber(m.calmar, 3)}</td>
        <td class="num">${m.trades.toLocaleString("tr-TR")}</td>
        <td class="num">${fmtUsd(m.fees, 0)}</td>
      </tr>`;
    }).join("");
  labelTableCells(card);

  const beat = BACKTEST_SERIES.filter((k) => payload.strategies[k]
    && payload.strategies[k].calmar > bench.calmar);
  const richer = BACKTEST_SERIES.filter((k) => payload.strategies[k]
    && payload.strategies[k].final > bench.final);
  // Both sentences, always, and in this order. Calmar and money disagree here
  // and that disagreement IS the finding -- reporting only the first would
  // repeat exactly the overstatement research/README.md section 17 exists to
  // correct.
  // `miners` wins both columns here and is NOT buyable: its edge was measured
  // to come almost entirely from a session-boundary phase shift between the
  // ~23-hour futures bar and GDX's 6.5-hour one, and it vanishes on GLD/IAU/
  // SLV (lead correlation +0.150 -> +0.040). The caveat travels with the name
  // everywhere else on this page; a summary line that named it as the money
  // winner without it would be the one place a reader could take it straight.
  const winners = (list) => list.length
    ? list.map((k) => backtestLabel(k) + (k === "miners" ? "*" : "")).join(", ")
    : "<strong>HİÇBİRİ</strong>";
  const minersNote = (beat.includes("miners") || richer.includes("miners"))
    ? ` <strong>*</strong> Madenciler satın alınabilir bir strateji DEĞİL — kazancı `
      + `vadeli kontratın seans saatlerinden geliyor ve ETF'te kayboluyor.`
    : "";
  document.getElementById("backtest-note").innerHTML =
    `Al-ve-tut'u <strong>Calmar'da</strong> (risk-ayarlı) geçen: ${winners(beat)}. `
    + `Al-ve-tut'tan <strong>daha fazla para</strong> kazandıran: ${winners(richer)}. `
    + `Bu ikisinin aynı liste olmaması bu projenin en pahalı dersidir: Calmar bir `
    + `risk ölçütüdür, kâr değil.${minersNote}`;
}

document.addEventListener("click", (event) => {
  const chip = event.target.closest("#backtest-toggle .chip");
  if (!chip) return;
  const key = chip.dataset.series;
  if (backtestSelection.has(key)) backtestSelection.delete(key);
  else backtestSelection.add(key);
  renderBacktest(ASSETS[currentAsset]);
});

// The SVG is rendered at the container's pixel width rather than scaled by
// viewBox, so the axis labels stay 11px at every width instead of shrinking
// to 4px on a phone. That means a resize needs a real re-render.
let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    renderBacktest(ASSETS[currentAsset]);
    // Same reason: the breakout panel's SVG is rendered at its container's
    // pixel width, so it needs a real re-render rather than a viewBox rescale.
    renderBreakout(cache.breakout, ASSETS[currentAsset]);
  }, 150);
});

/* Stamps every table cell with the header text above it.

   Needed because below ~700px no eight-column table fits a phone, and the
   answer this page is allowed to use is NOT a sideways scroll -- the rows
   turn into "label: value" blocks instead (see style.css). That needs each
   cell to carry its own label.

   Done by READING the <th> row rather than by having each render function
   write `data-label` itself. Six different functions emit table rows here,
   and a label typed out a second time next to the value is a label that
   drifts from its header the first time someone renames a column. This
   cannot drift: it is the header, at render time.

   Cells that span (the "no rows yet" placeholder) are skipped -- they have no
   single header and a label on them would read as a column that does exist. */
function labelTableCells(root = document) {
  for (const table of root.querySelectorAll("table")) {
    const headers = [...table.querySelectorAll("thead th")].map((th) => th.textContent.trim());
    if (!headers.length) continue;
    for (const row of table.querySelectorAll("tbody tr")) {
      [...row.cells].forEach((cell, i) => {
        if (cell.colSpan > 1) return;
        if (headers[i]) cell.setAttribute("data-label", headers[i]);
      });
    }
  }
}

function renderAll() {
  const asset = ASSETS[currentAsset];
  // Repaints every asset-scoped card in the selected metal's colour. The
  // numbers below the tab strip are mostly percentages that look identical
  // between the two assets, so this is the cue that they changed meaning.
  document.getElementById("app").dataset.asset = currentAsset;
  const row = cache.predictions[currentAsset]?.[0] ?? null;
  const mark = valuationPrice(currentAsset);

  renderToday(cache.portfolios, mark.price, asset, row);
  renderBacktest(asset);
  renderPrediction(row, asset);
  renderContext(row, asset);
  renderComponents(row, asset);
  renderRecords(cache.records, asset, row);
  renderStrategies(cache.portfolios, mark.price, asset, cache.costBasis);
  renderLiveChart(asset, mark.price);
  renderValuationNote(asset, mark);
  renderHistory(cache.predictions[currentAsset] ?? [], asset);
  renderKanalFinansBook(cache.portfolios, mark.price, asset, cache.costBasis);
  renderBreakout(cache.breakout, asset);
  renderBreakoutBook(cache.portfolios, mark.price, asset, cache.costBasis);
  renderKanalFinans(cache.mentions, cache.themes);
  // Asset-scoped -- see renderEtfBooks. Rendered from renderAll anyway
  // so a tab switch repaints it with whatever the price loop last had.
  renderEtfBooks(cache.portfolios, cache.live);
  // LAST, and after every table on the page has been written. See
  // labelTableCells: the narrow-screen layout reads these labels.
  labelTableCells();
}

/* ------------------------------------------------------------------ load */

// Declared before its use in loadData rather than after: a `const` is in the
// temporal dead zone until evaluated, so the current bottom-of-file call
// order is the only thing that makes a later declaration work.
const EMPTY_LIVE = { gold: null, silver: null, usdtry: null, futures: {}, etfs: {}, open: {}, delayed: false, source: "" };

/* Supabase data. One row per trading day, so this stays on the slow cycle --
   polling it every few seconds would re-download identical bytes. */
// The measured history, fetched once. A failure here must not take the live
// dashboard down with it: the card hides itself and everything else renders,
// which is the same fail-soft rule predict.py applies to a dead macro series.
// SCHEMA is checked rather than trusted -- a payload whose fields moved
// should blank the card, not draw half a chart from the fields that survived.
const BACKTEST_SCHEMA = 1;

async function loadBacktest() {
  if (cache.backtest) return;
  try {
    const response = await fetch("data/backtest.json", { cache: "no-cache" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    if (payload.schema !== BACKTEST_SCHEMA) {
      console.warn(`backtest.json şema ${payload.schema}, beklenen ${BACKTEST_SCHEMA} -- atlandı.`);
      return;
    }
    cache.backtest = payload;
    // Drawn the moment it lands, rather than waiting for renderAll() at the
    // end of the Supabase batch. This card needs NO live data -- a static
    // file and nothing else -- so making it wait on Supabase would mean an
    // outage there blanks the one panel on this page that cannot be affected
    // by it. Same fail-soft rule predict.py applies to a dead macro series.
    renderBacktest(ASSETS[currentAsset]);
  } catch (error) {
    console.warn("Ölçülmüş geçmiş yüklenemedi:", error.message);
  }
}

/* The breakout window. Fetched with its OWN error handling rather than inside
   loadData's batch, and that is not tidiness.

   `api()` throws on a non-200 and loadData wraps the whole batch in one
   try/catch, so a `breakout_state` that does not exist yet -- the migration
   is applied by hand, by a person, later than the deploy -- would take down
   the entire page with "Veri yüklenemedi". Every portfolio, every price and
   every prediction, gone, because one card's table is missing.

   Same fail-soft rule loadBacktest() follows, and the same one predict.py
   applies to a dead macro series: the part that cannot load says so, and
   nothing else notices. */
async function loadBreakout() {
  try {
    // Two metals x WINDOW_SESSIONS rows. Well under PostgREST's ~1000-row
    // cap, so this does not need apiAll -- but it is asked for explicitly
    // rather than left to the default, because the default is what would
    // silently truncate the chart if the window were ever widened.
    cache.breakout = await api(
      "breakout_state?select=*&order=session_date.desc&limit=500");
  } catch (error) {
    console.warn("Kırılım durumu yüklenemedi:", error.message);
    cache.breakout = null;
  }
}

async function loadData() {
  try {
    // In the same batch, not before it: serialising them would add a round
    // trip to every five-minute cycle for a file that is fetched once.
    const [, , gold, silver, portfolios, trades, records, mentions, themes] = await Promise.all([
      loadBacktest(),
      loadBreakout(),
      // 400, not 30. The track-record table shows a window, but the live
      // equity curve is rebuilt from EVERY row -- each one is a day's mark
      // price -- so a 30-row cap would quietly truncate the chart to its last
      // six weeks about a month from now, with nothing on screen saying so.
      // One row per trading day per metal: 400 is roughly a year and a half.
      api("predictions?select=*&asset=eq.gold&order=target_date.desc&limit=400"),
      api("predictions?select=*&asset=eq.silver&order=target_date.desc&limit=400"),
      api("portfolios?select=*"),
      // Ascending and complete: the average-cost replay has to see every fill
      // in the order it happened, so this is the one query that pages.
      // created_at/fee_usd/reason ride along for the trade log -- the rows
      // were already being downloaded, so the log costs no extra round trip.
      apiAll("trades?select=asset,strategy,side,price,ounce_amount,usd_amount,fee_usd,"
             + "reason,created_at&order=created_at.asc"),
      // Ten rows (five components x two metals). The evidence behind the
      // "Etki" column, which retrain.py rebuilds from scratch every night.
      api("model_state?select=*"),
      api("kanal_finans_mentions?select=*&order=published_at.desc&limit=40"),
      api("kanal_finans_themes?select=*&order=published_at.desc&limit=40"),
    ]);

    cache.predictions = { gold, silver };
    cache.portfolios = portfolios;
    cache.trades = trades;
    cache.records = records;
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
    etfs: tv?.etfs ?? {},
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
    renderLiveChart(asset, mark.price);
    renderValuationNote(asset, mark);
    // The follower's book is ounces x price like the rest; it just lives in
    // another card now, and leaving it out would freeze one panel on the page
    // at whatever loadData last saw while its neighbours moved.
    renderKanalFinansBook(cache.portfolios, mark.price, asset, cache.costBasis);
    // Same again for the breakout book: ounces x price, and its "waiting for
    // $X (+%Y)" line is computed against the live price, so it is stale by
    // exactly as much as the tick it misses.
    renderBreakoutBook(cache.portfolios, mark.price, asset, cache.costBasis);
    // The ETF books are ounces x price too, and their price arrives on this
    // same tick. Left out, the card would sit at whatever loadData last saw
    // (five minutes) while everything beside it moved every two seconds.
    renderEtfBooks(cache.portfolios, cache.live);
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
