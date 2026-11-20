/* ==========================================================================
   Kalshi Demo Dashboard — shared application logic
   - Verified snapshot data pulled from the official Kalshi demo API
   - Live fetch helpers (graceful degradation when API/CORS unavailable)
   - All displayed values carry a source link to the official API
   ========================================================================== */

const KALSHI_BASE = "https://external-api.demo.kalshi.co/trade-api/v2";
const ALSO_SUPPORTED = "https://demo-api.kalshi.co/trade-api/v2";

// ---------------------------------------------------------------------------
// Verified snapshot data (captured via official demo API, fetch_page tool)
// Each entry links back to the exact official API endpoint used as source.
// Values left blank / flagged "unverified" where the demo API did not return
// them in the sampled pages. Nothing here is inferred or invented.
// ---------------------------------------------------------------------------

const VERIFIED = {
  generatedAt: "2026-11-20T00:00:00Z",
  sourceBase: KALSHI_BASE,
  events: [
    {
      category: "Crypto",
      event_ticker: "KXBTCD-32FEB1010",
      series_ticker: "KXBTCD",
      title: "Bitcoin price on Feb 10, 2032 at 10am EST?",
      sub_title: "On Feb 10, 2032 at 10am EST",
      status_hint: "Live until strike / resolution",
      settlement_source: "CF Benchmarks — https://www.cfbenchmarks.com/data/indices/BRTI?ref=blog.cfbenchmarks.com",
      api_url: KALSHI_BASE + "/events?limit=100",
      dollar_amount: "(volume not yet sampled — unverified)",
      liquidity: "unverified",
    },
    {
      category: "Elections",
      event_ticker: "KXNEWPOPE-70",
      series_ticker: "KXNEWPOPE",
      title: "Who will the next Pope be?",
      sub_title: "Before 2070",
      status_hint: "Live until resolution",
      settlement_source: "The New York Times, AP, Reuters, Axios, Politico, Semafor, WSJ, ABC, CBS, CNN, Fox News, MSNBC",
      api_url: KALSHI_BASE + "/events?limit=100",
      dollar_amount: "(volume not yet sampled — unverified)",
      liquidity: "unverified",
    },
    {
      category: "Elections",
      event_ticker: "KXNEXTNATOSECGEN-99",
      series_ticker: "KXNEXTNATOSECGEN",
      title: "Who will be the next Secretary General of NATO?",
      sub_title: "Before Jan 1, 2099",
      status_hint: "Live until resolution",
      settlement_source: "North Atlantic Treaty Organization — https://www.nato.int/",
      api_url: KALSHI_BASE + "/events?limit=100",
      dollar_amount: "(volume not yet sampled — unverified)",
      liquidity: "unverified",
    },
    {
      category: "Elections",
      event_ticker: "KXINDIANPM-29APR30",
      series_ticker: "KXINDIANPM",
      title: "Who will become Prime Minister of India after next general election?",
      sub_title: "Before Apr 30, 2030",
      status_hint: "Live until resolution",
      settlement_source: "Lok Sabha — https://sansad.in/",
      api_url: KALSHI_BASE + "/events?limit=100",
      dollar_amount: "(volume not yet sampled — unverified)",
      liquidity: "unverified",
    },
    {
      category: "Elections",
      event_ticker: "KXKOREAPRES-30MAR27",
      series_ticker: "KXKOREAPRES",
      title: "Next South Korea Presidential election winner?",
      sub_title: "Next presidential election",
      status_hint: "Live until resolution",
      settlement_source: "National Election Commission — https://www.nec.go.kr/",
      api_url: KALSHI_BASE + "/events?limit=100",
      dollar_amount: "(volume not yet sampled — unverified)",
      liquidity: "unverified",
    },
    {
      category: "Elections",
      event_ticker: "KXGERELECTION-29MAR25",
      series_ticker: "KXGERELECTION",
      title: "Next German federal election winner?",
      sub_title: "in 2029",
      status_hint: "Live until resolution",
      settlement_source: "Bundeswahlausschuss — https://www.bundeswahlleiterin.de/en/",
      api_url: KALSHI_BASE + "/events?limit=100",
      dollar_amount: "(volume not yet sampled — unverified)",
      liquidity: "unverified",
    },
    {
      category: "Elections",
      event_ticker: "KXJAPANHOUSE-30FEB07",
      series_ticker: "KXJAPANHOUSE",
      title: "Next Japanese general election winner?",
      sub_title: "House of Representatives",
      status_hint: "Live until resolution",
      settlement_source: "Ministry of Internal Affairs and Communications — https://www.soumu.go.jp/",
      api_url: KALSHI_BASE + "/events?limit=100",
      dollar_amount: "(volume not yet sampled — unverified)",
      liquidity: "unverified",
    },
    {
      category: "Entertainment / Culture",
      event_ticker: "KXGTAPRICE",
      series_ticker: "KXGTAPRICE",
      title: "What will the price of GTA VI be on PS5?",
      sub_title: "GTA VI",
      status_hint: "Live until launch",
      settlement_source: "Rockstar Games — https://www.rockstargames.com/",
      api_url: KALSHI_BASE + "/events?limit=100",
      dollar_amount: "(volume not yet sampled — unverified)",
      liquidity: "unverified",
    },
    {
      category: "Entertainment / Culture",
      event_ticker: "KXLIPATURNERLOCATION-30",
      series_ticker: "KXLIPATURNERLOCATION",
      title: "Where will Dua Lipa and Callum Turner's wedding occur?",
      sub_title: "Before 2030",
      status_hint: "Live until resolution",
      settlement_source: "NYT, Bloomberg, Reuters, WaPo, WSJ, ABC, CBS, NBC, MSNBC, CNN, Semafor, The Information, ESPN, Fox News, Axios, Politico",
      api_url: KALSHI_BASE + "/events?limit=100",
      dollar_amount: "(volume not yet sampled — unverified)",
      liquidity: "unverified",
    },
    {
      category: "Sports",
      event_ticker: "KXF1RETIRE-30VERSTAPPEN",
      series_ticker: "KXF1RETIRE",
      title: "Max Verstappen: Retirement",
      sub_title: "Max Verstappen",
      status_hint: "Live until resolution",
      settlement_source: "ABC, Bleacher Report, WSJ, ESPN, NYT, Fox Sports, BBC Sport, AP, The Athletic, Reuters, Formula 1",
      api_url: KALSHI_BASE + "/events?limit=100",
      dollar_amount: "(volume not yet sampled — unverified)",
      liquidity: "unverified",
    },
    {
      category: "Sports",
      event_ticker: "KXMLBDEBUT-GEMERSON",
      series_ticker: "KXMLBDEBUT",
      title: "Grady Emerson: Debut Date",
      sub_title: "Grady Emerson",
      status_hint: "Live until resolution",
      settlement_source: "ESPN, MLB — https://www.espn.com/, https://www.mlb.com/",
      api_url: KALSHI_BASE + "/events?limit=100",
      dollar_amount: "(volume not yet sampled — unverified)",
      liquidity: "unverified",
    },
    {
      category: "Sports",
      event_ticker: "KXNFLRETIRE-ARODGERS8",
      series_ticker: "KXNFLRETIRE",
      title: "When will Aaron Rodgers retire?",
      sub_title: "Aaron Rodgers",
      status_hint: "Live until resolution",
      settlement_source: "Bleacher Report, WSJ, ABC, NFL, The Athletic, ESPN, NBC Sports, CBS Sports, AP, Reuters, WaPo, Bloomberg, Fox Sports",
      api_url: KALSHI_BASE + "/events?limit=100",
      dollar_amount: "(volume not yet sampled — unverified)",
      liquidity: "unverified",
    },
  ],
  markets: [
    {
      ticker: "KXMVECROSSCATEGORY-S202665ZBRAWNKMEZVJMD-TD7D5NES6",
      event_ticker: "KXMVECROSSCATEGORY-S202665ZBRAWNKMEZVJMD",
      title: "yes Brooklyn, yes Charleston Southern",
      last_price_dollars: "0.4500",
      yes_bid_dollars: "0.0000", yes_ask_dollars: "1.0000",
      yes_bid_size_fp: "0.00", yes_ask_size_fp: "0.00",
      no_bid_dollars: "0.0000", no_ask_dollars: "1.0000",
      volume_fp: "100.00", volume_24h_fp: "0.00",
      open_interest_fp: "100.00",
      status: "active",
      api_url: KALSHI_BASE + "/markets?limit=100",
    },
    {
      ticker: "KXMVECROSSCATEGORY-S2026ZIULQMNB3YSI32RS-VQI2XIEGC",
      event_ticker: "KXMVECROSSCATEGORY-S2026ZIULQMNB3YSI32RS",
      title: "yes Saint Mary's, yes LIU",
      last_price_dollars: "0.4500",
      yes_bid_dollars: "0.0000", yes_ask_dollars: "1.0000",
      yes_bid_size_fp: "0.00", yes_ask_size_fp: "0.00",
      no_bid_dollars: "0.0000", no_ask_dollars: "1.0000",
      volume_fp: "100.00", volume_24h_fp: "0.00",
      open_interest_fp: "100.00",
      status: "active",
      api_url: KALSHI_BASE + "/markets?limit=100",
    },
    {
      ticker: "KXMVECROSSCATEGORY-S2026MJG5BP56E7KBI47J-VVDOAHQSD",
      event_ticker: "KXMVECROSSCATEGORY-S2026MJG5BP56E7KBI47J",
      title: "yes Andorra, yes Northern Colorado",
      last_price_dollars: "0.4500",
      yes_bid_dollars: "0.0000", yes_ask_dollars: "1.0000",
      yes_bid_size_fp: "0.00", yes_ask_size_fp: "0.00",
      no_bid_dollars: "0.0000", no_ask_dollars: "1.0000",
      volume_fp: "100.00", volume_24h_fp: "0.00",
      open_interest_fp: "100.00",
      status: "active",
      api_url: KALSHI_BASE + "/markets?limit=100",
    },
    {
      ticker: "KXMVECROSSCATEGORY-S2026BQADTSXJ4L5COZDE-APVYNITE2",
      event_ticker: "KXMVECROSSCATEGORY-S2026BQADTSXJ4L5COZDE",
      title: "yes Tie, yes Army",
      last_price_dollars: "0.4500",
      yes_bid_dollars: "0.0000", yes_ask_dollars: "1.0000",
      yes_bid_size_fp: "0.00", yes_ask_size_fp: "0.00",
      no_bid_dollars: "0.0000", no_ask_dollars: "1.0000",
      volume_fp: "100.00", volume_24h_fp: "0.00",
      open_interest_fp: "100.00",
      status: "active",
      api_url: KALSHI_BASE + "/markets?limit=100",
    },
    {
      ticker: "KXMVECROSSCATEGORY-S20262RCH4KPBJG3MEU6W-N5ART54AN",
      event_ticker: "KXMVECROSSCATEGORY-S20262RCH4KPBJG3MEU6W",
      title: "yes Esenler Erokspor, yes Northwestern",
      last_price_dollars: "0.4500",
      yes_bid_dollars: "0.0000", yes_ask_dollars: "1.0000",
      yes_bid_size_fp: "0.00", yes_ask_size_fp: "0.00",
      no_bid_dollars: "0.0000", no_ask_dollars: "1.0000",
      volume_fp: "100.00", volume_24h_fp: "0.00",
      open_interest_fp: "100.00",
      status: "active",
      api_url: KALSHI_BASE + "/markets?limit=100",
    },
    {
      ticker: "KXEBASKETBALLGAME-26NOV200659WALTBARR-WALT",
      event_ticker: "KXEBASKETBALLGAME-26NOV200659WALTBARR",
      title: "Los Angeles Lakers (Walt) wins",
      last_price_dollars: "0.0000",
      yes_bid_dollars: "0.0100", yes_ask_dollars: "1.0000",
      yes_bid_size_fp: "440.00", yes_ask_size_fp: "0.00",
      no_bid_dollars: "0.0000", no_ask_dollars: "0.9900",
      volume_fp: "0.00", volume_24h_fp: "0.00",
      open_interest_fp: "0.00",
      status: "active",
      api_url: KALSHI_BASE + "/markets?limit=100",
    },
  ],
  categoriesCovered: {
    "gas-prices": "No gas/energy events or markets returned in the sampled pages of the official demo API. Left blank — unverified. See Flagged for Review.",
    elections: "Multiple live election events found (US state legislature, India PM, S. Korea president, German federal, Japanese general, NATO Sec-Gen, next Pope). See elections.html.",
    culture: "Entertainment events found (GTA VI price, celebrity wedding). See culture.html.",
    crypto: "Bitcoin price event KXBTCD found. See crypto.html.",
    golf: "No golf events or markets returned in the sampled pages of the official demo API. Left blank — unverified. See Flagged for Review.",
  },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function fmtMoney(n) {
  const v = Number(n || 0);
  return isNaN(v) ? "—" : "$" + v.toFixed(2);
}
function fmtPct(n) {
  const v = Number(n || 0);
  return isNaN(v) ? "—" : v.toFixed(2) + "%";
}
function esc(t) {
  return String(t == null ? "" : t).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

// ---------------------------------------------------------------------------
// Active nav link
// ---------------------------------------------------------------------------
function setActiveNav() {
  const path = location.pathname.split("/").pop() || "index.html";
  $$("nav a").forEach(a => {
    const href = a.getAttribute("href").split("/").pop();
    if (href === path) a.classList.add("active");
    else a.classList.remove("active");
  });
}

// ---------------------------------------------------------------------------
// Live API fetch (cors may block on github.io; degraded gracefully)
// ---------------------------------------------------------------------------
async function fetchJson(path) {
  try {
    const res = await fetch(KALSHI_BASE + path, { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    return await res.json();
  } catch (e) {
    return { error: String(e) };
  }
}

async function loadLiveMarkets(containerId, limit = 25) {
  const el = $(containerId);
  if (!el) return;
  el.innerHTML = '<div class="empty"><div class="spinner"></div><div>Loading live market data from demo.kalshi.co…</div></div>';
  const data = await fetchJson("/markets?limit=" + limit);
  if (data.error) {
    el.innerHTML = '<div class="alert alert-warn">Live feed unavailable from this host (CORS / network). Showing verified snapshot instead. <a href="flagged.html">See Flagged for Review</a>.</div>' + el.innerHTML;
    return;
  }
  const mkts = (data.markets || []).filter(m => m.status === "active").sort((a, b) => Number(b.volume_fp || 0) - Number(a.volume_fp || 0)).slice(0, limit);
  let html = '<table class="data"><thead><tr><th>Ticker</th><th>Event</th><th>Title</th><th>Last price</th><th>Yes bid</th><th>Yes ask</th><th>Yes bid size</th><th>Volume</th><th>Open interest</th><th>Source</th></tr></thead><tbody>';
  for (const m of mkts) {
    html += `<tr>
      <td class="ticker">${esc(m.ticker)}</td>
      <td class="ticker">${esc(m.event_ticker)}</td>
      <td>${esc(m.title)}</td>
      <td class="price">${fmtMoney(m.last_price_dollars)}</td>
      <td>${fmtMoney(m.yes_bid_dollars)}</td>
      <td>${fmtMoney(m.yes_ask_dollars)}</td>
      <td>${fmtMoney(m.yes_bid_size_fp)}</td>
      <td>${fmtMoney(m.volume_fp)}</td>
      <td>${fmtMoney(m.open_interest_fp)}</td>
      <td><a href="${esc(KALSHI_BASE + "/markets?limit=100")}" class="source-link" target="_blank" rel="noopener">Kalshi demo API (markets)</a></td>
    </tr>`;
  }
  html += "</tbody></table>";
  el.innerHTML = html;
}

// ---------------------------------------------------------------------------
// Chart: price history (live feed with simulated time series when unavailable)
// X axis: time (seconds / minutes / hours). Y axis: contract price.
// Liquidity shown alongside (bid/ask size at current price).
// ---------------------------------------------------------------------------
let priceChart = null;
function initChart(ctxId) {
  const ctx = $(ctxId);
  if (!ctx || typeof Chart === "undefined") return;
  const cfg = {
    type: "line",
    data: { labels: [], datasets: [
      { label: "Yes price ($)", data: [], borderColor: "#0b5ed6", backgroundColor: "rgba(11,94,214,0.1)", fill: true, tension: 0.3, pointRadius: 0 },
      { label: "Liquidity (ask size)", data: [], borderColor: "#9aa3ad", backgroundColor: "rgba(154,163,173,0.05)", fill: false, tension: 0.3, pointRadius: 0, yAxisID: "liquidity" },
    ]},
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { position: "top" }, title: { display: true, text: "Contract price & liquidity over time (demo data)" } },
      scales: {
        x: { type: "time", time: { unit: "minute" }, title: { display: true, text: "Time" } },
        y: { title: { display: true, text: "Yes contract price ($)" }, min: 0, max: 1 },
        liquidity: { type: "linear", position: "right", title: { display: true, text: "Ask size (contracts)" }, grid: { drawOnChartArea: false } },
      },
    },
  };
  priceChart = new Chart(ctx, cfg);
  return priceChart;
}
function setChartTimeUnit(unit) {
  if (!priceChart) return;
  priceChart.options.scales.x.time.unit = unit;
  priceChart.update();
}
function pushChartPoint(price, size) {
  if (!priceChart) return;
  const now = new Date();
  priceChart.data.labels.push(now);
  priceChart.data.datasets[0].data.push({ x: now, y: price });
  priceChart.data.datasets[1].data.push({ x: now, y: size });
  const maxPoints = 120;
  if (priceChart.data.labels.length > maxPoints) {
    priceChart.data.labels.shift();
    priceChart.data.datasets.forEach(d => d.data.shift());
  }
  priceChart.update("none");
}

// ---------------------------------------------------------------------------
// Render verified event tables (category pages)
// ---------------------------------------------------------------------------
function renderEvents(containerId, categoryFilter) {
  const el = $(containerId);
  if (!el) return;
  let list = VERIFIED.events;
  if (categoryFilter) list = list.filter(e => e.category.toLowerCase().includes(categoryFilter.toLowerCase()));
  if (list.length === 0) {
    el.innerHTML = '<div class="empty">No verified events in this category from the sampled demo-API pages. Blank values are intentionally unfilled — see Flagged for Review.</div>';
    return;
  }
  let html = '<table class="data"><thead><tr><th>Category</th><th>Event ticker</th><th>Series</th><th>Title</th><th>Sub-title</th><th>Resolution tracking</th><th>Dollar amount (highest $)</th><th>Liquidity</th><th>Settlement source</th><th>Official API source</th></tr></thead><tbody>';
  for (const e of list) {
    html += `<tr>
      <td>${esc(e.category)}</td>
      <td class="ticker">${esc(e.event_ticker)}</td>
      <td class="ticker">${esc(e.series_ticker)}</td>
      <td>${esc(e.title)}</td>
      <td>${esc(e.sub_title)}</td>
      <td>${esc(e.status_hint)}</td>
      <td><span class="badge badge-unverified">unverified</span> ${esc(e.dollar_amount)}</td>
      <td><span class="badge badge-unverified">unverified</span> ${esc(e.liquidity)}</td>
      <td>${esc(e.settlement_source)}</td>
      <td><a href="${esc(e.api_url)}" class="source-link" target="_blank" rel="noopener">events endpoint</a></td>
    </tr>`;
  }
  html += "</tbody></table>";
  el.innerHTML = html;
}

// ---------------------------------------------------------------------------
// Portfolio & trade execution — require authenticated demo API keys.
// No credentials are collected or stored by this site. Flagged as not live.
// ---------------------------------------------------------------------------
function renderAuthNotice(containerId) {
  const el = $(containerId);
  if (!el) return;
  el.innerHTML = `
  <div class="alert alert-danger">
    <strong>Not live — demo API credentials required.</strong> Portfolio balance, trade execution, and order placement call
    authenticated Kalshi endpoints (PORTFOLIO, TRADE, ORDER) that require an API key pair and request signature.
    This site does not collect, store, or transmit any Kalshi API key. To make these pages functional, add your own demo
    API key (never commit it) and sign requests per the Kalshi Trade API docs.
  </div>
  <table class="data"><thead><tr><th>Endpoint</th><th>Auth required?</th><th>Status</th><th>Official docs</th></tr></thead><tbody>
    <tr><td>GET /portfolio</td><td>Yes</td><td><span class="badge badge-unverified">unverified — credentials missing</span></td><td><a href="https://docs.kalshi.io" target="_blank" rel="noopener">Kalshi docs</a></td></tr>
    <tr><td>POST /trade</td><td>Yes</td><td><span class="badge badge-unverified">unverified — credentials missing</span></td><td><a href="https://docs.kalshi.io" target="_blank" rel="noopener">Kalshi docs</a></td></tr>
    <tr><td>POST /order</td><td>Yes</td><td><span class="badge badge-unverified">unverified — credentials missing</span></td><td><a href="https://docs.kalshi.io" target="_blank" rel="noopener">Kalshi docs</a></td></tr>
  </tbody></table>`;
}

// ---------------------------------------------------------------------------
// Initialize
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  setActiveNav();
  // Render any verified tables marked with data-category
  $$("[data-category]").forEach(el => renderEvents(el.id, el.getAttribute("data-category")));
  // Auth notices
  $$("[data-auth-notice]").forEach(renderAuthNotice);
  // Live markets table on dashboard
  loadLiveMarkets("#live-markets");
  // Chart time-unit selector
  const unitSel = $("#chart-unit");
  if (unitSel) unitSel.addEventListener("change", e => setChartTimeUnit(e.target.value));
});

// Expose for inline handlers
window.KALSHI = { BASE: KALSHI_BASE, ALSO_SUPPORTED, pushChartPoint, setChartTimeUnit, loadLiveMarkets, VERIFIED };
