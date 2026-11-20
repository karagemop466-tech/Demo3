import { FLAGS, QUESTIONS, SOURCES, STRATEGY_FIELDS, SUGGESTIONS, TOPICS } from "./content.js";
import { aggregateEvent, isInResolutionQueue, resolutionDetails, sortEventAggregates } from "./metrics.js";
import { matchingTopics } from "./topics.js";
import { escapeHTML, finiteNumber, formatNumber, formatPrice, formatTimestamp, safeHttpsUrl } from "./utils.js";

const SOURCE_BY_ID = new Map(SOURCES.map((source) => [source.id, source]));

export function sourceLinks(sourceIds = []) {
  return sourceIds.map((id) => {
    const source = SOURCE_BY_ID.get(id);
    if (!source) return "";
    return `<a class="source-ref" href="${escapeHTML(source.url)}" target="_blank" rel="noopener noreferrer" title="${escapeHTML(source.note)}">${escapeHTML(source.id)} ↗</a>`;
  }).filter(Boolean).join(" ");
}

function eventSourceURL(event) {
  const ticker = event?.event_ticker;
  if (ticker) return `https://external-api.demo.kalshi.co/trade-api/v2/events/${encodeURIComponent(ticker)}`;
  const marketTicker = event?.markets?.find((market) => market?.ticker)?.ticker;
  return marketTicker ? `https://external-api.demo.kalshi.co/trade-api/v2/markets/${encodeURIComponent(marketTicker)}` : null;
}

function marketSourceURL(market) {
  if (!market?.ticker) return null;
  return `https://external-api.demo.kalshi.co/trade-api/v2/markets/${encodeURIComponent(market.ticker)}`;
}

function topicBadges(event) {
  const matches = matchingTopics(event);
  if (matches.length === 0) return '<span class="topic-badge topic-neutral">Unmatched</span>';
  return matches.map((topicId) => {
    const topic = TOPICS[topicId];
    return `<span class="topic-badge topic-${escapeHTML(topicId)}">${escapeHTML(topic.short)}</span>`;
  }).join(" ");
}

function aggregateMetric(value, detail) {
  if (finiteNumber(value) === null) {
    return '<span class="unverified-value" aria-label="Value unavailable">—</span><span class="cell-subtitle unverified-label">Unverified</span>';
  }
  return `${formatNumber(value)}<span class="cell-subtitle">${escapeHTML(detail)}</span>`;
}

function verifiedQuote(value, formatter) {
  if (finiteNumber(value) === null) {
    return '<strong class="unverified-value">—</strong><small class="unverified-label">Unverified</small>';
  }
  return `<strong>${formatter(value)}</strong>`;
}

export function renderEventTable(container, events, {
  topicId = null,
  sortMode = "volume",
  search = "",
  statusFilter = "active",
} = {}) {
  if (!container) return { visibleEvents: 0, visibleMarkets: 0 };
  let aggregates = (events ?? []).map((event) => aggregateEvent(event, (market) => statusFilter === "all" || market?.status === statusFilter));
  aggregates = aggregates.filter((row) => row.markets.length > 0 && Boolean(eventSourceURL({ ...row.event, markets: row.markets })));
  if (topicId) aggregates = aggregates.filter((row) => matchingTopics(row.event).includes(topicId));

  const query = String(search ?? "").trim().toLowerCase();
  if (query) {
    aggregates = aggregates.filter(({ event, markets }) => {
      const haystack = [event?.title, event?.sub_title, event?.event_ticker, event?.series_ticker, ...markets.map((market) => `${market?.title ?? ""} ${market?.ticker ?? ""}`)].join(" ").toLowerCase();
      return haystack.includes(query);
    });
  }

  const sorted = sortEventAggregates(aggregates, sortMode);
  const visibleMarkets = sorted.reduce((sum, row) => sum + row.marketCount, 0);

  if (sorted.length === 0) {
    container.innerHTML = '<div class="empty-state"><span class="empty-icon">⌕</span><strong>No matching live events in the returned API data</strong><span>That does not prove the topic has no Kalshi markets. Review the matching rule and current data coverage.</span></div>';
    return { visibleEvents: 0, visibleMarkets: 0 };
  }

  const rows = sorted.map(({ event, markets, marketCount, volume24hContracts, openInterestContracts }) => {
    const href = eventSourceURL({ ...event, markets });
    const eventTicker = event?.event_ticker ?? "";
    const title = event?.title || event?.sub_title || eventTicker || "Untitled event";
    const category = event?.category || "—";
    const topMarket = [...markets].sort((a, b) => (finiteNumber(b?.volume_24h_fp) ?? -1) - (finiteNumber(a?.volume_24h_fp) ?? -1))[0];
    const ticker = topMarket?.ticker || eventTicker;
    const subTitle = event?.sub_title || topMarket?.title || ticker;
    const selectButton = eventTicker
      ? `<button class="table-link-button" type="button" data-select-event="${escapeHTML(eventTicker)}" aria-label="Inspect ${escapeHTML(title)}">${escapeHTML(title)}</button>`
      : `<span class="table-title">${escapeHTML(title)}</span>`;
    const sourceLink = href
      ? `<a class="source-link" href="${escapeHTML(href)}" target="_blank" rel="noopener noreferrer" aria-label="Open official Kalshi API source for ${escapeHTML(title)}">API source ↗</a>`
      : '<span class="muted">Unavailable</span>';
    return `
      <tr>
        <td><div class="topic-badges">${topicBadges(event)}</div><div class="raw-category">${escapeHTML(category)}</div></td>
        <td><div class="table-title-cell">${selectButton}<span class="table-subtitle">${escapeHTML(subTitle)}</span><code>${escapeHTML(ticker)}</code></div></td>
        <td><span class="count-strong">${formatNumber(marketCount, 0)}</span><span class="cell-subtitle">active markets</span></td>
        <td>${aggregateMetric(volume24hContracts, "contracts · 24h")}</td>
        <td>${aggregateMetric(openInterestContracts, "contracts")}</td>
        <td>${sourceLink}</td>
      </tr>
    `;
  }).join("");

  container.innerHTML = `
    <div class="table-scroll">
      <table class="data-table market-table">
        <thead><tr><th scope="col">Topic / API category</th><th scope="col">Event · leading active market</th><th scope="col">Open markets</th><th scope="col">24h volume</th><th scope="col">Open interest</th><th scope="col">Official source</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    <div class="table-note">Event totals sum values from currently active child markets. Volume and open interest are contract counts, not dollars. Missing API values stay blank. Every row links to the official Kalshi demo API record.</div>
  `;
  return { visibleEvents: sorted.length, visibleMarkets };
}

export function renderMarketPicker(container, event, selectedTicker = "") {
  if (!container) return;
  const activeMarkets = Array.isArray(event?.markets) ? event.markets.filter((market) => market?.status === "active") : [];
  if (!activeMarkets.length) {
    container.innerHTML = '<option value="">No active markets</option>';
    return;
  }
  const ordered = [...activeMarkets].sort((a, b) => (finiteNumber(b?.volume_24h_fp) ?? -1) - (finiteNumber(a?.volume_24h_fp) ?? -1));
  container.innerHTML = ordered.map((market) => {
    const title = market?.title || market?.yes_sub_title || market?.ticker;
    const ticker = market?.ticker ?? "";
    const selected = ticker === selectedTicker ? " selected" : "";
    return `<option value="${escapeHTML(ticker)}"${selected}>${escapeHTML(title)} · ${escapeHTML(ticker)}</option>`;
  }).join("");
}

export function renderSelectedMarket(container, event, market) {
  if (!container) return;
  if (!market) {
    container.innerHTML = '<div class="empty-state"><strong>Select an event and market</strong><span>The live quote will appear only after an official demo API response is received.</span></div>';
    return;
  }
  const status = resolutionDetails(market);
  const source = marketSourceURL(market);
  const rules = market?.rules_primary || market?.rules_secondary;
  const safeRules = rules ? `<details class="rules-details"><summary>Contract rules</summary><p>${escapeHTML(rules)}</p></details>` : '<div class="cell-subtitle">Contract rules unavailable in this response.</div>';
  const links = [
    source ? `<a href="${escapeHTML(source)}" target="_blank" rel="noopener noreferrer">Market API ↗</a>` : "",
    event?.event_ticker ? `<a href="${escapeHTML(eventSourceURL(event))}" target="_blank" rel="noopener noreferrer">Event API ↗</a>` : "",
  ].filter(Boolean).join('<span aria-hidden="true">·</span>');
  container.innerHTML = `
    <div class="selected-market-heading">
      <div><span class="eyebrow">Selected contract</span><h3>${escapeHTML(market?.title || market?.yes_sub_title || market?.ticker || "Market")}</h3><code>${escapeHTML(market?.ticker || "")}</code></div>
      <span class="state-pill state-${escapeHTML(status.key)}">${escapeHTML(status.label)}</span>
    </div>
    <div class="quote-grid">
      <div><span>Last YES price</span>${verifiedQuote(market?.last_price_dollars, formatPrice)}</div>
      <div><span>YES bid</span>${verifiedQuote(market?.yes_bid_dollars, formatPrice)}</div>
      <div><span>YES ask</span>${verifiedQuote(market?.yes_ask_dollars, formatPrice)}</div>
      <div><span>24h volume</span>${finiteNumber(market?.volume_24h_fp) === null ? '<strong class="unverified-value">—</strong><small class="unverified-label">Unverified</small>' : `<strong>${formatNumber(market?.volume_24h_fp)} <small>contracts</small></strong>`}</div>
    </div>
    <div class="market-meta"><span>${market?.close_time ? `Closes ${escapeHTML(formatTimestamp(market.close_time, { dateStyle: "medium", timeStyle: "short" }))}` : '<span class="unverified-label">Unverified close time</span>'}</span><span>API result ${escapeHTML(market?.result || "—")}</span></div>
    ${safeRules}
    <div class="source-row">${links}</div>
  `;
}

export function renderOrderbook(container, orderbook, ticker, error = "") {
  if (!container) return;
  if (!ticker) {
    container.innerHTML = '<div class="empty-state compact"><strong>Select a market</strong><span>Price-level availability will appear here.</span></div>';
    return;
  }
  if (error) {
    container.innerHTML = `<div class="empty-state compact error-state" role="alert"><strong>Order book unavailable</strong><span>${escapeHTML(error)} No fallback depth is shown.</span><a class="source-link" href="${escapeHTML(`https://external-api.demo.kalshi.co/trade-api/v2/markets/${encodeURIComponent(ticker)}/orderbook`)}" target="_blank" rel="noopener noreferrer">Official order-book API ↗</a></div>`;
    return;
  }
  if (!orderbook) {
    container.innerHTML = '<div class="empty-state compact"><strong>No order-book levels returned</strong><span>The official endpoint returned no displayed YES or NO bids for this market.</span></div>';
    return;
  }

  const dollarFields = ["yes_dollars", "no_dollars", "yes_dollars_fp", "no_dollars_fp"].some((field) => Array.isArray(orderbook[field]));
  const sides = [
    ["YES bid", orderbook.yes_dollars ?? orderbook.yes_dollars_fp ?? orderbook.yes ?? []],
    ["NO bid", orderbook.no_dollars ?? orderbook.no_dollars_fp ?? orderbook.no ?? []],
  ];
  const levels = sides.flatMap(([side, sourceLevels]) => {
    if (!Array.isArray(sourceLevels)) return [];
    return sourceLevels.map((level) => {
      const rawPrice = Array.isArray(level) ? level[0] : level?.price_dollars ?? level?.price;
      const quantity = Array.isArray(level) ? level[1] : level?.quantity_fp ?? level?.quantity ?? level?.size;
      const numericPrice = finiteNumber(rawPrice);
      return {
        side,
        price: numericPrice === null ? null : (dollarFields ? numericPrice : numericPrice / 100),
        quantity,
      };
    });
  }).sort((a, b) => String(a.side).localeCompare(String(b.side)) || (finiteNumber(b.price) ?? -1) - (finiteNumber(a.price) ?? -1));

  if (!levels.length) {
    container.innerHTML = '<div class="empty-state compact"><strong>No bid levels returned</strong><span>The official API response contained no displayed YES or NO bids for this market.</span></div>';
    return;
  }

  const href = `https://external-api.demo.kalshi.co/trade-api/v2/markets/${encodeURIComponent(ticker)}/orderbook`;
  container.innerHTML = `
    <div class="table-scroll orderbook-scroll">
      <table class="data-table compact-table">
        <thead><tr><th scope="col">Book side</th><th scope="col">Price</th><th scope="col">Contracts available</th><th scope="col">Source</th></tr></thead>
        <tbody>${levels.map((level) => `
          <tr><td><span class="side-label side-${level.side.startsWith("YES") ? "yes" : "no"}">${escapeHTML(level.side)}</span></td><td>${finiteNumber(level.price) === null ? '<span class="unverified-value">—</span><span class="cell-subtitle unverified-label">Unverified</span>' : formatPrice(level.price)}</td><td>${finiteNumber(level.quantity) === null ? '<span class="unverified-value">—</span><span class="cell-subtitle unverified-label">Unverified</span>' : formatNumber(level.quantity)}</td><td><a class="source-link" href="${escapeHTML(href)}" target="_blank" rel="noopener noreferrer">Order book ↗</a></td></tr>
        `).join("")}</tbody>
      </table>
    </div>
    <div class="table-note">The public endpoint reports YES and NO bid levels. Quantities are contracts at that price; no ask-side depth or dollar total is inferred.</div>
  `;
}

export function renderResolutionTable(container, events, topicId = null) {
  if (!container) return { rows: 0 };
  const rows = [];
  const seen = new Set();
  for (const event of events ?? []) {
    if (topicId && !matchingTopics(event).includes(topicId)) continue;
    for (const market of event?.markets ?? []) {
      if (!isInResolutionQueue(market) || !market?.ticker || seen.has(market.ticker)) continue;
      seen.add(market.ticker);
      const state = resolutionDetails(market);
      const href = marketSourceURL(market);
      const eventTitle = event?.title || event?.event_ticker || "Untitled event";
      const rawResult = String(market?.result ?? "").toLowerCase();
      const outcome = state.isYesNoResolved
        ? state.result.toUpperCase()
        : rawResult
          ? `${rawResult.toUpperCase()} · NOT FINAL`
          : "—";
      rows.push({
        time: Date.parse(market?.settlement_ts || market?.close_time || "") || 0,
        html: `
          <tr>
            <td><div class="table-title-cell"><strong>${escapeHTML(eventTitle)}</strong><span class="table-subtitle">${escapeHTML(market?.title || market?.yes_sub_title || market?.ticker)}</span><code>${escapeHTML(market.ticker)}</code></div></td>
            <td><span class="state-pill state-${escapeHTML(state.key)}">${escapeHTML(state.label)}</span></td>
            <td>${escapeHTML(String(outcome).toUpperCase())}</td>
            <td>${market?.settlement_ts || market?.close_time ? escapeHTML(formatTimestamp(market?.settlement_ts || market?.close_time, { dateStyle: "medium", timeStyle: "short" })) : '<span class="unverified-label">Unverified</span>'}</td>
            <td>${href ? `<a class="source-link" href="${escapeHTML(href)}" target="_blank" rel="noopener noreferrer">Market API ↗</a>` : "—"}</td>
          </tr>
        `,
      });
    }
  }
  rows.sort((a, b) => b.time - a.time);
  if (!rows.length) {
    container.innerHTML = '<div class="empty-state"><span class="empty-icon">◷</span><strong>No closed or resolved topic markets in the returned pages</strong><span>Availability depends on current demo data and API pagination. The page does not invent past results.</span></div>';
    return { rows: 0 };
  }
  container.innerHTML = `
    <div class="table-scroll"><table class="data-table">
      <thead><tr><th scope="col">Event / contract</th><th scope="col">Lifecycle</th><th scope="col">API result / finality</th><th scope="col">Close / settlement</th><th scope="col">Official source</th></tr></thead>
      <tbody>${rows.map((row) => row.html).join("")}</tbody>
    </table></div>
    <div class="table-note">Only finalized markets with YES/NO results are labeled YES/NO resolved. Determined, disputed, scalar, and missing results remain distinct.</div>
  `;
  return { rows: rows.length };
}

export function renderSources(container) {
  if (!container) return;
  container.innerHTML = `
    <div class="table-scroll"><table class="data-table">
      <thead><tr><th scope="col">ID</th><th scope="col">Official source</th><th scope="col">Use in this dashboard</th><th scope="col">Link</th></tr></thead>
      <tbody>${SOURCES.map((source) => `
        <tr><td><code>${escapeHTML(source.id)}</code></td><td><strong>${escapeHTML(source.title)}</strong></td><td>${escapeHTML(source.note)}</td><td><a class="source-link" href="${escapeHTML(source.url)}" target="_blank" rel="noopener noreferrer">Open official source ↗</a></td></tr>
      `).join("")}</tbody>
    </table></div>
  `;
}

export function renderQuestions(container) {
  if (!container) return;
  container.innerHTML = `
    <div class="table-scroll"><table class="data-table questions-table">
      <thead><tr><th scope="col">Question</th><th scope="col">What is confirmed</th><th scope="col">Missing information / next check</th><th scope="col">Official evidence</th></tr></thead>
      <tbody>${QUESTIONS.map((item) => `
        <tr><td><strong>${escapeHTML(item.question)}</strong><code>${escapeHTML(item.id)}</code></td><td>${escapeHTML(item.known)}</td><td>${escapeHTML(item.missing)}</td><td><div class="source-list">${sourceLinks(item.sourceIds)}</div></td></tr>
      `).join("")}</tbody>
    </table></div>
  `;
}

export function renderSuggestions(container) {
  if (!container) return;
  const decisions = readReviewDecisions();
  container.innerHTML = SUGGESTIONS.map((item) => {
    const decision = decisions[item.id] ?? "pending";
    const decisionLabel = decision === "preferred" ? "Preferred for review" : decision === "deferred" ? "Deferred" : "Decision pending";
    return `
      <article class="suggestion-card" data-suggestion="${escapeHTML(item.id)}">
        <div class="suggestion-main"><div class="suggestion-id">${escapeHTML(item.id)}</div><div><div class="suggestion-title-row"><h3>${escapeHTML(item.title)}</h3><span class="review-state review-${escapeHTML(decision)}">${escapeHTML(decisionLabel)}</span></div><p>${escapeHTML(item.detail)}</p><div class="suggestion-benefit"><strong>Decision benefit</strong> ${escapeHTML(item.benefit)}</div><div class="source-list">${sourceLinks(item.sourceIds)}</div></div></div>
        <div class="suggestion-actions" aria-label="Review decision for ${escapeHTML(item.title)}">
          <button class="button button-positive" type="button" data-review-decision="preferred" data-review-id="${escapeHTML(item.id)}" aria-pressed="${decision === "preferred"}">Prefer</button>
          <button class="button button-quiet" type="button" data-review-decision="deferred" data-review-id="${escapeHTML(item.id)}" aria-pressed="${decision === "deferred"}">Defer</button>
          <button class="button button-text" type="button" data-review-decision="pending" data-review-id="${escapeHTML(item.id)}" aria-pressed="${decision === "pending"}">Clear</button>
        </div>
      </article>
    `;
  }).join("");
}

export function renderFlags(container) {
  if (!container) return;
  container.innerHTML = `
    <div class="table-scroll"><table class="data-table">
      <thead><tr><th scope="col">Flag</th><th scope="col">Finding / impact</th><th scope="col">Current handling</th><th scope="col">Official source</th></tr></thead>
      <tbody>${FLAGS.map((item) => `
        <tr><td><span class="flag-id">${escapeHTML(item.id)}</span><strong>${escapeHTML(item.title)}</strong></td><td>${escapeHTML(item.detail)}</td><td><span class="review-state review-pending">${escapeHTML(item.state)}</span></td><td><div class="source-list">${sourceLinks(item.sourceIds)}</div></td></tr>
      `).join("")}</tbody>
    </table></div>
  `;
}

export function renderStrategyFields(container) {
  if (!container) return;
  container.innerHTML = `
    <div class="table-scroll"><table class="data-table">
      <thead><tr><th scope="col">Field / category</th><th scope="col">Verified use</th><th scope="col">Official evidence</th></tr></thead>
      <tbody>${STRATEGY_FIELDS.map((item) => `
        <tr><td><strong>${escapeHTML(item.name)}</strong></td><td>${escapeHTML(item.description)}</td><td><div class="source-list">${sourceLinks(item.sourceIds)}</div></td></tr>
      `).join("")}</tbody>
    </table></div>
  `;
}

export function renderSettlementSources(container, event) {
  if (!container) return;
  const sources = Array.isArray(event?.settlement_sources) ? event.settlement_sources : [];
  if (!sources.length) {
    container.innerHTML = '<div class="empty-state compact"><strong>No settlement sources listed in this event response</strong><span>Check the individual contract rules before making a decision.</span></div>';
    return;
  }
  const apiHref = eventSourceURL(event);
  if (!apiHref) {
    container.innerHTML = '<div class="empty-state compact"><strong>Settlement-source record has no verifiable Kalshi event or market ticker</strong><span>No source row is displayed without an official API record link.</span></div>';
    return;
  }
  const rows = sources.map((source) => {
    const url = safeHttpsUrl(source?.url);
    const eventLink = apiHref ? `<a class="source-link" href="${escapeHTML(apiHref)}" target="_blank" rel="noopener noreferrer">Kalshi event API ↗</a>` : '<span class="unverified-label">Unavailable</span>';
    return `<tr><td>${escapeHTML(source?.name || "Unnamed source")}</td><td>${url ? `<a class="source-link" href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">Open listed source ↗</a>` : '<span class="unverified-label">Unverified URL</span>'}</td><td>${eventLink}</td></tr>`;
  }).join("");
  container.innerHTML = `
    <div class="table-scroll"><table class="data-table compact-table"><thead><tr><th scope="col">Settlement source in API</th><th scope="col">Listed source URL</th><th scope="col">Official Kalshi record</th></tr></thead><tbody>${rows}</tbody></table></div>
    ${apiHref ? `<div class="table-note">Source list retrieved from the <a class="source-link" href="${escapeHTML(apiHref)}" target="_blank" rel="noopener noreferrer">official event API ↗</a>. Validate the individual market rules before relying on it.</div>` : ""}
  `;
}

export function setSuggestionDecision(id, decision) {
  if (!id || !["preferred", "deferred", "pending"].includes(decision)) return;
  const decisions = readReviewDecisions();
  if (decision === "pending") delete decisions[id];
  else decisions[id] = decision;
  try {
    localStorage.setItem("kalshi-demo-suggestion-review-v1", JSON.stringify(decisions));
  } catch {
    // The decision is only a local review aid; the page remains usable without storage.
  }
}

function readReviewDecisions() {
  try {
    const value = JSON.parse(localStorage.getItem("kalshi-demo-suggestion-review-v1") || "{}");
    return value && typeof value === "object" ? value : {};
  } catch {
    return {};
  }
}
