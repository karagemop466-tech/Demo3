export const DEMO_API_BASE = "https://external-api.demo.kalshi.co/trade-api/v2";
export const API_DOCS = "https://docs.kalshi.com";
export const EVENT_DOC = `${API_DOCS}/api-reference/events/get-events`;
export const MARKET_DOC = `${API_DOCS}/api-reference/market/get-market`;
export const ORDERBOOK_DOC = `${API_DOCS}/api-reference/market/get-market-orderbook`;
export const CANDLE_DOC = `${API_DOCS}/api-reference/market/get-market-candlesticks`;
export const DEFAULT_EVENT_PAGE_LIMIT = 200;

const VALID_EVENT_FILTERS = new Set(["open", "closed", "settled"]);

export function eventSourceURL(eventTicker) {
  return `${DEMO_API_BASE}/events/${encodeURIComponent(eventTicker)}`;
}

export function marketSourceURL(marketTicker) {
  return `${DEMO_API_BASE}/markets/${encodeURIComponent(marketTicker)}`;
}

export function orderbookSourceURL(marketTicker) {
  return `${marketSourceURL(marketTicker)}/orderbook`;
}

export function eventsSourceURL(status = "open") {
  const query = new URLSearchParams({
    status,
    with_nested_markets: "true",
    limit: String(DEFAULT_EVENT_PAGE_LIMIT),
  });
  return `${DEMO_API_BASE}/events?${query.toString()}`;
}

export async function requestJSON(url, { signal } = {}) {
  let response;
  try {
    response = await fetch(url, {
      method: "GET",
      mode: "cors",
      credentials: "omit",
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal,
    });
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    throw new Error("Could not reach the Kalshi demo API from this browser. Check network/CORS access; no substitute data was loaded.");
  }

  if (!response.ok) {
    const reason = response.status === 429
      ? "Kalshi demo API rate limit reached. Wait before refreshing."
      : `Kalshi demo API returned HTTP ${response.status}.`;
    throw new Error(reason);
  }

  try {
    return await response.json();
  } catch {
    throw new Error("Kalshi demo API returned an unreadable response. No cached or invented data was loaded.");
  }
}

export async function fetchEventsByStatus(status = "open", {
  cursor = null,
  maxPages = 50,
  signal,
  onPage = () => {},
} = {}) {
  if (!VALID_EVENT_FILTERS.has(status)) {
    throw new Error(`Unsupported event status filter: ${status}`);
  }

  const events = [];
  const seenCursors = new Set();
  let nextCursor = cursor;
  let pages = 0;

  while (pages < maxPages) {
    const params = new URLSearchParams({
      status,
      with_nested_markets: "true",
      limit: String(DEFAULT_EVENT_PAGE_LIMIT),
    });
    if (nextCursor) params.set("cursor", nextCursor);

    const payload = await requestJSON(`${DEMO_API_BASE}/events?${params.toString()}`, { signal });
    if (!Array.isArray(payload.events)) {
      throw new Error("Kalshi demo API response did not contain an events array.");
    }

    events.push(...payload.events);
    pages += 1;
    const returnedCursor = payload.cursor ? String(payload.cursor) : null;
    onPage({ status, pages, received: payload.events.length, total: events.length });

    if (!returnedCursor) {
      nextCursor = null;
      break;
    }
    if (seenCursors.has(returnedCursor) || returnedCursor === nextCursor) {
      throw new Error("Kalshi demo API repeated a pagination cursor; the result is incomplete.");
    }
    seenCursors.add(returnedCursor);
    nextCursor = returnedCursor;
  }

  return {
    events,
    cursor: nextCursor,
    pages,
    complete: nextCursor === null,
  };
}

export async function fetchEvent(eventTicker, options = {}) {
  const params = new URLSearchParams({ with_nested_markets: "true" });
  const payload = await requestJSON(`${eventSourceURL(eventTicker)}?${params.toString()}`, options);
  return payload.event ?? null;
}

export async function fetchMarket(marketTicker, options = {}) {
  const payload = await requestJSON(marketSourceURL(marketTicker), options);
  return payload.market ?? null;
}

export async function fetchOrderbook(marketTicker, options = {}) {
  const payload = await requestJSON(orderbookSourceURL(marketTicker), options);
  return payload.orderbook_fp ?? payload.orderbook ?? null;
}

export async function fetchMarketCandlesticks(seriesTicker, marketTicker, {
  startTs,
  endTs,
  periodInterval,
  signal,
} = {}) {
  if (!seriesTicker || !marketTicker) return [];
  const path = `${DEMO_API_BASE}/series/${encodeURIComponent(seriesTicker)}/markets/${encodeURIComponent(marketTicker)}/candlesticks`;
  const params = new URLSearchParams({
    start_ts: String(startTs),
    end_ts: String(endTs),
    period_interval: String(periodInterval),
  });
  const payload = await requestJSON(`${path}?${params.toString()}`, { signal });
  return Array.isArray(payload.candlesticks) ? payload.candlesticks : [];
}
