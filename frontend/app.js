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
const TROY_OUNCE_GRAMS = 31.1034768;

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
let cache = { predictions: {}, portfolios: [], mentions: [], themes: [] };

/* ---------------------------------------------------------------- helpers */

async function api(path) {
  const response = await fetch(`${REST}/${path}`, { headers: HEADERS });
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
  return response.json();
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
        symbols: { tickers: Object.values(TV_TICKERS) },
        columns: ["close", "update_mode"],
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
    const gold = read(TV_TICKERS.gold);
    const silver = read(TV_TICKERS.silver);
    if (gold === null && silver === null) return null;
    // The feed says whether it is real-time or delayed. Reading it means the
    // "canlı" badge stops being a hardcoded claim: if TradingView ever serves
    // this account a delayed quote, the card says "gecikmeli" instead of
    // asserting something that is no longer true.
    const modes = Object.values(TV_TICKERS)
      .map((t) => bySymbol.get(t)?.[1])
      .filter(Boolean);
    return {
      gold, silver,
      usdtry: read(TV_TICKERS.usdtry),
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

function livePriceCard({ label, metal, usd, usdtry, source, live, badge, footnote }) {
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
  return `
    <div class="${skin}${live ? " is-live" : ""}">
      <div class="live-label">${label}
        <span class="live-badge">${badge ?? (live ? "canlı" : "son kapanış")}</span>
      </div>
      <div class="live-usd">${fmtUsd(usd, digits)}<span class="unit">/ons</span></div>
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
    return livePriceCard({
      label,
      metal: key,
      usd: spot ?? close,
      usdtry,
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

  document.getElementById("live-note").innerHTML = usdtry
    ? `TL değerleri <strong>paritedir</strong>: dolar fiyatı × USDTRY `
      + `(${fmtNumber(usdtry, 4)}). Türkiye'de gram altın bu paritenin `
      + `<em>üzerinde</em> bir primle işlem görür, dolayısıyla bu sayı kuyumcu fiyatı değildir.`
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

function renderStrategies(portfolios, price, asset) {
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

function renderAll() {
  const asset = ASSETS[currentAsset];
  // Repaints every asset-scoped card in the selected metal's colour. The
  // numbers below the tab strip are mostly percentages that look identical
  // between the two assets, so this is the cue that they changed meaning.
  document.getElementById("app").dataset.asset = currentAsset;
  const row = cache.predictions[currentAsset]?.[0] ?? null;
  const price = row ? Number(row.price_at_prediction) : 0;

  renderPrediction(row, asset);
  renderContext(row, asset);
  renderComponents(row, asset);
  renderStrategies(cache.portfolios, price, asset);
  renderHistory(cache.predictions[currentAsset] ?? [], asset);
}

/* ------------------------------------------------------------------ load */

async function load() {
  try {
    // Every price call rides in the same Promise.all as the Supabase ones
    // rather than in a second round trip, and each resolves to null on
    // failure, so none of them can delay or break the rest of the page.
    // Binance is fetched unconditionally rather than only when TradingView
    // fails: it costs one small request and it means the fallback is already
    // in hand instead of adding a second serial round trip at the worst
    // possible moment.
    const [gold, silver, portfolios, mentions, themes, tv, paxg, binanceFx] =
      await Promise.all([
        api("predictions?select=*&asset=eq.gold&order=target_date.desc&limit=30"),
        api("predictions?select=*&asset=eq.silver&order=target_date.desc&limit=30"),
        api("portfolios?select=*"),
        api("kanal_finans_mentions?select=*&order=published_at.desc&limit=40"),
        api("kanal_finans_themes?select=*&order=published_at.desc&limit=40"),
        fetchTradingView(),
        fetchBinance("PAXGUSDT"),
        fetchBinance("USDTTRY"),
      ]);

    // TradingView first because it is the only source that carries silver.
    // Binance fills whatever it left null -- gold and FX only, since it has
    // no silver at all -- and silver then falls through to its last COMEX
    // close, labelled as such by the renderer.
    const live = {
      gold: tv?.gold ?? paxg,
      silver: tv?.silver ?? null,
      usdtry: tv?.usdtry ?? binanceFx,
      delayed: tv?.delayed ?? false,
      source: tv?.gold ? tv.source : "Binance",
    };

    cache = { predictions: { gold, silver }, portfolios, mentions, themes };

    // The gold/silver ratio is not per-asset, so it renders outside the
    // per-asset block. Prefer the value predict.py stored (it comes from the
    // same aligned panel the model sees) and fall back to dividing the two
    // latest prices, which is right whenever both rows are from the same day
    // and quietly wrong when one metal's row is staler than the other's.
    renderRatio(gold[0], silver[0]);
    renderLivePrices(live, gold[0], silver[0]);

    renderKanalFinans(mentions, themes);
    renderAll();
  } catch (error) {
    showError(error.message);
  }
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

load();
// The backend produces one row per trading day, so polling faster than this
// would just re-fetch identical data. Five minutes keeps a left-open tab
// current without hammering Supabase.
setInterval(load, 5 * 60 * 1000);

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}
