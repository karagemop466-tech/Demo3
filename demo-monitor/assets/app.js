(function () {
  "use strict";

  const API = window.KalshiAPI;
  const STORAGE = {
    watchlist: "kalshi-demo-monitor.watchlist.v1",
    paperTrades: "kalshi-demo-monitor.paper-trades.v1",
    suggestionReviews: "kalshi-demo-monitor.suggestion-reviews.v1"
  };
  const LIVE_SAMPLE_MS = 15000;
  const EVENT_REFRESH_MS = 60000;
  const RANGE_MS = { "60s": 60000, "5m": 300000, "15m": 900000, "1h": 3600000, "6h": 21600000, "24h": 86400000 };
  const state = {
    page: document.body.dataset.page || "home",
    topicKey: document.body.dataset.topic || "all",
    events: [],
    marketByTicker: new Map(),
    selectedMarketTicker: "",
    selectedMarket: null,
    selectedEvent: null,
    selectedBook: null,
    range: "15m",
    candlePoints: [],
    observedPoints: [],
    candleRange: "",
    candleError: "",
    bookCheckedAt: 0,
    currentErrors: [],
    feedConnected: false,
    feedQueried: false,
    refreshTimer: null,
    selectedTimer: null,
    watchTimer: null,
    loadedAt: 0
  };

  const one = (selector, root) => (root || document).querySelector(selector);
  const all = (selector, root) => Array.from((root || document).querySelectorAll(selector));

  function make(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  }

  function setText(selector, value) {
    const element = one(selector);
    if (element) element.textContent = value == null ? "" : String(value);
  }

  function setVisible(element, visible) {
    if (element) element.classList.toggle("hidden", !visible);
  }

  function isNumber(value) {
    return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
  }

  function number(value) {
    return isNumber(value) ? Number(value) : null;
  }

  function formatUsd(value) {
    if (!isNumber(value)) return "—";
    return new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 4 }).format(Number(value));
  }

  function formatContracts(value) {
    if (!isNumber(value)) return "—";
    return new Intl.NumberFormat(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(Number(value));
  }

  function formatTime(value, options) {
    if (!value) return "";
    const date = typeof value === "number" ? new Date(value) : new Date(value);
    if (!Number.isFinite(date.getTime())) return "";
    return new Intl.DateTimeFormat(undefined, options || { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(date);
  }

  function sourceLink(href, label, className) {
    const link = make("a", className || "source-link", label);
    link.href = href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    return link;
  }

  function addCell(row, content, className) {
    const cell = make("td", className || "");
    if (content instanceof Node) cell.appendChild(content);
    else if (content !== null && content !== undefined) cell.textContent = String(content);
    row.appendChild(cell);
    return cell;
  }

  function marketUrl(ticker) {
    return API.directUrl(`/markets/${encodeURIComponent(ticker)}`);
  }

  function eventUrl(ticker) {
    return API.directUrl(`/events/${encodeURIComponent(ticker)}`, { with_nested_markets: "true" });
  }

  function orderbookUrl(ticker) {
    return API.directUrl(`/markets/${encodeURIComponent(ticker)}/orderbook`);
  }

  function readStorage(key, fallback) {
    try {
      const value = window.localStorage.getItem(key);
      return value ? JSON.parse(value) : fallback;
    } catch (error) {
      return fallback;
    }
  }

  function writeStorage(key, value) {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
      return true;
    } catch (error) {
      return false;
    }
  }

  function getWatchlist() {
    const value = readStorage(STORAGE.watchlist, []);
    return Array.isArray(value) ? value : [];
  }

  function setWatchlist(value) {
    writeStorage(STORAGE.watchlist, value);
  }

  function getPaperTrades() {
    const value = readStorage(STORAGE.paperTrades, []);
    return Array.isArray(value) ? value : [];
  }

  function setPaperTrades(value) {
    return writeStorage(STORAGE.paperTrades, value);
  }

  function isOpenMarket(market) {
    const status = String(market && market.status || "").toLowerCase();
    return status === "active" || status === "open";
  }

  function isSettledMarket(market) {
    const status = String(market && market.status || "").toLowerCase();
    return status === "finalized" || status === "settled";
  }

  function marketArray(event) {
    if (Array.isArray(event && event.markets)) return event.markets;
    if (Array.isArray(event && event._markets)) return event._markets;
    return [];
  }

  function marketsFor(event, kind) {
    const markets = marketArray(event);
    if (kind === "settled") return markets.filter(isSettledMarket);
    return markets.filter(isOpenMarket);
  }

  function aggregateEvent(event, kind) {
    const markets = marketsFor(event, kind || "open");
    const validPrice = value => isNumber(value) && Number(value) >= 0 && Number(value) <= 1;
    const validCount = value => isNumber(value) && Number(value) >= 0;
    const complete = markets.length > 0 && markets.every(market =>
      validPrice(market.yes_bid_dollars) && validCount(market.yes_bid_size_fp) &&
      validPrice(market.yes_ask_dollars) && validCount(market.yes_ask_size_fp)
    );
    let bidValue = 0;
    let askValue = 0;
    if (complete) {
      markets.forEach(market => {
        bidValue += Number(market.yes_bid_dollars) * Number(market.yes_bid_size_fp);
        askValue += Number(market.yes_ask_dollars) * Number(market.yes_ask_size_fp);
      });
    }
    const computed = complete && Number.isFinite(bidValue) && Number.isFinite(askValue) && Number.isFinite(bidValue + askValue);
    const sumContractField = field => {
      if (!markets.length || !markets.every(market => isNumber(market[field]) && Number(market[field]) >= 0)) return null;
      const total = markets.reduce((sum, market) => sum + Number(market[field]), 0);
      return Number.isFinite(total) ? total : null;
    };
    const closeTimes = markets.map(market => market.close_time).filter(Boolean).map(value => new Date(value)).filter(date => Number.isFinite(date.getTime())).sort((a, b) => a - b);
    return {
      markets,
      marketCount: markets.length,
      bidValue: computed ? bidValue : null,
      askValue: computed ? askValue : null,
      displayedValue: computed ? bidValue + askValue : null,
      complete: computed,
      volume24h: sumContractField("volume_24h_fp"),
      openInterest: sumContractField("open_interest_fp"),
      nearestClose: closeTimes.length ? closeTimes[0] : null
    };
  }

  function setFeedStatus(mode, message) {
    all("[data-live-status]").forEach(wrapper => {
      const dot = one(".status-dot", wrapper);
      if (dot) {
        dot.classList.toggle("is-live", mode === "live");
        dot.classList.toggle("is-error", mode === "error");
        dot.classList.toggle("is-waiting", mode === "waiting");
      }
      const label = one("[data-live-label]", wrapper);
      if (label) label.textContent = message;
    });
    all("[data-feed-dot]").forEach(dot => {
      dot.classList.toggle("is-live", mode === "live");
      dot.classList.toggle("is-error", mode === "error");
      dot.classList.toggle("is-waiting", mode === "waiting");
    });
    all("[data-feed-label]").forEach(label => { label.textContent = message; });
  }

  function setPageTopicCopy() {
    if (state.page !== "markets" || state.topicKey === "all") return;
    const topic = API.TOPICS[state.topicKey];
    if (!topic) return;
    document.title = `${topic.pageTitle} · Kalshi Demo Monitor`;
    const heading = one("[data-page-heading]");
    const description = one("[data-page-description]");
    if (heading) heading.textContent = `${topic.pageTitle} events`;
    if (description) description.textContent = topic.description;
    all(".subnav a").forEach(link => {
      const isCurrent = (state.topicKey === "gas" && link.getAttribute("href") === "gas-prices.html") ||
        (state.topicKey === "elections" && link.getAttribute("href") === "elections.html") ||
        (state.topicKey === "culture" && link.getAttribute("href") === "culture.html") ||
        (state.topicKey === "crypto" && link.getAttribute("href") === "crypto.html") ||
        (state.topicKey === "golf" && link.getAttribute("href") === "golf.html");
      if (isCurrent) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
  }

  function eventTopicText(event) {
    const labels = event._topicLabels || [event._topicLabel || ""];
    const category = event.category || (event._series && event._series.category) || "";
    const series = (event._series && event._series.ticker) || event.series_ticker || "";
    const pieces = [];
    if (labels.filter(Boolean).length) pieces.push(Array.from(new Set(labels.filter(Boolean))).join(" / "));
    if (category) pieces.push(category);
    if (series) pieces.push(series);
    return pieces.join(" · ") || "";
  }

  function rebuildMarketIndex(events, kind) {
    state.marketByTicker.clear();
    events.forEach(event => {
      const markets = marketsFor(event, kind || "open");
      markets.forEach(market => {
        if (!market || !market.ticker) return;
        const record = { ...market, _event: event, _topicKey: event._topicKey || state.topicKey, _topicLabel: event._topicLabel || "", _series: event._series || null };
        if (!state.marketByTicker.has(record.ticker)) state.marketByTicker.set(record.ticker, record);
      });
    });
  }

  function eventRankValue(event, sortBy) {
    const metrics = aggregateEvent(event, "open");
    if (sortBy === "volume") return metrics.volume24h;
    if (sortBy === "open-interest") return metrics.openInterest;
    return metrics.displayedValue;
  }

  function renderEventTable(events, errors, successful) {
    const tbody = one("[data-event-rows]");
    const empty = one("[data-event-empty]");
    if (!tbody) return;
    tbody.replaceChildren();
    const sortBy = (one("[data-ranking]") && one("[data-ranking]").value) || "notional";
    const visibleEvents = events.filter(event => aggregateEvent(event, "open").marketCount > 0);
    visibleEvents.sort((a, b) => {
      const left = eventRankValue(a, sortBy);
      const right = eventRankValue(b, sortBy);
      if (left === null && right === null) return String(a.event_ticker || "").localeCompare(String(b.event_ticker || ""));
      if (left === null) return 1;
      if (right === null) return -1;
      return right - left;
    });

    visibleEvents.forEach((event, index) => {
      const metrics = aggregateEvent(event, "open");
      const row = make("tr");
      addCell(row, String(index + 1), "number");
      const eventCell = make("td");
      const title = make("span", "cell-title", event.title || event.sub_title || event.event_ticker || "");
      eventCell.appendChild(title);
      const ticker = make("span", "cell-subtitle", event.event_ticker || "");
      eventCell.appendChild(ticker);
      const actions = make("div", "row-actions");
      const inspect = make("button", "btn-ghost", "Inspect");
      inspect.type = "button";
      inspect.dataset.inspectTicker = metrics.markets[0] && metrics.markets[0].ticker || "";
      inspect.title = "Inspect the first open market in this event";
      actions.appendChild(inspect);
      const watch = make("button", "btn-secondary", isTracked(event.event_ticker) ? "Tracking" : "Track event");
      watch.type = "button";
      watch.dataset.trackTicker = event.event_ticker || "";
      watch.dataset.trackTitle = event.title || event.event_ticker || "";
      watch.dataset.trackTopic = event._topicLabel || (event._topicLabels || []).join(" / ") || "";
      watch.dataset.trackSeries = (event._series && event._series.ticker) || event.series_ticker || "";
      if (isTracked(event.event_ticker)) watch.classList.add("is-tracking");
      actions.appendChild(watch);
      eventCell.appendChild(actions);
      row.appendChild(eventCell);

      addCell(row, eventTopicText(event));
      addCell(row, String(metrics.marketCount), "number");
      const valueCell = make("td", "number");
      if (metrics.displayedValue !== null) {
        valueCell.appendChild(make("strong", "", formatUsd(metrics.displayedValue)));
        const split = make("span", "cell-subtitle", `Bid ${formatUsd(metrics.bidValue)} · Ask ${formatUsd(metrics.askValue)}`);
        valueCell.appendChild(split);
      } else {
        valueCell.appendChild(make("span", "empty-inline", "—"));
        valueCell.appendChild(make("span", "cell-subtitle", "Unverified · quote fields missing or invalid"));
      }
      row.appendChild(valueCell);
      const volume = metrics.volume24h === null ? "—" : formatContracts(metrics.volume24h);
      addCell(row, volume, "number");
      addCell(row, metrics.nearestClose ? formatTime(metrics.nearestClose) : "", "number");
      const sourceCell = make("td");
      sourceCell.appendChild(sourceLink(eventUrl(event.event_ticker), "Event API"));
      row.appendChild(sourceCell);
      tbody.appendChild(row);
    });

    if (empty) {
      setVisible(empty, visibleEvents.length === 0);
      if (!visibleEvents.length) {
        const title = one("strong", empty);
        const paragraph = one("p", empty);
        if (errors && errors.length) {
          if (title) title.textContent = "Official demo data could not be verified";
          if (paragraph) paragraph.textContent = errors.slice(0, 2).map(error => error.message).join(" · ");
        } else if (successful) {
          if (title) title.textContent = "No matching open events returned";
          if (paragraph) paragraph.textContent = "The official API responded, but no open events matched the selected topic metadata. No values or sample events have been substituted.";
        }
      }
    }
    updateMarketMetrics(visibleEvents);
  }

  function updateMarketMetrics(events) {
    const eventCount = one("[data-metric-events]");
    const marketCount = one("[data-metric-markets]");
    const topValue = one("[data-metric-top-value]");
    const updated = one("[data-metric-updated]");
    const validEvents = events.map(event => aggregateEvent(event, "open")).filter(metrics => metrics.displayedValue !== null);
    const max = validEvents.length ? Math.max(...validEvents.map(metrics => metrics.displayedValue)) : null;
    const completeRanking = state.feedConnected && events.length > 0 && validEvents.length === events.length;
    if (eventCount) eventCount.textContent = state.feedConnected ? String(events.length) : "—";
    if (marketCount) marketCount.textContent = state.feedConnected ? String(events.reduce((sum, event) => sum + aggregateEvent(event, "open").marketCount, 0)) : "—";
    if (topValue) topValue.textContent = !completeRanking || max === null ? "—" : formatUsd(max);
    if (updated) updated.textContent = state.loadedAt && state.feedQueried ? formatTime(state.loadedAt, { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";
    const homeCount = one("[data-summary-count]");
    const homeNotional = one("[data-summary-notional]");
    const homeSource = one("[data-summary-source]");
    const homeUpdated = one("[data-summary-updated]");
    if (homeCount) homeCount.textContent = state.feedConnected ? String(events.length) : "—";
    if (homeNotional) homeNotional.textContent = !completeRanking || max === null ? "—" : formatUsd(max);
    if (homeSource) homeSource.textContent = state.feedConnected ? "Connected" : state.feedQueried ? "Partial · review" : state.loadedAt ? "Unverified" : "Not checked";
    if (homeUpdated) homeUpdated.textContent = state.loadedAt && state.feedQueried ? `Observed ${formatTime(state.loadedAt, { hour: "2-digit", minute: "2-digit", second: "2-digit" })}` : state.loadedAt ? "Attempted · no verified response" : "Values are not preloaded";
  }

  function populateMarketPicker() {
    const picker = one("[data-market-picker]");
    if (!picker) return;
    const previous = state.selectedMarketTicker;
    picker.replaceChildren();
    const first = make("option", "", state.marketByTicker.size ? "Select an open market…" : "No verified open markets available");
    first.value = "";
    picker.appendChild(first);
    const records = Array.from(state.marketByTicker.values()).sort((a, b) => {
      const at = `${a._event && a._event.title || ""} ${a.title || a.ticker}`;
      const bt = `${b._event && b._event.title || ""} ${b.title || b.ticker}`;
      return at.localeCompare(bt);
    });
    records.forEach(market => {
      const option = make("option", "", `${market._event && market._event.title || "Event"} — ${market.title || market.subtitle || market.ticker} · ${market.ticker}`);
      option.value = market.ticker;
      picker.appendChild(option);
    });
    picker.disabled = records.length === 0;
    if (records.some(market => market.ticker === previous)) {
      picker.value = previous;
    } else if (records.length) {
      picker.value = records[0].ticker;
    } else {
      picker.value = "";
    }
    if (picker.value && picker.value !== previous) selectMarket(picker.value);
    else if (picker.value && !state.selectedMarket) selectMarket(picker.value);
    else if (!picker.value && state.selectedMarketTicker) selectMarket("");
  }

  async function loadMarketView(force) {
    const topicKeys = state.topicKey === "all" ? Object.keys(API.TOPICS) : [state.topicKey];
    setFeedStatus("waiting", "Connecting to Kalshi demo");
    const refreshButton = one("[data-refresh]");
    if (refreshButton) refreshButton.disabled = true;
    try {
      const result = await API.loadTopics(topicKeys, "open", Boolean(force));
      state.events = result.events;
      state.currentErrors = result.errors;
      state.feedQueried = result.queried;
      state.feedConnected = result.queried && result.complete;
      state.loadedAt = Date.now();
      rebuildMarketIndex(state.events, "open");
      renderEventTable(state.events, result.errors, result.queried);
      const coverage = one("[data-feed-coverage]");
      if (coverage) {
        const incompleteQuotes = result.events.filter(event => aggregateEvent(event, "open").marketCount > 0 && aggregateEvent(event, "open").displayedValue === null).length;
        if (result.errors.length || !result.complete) coverage.textContent = `Partial API response · ${result.errors.length} issue(s). Rows link to returned event responses, but overall coverage and the highest-event ranking are not verified.`;
        else if (incompleteQuotes) coverage.textContent = `API pagination completed; ${incompleteQuotes} open event(s) have missing or invalid quote fields. Their dollar value stays blank, so the highest-event ranking is not fully verified.`;
        else coverage.textContent = "Complete response for the requested topic metadata and open-event pages; missing market fields, if any, remain blank.";
      }
      populateMarketPicker();
      renderPaperMarketOptions();
      if (result.queried) {
        const partial = result.errors.length > 0 || !result.complete;
        const status = partial ? `Demo feed partial · ${result.errors.length} issue${result.errors.length === 1 ? "" : "s"}` : "Demo feed connected · REST";
        setFeedStatus(partial ? "waiting" : "live", status);
      } else {
        setFeedStatus("error", "Demo data unavailable");
      }
    } catch (error) {
      state.feedConnected = false;
      state.feedQueried = false;
      state.currentErrors = [error];
      state.loadedAt = 0;
      state.events = [];
      state.marketByTicker.clear();
      renderEventTable([], [error], false);
      populateMarketPicker();
      renderPaperMarketOptions();
      setFeedStatus("error", "Demo data unavailable");
    } finally {
      if (refreshButton) refreshButton.disabled = false;
    }
  }

  function selectedMarketRecord() {
    return state.marketByTicker.get(state.selectedMarketTicker) || null;
  }

  function selectMarket(ticker) {
    if (state.selectedTimer) {
      window.clearInterval(state.selectedTimer);
      state.selectedTimer = null;
    }
    state.selectedMarketTicker = ticker || "";
    state.selectedMarket = null;
    state.selectedEvent = null;
    state.selectedBook = null;
    state.candlePoints = [];
    state.observedPoints = [];
    state.candleRange = "";
    state.candleError = "";
    state.bookCheckedAt = 0;
    const market = selectedMarketRecord();
    if (!market) {
      updateChartHeader(null);
      drawChart();
      renderOrderbookEmpty("Choose a market to load price levels.");
      return;
    }
    state.selectedMarket = market;
    state.selectedEvent = market._event || null;
    updateChartHeader(market);
    updateBookSource(market.ticker);
    refreshSelectedMarket(true);
    state.selectedTimer = window.setInterval(() => {
      if (document.visibilityState === "visible") refreshSelectedMarket(false);
    }, LIVE_SAMPLE_MS);
  }

  function updateChartHeader(market) {
    const title = one("[data-chart-title]");
    const subtitle = one("[data-chart-subtitle]");
    const source = one("[data-selected-market-source]");
    if (!market) {
      if (title) title.textContent = "No market selected";
      if (subtitle) subtitle.textContent = "Time on the horizontal axis · contract price in USD on the vertical axis";
      if (source) source.href = "https://docs.kalshi.com/api-reference/market/get-market";
      setText("[data-current-price]", "—");
      return;
    }
    const label = market.title || market.subtitle || market.ticker;
    if (title) title.textContent = label;
    if (subtitle) subtitle.textContent = `${market.ticker} · Last-traded contract price · X: local time · Y: USD`;
    if (source) {
      source.href = marketUrl(market.ticker);
      source.textContent = "Raw market API";
    }
  }

  function updateBookSource(ticker) {
    const source = one("[data-orderbook-source]");
    if (source && ticker) {
      source.href = orderbookUrl(ticker);
      source.textContent = "Raw order book";
    }
  }

  async function refreshSelectedMarket(loadAll) {
    const record = selectedMarketRecord();
    if (!record) return;
    try {
      const response = await API.get(`/markets/${encodeURIComponent(record.ticker)}`);
      const current = response.market || response;
      state.selectedMarket = { ...record, ...current };
      state.marketByTicker.set(record.ticker, state.selectedMarket);
      const price = number(current.last_price_dollars);
      if (price !== null) {
        state.observedPoints.push({ time: Date.now(), price, source: "browser-observed REST snapshot" });
        const keepAfter = Date.now() - RANGE_MS["24h"] - 60000;
        state.observedPoints = state.observedPoints.filter(point => point.time >= keepAfter).slice(-10000);
      }
      setText("[data-current-price]", price === null ? "Last price unavailable" : `Last price ${formatUsd(price)}`);
      if (loadAll || state.candleRange !== state.range) await loadCandlesForRange();
      if (loadAll || Date.now() - state.bookCheckedAt > 30000) await loadOrderbook(record.ticker);
      updateChartStatus();
      drawChart();
      renderPaperMarketOptions();
      renderPaperLedger();
    } catch (error) {
      const status = one("[data-chart-status]");
      if (status) status.textContent = `Market data unavailable: ${error.message}`;
      updateChartHeader(record);
      drawChart();
    }
  }

  async function loadCandlesForRange() {
    const market = state.selectedMarket || selectedMarketRecord();
    const seriesTicker = market && market._series && market._series.ticker || (state.selectedEvent && state.selectedEvent.series_ticker);
    const ticker = market && market.ticker;
    state.candlePoints = [];
    state.candleRange = state.range;
    state.candleError = "";
    if (!market || !ticker || !seriesTicker) {
      state.candleError = "Series metadata is not available for a candlestick request.";
      updateChartStatus();
      return;
    }
    if (state.range === "60s") {
      updateChartStatus();
      return;
    }
    const interval = state.range === "6h" || state.range === "24h" ? 60 : 1;
    const endMs = Date.now();
    const startMs = endMs - RANGE_MS[state.range];
    const path = `/series/${encodeURIComponent(seriesTicker)}/markets/${encodeURIComponent(ticker)}/candlesticks`;
    try {
      const response = await API.get(path, {
        start_ts: Math.floor(startMs / 1000),
        end_ts: Math.floor(endMs / 1000),
        period_interval: interval
      });
      const candles = Array.isArray(response.candlesticks) ? response.candlesticks : [];
      state.candlePoints = candles.map(candle => ({
        time: Number(candle.end_period_ts) * 1000,
        price: number(candle.price && candle.price.close_dollars),
        source: `official ${interval}-minute candle`
      })).filter(point => Number.isFinite(point.time) && point.price !== null);
    } catch (error) {
      state.candleError = error.message;
    }
    updateChartStatus();
    drawChart();
  }

  function updateChartStatus() {
    const status = one("[data-chart-status]");
    if (!status) return;
    if (!state.selectedMarket) {
      status.textContent = "No price history is embedded. Select a live market to fetch candles and begin local observations.";
      return;
    }
    const intervalText = state.range === "60s" ? "seconds-range browser observations only (15-second REST polling)" : (state.range === "6h" || state.range === "24h" ? "official 60-minute candles plus browser observations" : "official 1-minute candles plus browser observations");
    const observationCount = state.observedPoints.filter(point => point.time >= Date.now() - RANGE_MS[state.range]).length;
    if (state.candleError) {
      status.textContent = `Chart source: ${intervalText}. Candle request did not verify: ${state.candleError} ${observationCount ? `${observationCount} browser observation(s) collected.` : ""}`;
    } else {
      status.textContent = `Chart source: ${intervalText}. ${observationCount} browser observation(s) collected in this open page; observations are not persistent server history.`;
    }
  }

  function visibleChartPoints() {
    const span = RANGE_MS[state.range] || RANGE_MS["15m"];
    const cutoff = Date.now() - span;
    const points = state.candlePoints.filter(point => point.time >= cutoff && point.price !== null);
    state.observedPoints.filter(point => point.time >= cutoff).forEach(point => points.push(point));
    points.sort((a, b) => a.time - b.time);
    const deduped = [];
    points.forEach(point => {
      const last = deduped[deduped.length - 1];
      if (last && Math.abs(last.time - point.time) < 1000) deduped[deduped.length - 1] = point;
      else deduped.push(point);
    });
    return deduped;
  }

  function drawChart() {
    const canvas = one("[data-price-chart]");
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) return;
    const ratio = Math.max(1, window.devicePixelRatio || 1);
    canvas.width = Math.round(rect.width * ratio);
    canvas.height = Math.round(rect.height * ratio);
    const context = canvas.getContext("2d");
    if (!context) return;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    const width = rect.width;
    const height = rect.height;
    const left = 53;
    const right = 15;
    const top = 14;
    const bottom = 30;
    const plotW = Math.max(20, width - left - right);
    const plotH = Math.max(20, height - top - bottom);
    context.clearRect(0, 0, width, height);
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, width, height);
    context.font = "10px ui-sans-serif, system-ui, sans-serif";
    context.strokeStyle = "#e8eff0";
    context.fillStyle = "#748690";
    context.lineWidth = 1;
    for (let index = 0; index <= 4; index += 1) {
      const y = top + plotH * index / 4;
      context.beginPath();
      context.moveTo(left, y);
      context.lineTo(left + plotW, y);
      context.stroke();
    }
    const points = visibleChartPoints();
    if (!points.length) {
      context.fillStyle = "#71828c";
      context.textAlign = "center";
      context.fillText("No verified price points yet", left + plotW / 2, top + plotH / 2);
      context.textAlign = "left";
      context.fillStyle = "#748690";
      context.fillText("Time", left + plotW / 2 - 10, height - 5);
      context.save();
      context.translate(12, top + plotH / 2);
      context.rotate(-Math.PI / 2);
      context.fillText("Contract price (USD)", -55, 0);
      context.restore();
      return;
    }
    const values = points.map(point => point.price);
    let min = Math.min(...values);
    let max = Math.max(...values);
    if (min === max) {
      const pad = Math.max(Math.abs(min) * 0.04, 0.01);
      min -= pad;
      max += pad;
    } else {
      const pad = (max - min) * 0.08;
      min -= pad;
      max += pad;
    }
    const firstTime = points[0].time;
    const lastTime = points[points.length - 1].time;
    const timeSpan = Math.max(1, lastTime - firstTime);
    const x = time => left + ((time - firstTime) / timeSpan) * plotW;
    const y = price => top + ((max - price) / (max - min)) * plotH;
    context.fillStyle = "#748690";
    context.textAlign = "right";
    for (let index = 0; index <= 4; index += 1) {
      const value = max - (max - min) * index / 4;
      const label = new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(value);
      context.fillText(label, left - 8, top + plotH * index / 4 + 3);
    }
    context.textAlign = "left";
    context.fillText(formatTime(firstTime, { hour: "2-digit", minute: "2-digit", second: state.range === "60s" ? "2-digit" : undefined }), left, height - 6);
    context.textAlign = "right";
    context.fillText(formatTime(lastTime, { hour: "2-digit", minute: "2-digit", second: state.range === "60s" ? "2-digit" : undefined }), left + plotW, height - 6);
    context.textAlign = "center";
    context.fillText("Time", left + plotW / 2, height - 6);
    context.save();
    context.translate(13, top + plotH / 2);
    context.rotate(-Math.PI / 2);
    context.fillText("Contract price (USD)", 0, 0);
    context.restore();
    context.beginPath();
    points.forEach((point, index) => {
      if (index === 0) context.moveTo(x(point.time), y(point.price));
      else context.lineTo(x(point.time), y(point.price));
    });
    context.strokeStyle = "#087d75";
    context.lineWidth = 2.2;
    context.lineJoin = "round";
    context.lineCap = "round";
    context.stroke();
    const last = points[points.length - 1];
    context.beginPath();
    context.arc(x(last.time), y(last.price), 3.5, 0, Math.PI * 2);
    context.fillStyle = "#087d75";
    context.fill();
  }

  function setRange(range) {
    if (!RANGE_MS[range]) return;
    state.range = range;
    all("[data-chart-range]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.chartRange === range)));
    state.candleRange = "";
    loadCandlesForRange().then(() => {
      updateChartStatus();
      drawChart();
    });
  }

  function renderOrderbookEmpty(message) {
    const status = one("[data-orderbook-status]");
    if (status) status.textContent = message;
    const tbody = one("[data-orderbook-rows]");
    const empty = one("[data-orderbook-empty]");
    if (tbody) tbody.replaceChildren();
    if (empty) setVisible(empty, true);
  }

  async function loadOrderbook(ticker) {
    const tbody = one("[data-orderbook-rows]");
    if (!tbody || !ticker) return;
    const status = one("[data-orderbook-status]");
    const empty = one("[data-orderbook-empty]");
    if (status) status.textContent = "Fetching current public order book…";
    updateBookSource(ticker);
    try {
      const response = await API.get(`/markets/${encodeURIComponent(ticker)}/orderbook`);
      const book = response && response.orderbook_fp;
      if (!book || !Array.isArray(book.yes_dollars) || !Array.isArray(book.no_dollars)) {
        throw new Error("The response did not contain documented orderbook_fp yes_dollars and no_dollars arrays.");
      }
      const yes = book.yes_dollars;
      const no = book.no_dollars;
      const levels = [];
      const addLevel = (side, price, count, implied) => {
        if (!isNumber(price) || !isNumber(count)) return;
        const priceNumber = Number(price);
        const countNumber = Number(count);
        if (priceNumber < 0 || priceNumber > 1 || countNumber < 0) return;
        levels.push({ side, price: priceNumber, count: countNumber, value: priceNumber * countNumber, implied: Boolean(implied) });
      };
      yes.forEach(level => {
        if (Array.isArray(level) && level.length >= 2 && isNumber(level[0])) {
          const price = Number(level[0]);
          addLevel("YES bid", price, level[1], false);
          addLevel("NO ask · implied", (1 - price).toFixed(4), level[1], true);
        }
      });
      no.forEach(level => {
        if (Array.isArray(level) && level.length >= 2 && isNumber(level[0])) {
          const price = Number(level[0]);
          addLevel("NO bid", price, level[1], false);
          addLevel("YES ask · implied", (1 - price).toFixed(4), level[1], true);
        }
      });
      levels.sort((a, b) => a.side.localeCompare(b.side) || a.price - b.price);
      tbody.replaceChildren();
      levels.forEach(level => {
        const row = make("tr");
        addCell(row, level.side);
        addCell(row, formatUsd(level.price), "number");
        addCell(row, formatContracts(level.count), "number");
        addCell(row, formatUsd(level.value), "number level-value");
        addCell(row, sourceLink(orderbookUrl(ticker), "Book API"));
        tbody.appendChild(row);
      });
      if (empty) setVisible(empty, levels.length === 0);
      if (status) status.textContent = levels.length ? `${levels.length} bid and implied-ask levels · observed ${formatTime(Date.now())}` : `No bids returned for this market · observed ${formatTime(Date.now())}`;
      state.selectedBook = response;
      state.bookCheckedAt = Date.now();
    } catch (error) {
      tbody.replaceChildren();
      if (empty) setVisible(empty, true);
      if (status) status.textContent = `Order book not verified: ${error.message}`;
      state.bookCheckedAt = Date.now();
    }
  }

  function isTracked(eventTicker) {
    return getWatchlist().some(item => item.eventTicker === eventTicker);
  }

  function trackEvent(button) {
    const eventTicker = button.dataset.trackTicker;
    if (!eventTicker) return;
    const items = getWatchlist();
    if (items.some(item => item.eventTicker === eventTicker)) return;
    const item = {
      eventTicker,
      title: button.dataset.trackTitle || eventTicker,
      topicLabel: button.dataset.trackTopic || "",
      seriesTicker: button.dataset.trackSeries || "",
      addedAt: new Date().toISOString(),
      checkedAt: "",
      error: "",
      markets: []
    };
    items.push(item);
    setWatchlist(items);
    button.textContent = "Tracking";
    button.disabled = true;
    button.classList.add("is-tracking");
  }

  function updateWatchButton(ticker) {
    const button = one(`[data-track-ticker="${CSS.escape(ticker)}"]`);
    if (button && isTracked(ticker)) {
      button.textContent = "Tracking";
      button.disabled = true;
      button.classList.add("is-tracking");
    }
  }

  function renderWatchRows() {
    const tbody = one("[data-watch-rows]");
    const empty = one("[data-watch-empty]");
    if (!tbody) return;
    const list = getWatchlist();
    tbody.replaceChildren();
    setText("[data-watch-count]", `${list.length} tracked`);
    if (empty) setVisible(empty, list.length === 0);
    list.forEach(item => {
      const markets = Array.isArray(item.markets) && item.markets.length ? item.markets : [null];
      markets.forEach(market => {
        const row = make("tr");
        const titleCell = make("td");
        titleCell.appendChild(make("span", "cell-title", item.title || item.eventTicker));
        if (market) titleCell.appendChild(make("span", "cell-subtitle", market.title || market.ticker || ""));
        row.appendChild(titleCell);
        addCell(row, item.topicLabel || "");
        const status = market && market.status ? market.status : (item.error ? "Could not check" : "Waiting for first refresh");
        addCell(row, status);
        const resultCell = make("td");
        const rawResult = market && market.result ? String(market.result) : "";
        if (rawResult) {
          const resultTag = make("span", `tag ${rawResult.toLowerCase() === "yes" ? "result-yes" : rawResult.toLowerCase() === "no" ? "result-no" : "warn"}`, isSettledMarket(market) ? rawResult : `Reported: ${rawResult} · pending settlement`);
          resultCell.appendChild(resultTag);
        } else if (market && isSettledMarket(market)) {
          resultCell.appendChild(make("span", "tag warn", "Result missing · review"));
        } else if (item.error) {
          resultCell.appendChild(make("span", "tag warn", "Unverified · check failed"));
        }
        row.appendChild(resultCell);
        addCell(row, item.checkedAt ? formatTime(item.checkedAt) : "");
        const actionCell = make("td");
        const remove = make("button", "btn-ghost", "Stop tracking");
        remove.type = "button";
        remove.dataset.unwatchTicker = item.eventTicker;
        actionCell.appendChild(remove);
        row.appendChild(actionCell);
        addCell(row, sourceLink(eventUrl(item.eventTicker), "Event API"));
        tbody.appendChild(row);
      });
    });
  }

  async function refreshWatchlist() {
    const list = getWatchlist();
    if (!list.length) {
      renderWatchRows();
      return;
    }
    const updateResults = await Promise.all(list.map(async item => {
      try {
        const response = await API.get(`/events/${encodeURIComponent(item.eventTicker)}`, { with_nested_markets: "true" });
        const event = response.event || response;
        const markets = Array.isArray(response.markets) ? response.markets : marketArray(event);
        return {
          ...item,
          title: event.title || item.title,
          seriesTicker: event.series_ticker || item.seriesTicker,
          checkedAt: new Date().toISOString(),
          error: "",
          markets: markets.map(market => ({
            ticker: market.ticker || "",
            title: market.title || market.subtitle || market.ticker || "",
            status: market.status || "",
            result: market.result || "",
            settlement_ts: market.settlement_ts || "",
            market_type: market.market_type || ""
          }))
        };
      } catch (error) {
        return { ...item, checkedAt: new Date().toISOString(), error: error.message };
      }
    }));
    setWatchlist(updateResults);
    renderWatchRows();
  }

  function removeWatch(eventTicker) {
    setWatchlist(getWatchlist().filter(item => item.eventTicker !== eventTicker));
    renderWatchRows();
  }

  async function loadResolvedEvents(force) {
    const topicKeys = Object.keys(API.TOPICS);
    setFeedStatus("waiting", "Checking settled demo events");
    try {
      const result = await API.loadTopics(topicKeys, "settled", Boolean(force));
      const rows = [];
      result.events.forEach(event => {
        marketsFor(event, "settled").forEach(market => rows.push({ event, market }));
      });
      rows.sort((a, b) => String(b.market.settlement_ts || "").localeCompare(String(a.market.settlement_ts || "")));
      renderResolvedRows(rows);
      state.feedQueried = result.queried;
      state.feedConnected = result.queried && result.complete;
      const partial = result.errors.length > 0 || !result.complete;
      setFeedStatus(!result.queried ? "error" : (partial ? "waiting" : "live"), !result.queried ? "Settled feed unavailable" : (partial ? `Settled feed partial · ${result.errors.length} issue${result.errors.length === 1 ? "" : "s"}` : "Demo feed connected · settled results"));
    } catch (error) {
      state.feedConnected = false;
      state.feedQueried = false;
      renderResolvedRows([], error.message);
      setFeedStatus("error", "Settled feed unavailable");
    }
  }

  function renderResolvedRows(items, error) {
    const tbody = one("[data-resolved-rows]");
    const empty = one("[data-resolved-empty]");
    if (!tbody) return;
    tbody.replaceChildren();
    items.forEach(({ event, market }) => {
      const row = make("tr");
      const titleCell = make("td");
      titleCell.appendChild(make("span", "cell-title", event.title || event.event_ticker || ""));
      titleCell.appendChild(make("span", "cell-subtitle", market.title || market.subtitle || market.ticker || ""));
      row.appendChild(titleCell);
      addCell(row, eventTopicText(event));
      const statusCell = make("td");
      statusCell.appendChild(make("span", "tag live", market.status || ""));
      row.appendChild(statusCell);
      const resultCell = make("td");
      if (market.result) {
        const result = String(market.result);
        const klass = result.toLowerCase() === "yes" ? "result-yes" : result.toLowerCase() === "no" ? "result-no" : "warn";
        resultCell.appendChild(make("span", `tag ${klass}`, result));
      } else {
        resultCell.appendChild(make("span", "tag warn", "Result missing · review"));
      }
      row.appendChild(resultCell);
      addCell(row, market.settlement_ts ? formatTime(market.settlement_ts) : "", "number");
      addCell(row, sourceLink(eventUrl(event.event_ticker), "Event API"));
      tbody.appendChild(row);
    });
    if (empty) {
      setVisible(empty, items.length === 0);
      if (error) {
        const title = one("strong", empty);
        const text = one("p", empty);
        if (title) title.textContent = "Settled data could not be verified";
        if (text) text.textContent = error;
      }
    }
  }

  function renderPaperMarketOptions() {
    const picker = one("[data-paper-market]");
    if (!picker) return;
    const previous = picker.value;
    const records = Array.from(state.marketByTicker.values()).filter(market => {
      const type = String(market.market_type || "").toLowerCase();
      return isOpenMarket(market) && type === "binary";
    }).sort((a, b) => String(a.ticker).localeCompare(String(b.ticker)));
    picker.replaceChildren();
    const placeholder = make("option", "", records.length ? "Select a verified open binary market…" : "No verified open binary market");
    placeholder.value = "";
    picker.appendChild(placeholder);
    records.forEach(market => {
      const eventTitle = market._event && (market._event.title || market._event.event_ticker) || "Event";
      const label = `${eventTitle} — ${market.title || market.subtitle || market.ticker} · ${market.ticker}`;
      const option = make("option", "", label);
      option.value = market.ticker;
      picker.appendChild(option);
    });
    picker.disabled = records.length === 0;
    picker.value = records.some(record => record.ticker === previous) ? previous : (records.length ? records[0].ticker : "");
    updatePaperPreview();
    renderPaperLedger();
  }

  function paperEntryQuote(market, side) {
    if (!market || String(market.market_type || "").toLowerCase() !== "binary") return null;
    const field = side === "no" ? "no_ask_dollars" : "yes_ask_dollars";
    const price = number(market[field]);
    return price !== null && price >= 0 && price <= 1 ? price : null;
  }

  function updatePaperPreview() {
    const picker = one("[data-paper-market]");
    const side = one("[data-paper-side]");
    const count = one("[data-paper-count]");
    const button = one("[data-paper-submit]");
    const preview = one("[data-paper-preview]");
    if (!picker || !preview) return;
    const market = state.marketByTicker.get(picker.value);
    const countNumber = count ? Number(count.value) : null;
    const sideValue = side ? side.value : "yes";
    const price = paperEntryQuote(market, sideValue);
    const valid = Boolean(market && isOpenMarket(market) && price !== null && Number.isFinite(countNumber) && countNumber > 0);
    if (button) button.disabled = !valid;
    if (!market) {
      preview.textContent = "Waiting for a verified public open binary-market quote. No value will be guessed if the quote is missing.";
    } else if (price === null) {
      preview.textContent = `No official ${sideValue.toUpperCase()} ask quote is present for ${market.ticker}; paper entry is disabled rather than estimated.`;
    } else if (!Number.isFinite(countNumber) || countNumber <= 0) {
      preview.textContent = "Enter a positive contract count to preview a local paper simulation.";
    } else {
      preview.textContent = `Paper-only preview: ${sideValue.toUpperCase()} ask ${formatUsd(price)} × ${formatContracts(countNumber)} contract(s) = ${formatUsd(price * countNumber)} before fees. This is not an executable order or guaranteed fill.`;
    }
  }

  function submitPaperTrade(event) {
    event.preventDefault();
    const picker = one("[data-paper-market]");
    const sideInput = one("[data-paper-side]");
    const countInput = one("[data-paper-count]");
    const strategyInput = one("[data-paper-strategy]");
    const market = picker && state.marketByTicker.get(picker.value);
    const side = sideInput ? sideInput.value : "yes";
    const count = countInput ? Number(countInput.value) : NaN;
    const entry = paperEntryQuote(market, side);
    if (!market || !isOpenMarket(market) || entry === null || !Number.isFinite(count) || count <= 0) {
      updatePaperPreview();
      return;
    }
    const eventInfo = market._event || {};
    const trade = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
      createdAt: new Date().toISOString(),
      ticker: market.ticker,
      eventTicker: market.event_ticker || eventInfo.event_ticker || "",
      eventTitle: eventInfo.title || market.title || market.ticker,
      marketTitle: market.title || market.subtitle || market.ticker,
      topic: market._topicLabel || eventInfo._topicLabel || "",
      seriesTicker: market._series && market._series.ticker || eventInfo.series_ticker || "",
      side,
      count,
      entryPrice: entry,
      strategy: strategyInput ? strategyInput.value : "Unassigned",
      status: "open",
      exitPrice: null,
      closedAt: "",
      realizedPnl: null
    };
    const trades = getPaperTrades();
    trades.unshift(trade);
    if (!setPaperTrades(trades)) {
      const preview = one("[data-paper-preview]");
      if (preview) preview.textContent = "This browser could not save local storage. No simulation was recorded.";
      return;
    }
    if (countInput) countInput.value = "1.00";
    updatePaperPreview();
    renderPaperLedger();
  }

  function paperMark(trade) {
    const market = state.marketByTicker.get(trade.ticker);
    if (!market || !isNumber(market.last_price_dollars)) return null;
    if (String(market.market_type || "").toLowerCase() !== "binary") return null;
    const yesPrice = Number(market.last_price_dollars);
    if (yesPrice < 0 || yesPrice > 1) return null;
    if (trade.side === "yes") return yesPrice;
    return 1 - yesPrice;
  }

  function paperExitQuote(trade) {
    const market = state.marketByTicker.get(trade.ticker);
    if (!market || String(market.market_type || "").toLowerCase() !== "binary") return null;
    const field = trade.side === "no" ? "no_bid_dollars" : "yes_bid_dollars";
    const price = number(market[field]);
    return price !== null && price >= 0 && price <= 1 ? price : null;
  }

  function renderPaperLedger() {
    const tbody = one("[data-paper-rows]");
    const empty = one("[data-paper-empty]");
    const trades = getPaperTrades();
    if (tbody) tbody.replaceChildren();
    if (empty) setVisible(empty, trades.length === 0);
    let openCount = 0;
    let totalUnrealized = 0;
    let markedCount = 0;
    trades.forEach(trade => {
      const row = make("tr");
      addCell(row, trade.createdAt ? formatTime(trade.createdAt) : "");
      const marketCell = make("td");
      marketCell.appendChild(make("span", "cell-title", trade.eventTitle || trade.ticker));
      marketCell.appendChild(make("span", "cell-subtitle", `${trade.marketTitle || trade.ticker} · ${trade.topic || "Topic unavailable"}`));
      row.appendChild(marketCell);
      addCell(row, trade.strategy || "Unassigned");
      addCell(row, String(trade.side || "").toUpperCase());
      addCell(row, formatContracts(trade.count), "number");
      addCell(row, formatUsd(trade.entryPrice), "number");
      let currentMark = null;
      let pnl = null;
      if (trade.status === "open") {
        openCount += 1;
        currentMark = paperMark(trade);
        if (currentMark !== null) {
          pnl = (currentMark - Number(trade.entryPrice)) * Number(trade.count);
          totalUnrealized += pnl;
          markedCount += 1;
        }
      } else if (isNumber(trade.exitPrice)) {
        currentMark = Number(trade.exitPrice);
        pnl = isNumber(trade.realizedPnl) ? Number(trade.realizedPnl) : null;
      }
      addCell(row, currentMark === null ? "—" : formatUsd(currentMark), "number");
      addCell(row, pnl === null ? "—" : formatUsd(pnl), "number");
      const modeCell = make("td");
      modeCell.appendChild(make("span", "tag warn", trade.status === "open" ? "Paper · open" : "Paper · closed"));
      row.appendChild(modeCell);
      addCell(row, sourceLink(marketUrl(trade.ticker), "Market API"));
      const actionCell = make("td");
      if (trade.status === "open") {
        const close = make("button", "btn-ghost", "Close paper");
        close.type = "button";
        close.dataset.paperCloseId = trade.id;
        if (paperExitQuote(trade) === null) close.disabled = true;
        actionCell.appendChild(close);
      }
      row.appendChild(actionCell);
      if (tbody) tbody.appendChild(row);
    });
    setText("[data-paper-open-count]", String(openCount));
    const pnlElement = one("[data-paper-pnl]");
    if (pnlElement) pnlElement.textContent = openCount === 0 ? "—" : (markedCount === openCount ? formatUsd(totalUnrealized) : "—");
    renderStrategySummaries();
  }

  function closePaperTrade(tradeId) {
    const trades = getPaperTrades();
    const index = trades.findIndex(trade => trade.id === tradeId && trade.status === "open");
    if (index < 0) return;
    const trade = trades[index];
    const exitPrice = paperExitQuote(trade);
    if (exitPrice === null) return;
    trade.exitPrice = exitPrice;
    trade.closedAt = new Date().toISOString();
    trade.realizedPnl = (exitPrice - Number(trade.entryPrice)) * Number(trade.count);
    trade.status = "closed";
    trades[index] = trade;
    setPaperTrades(trades);
    renderPaperLedger();
  }

  function renderStrategySummaries() {
    const tbody = one("[data-strategy-rows]");
    const empty = one("[data-strategy-empty]");
    if (!tbody) return;
    tbody.replaceChildren();
    const trades = getPaperTrades();
    const groups = new Map();
    trades.forEach(trade => {
      const name = trade.strategy || "Unassigned";
      if (!groups.has(name)) groups.set(name, { trades: [], open: 0, realized: 0, unrealized: 0, unrealizedCount: 0 });
      const group = groups.get(name);
      group.trades.push(trade);
      if (trade.status === "open") {
        group.open += 1;
        const mark = paperMark(trade);
        if (mark !== null) {
          group.unrealized += (mark - Number(trade.entryPrice)) * Number(trade.count);
          group.unrealizedCount += 1;
        }
      } else if (isNumber(trade.realizedPnl)) {
        group.realized += Number(trade.realizedPnl);
      }
    });
    if (empty) setVisible(empty, groups.size === 0);
    Array.from(groups.entries()).sort((a, b) => a[0].localeCompare(b[0])).forEach(([name, group]) => {
      const row = make("tr");
      addCell(row, name);
      addCell(row, String(group.trades.length), "number");
      addCell(row, String(group.open), "number");
      addCell(row, formatUsd(group.realized), "number");
      addCell(row, group.open === group.unrealizedCount ? formatUsd(group.unrealized) : "—", "number");
      const sourceCell = make("td");
      sourceCell.appendChild(sourceLink(marketUrl(group.trades[0].ticker), "Paper market data"));
      sourceCell.appendChild(document.createTextNode(" · "));
      sourceCell.appendChild(sourceLink("https://docs.kalshi.com/api-reference/portfolio/get-fills", "Fill fields"));
      row.appendChild(sourceCell);
      tbody.appendChild(row);
    });
  }

  function initSuggestionReviews() {
    const stored = readStorage(STORAGE.suggestionReviews, {});
    all("[data-suggestion-status]").forEach(select => {
      const id = select.dataset.suggestionStatus;
      if (stored[id]) select.value = stored[id];
      select.addEventListener("change", () => {
        const values = readStorage(STORAGE.suggestionReviews, {});
        values[id] = select.value;
        writeStorage(STORAGE.suggestionReviews, values);
      });
    });
  }

  function bindControls() {
    const refresh = one("[data-refresh]");
    if (refresh) refresh.addEventListener("click", () => {
      if (state.page === "markets" || state.page === "portfolio") loadMarketView(true);
      else if (state.page === "resolved") Promise.all([refreshWatchlist(), loadResolvedEvents(true)]);
    });
    const picker = one("[data-market-picker]");
    if (picker) picker.addEventListener("change", () => selectMarket(picker.value));
    const ranking = one("[data-ranking]");
    if (ranking) ranking.addEventListener("change", () => renderEventTable(state.events, state.currentErrors, state.feedConnected));
    all("[data-chart-range]").forEach(button => button.addEventListener("click", () => setRange(button.dataset.chartRange)));
    const eventRows = one("[data-event-rows]");
    if (eventRows) eventRows.addEventListener("click", event => {
      const inspect = event.target.closest("[data-inspect-ticker]");
      if (inspect && inspect.dataset.inspectTicker) {
        const picker = one("[data-market-picker]");
        if (picker) picker.value = inspect.dataset.inspectTicker;
        selectMarket(inspect.dataset.inspectTicker);
        one("[data-chart-title]")?.scrollIntoView({ behavior: "smooth", block: "center" });
        return;
      }
      const track = event.target.closest("[data-track-ticker]");
      if (track) trackEvent(track);
    });
    const watchRows = one("[data-watch-rows]");
    if (watchRows) watchRows.addEventListener("click", event => {
      const remove = event.target.closest("[data-unwatch-ticker]");
      if (remove) removeWatch(remove.dataset.unwatchTicker);
    });
    const paperForm = one("[data-paper-form]");
    if (paperForm) paperForm.addEventListener("submit", submitPaperTrade);
    const paperRows = one("[data-paper-rows]");
    if (paperRows) paperRows.addEventListener("click", event => {
      const close = event.target.closest("[data-paper-close-id]");
      if (close) closePaperTrade(close.dataset.paperCloseId);
    });
    [one("[data-paper-market]"), one("[data-paper-side]"), one("[data-paper-count]")].filter(Boolean).forEach(element => {
      element.addEventListener("change", updatePaperPreview);
      element.addEventListener("input", updatePaperPreview);
    });
    window.addEventListener("resize", drawChart);
  }

  function init() {
    setPageTopicCopy();
    bindControls();
    if (state.page === "home") {
      setFeedStatus("waiting", "Open dashboard to check demo feed");
      return;
    }
    if (state.page === "markets" || state.page === "portfolio") {
      loadMarketView(false);
      state.refreshTimer = window.setInterval(() => {
        if (document.visibilityState === "visible") loadMarketView(true);
      }, EVENT_REFRESH_MS);
      if (state.page === "portfolio") renderPaperLedger();
      return;
    }
    if (state.page === "resolved") {
      renderWatchRows();
      Promise.all([refreshWatchlist(), loadResolvedEvents(false)]);
      state.watchTimer = window.setInterval(() => {
        if (document.visibilityState === "visible") Promise.all([refreshWatchlist(), loadResolvedEvents(true)]);
      }, EVENT_REFRESH_MS);
      return;
    }
    if (state.page === "strategies") {
      renderPaperLedger();
      return;
    }
    if (state.page === "suggestions") initSuggestionReviews();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
