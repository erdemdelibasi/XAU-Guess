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
   (2026-09-08). Yahoo -- the backend's primary -- returns no
   Access-Control-Allow-Origin header, so a browser simply cannot call it;
   every price on this page therefore has to come from somewhere else or from
   Supabase. Binance's public host does send `Access-Control-Allow-Origin: *`
   and carries both PAXGUSDT and USDTTRY, so it can serve gold and the FX
   rate 24/7.

   It cannot serve SILVER. XAGUSDT, SLVUSDT and KAGUSDT all come back
   "Invalid symbol" -- there is no silver token on that venue, which is the
   same gap fetch_data.py documents on the backend. So silver's number here
   is its last COMEX close, out of Supabase, LABELLED as such. Printing it
   under a heading that says "anlık" would be exactly the substitution this
   project refuses to make: a number whose provenance differs from its label
   is worse than an honest gap. */
const BINANCE = "https://data-api.binance.vision/api/v3/ticker/price";
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

function livePriceCard({ label, usd, usdtry, source, live, footnote }) {
  if (usd === null || usd === undefined) {
    return `<div class="live-card"><div class="live-label">${label}</div>
            <div class="live-usd">-</div>
            <div class="muted small">fiyat alınamadı</div></div>`;
  }
  const digits = label === "Gümüş" ? 3 : 2;
  // TL is always DERIVED, never quoted: there is no lira-denominated feed
  // here, so it is dollar price x USDTRY and nothing more.
  const tlOunce = usdtry ? usd * usdtry : null;
  const tlGram = tlOunce === null ? null : tlOunce / TROY_OUNCE_GRAMS;
  return `
    <div class="live-card${live ? " is-live" : ""}">
      <div class="live-label">${label}
        <span class="live-badge">${live ? "canlı" : "son kapanış"}</span>
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

function renderLivePrices(spotGold, usdtry, goldRow, silverRow) {
  const comexGold = goldRow ? Number(goldRow.price_at_prediction) : null;
  const comexSilver = silverRow ? Number(silverRow.price_at_prediction) : null;
  const asOf = (row) => (row?.created_at ? fmtDate(row.created_at) : "-");

  // Gold's live quote is PAXG, which tracks SPOT; the model reads GC=F, a
  // futures contract sitting above spot by its financing and storage cost
  // (measured 1.9% on 2026-09-07 and 0.94% on 2026-09-08 -- not a constant).
  // Both are shown because a reader comparing this panel against the
  // prediction card would otherwise find a few-percent discrepancy with no
  // explanation.
  //
  // The gap is NOT labelled "basis", which is what it was called first and
  // is wrong: the stored close can be days old, so the difference is the
  // futures-spot basis PLUS everything the market did since that close. Two
  // effects share one number and the label has to say so, or the panel
  // quietly reports a stale price move as a financing cost.
  const gap = spotGold && comexGold ? spotGold / comexGold - 1 : null;

  const cards = [
    livePriceCard({
      label: "Altın",
      usd: spotGold ?? comexGold,
      usdtry,
      live: Boolean(spotGold),
      source: spotGold
        ? "PAXG spot &middot; Binance, 7/24"
        : `COMEX GC=F kapanışı &middot; ${asOf(goldRow)}`,
      footnote:
        spotGold && comexGold
          ? `Model <strong>COMEX vadeli</strong> kapanışını kullanıyor: ${fmtUsd(comexGold, 2)} `
            + `(${asOf(goldRow)}). Aradaki %${fmtNumber(Math.abs(gap * 100), 1)} fark iki şeyi `
            + `birden içerir: vadeli&ndash;spot bazı ve o kapanıştan bu yana olan hareket.`
          : "",
    }),
    livePriceCard({
      label: "Gümüş",
      usd: comexSilver,
      usdtry,
      live: false,
      source: `COMEX SI=F kapanışı &middot; ${asOf(silverRow)}`,
      footnote: "Gümüşün tarayıcıdan çağrılabilen 7/24 kaynağı yok &mdash; bu fiyat anlık değil.",
    }),
  ];
  document.getElementById("live-prices").innerHTML = cards.join("");

  document.getElementById("live-note").innerHTML = usdtry
    ? `TL değerleri <strong>paritedir</strong>: dolar fiyatı × USDTRY `
      + `(${fmtNumber(usdtry, 4)}, Binance USDTTRY). Türkiye'de gram altın bu paritenin `
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
  const note = document.getElementById("components-note");
  if (row.cold_start) {
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

    return `
      <div class="strategy-panel${strategy.benchmark ? " benchmark" : ""}${strategy.follower ? " follower" : ""}">
        <div class="name">${strategy.label}${strategy.benchmark ? '<span class="badge">kıyas</span>' : ""}</div>
        <p class="desc">${strategy.desc}</p>
        <div class="value">${fmtUsd(value, 0)}</div>
        <div class="pnl ${pnl >= 0 ? "up-text" : "down-text"}">${pnl >= 0 ? "+" : ""}${(pnl * 100).toFixed(2)}%</div>
        <div class="row"><span>pozisyon</span><span>${fmtPct(exposure, 0)}</span></div>
        ${extraRow}
        ${vsBenchmark === null ? "" : `
        <div class="row"><span>al-ve-tut'a göre</span>
          <span class="${vsBenchmark >= 0 ? "up-text" : "down-text"}">
            ${vsBenchmark >= 0 ? "+" : ""}${(vsBenchmark * 100).toFixed(2)}%
          </span></div>`}
        <div class="exposure-bar"><div style="width:${Math.min(100, exposure * 100).toFixed(1)}%"></div></div>
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
    return `
      <tr>
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
    summary.textContent = "Henüz çözülmüş tahmin yok.";
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
    // The two Binance calls sit in the same Promise.all as the Supabase ones
    // rather than in a second round trip: they resolve to null on failure,
    // so they can never delay or break the rest of the page.
    const [gold, silver, portfolios, mentions, themes, spotGold, usdtry] =
      await Promise.all([
        api("predictions?select=*&asset=eq.gold&order=target_date.desc&limit=30"),
        api("predictions?select=*&asset=eq.silver&order=target_date.desc&limit=30"),
        api("portfolios?select=*"),
        api("kanal_finans_mentions?select=*&order=published_at.desc&limit=40"),
        api("kanal_finans_themes?select=*&order=published_at.desc&limit=40"),
        fetchBinance("PAXGUSDT"),
        fetchBinance("USDTTRY"),
      ]);

    cache = { predictions: { gold, silver }, portfolios, mentions, themes };

    // The gold/silver ratio is not per-asset, so it renders outside the
    // per-asset block. Prefer the value predict.py stored (it comes from the
    // same aligned panel the model sees) and fall back to dividing the two
    // latest prices, which is right whenever both rows are from the same day
    // and quietly wrong when one metal's row is staler than the other's.
    renderRatio(gold[0], silver[0]);
    renderLivePrices(spotGold, usdtry, gold[0], silver[0]);

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
