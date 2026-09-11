/* Dependency-free SVG charts for XAU-Guess.

   WHY HAND-ROLLED AND NOT A LIBRARY
   ---------------------------------
   The rest of this frontend is plain HTML/CSS/JS with no build step, served
   as a PWA with an offline service worker. Pulling a charting library in
   would add a CDN dependency to a page whose whole value is that it keeps
   working, and would do it for two chart types. What is here is the two
   chart types.

   WHY THE CHARTS EXIST AT ALL
   ---------------------------
   This project's central measured claim is "the same money with less pain"
   -- maximum drawdown 44.4% -> 40.0% on gold, at the cost of some return.
   Until now that claim lived in a table. A number in a table is read; a
   drawdown band is FELT, which is the entire point of the claim. The
   drawdown chart below is not decoration, it is the argument.

   COLOUR
   ------
   The eight categorical hues are the dataviz reference palette's dark steps,
   validated against THIS page's card surface (#15120d) rather than assumed:
   lightness band, chroma floor, adjacent CVD separation (worst dE 8.4),
   normal-vision floor (worst dE 19.3) and 3:1 contrast all pass. Do not
   substitute a hue by eye -- re-run the validator.

   Two rules that are easy to break later:

     * Colour follows the STRATEGY, never its position in the legend or its
       rank in the table. Toggling a series off must not repaint the others,
       or the reader's memory of "blue is voltarget" is destroyed every time
       they filter.
     * `buyhold` is deliberately NOT one of the eight. It is the benchmark
       every other line is judged against, so it reads as a different KIND of
       mark -- muted, dashed -- rather than as a ninth competitor. Giving it a
       categorical hue would put the reference line into the comparison it is
       the reference for.

   Every visible line is ALSO direct-labelled at its right end, so identity
   never rests on colour alone. */

/* Everything below lives inside one IIFE and reaches app.js through a single
   global, `Viz`. Both files are plain <script> tags sharing one global scope,
   and the first version of this file declared a top-level `const esc` that
   app.js also declares -- which does not warn, does not fail at the
   collision, and instead makes the SECOND script fail to parse in its
   entirety. The page rendered its static HTML and every number stayed "-",
   with one line in the console. A namespace makes that impossible rather
   than merely unlikely. */
const Viz = (() => {

// Fixed slot order. Assigned in the order the series appear in the legend,
// because that is the adjacency the palette validator scored.
const SERIES_COLOURS = {
  voltarget: "#3987e5",   // slot 1  blue
  trend:     "#d95926",   // slot 2  orange
  defensive: "#199e70",   // slot 3  aqua
  ensemble:  "#c98500",   // slot 4  yellow
  technical: "#d55181",   // slot 5  magenta
  ml:        "#008300",   // slot 6  green
  macro:     "#9085e9",   // slot 7  violet
  miners:    "#e66767",   // slot 8  red
};
const BENCHMARK_COLOUR = "#b9ae99";   // muted ink, not a categorical slot

const AXIS = "#6f6552";
const GRID = "rgba(255,255,255,0.06)";
const INK = "#9a8f7d";

function colourFor(key) {
  return key === "buyhold" ? BENCHMARK_COLOUR : (SERIES_COLOURS[key] ?? BENCHMARK_COLOUR);
}

const esc = (s) => String(s).replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ---------------------------------------------------------------- scales */

// Log ticks at 1-2-5 per decade. A 19.5-year equity curve runs $1,000 ->
// $9,700; on a linear axis the first decade is a flat line against the
// bottom and the reader concludes nothing happened for ten years. Log is the
// honest axis for a compounding series -- equal vertical distance is equal
// PERCENTAGE move, which is what a strategy comparison is about.
// Nearest 1-2-5 step at or beyond `v`, so an axis bound always lands on a
// value logTicks() will actually draw a line at.
function snapLog(v, direction) {
  const exp = Math.floor(Math.log10(v));
  const steps = [];
  for (let e = exp - 1; e <= exp + 1; e++) {
    for (const m of [1, 2, 5]) steps.push(m * Math.pow(10, e));
  }
  steps.sort((a, b) => a - b);
  return direction === "down"
    ? steps.filter((s) => s <= v).pop() ?? v
    : steps.find((s) => s >= v) ?? v;
}

function logTicks(min, max) {
  const out = [];
  for (let exp = Math.floor(Math.log10(min)); exp <= Math.ceil(Math.log10(max)); exp++) {
    for (const m of [1, 2, 5]) {
      const v = m * Math.pow(10, exp);
      if (v >= min * 0.999 && v <= max * 1.001) out.push(v);
    }
  }
  return out.length >= 3 ? out : [min, (min + max) / 2, max];
}

function niceTicks(min, max, count = 5) {
  const span = max - min || 1;
  const raw = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].find((m) => m * mag >= raw) * mag;
  const out = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(v);
  return out;
}

/* ----------------------------------------------------------------- chart */

/**
 * One time-series panel as an SVG string.
 *
 * `series`  [{ key, label, values:[number|null] }]  -- aligned to `dates`
 * `yType`   "log" (equity) | "linear" (drawdown, percentages <= 0)
 */
function timeSeriesPanel({ series, dates, width, height, yType, yFormat, zeroLine,
                          xLabels = true }) {
  // padR holds the direct labels. Measured rather than guessed: the longest
  // is "Al-ve-tut" at 11px/600, which needs ~64px plus the 6px leader.
  const padL = 54, padR = 78, padT = 12;
  const padB = xLabels ? 22 : 8;
  const w = Math.max(280, width), h = height;
  const plotW = w - padL - padR, plotH = h - padT - padB;

  const all = series.flatMap((s) => s.values).filter((v) => v != null && isFinite(v));
  if (!all.length || !dates.length) return "";
  let lo = Math.min(...all), hi = Math.max(...all);
  if (yType === "log") {
    // Snap to the nearest 1-2-5 step, NOT to the full decade. Rounding out to
    // decades put a $100 gridline under a series whose lowest point is $840,
    // spending 40% of the panel's height on empty space and flattening the
    // curve it exists to show.
    lo = snapLog(lo, "down");
    hi = snapLog(hi, "up");
  } else {
    hi = Math.max(hi, 0);
    lo = lo - (hi - lo) * 0.04;
  }

  const xAt = (i) => padL + (dates.length < 2 ? plotW / 2 : (i / (dates.length - 1)) * plotW);
  const yAt = (v) => {
    const t = yType === "log"
      ? (Math.log10(v) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo))
      : (v - lo) / (hi - lo || 1);
    return padT + plotH - t * plotH;
  };

  const ticks = yType === "log" ? logTicks(lo, hi) : niceTicks(lo, hi, 4);
  const grid = ticks.map((v) => {
    const y = yAt(v).toFixed(1);
    return `<line x1="${padL}" x2="${padL + plotW}" y1="${y}" y2="${y}" stroke="${GRID}"/>`
      + `<text x="${padL - 8}" y="${y}" fill="${INK}" font-size="11" text-anchor="end"`
      + ` dominant-baseline="middle">${esc(yFormat(v))}</text>`;
  }).join("");

  // Year boundaries, thinned so labels never collide at phone width.
  const yearAt = [];
  let lastYear = null;
  dates.forEach((d, i) => {
    const y = d.slice(0, 4);
    if (y !== lastYear) { yearAt.push({ i, y }); lastYear = y; }
  });
  const everyN = Math.ceil(yearAt.length / Math.max(3, Math.floor(plotW / 62)));
  // Gridlines on both panels, the year TEXT only on the lower one. They are
  // stacked on one shared x-axis, so printing the years twice labels the
  // same axis twice and reads as two separate charts.
  const xAxis = yearAt.filter((_, n) => n % everyN === 0).map(({ i, y }) =>
    `<line x1="${xAt(i).toFixed(1)}" x2="${xAt(i).toFixed(1)}" y1="${padT}" y2="${padT + plotH}"`
    + ` stroke="${GRID}"/>`
    + (xLabels
       ? `<text x="${xAt(i).toFixed(1)}" y="${h - 6}" fill="${INK}" font-size="11"`
         + ` text-anchor="middle">${y}</text>`
       : "")).join("");

  const zero = zeroLine
    ? `<line x1="${padL}" x2="${padL + plotW}" y1="${yAt(0).toFixed(1)}" y2="${yAt(0).toFixed(1)}"`
      + ` stroke="${AXIS}" stroke-width="1"/>` : "";

  // 2px lines; the benchmark dashed so it reads as a reference rather than a
  // competitor, and drawn FIRST so live strategies sit above it.
  const ordered = [...series].sort((a, b) => (a.key === "buyhold" ? -1 : b.key === "buyhold" ? 1 : 0));
  const paths = ordered.map((s) => {
    let d = "", pen = false;
    s.values.forEach((v, i) => {
      if (v == null || !isFinite(v)) { pen = false; return; }
      d += `${pen ? "L" : "M"}${xAt(i).toFixed(1)} ${yAt(v).toFixed(1)}`;
      pen = true;
    });
    const bench = s.key === "buyhold";
    return `<path d="${d}" fill="none" stroke="${colourFor(s.key)}" stroke-width="2"`
      + ` stroke-linejoin="round" stroke-linecap="round"`
      + `${bench ? ' stroke-dasharray="6 4"' : ""} opacity="${bench ? 0.85 : 1}"/>`;
  }).join("");

  // Direct labels at the right end -- identity without relying on colour.
  // Nudged apart so two series that finish close together stay readable.
  const ends = ordered.map((s) => {
    for (let i = s.values.length - 1; i >= 0; i--) {
      if (s.values[i] != null && isFinite(s.values[i])) {
        // `short` on the plot, `label` in the legend and the table. A direct
        // label has to fit in the right margin; the legend has a whole row.
        return { key: s.key, label: s.short ?? s.label, y: yAt(s.values[i]) };
      }
    }
    return null;
  }).filter(Boolean).sort((a, b) => a.y - b.y);
  for (let i = 1; i < ends.length; i++) {
    if (ends[i].y - ends[i - 1].y < 12) ends[i].y = ends[i - 1].y + 12;
  }
  const labels = ends.map((e) =>
    `<text x="${padL + plotW + 6}" y="${Math.min(e.y, h - padB).toFixed(1)}"`
    + ` fill="${colourFor(e.key)}" font-size="11" font-weight="600"`
    + ` dominant-baseline="middle">${esc(e.label)}</text>`).join("");

  const hover = `<g class="crosshair" style="display:none">`
    + `<line y1="${padT}" y2="${padT + plotH}" stroke="${AXIS}" stroke-width="1"/>`
    + ordered.map((s) => `<circle r="4" fill="${colourFor(s.key)}" stroke="#15120d"`
      + ` stroke-width="2" data-key="${esc(s.key)}"/>`).join("")
    + `</g>`;

  return `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img"`
    + ` data-padl="${padL}" data-padr="${padR}" data-plotw="${plotW}">`
    + grid + xAxis + zero + paths + labels + hover
    + `<rect class="hit" x="${padL}" y="${padT}" width="${plotW}" height="${plotH}"`
    + ` fill="transparent"/></svg>`;
}

/* ------------------------------------------------------- public renderer */

/**
 * Draws the equity + drawdown pair into `root` and wires the shared crosshair.
 *
 * The two panels are stacked and share one x-axis on purpose. They answer the
 * two halves of the same question -- "what did it earn" and "what did it cost
 * you to sit through" -- and this project's own finding is that the second is
 * where the measurable difference is. Side by side, a reader compares them;
 * stacked and aligned, they read as one statement about the same weeks.
 */
function renderBacktestCharts(root, { dates, series, readout }) {
  const width = Math.max(280, root.clientWidth || 640);
  const tall = width > 620;

  const equity = series.map((s) => ({ ...s, values: s.equity }));
  const drawdown = series.map((s) => ({ ...s, values: s.drawdown }));

  root.innerHTML =
    `<div class="chart-panel" data-panel="equity">`
    + `<div class="chart-label">Sermaye &mdash; $1.000 başlangıç, logaritmik eksen</div>`
    + timeSeriesPanel({ series: equity, dates, width, height: tall ? 250 : 200, xLabels: false,
                        yType: "log", yFormat: (v) => "$" + v.toLocaleString("tr-TR") })
    + `</div>`
    + `<div class="chart-panel" data-panel="drawdown">`
    + `<div class="chart-label">Düşüş &mdash; zirveden ne kadar aşağıda</div>`
    + timeSeriesPanel({ series: drawdown, dates, width, height: tall ? 190 : 150,
                        yType: "linear", zeroLine: true,
                        yFormat: (v) => (v < 0 ? "−%" : "%") + Math.abs(Math.round(v)) })
    + `</div>`;

  wireCrosshair(root, dates, series, readout);
}

/* The hover layer. An HTML chart IS interactive; a 19.5-year curve with no
   way to ask "what was it in March 2020" is a picture of data rather than a
   view of it. Pointer events rather than mouse events so the same code path
   serves touch. */
function wireCrosshair(root, dates, series, readout) {
  const svgs = [...root.querySelectorAll("svg")];
  if (!svgs.length) return;

  const show = (index) => {
    svgs.forEach((svg) => {
      const g = svg.querySelector(".crosshair");
      const padL = +svg.dataset.padl, plotW = +svg.dataset.plotw;
      const x = padL + (dates.length < 2 ? plotW / 2 : (index / (dates.length - 1)) * plotW);
      g.style.display = "";
      g.querySelector("line").setAttribute("x1", x);
      g.querySelector("line").setAttribute("x2", x);
      const isEquity = svg.closest(".chart-panel").dataset.panel === "equity";
      g.querySelectorAll("circle").forEach((dot) => {
        const s = series.find((one) => one.key === dot.dataset.key);
        const v = s && (isEquity ? s.equity : s.drawdown)[index];
        if (v == null || !isFinite(v)) { dot.style.display = "none"; return; }
        dot.style.display = "";
        dot.setAttribute("cx", x);
        // The path geometry is already on screen; rather than recompute the
        // scale here, read the y straight off the rendered path so the dot
        // can never sit somewhere the line does not.
        dot.setAttribute("cy", yOnPath(svg, s.key, x));
      });
    });
    readout(index);
  };

  const hide = () => {
    svgs.forEach((svg) => { svg.querySelector(".crosshair").style.display = "none"; });
    readout(null);
  };

  svgs.forEach((svg) => {
    const hit = svg.querySelector(".hit");
    const toIndex = (event) => {
      const box = svg.getBoundingClientRect();
      const padL = +svg.dataset.padl, plotW = +svg.dataset.plotw;
      const scale = box.width / svg.viewBox.baseVal.width;
      const t = (event.clientX - box.left - padL * scale) / (plotW * scale);
      return Math.max(0, Math.min(dates.length - 1, Math.round(t * (dates.length - 1))));
    };
    hit.addEventListener("pointermove", (e) => show(toIndex(e)));
    hit.addEventListener("pointerdown", (e) => show(toIndex(e)));
    hit.addEventListener("pointerleave", hide);
  });
}

// Nearest point on a rendered <path> at a given x. Uses the browser's own
// geometry (getPointAtLength) rather than a second copy of the scale maths --
// two implementations of one mapping is how a dot ends up half a pixel, or
// half a decade, off the line it belongs to.
function yOnPath(svg, key, x) {
  const paths = [...svg.querySelectorAll("path")];
  const order = [...svg.querySelectorAll("circle")].map((c) => c.dataset.key);
  const path = paths[order.indexOf(key)];
  if (!path) return 0;
  const total = path.getTotalLength();
  let lo = 0, hi = total;
  for (let i = 0; i < 18; i++) {
    const mid = (lo + hi) / 2;
    if (path.getPointAtLength(mid).x < x) lo = mid; else hi = mid;
  }
  return path.getPointAtLength((lo + hi) / 2).y;
}

// Peak-to-trough decline at every point, as a negative percentage. Computed
// in the browser rather than shipped in backtest.json: it is a pure function
// of the equity curve already in the payload, so storing it would double the
// file for a number that can never disagree with its own source.
function drawdownOf(equity) {
  let peak = -Infinity;
  return equity.map((v) => {
    peak = Math.max(peak, v);
    return peak > 0 ? -100 * (1 - v / peak) : 0;
  });
}

return { renderBacktestCharts, drawdownOf, colourFor };
})();
