import { TOPICS } from "./content.js";
import {
  fetchEventsByStatus,
  fetchEvent,
  fetchMarket,
  fetchMarketCandlesticks,
  fetchOrderbook,
} from "./api.js";
import { renderPriceChart, localPriceSamples, mergePriceSeries, recordPriceSample } from "./chart.js";
import { activeMarketsForEvent, aggregateEvent, isInResolutionQueue, resolutionDetails } from "./metrics.js";
import { matchingTopics, topicDefinition } from "./topics.js";
import {
  renderEventTable,
  renderFlags,
  renderMarketPicker,
  renderOrderbook,
  renderQuestions,
  renderResolutionTable,
  renderSelectedMarket,
  renderSettlementSources,
  renderSources,
  renderStrategyFields,
  renderSuggestions,
  setSuggestionDecision,
} from "./renderers.js";
import { mountShell, setFeedStatus } from "./shell.js";
import { escapeHTML, finiteNumber, formatNumber, formatTimestamp } from "./utils.js";

const POLL_INTERVAL_MS = 15_000;
const EVENT_REFRESH_INTERVAL_MS = 60_000;
const EVENT_PAGE_LIMIT = 50;
const page = document.body.dataset.page ?? "home";

const state = {
  events: [],
  eventPages: 0,
  eventsComplete: false,
  eventsLastUpdated: null,
  eventsLastAttempt: 0,
  selectedEvent: null,
  selectedMarket: null,
  marketSnapshot: null,
  orderbook: null,
  candles: [],
  candlePeriod: null,
  candleInterval: null,
  candleRequestPeriod: null,
  candlesLastUpdated: 0,
  candleError: "",
  candleNote: "",
  selectedError: "",
  selectionVersion: 0,
  selectedLoadingVersion: 0,
  eventRequestVersion: 0,
  resolutionEvents: [],
  resolutionLastUpdated: 0,
  resolutionLastAttempt: 0,
  resolutionLoading: false,
  resolutionPages: { closed: 0, settled: 0 },
  resolutionComplete: { closed: false, settled: false },
  loading: false,
  selectedLoading: false,
  forceCandlesPending: false,
  refreshTimer: null,
  lastChartRender: 0,
};

function byId(id) {
  return document.getElementById(id);
}

function setText(id, text) {
  const element = byId(id);
  if (element) element.textContent = text;
}

function setError(container, title, message, sourceURL = "") {
  if (!container) return;
  const source = sourceURL
    ? `<a class="source-link" href="${escapeHTML(sourceURL)}" target="_blank" rel="noopener noreferrer">Official endpoint ↗</a>`
    : "";
  container.innerHTML = `
    <div class="empty-state error-state" role="alert">
      <span class="error-mark" aria-hidden="true">!</span>
      <strong>${escapeHTML(title)}</strong>
      <span>${escapeHTML(message)}</span>
      ${source}
    </div>
  `;
}

function setMetric(id, value) {
  const element = byId(id);
  if (element) element.textContent = value;
}

function currentSearch() {
  return byId("event-search")?.value ?? "";
}

function currentSort() {
  return byId("event-sort")?.value ?? "volume";
}

function currentTopicId() {
  return TOPICS[page] ? page : null;
}

function activeEventRows(events = state.events) {
  return (events ?? []).map((event) => aggregateEvent(event));
}

function topicAggregate(events, topicId) {
  return activeEventRows(events).filter(({ event }) => matchingTopics(event).includes(topicId));
}

function renderOpenEventTable() {
  const container = byId("market-table-container");
  if (!container) return;
  renderEventTable(container, state.events, {
    topicId: currentTopicId(),
    sortMode: currentSort(),
    search: currentSearch(),
    statusFilter: "active",
  });
}

function updateOpenCounts() {
  const openAggregates = activeEventRows(state.events);
  const activeMarkets = openAggregates.reduce((sum, row) => sum + row.marketCount, 0);
  setMetric("stat-events", formatNumber(openAggregates.length, 0));
  setMetric("stat-markets", formatNumber(activeMarkets, 0));

  for (const [topicId] of Object.entries(TOPICS)) {
    const matches = topicAggregate(state.events, topicId);
    const count = matches.length;
    const marketCount = matches.reduce((sum, row) => sum + row.marketCount, 0);
    const topicCount = byId(`topic-count-${topicId}`);
    if (topicCount) topicCount.textContent = `${formatNumber(count, 0)} events`;
    const topicMetric = byId("topic-event-count");
    if (topicMetric && currentTopicId() === topicId) topicMetric.textContent = formatNumber(count, 0);
    const topicMarkets = byId("topic-market-count");
    if (topicMarkets && currentTopicId() === topicId) topicMarkets.textContent = formatNumber(marketCount, 0);
  }
}

function updateOpenCoverage() {
  const status = byId("coverage-status");
  if (!status) return;
  const topicId = currentTopicId();
  const rows = topicId ? topicAggregate(state.events, topicId) : activeEventRows(state.events);
  const eventCount = rows.length;
  const marketCount = rows.reduce((sum, row) => sum + row.marketCount, 0);
  const base = `${formatNumber(eventCount, 0)} matching events · ${formatNumber(marketCount, 0)} active markets · ${formatNumber(state.eventPages, 0)} API page${state.eventPages === 1 ? "" : "s"}`;
  status.textContent = state.eventsComplete
    ? `${base} · all returned pages read`
    : `${base} · partial scan (page limit reached)`;
  status.dataset.state = state.eventsComplete ? "success" : "warning";
}

function renderLatestTimestamp() {
  setText("last-updated", state.eventsLastUpdated
    ? `Last data response ${formatTimestamp(state.eventsLastUpdated, { dateStyle: "medium", timeStyle: "short" })}`
    : "Waiting for first response");
}

function clearSelectedMarket() {
  state.selectionVersion += 1;
  state.selectedEvent = null;
  state.selectedMarket = null;
  state.marketSnapshot = null;
  state.orderbook = null;
  state.candles = [];
  state.candlePeriod = null;
  state.candleInterval = null;
  state.candleRequestPeriod = null;
  state.candlesLastUpdated = 0;
  state.candleError = "";
  state.candleNote = "";
  state.selectedError = "";
  state.selectedLoading = false;
  state.selectedLoadingVersion = state.selectionVersion;
  state.forceCandlesPending = false;
  renderMarketPicker(byId("event-market-picker"), null);
  renderSelectedMarket(byId("selected-market-summary"), null, null);
  renderOrderbook(byId("orderbook-container"), null, "");
  renderPriceChart(byId("chart-container"), [], currentChartWindow());
  setText("chart-source-note", "No chart data loaded.");
  renderSettlementSources(byId("settlement-source-container"), null);
}

function renderChartSourceNote(points) {
  const parts = [];
  if (state.candles.length && state.candlePeriod) {
    parts.push(`Official ${state.candlePeriod} candles (${formatNumber(state.candles.length, 0)} returned)`);
  } else if (state.candleInterval) {
    parts.push(`No official ${state.candleInterval === 1 ? "1-minute" : "1-hour"} candle rows returned`);
  }
  const localCount = points.filter((point) => point.origin === "REST observation").length;
  if (localCount) parts.push(`${formatNumber(localCount, 0)} local REST observation${localCount === 1 ? "" : "s"}`);
  if (!parts.length) parts.push("No verified price history returned");
  let note = parts.join(" + ");
  if (state.candleError) note += ` · candle request failed: ${state.candleError}`;
  if (state.candleNote) note += ` · ${state.candleNote}`;
  if (!state.candlePeriod && localCount) note += " · browser-local samples, not official candles";
  setText("chart-source-note", note);
}

function currentChartWindow() {
  const value = finiteNumber(byId("chart-window")?.value);
  return value !== null && value > 0 ? value : 15 * 60_000;
}

function chartPeriodForWindow(windowMs) {
  if (windowMs < 60_000) return null;
  return windowMs > 6 * 60 * 60_000 ? 60 : 1;
}

function renderSelectedChart(now = Date.now()) {
  const windowMs = currentChartWindow();
  const ticker = state.selectedMarket?.ticker;
  if (!ticker) {
    renderPriceChart(byId("chart-container"), [], windowMs);
    setText("chart-source-note", "No chart data loaded.");
    return;
  }
  const samples = localPriceSamples(ticker, windowMs, now);
  const points = mergePriceSeries(state.candles, samples, windowMs, now);
  renderPriceChart(byId("chart-container"), points, windowMs, now);
  renderChartSourceNote(points);
  state.lastChartRender = now;
}

function mergeMarketDetails(listedMarket, detailedMarket) {
  if (!detailedMarket) return null;
  const snapshot = { ...(listedMarket ?? {}), ...detailedMarket };
  for (const field of ["title", "ticker", "status", "event_ticker", "series_ticker"]) {
    if (!snapshot[field] && listedMarket?.[field]) snapshot[field] = listedMarket[field];
  }
  return snapshot;
}

function selectedListedMarket() {
  const ticker = state.selectedMarket?.ticker;
  if (!ticker || !Array.isArray(state.selectedEvent?.markets)) return null;
  return state.selectedEvent.markets.find((market) => market?.ticker === ticker) ?? state.selectedMarket;
}

function setSelectedDataError(error, ticker) {
  const message = error?.message || "The official demo API request failed.";
  state.selectedError = message;
  state.marketSnapshot = null;
  state.candles = [];
  state.candlePeriod = null;
  state.candleInterval = null;
  state.candleRequestPeriod = null;
  state.candleError = "";
  state.candleNote = "";
  renderSelectedMarket(byId("selected-market-summary"), state.selectedEvent, null);
  setError(byId("selected-market-summary"), "Official market data unavailable", message,
    ticker ? `https://external-api.demo.kalshi.co/trade-api/v2/markets/${encodeURIComponent(ticker)}` : "");
  renderPriceChart(byId("chart-container"), [], currentChartWindow());
  setText("chart-source-note", "Market endpoint failed. No substitute quote or price history is shown.");
}

async function loadSelectedCandles(snapshot, version, force = false) {
  const windowMs = currentChartWindow();
  const period = chartPeriodForWindow(windowMs);
  const now = Date.now();
  if (!period) {
    state.candles = [];
    state.candlePeriod = null;
    state.candleInterval = null;
    state.candleRequestPeriod = null;
    state.candlesLastUpdated = now;
    state.candleError = "";
    state.candleNote = "Official candles start at 1 minute; this short window uses only browser-local REST observations.";
    renderSelectedChart(now);
    return;
  }

  const seriesTicker = snapshot.series_ticker || state.selectedEvent?.series_ticker;
  if (!seriesTicker) {
    state.candles = [];
    state.candlePeriod = null;
    state.candleInterval = null;
    state.candleRequestPeriod = period;
    state.candlesLastUpdated = now;
    state.candleError = "";
    state.candleNote = "Series ticker was not returned; no candle endpoint was queried.";
    renderSelectedChart(now);
    return;
  }
  if (!force && state.candleRequestPeriod === period && now - state.candlesLastUpdated < 60_000) return;

  state.candlesLastUpdated = now;
  state.candleRequestPeriod = period;
  state.candleInterval = period;
  state.candleError = "";
  state.candleNote = "";
  try {
    const candles = await fetchMarketCandlesticks(seriesTicker, snapshot.ticker, {
      startTs: Math.floor((now - windowMs) / 1000),
      endTs: Math.ceil(now / 1000),
      periodInterval: period,
    });
    if (version !== state.selectionVersion || snapshot.ticker !== state.selectedMarket?.ticker) return;
    state.candles = candles;
    state.candlePeriod = candles.length ? (period === 1 ? "1-minute" : "1-hour") : null;
    state.candlesLastUpdated = Date.now();
    state.candleError = "";
    state.candleNote = candles.length ? "" : "No official candles were returned for this market and window.";
  } catch (error) {
    if (version !== state.selectionVersion) return;
    state.candles = [];
    state.candlePeriod = null;
    state.candleError = error?.message || "Official candle data unavailable.";
    state.candleNote = "Only verified local REST observations, if any, remain visible.";
    state.candlesLastUpdated = Date.now();
  }
  renderSelectedChart();
}

async function refreshSelectedMarket({ forceCandles = false } = {}) {
  const ticker = state.selectedMarket?.ticker;
  if (!ticker) return;
  const version = state.selectionVersion;
  if (state.selectedLoading && state.selectedLoadingVersion === version) {
    if (forceCandles) state.forceCandlesPending = true;
    return;
  }
  const loadCandlesNow = forceCandles || state.forceCandlesPending;
  state.forceCandlesPending = false;
  state.selectedLoading = true;
  state.selectedLoadingVersion = version;
  state.selectedError = "";
  const listedMarket = selectedListedMarket();

  try {
    const [marketResult, orderbookResult] = await Promise.allSettled([
      fetchMarket(ticker),
      fetchOrderbook(ticker),
    ]);
    if (version !== state.selectionVersion || ticker !== state.selectedMarket?.ticker) return;

    if (marketResult.status === "rejected" || !marketResult.value) {
      setSelectedDataError(marketResult.status === "rejected" ? marketResult.reason : new Error("The official market endpoint returned no market record."), ticker);
    } else {
      state.marketSnapshot = mergeMarketDetails(listedMarket, marketResult.value);
      const price = finiteNumber(state.marketSnapshot?.last_price_dollars);
      if (price !== null) recordPriceSample(ticker, price, Date.now());
      renderSelectedMarket(byId("selected-market-summary"), state.selectedEvent, state.marketSnapshot);
    }

    if (orderbookResult.status === "fulfilled") {
      state.orderbook = orderbookResult.value;
      renderOrderbook(byId("orderbook-container"), state.orderbook, ticker);
    } else {
      state.orderbook = null;
      renderOrderbook(byId("orderbook-container"), null, ticker, orderbookResult.reason?.message || "Order-book request failed.");
    }

    if (state.marketSnapshot) {
      await loadSelectedCandles(state.marketSnapshot, version, loadCandlesNow);
      if (version === state.selectionVersion) {
        renderSelectedChart();
        if (state.marketSnapshot?.updated_time) {
          setText("market-observed-at", formatTimestamp(state.marketSnapshot.updated_time, { dateStyle: "medium", timeStyle: "short" }));
        }
      }
    }
  } finally {
    if (state.selectedLoadingVersion === version) {
      state.selectedLoading = false;
      if (state.forceCandlesPending && version === state.selectionVersion) {
        state.forceCandlesPending = false;
        queueMicrotask(() => refreshSelectedMarket({ forceCandles: true }));
      }
    }
  }
}

async function selectMarket(event, marketTicker, { forceCandles = true } = {}) {
  if (!event || !marketTicker) return;
  const market = (event.markets ?? []).find((item) => item?.ticker === marketTicker);
  if (!market) return;
  state.selectionVersion += 1;
  state.selectedEvent = event;
  state.selectedMarket = market;
  state.marketSnapshot = null;
  state.orderbook = null;
  state.candles = [];
  state.candlePeriod = null;
  state.candleInterval = null;
  state.candleRequestPeriod = null;
  state.candlesLastUpdated = 0;
  state.candleError = "";
  state.candleNote = "";
  state.selectedError = "";
  state.selectedLoading = false;
  state.selectedLoadingVersion = state.selectionVersion;
  state.forceCandlesPending = false;
  renderMarketPicker(byId("event-market-picker"), event, marketTicker);
  renderSelectedMarket(byId("selected-market-summary"), event, market);
  renderOrderbook(byId("orderbook-container"), null, marketTicker);
  renderPriceChart(byId("chart-container"), [], currentChartWindow());
  setText("chart-source-note", "Loading official market and chart data…");
  renderSettlementSources(byId("settlement-source-container"), event);
  await refreshSelectedMarket({ forceCandles });
}

async function selectEvent(event) {
  if (!event) return;
  const requestedSelection = ++state.selectionVersion;
  state.selectedEvent = event;
  state.selectedMarket = null;
  state.marketSnapshot = null;
  state.orderbook = null;
  state.candles = [];
  state.candlePeriod = null;
  state.candleInterval = null;
  state.candleRequestPeriod = null;
  state.candleError = "";
  state.candleNote = "";
  state.selectedLoading = false;
  state.forceCandlesPending = false;
  renderMarketPicker(byId("event-market-picker"), event);
  renderSelectedMarket(byId("selected-market-summary"), event, null);
  renderOrderbook(byId("orderbook-container"), null, "");
  renderPriceChart(byId("chart-container"), [], currentChartWindow());
  setText("chart-source-note", "Loading official event details…");
  renderSettlementSources(byId("settlement-source-container"), event);
  let resolvedEvent = event;
  if (event.event_ticker) {
    try {
      const detailed = await fetchEvent(event.event_ticker);
      if (requestedSelection !== state.selectionVersion) return;
      if (detailed) {
        resolvedEvent = {
          ...event,
          ...detailed,
          markets: Array.isArray(detailed.markets) && detailed.markets.length ? detailed.markets : event.markets,
        };
      }
    } catch {
      if (requestedSelection !== state.selectionVersion) return;
      // The listed event is already official API data; a failed detail request does not invent fields.
    }
  }
  if (requestedSelection !== state.selectionVersion) return;
  if (resolvedEvent.event_ticker) state.selectedEvent = resolvedEvent;
  const markets = activeMarketsForEvent(resolvedEvent);
  const market = [...markets].sort((a, b) => (finiteNumber(b?.volume_24h_fp) ?? -1) - (finiteNumber(a?.volume_24h_fp) ?? -1))[0];
  if (!market?.ticker) {
    state.selectedEvent = resolvedEvent;
    renderMarketPicker(byId("event-market-picker"), resolvedEvent);
    renderSelectedMarket(byId("selected-market-summary"), resolvedEvent, null);
    renderOrderbook(byId("orderbook-container"), null, "");
    renderPriceChart(byId("chart-container"), [], currentChartWindow());
    setText("chart-source-note", "The selected event has no active market in the returned API data.");
    renderSettlementSources(byId("settlement-source-container"), resolvedEvent);
    return;
  }
  await selectMarket(resolvedEvent, market.ticker);
}

function renderPageError(error, requestURL) {
  const container = byId("market-table-container");
  const message = error?.message || "The official demo API request failed.";
  setError(container, "Live market data unavailable", message, requestURL);
  state.events = [];
  state.eventPages = 0;
  state.eventsComplete = false;
  state.eventsLastUpdated = null;
  clearSelectedMarket();
  setMetric("stat-events", "—");
  setMetric("stat-markets", "—");
  setMetric("topic-event-count", "—");
  setMetric("topic-market-count", "—");
  for (const topicId of Object.keys(TOPICS)) setText(`topic-count-${topicId}`, "— events");
  setText("coverage-status", "API error · no values shown");
  setText("last-updated", "No successful API response");
  setFeedStatus("API request failed · no data shown", "error");
}

async function loadOpenEvents({ preserveSelection = false } = {}) {
  if (state.loading) return;
  const selectedEventTicker = preserveSelection ? state.selectedEvent?.event_ticker : null;
  const selectedMarketTicker = preserveSelection ? state.selectedMarket?.ticker : null;
  state.loading = true;
  state.eventsLastAttempt = Date.now();
  const requestVersion = ++state.eventRequestVersion;
  const container = byId("market-table-container");
  if (container) container.innerHTML = '<div class="loading-state"><span class="spinner" aria-hidden="true"></span>Connecting to the Kalshi demo API…</div>';
  setFeedStatus("Loading public demo events…", "loading");
  setText("coverage-status", "Reading event pages from the official demo API");
  if (!preserveSelection && state.events.length) clearSelectedMarket();
  state.events = [];
  state.eventPages = 0;
  state.eventsComplete = false;
  state.eventsLastUpdated = null;

  try {
    const result = await fetchEventsByStatus("open", { maxPages: EVENT_PAGE_LIMIT });
    if (requestVersion !== state.eventRequestVersion) return;
    state.events = result.events;
    state.eventPages = result.pages;
    state.eventsComplete = result.complete;
    state.eventsLastUpdated = Date.now();
    renderOpenEventTable();
    updateOpenCounts();
    updateOpenCoverage();
    renderLatestTimestamp();
    setFeedStatus(result.complete ? "Public demo data connected" : "Public demo data · partial scan", result.complete ? "success" : "warning");
    if (!result.complete) {
      setText("coverage-status", `${byId("coverage-status")?.textContent ?? ""} · stopped at the ${EVENT_PAGE_LIMIT}-page safety limit`);
    }
    if (selectedEventTicker && selectedMarketTicker) {
      const refreshedEvent = state.events.find((event) => event.event_ticker === selectedEventTicker);
      const refreshedMarket = refreshedEvent?.markets?.find((market) => market?.ticker === selectedMarketTicker && market?.status === "active");
      if (refreshedEvent && refreshedMarket) await selectMarket(refreshedEvent, selectedMarketTicker, { forceCandles: false });
      else clearSelectedMarket();
    }
  } catch (error) {
    if (requestVersion !== state.eventRequestVersion) return;
    renderPageError(error, "https://external-api.demo.kalshi.co/trade-api/v2/events?status=open&with_nested_markets=true");
  } finally {
    if (requestVersion === state.eventRequestVersion) state.loading = false;
  }
}

function mergeEventPages(results) {
  const eventMap = new Map();
  for (const result of results) {
    for (const event of result.events) {
      const key = event.event_ticker || `${event.series_ticker ?? ""}:${event.title ?? ""}`;
      const existing = eventMap.get(key);
      if (!existing) {
        eventMap.set(key, { ...event, markets: [...(event.markets ?? [])] });
        continue;
      }
      const marketMap = new Map((existing.markets ?? []).map((market) => [market.ticker, market]));
      for (const market of event.markets ?? []) {
        const previous = marketMap.get(market.ticker);
        if (!previous || (Date.parse(market.updated_time ?? "") || 0) >= (Date.parse(previous.updated_time ?? "") || 0)) {
          marketMap.set(market.ticker, market);
        }
      }
      existing.markets = [...marketMap.values()];
      Object.assign(existing, { ...event, markets: existing.markets });
    }
  }
  return [...eventMap.values()];
}

function renderResolutionStats(events) {
  const markets = [];
  const seen = new Set();
  for (const event of events) {
    for (const market of event.markets ?? []) {
      if (!isInResolutionQueue(market) || !market.ticker || seen.has(market.ticker)) continue;
      seen.add(market.ticker);
      markets.push(market);
    }
  }
  const finalized = markets.filter((market) => resolutionDetails(market).isYesNoResolved).length;
  const reviewCount = markets.filter((market) => ["disputed", "amended"].includes(market.status) || market.result === "scalar").length;
  setMetric("resolution-total", formatNumber(markets.length, 0));
  setMetric("resolution-finalized", formatNumber(finalized, 0));
  setMetric("resolution-review-count", formatNumber(reviewCount, 0));
}

function renderResolutionPage(topicId = null) {
  const results = renderResolutionTable(byId("resolution-table-container"), state.resolutionEvents, topicId);
  setText("resolution-table-count", `${formatNumber(results.rows, 0)} returned market rows`);
}

async function loadResolutionEvents() {
  if (state.resolutionLoading) return;
  state.resolutionLoading = true;
  state.resolutionLastAttempt = Date.now();
  setFeedStatus("Loading closed and settled event pages…", "loading");
  setText("resolution-coverage", "Reading official closed and settled event pages");
  const container = byId("resolution-table-container");
  if (container) container.innerHTML = '<div class="loading-state"><span class="spinner" aria-hidden="true"></span>Loading official lifecycle records…</div>';
  try {
    const closed = await fetchEventsByStatus("closed", { maxPages: EVENT_PAGE_LIMIT });
    const settled = await fetchEventsByStatus("settled", { maxPages: EVENT_PAGE_LIMIT });
    state.resolutionEvents = mergeEventPages([closed, settled]);
    state.resolutionPages = { closed: closed.pages, settled: settled.pages };
    state.resolutionComplete = { closed: closed.complete, settled: settled.complete };
    state.resolutionLastUpdated = Date.now();
    renderResolutionStats(state.resolutionEvents);
    renderResolutionPage(byId("resolution-topic-filter")?.value === "all" ? null : byId("resolution-topic-filter")?.value);
    const complete = closed.complete && settled.complete;
    setText("resolution-coverage", `${formatNumber(closed.pages, 0)} closed + ${formatNumber(settled.pages, 0)} settled API pages · ${complete ? "all returned pages read" : "partial scan at page limit"}`);
    setFeedStatus(complete ? "Resolution records loaded" : "Resolution records · partial scan", complete ? "success" : "warning");
    setText("last-updated", `Last data response ${formatTimestamp(state.resolutionLastUpdated, { dateStyle: "medium", timeStyle: "short" })}`);
  } catch (error) {
    state.resolutionEvents = [];
    state.resolutionLastUpdated = 0;
    setMetric("resolution-total", "—");
    setMetric("resolution-finalized", "—");
    setMetric("resolution-review-count", "—");
    const requestURL = "https://external-api.demo.kalshi.co/trade-api/v2/events?status=closed&with_nested_markets=true";
    setError(container, "Resolution data unavailable", error?.message || "The Kalshi demo API request failed.", requestURL);
    setText("resolution-coverage", "API error · no lifecycle values shown");
    setText("last-updated", "No successful API response");
    setFeedStatus("Resolution API request failed", "error");
  } finally {
    state.resolutionLoading = false;
  }
}

function bindOpenPageControls() {
  byId("event-search")?.addEventListener("input", renderOpenEventTable);
  byId("event-sort")?.addEventListener("change", renderOpenEventTable);
  byId("market-table-container")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-select-event]");
    if (!button) return;
    const ticker = button.dataset.selectEvent;
    const selected = state.events.find((item) => item.event_ticker === ticker);
    if (selected) {
      selectEvent(selected);
      byId("chart-heading")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });
  byId("event-market-picker")?.addEventListener("change", (event) => {
    const ticker = event.currentTarget.value;
    if (state.selectedEvent && ticker) selectMarket(state.selectedEvent, ticker);
  });
  byId("chart-window")?.addEventListener("change", () => {
    state.candlesLastUpdated = 0;
    if (state.marketSnapshot) refreshSelectedMarket({ forceCandles: true });
    else renderSelectedChart();
  });
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-review-decision][data-review-id]");
    if (!button) return;
    setSuggestionDecision(button.dataset.reviewId, button.dataset.reviewDecision);
    renderSuggestions(byId("suggestion-list"));
    const replacement = byId("suggestion-list")?.querySelector(`[data-review-id="${CSS.escape(button.dataset.reviewId)}"][data-review-decision="${button.dataset.reviewDecision}"]`);
    replacement?.focus();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && state.selectedMarket) refreshSelectedMarket();
  });
}

function bindResolutionControls() {
  byId("resolution-topic-filter")?.addEventListener("change", (event) => {
    renderResolutionPage(event.currentTarget.value === "all" ? null : event.currentTarget.value);
  });
}

function startPolling() {
  if (state.refreshTimer) clearInterval(state.refreshTimer);
  state.refreshTimer = setInterval(() => {
    if (document.visibilityState !== "visible") return;
    if (page === "resolution") {
      if (Date.now() - state.resolutionLastAttempt >= EVENT_REFRESH_INTERVAL_MS) loadResolutionEvents();
      return;
    }
    if (state.selectedMarket) {
      refreshSelectedMarket();
      if (Date.now() - state.eventsLastAttempt >= EVENT_REFRESH_INTERVAL_MS) loadOpenEvents({ preserveSelection: true });
      return;
    }
    if (Date.now() - state.eventsLastAttempt >= EVENT_REFRESH_INTERVAL_MS) loadOpenEvents();
  }, POLL_INTERVAL_MS);
}

function hydrateStaticPage() {
  if (byId("source-table-container")) renderSources(byId("source-table-container"));
  if (byId("question-table-container")) renderQuestions(byId("question-table-container"));
  if (byId("suggestion-list")) renderSuggestions(byId("suggestion-list"));
  if (byId("flag-table-container")) renderFlags(byId("flag-table-container"));
  if (byId("strategy-field-table")) renderStrategyFields(byId("strategy-field-table"));

  const topic = topicDefinition(page);
  if (topic) {
    setText("topic-description", topic.description);
    setText("topic-rule", topic.rule);
  }
}

function bindRefresh() {
  window.addEventListener("kalshi:refresh", () => {
    if (page === "resolution") loadResolutionEvents();
    else if (byId("market-table-container")) loadOpenEvents();
    else setFeedStatus("This page has no live values to refresh", "neutral");
  });
}

function boot() {
  mountShell();
  hydrateStaticPage();
  bindOpenPageControls();
  bindResolutionControls();
  bindRefresh();

  if (byId("market-table-container")) {
    loadOpenEvents();
    startPolling();
  } else if (page === "resolution") {
    loadResolutionEvents();
    startPolling();
  } else {
    setFeedStatus("Read-only · no account data loaded", "neutral");
  }
}

boot();
