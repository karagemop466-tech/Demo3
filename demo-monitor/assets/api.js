(function (global) {
  "use strict";

  const API_ROOTS = [
    "https://external-api.demo.kalshi.co/trade-api/v2",
    "https://demo-api.kalshi.co/trade-api/v2"
  ];
  const PAGE_SIZE = 200;
  const SERIES_PAGE_SIZE = 100;
  const SERIES_TTL_MS = 15 * 60 * 1000;
  const EVENT_TTL_MS = 45 * 1000;
  const seriesCache = new Map();
  const eventCache = new Map();
  let activeRoot = API_ROOTS[0];

  const TOPICS = {
    gas: {
      label: "Gas prices",
      pageTitle: "Gas prices",
      description: "Open events matched from official series categories, tags, and titles. The Kalshi glossary's US gas-price example uses Economics/Commodities and Oil & Gas-related tags.",
      categories: ["Economics", "Commodities"],
      matches(series) {
        const tags = (Array.isArray(series.tags) ? series.tags : []).map(normalize);
        const title = String(series.title || "");
        if (tags.includes("oil & gas") || tags.includes("oil and energy")) return "official series tag";
        if (/\b(natural gas|gas prices?|gasoline prices?)\b/i.test(title)) return "official series title";
        return "";
      }
    },
    elections: {
      label: "Elections",
      pageTitle: "Elections",
      description: "Open events matched using official Elections category/tag metadata or the official series title. Category membership is taken from Kalshi's series response, not parsed from a ticker.",
      categories: ["Elections"],
      matches(series) {
        const categories = seriesCategories(series).map(normalize);
        const tags = (Array.isArray(series.tags) ? series.tags : []).map(normalize);
        const title = String(series.title || "");
        if (categories.includes("elections") || tags.includes("elections")) return "official Elections metadata";
        if (/\belections?\b/i.test(title)) return "official series title";
        return "";
      }
    },
    culture: {
      label: "Culture / entertainment",
      pageTitle: "Culture / entertainment",
      description: "This site-defined view maps the broad word “culture” to official Entertainment category/tag metadata, with a title match as a fallback. Review this mapping before relying on the category.",
      categories: ["Entertainment"],
      matches(series) {
        const categories = seriesCategories(series).map(normalize);
        const tags = (Array.isArray(series.tags) ? series.tags : []).map(normalize);
        const title = String(series.title || "");
        if (categories.includes("entertainment") || categories.includes("culture") || tags.includes("entertainment") || tags.includes("culture")) return "official category/tag; site mapping";
        if (/\b(culture|entertainment)\b/i.test(title)) return "official series title; site mapping";
        return "";
      }
    },
    crypto: {
      label: "Crypto",
      pageTitle: "Crypto",
      description: "Open events matched from Kalshi's exact Crypto series category/tag metadata. Returned category and series fields remain visible in the event rows.",
      categories: ["Crypto"],
      matches(series) {
        const categories = seriesCategories(series).map(normalize);
        const tags = (Array.isArray(series.tags) ? series.tags : []).map(normalize);
        if (categories.includes("crypto") || tags.includes("crypto")) return "official Crypto category/tag";
        return "";
      }
    },
    golf: {
      label: "Golf",
      pageTitle: "Golf",
      description: "Open events matched from official Sports series with a Golf tag or title. A row appears only when the returned Kalshi metadata provides that match.",
      categories: ["Sports"],
      matches(series) {
        const categories = seriesCategories(series).map(normalize);
        const tags = (Array.isArray(series.tags) ? series.tags : []).map(normalize);
        const title = String(series.title || "");
        if (categories.includes("sports") && (tags.includes("golf") || /\bgolf\b/i.test(title))) return "official Sports series metadata";
        return "";
      }
    }
  };

  function normalize(value) {
    return String(value == null ? "" : value).trim().toLowerCase();
  }

  function seriesCategories(series) {
    if (Array.isArray(series.categories) && series.categories.length) return series.categories;
    return series.category ? [series.category] : [];
  }

  function apiUrl(path, params, root) {
    const url = new URL((root || activeRoot) + path);
    Object.entries(params || {}).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, String(value));
    });
    return url.toString();
  }

  async function fetchFromRoot(root, path, params) {
    const controller = new AbortController();
    const timeout = global.setTimeout(() => controller.abort(), 15000);
    try {
      const response = await global.fetch(apiUrl(path, params, root), {
        method: "GET",
        headers: { Accept: "application/json" },
        cache: "no-store",
        credentials: "omit",
        signal: controller.signal
      });
      if (!response.ok) {
        const error = new Error(`Kalshi demo API returned HTTP ${response.status}`);
        error.status = response.status;
        throw error;
      }
      const body = await response.json();
      activeRoot = root;
      return body;
    } finally {
      global.clearTimeout(timeout);
    }
  }

  async function get(path, params) {
    let lastError = null;
    for (let index = 0; index < API_ROOTS.length; index += 1) {
      const root = index === 0 ? activeRoot : API_ROOTS.find(item => item !== activeRoot) || API_ROOTS[index];
      try {
        return await fetchFromRoot(root, path, params);
      } catch (error) {
        lastError = error;
        const isClientError = Number.isInteger(error.status) && error.status >= 400 && error.status < 500;
        if (isClientError || index === API_ROOTS.length - 1) break;
      }
    }
    const message = lastError && lastError.name === "AbortError"
      ? "Kalshi demo API request timed out."
      : (lastError && lastError.message) || "Kalshi demo API could not be reached from this browser.";
    throw new Error(`${message} Both published demo hosts were attempted where applicable.`);
  }

  function directUrl(path, params) {
    return apiUrl(path, params, activeRoot);
  }

  async function paged(path, params, key, pageSize) {
    const values = [];
    let cursor = "";
    const seen = new Set();
    const limit = pageSize || PAGE_SIZE;
    for (let page = 0; page < 200; page += 1) {
      const response = await get(path, { ...params, limit, cursor });
      if (!response || !Array.isArray(response[key])) {
        throw new Error(`Unexpected response schema from ${path}; no ${key} array was returned.`);
      }
      values.push(...response[key]);
      const next = response.cursor || "";
      if (!next) return values;
      if (seen.has(next)) throw new Error(`Repeated pagination cursor from ${path}; stopping to avoid a loop.`);
      seen.add(next);
      cursor = next;
    }
    throw new Error(`Pagination exceeded the safety limit while reading ${path}.`);
  }

  async function seriesForCategory(category) {
    const cached = seriesCache.get(category);
    if (cached && Date.now() - cached.at < SERIES_TTL_MS) return cached.values;
    const values = await paged("/series", { category }, "series", SERIES_PAGE_SIZE);
    seriesCache.set(category, { at: Date.now(), values });
    return values;
  }

  async function eventsForSeries(series, status, force) {
    const cacheKey = `${status}:${series.ticker}`;
    const cached = eventCache.get(cacheKey);
    if (!force && cached && Date.now() - cached.at < EVENT_TTL_MS) return cached.values;
    const values = await paged("/events", {
      status,
      series_ticker: series.ticker,
      with_nested_markets: "true"
    }, "events", PAGE_SIZE);
    eventCache.set(cacheKey, { at: Date.now(), values });
    return values;
  }

  async function mapPool(items, concurrency, callback) {
    const results = new Array(items.length);
    let nextIndex = 0;
    const workers = Array.from({ length: Math.min(concurrency, items.length) }, async () => {
      while (true) {
        const index = nextIndex;
        nextIndex += 1;
        if (index >= items.length) return;
        try {
          results[index] = { value: await callback(items[index], index) };
        } catch (error) {
          results[index] = { error };
        }
      }
    });
    await Promise.all(workers);
    return results;
  }

  async function loadTopic(topicKey, status, force) {
    const topic = TOPICS[topicKey];
    if (!topic) return { topicKey, series: [], events: [], errors: [new Error(`Unknown topic: ${topicKey}`)], queried: false };
    const categoryResults = await Promise.all(topic.categories.map(async category => {
      try {
        return { category, values: await seriesForCategory(category) };
      } catch (error) {
        return { category, error };
      }
    }));
    const errors = categoryResults.filter(result => result.error).map(result => new Error(`${result.category}: ${result.error.message}`));
    const seriesMap = new Map();
    categoryResults.forEach(result => {
      (result.values || []).forEach(series => {
        if (series && series.ticker) seriesMap.set(series.ticker, series);
      });
    });
    const matchedSeries = Array.from(seriesMap.values()).map(series => ({
      ...series,
      _topicMatch: topic.matches(series)
    })).filter(series => series._topicMatch);

    const eventResults = await mapPool(matchedSeries, 4, series => eventsForSeries(series, status, force));
    const events = [];
    eventResults.forEach((result, index) => {
      if (result.error) {
        errors.push(new Error(`${matchedSeries[index].ticker}: ${result.error.message}`));
        return;
      }
      (result.value || []).forEach(event => {
        events.push({ ...event, _series: matchedSeries[index], _topicKey: topicKey, _topicLabel: topic.label, _topicMatch: matchedSeries[index]._topicMatch });
      });
    });

    const byTicker = new Map();
    events.forEach(event => {
      const key = event.event_ticker || `${event.series_ticker || ""}:${event.title || ""}`;
      if (!byTicker.has(key)) {
        byTicker.set(key, event);
      } else {
        const current = byTicker.get(key);
        current._topicLabels = Array.from(new Set([...(current._topicLabels || [current._topicLabel]), event._topicLabel]));
      }
    });
    const uniqueEvents = Array.from(byTicker.values());
    const categoryComplete = categoryResults.every(result => !result.error);
    const eventComplete = eventResults.every(result => !result.error);
    const queried = categoryResults.some(result => !result.error) && (matchedSeries.length === 0 || eventResults.some(result => !result.error));
    return { topicKey, series: matchedSeries, events: uniqueEvents, errors, queried, complete: categoryComplete && eventComplete };
  }

  async function loadTopics(topicKeys, status, force) {
    const keys = topicKeys && topicKeys.length ? topicKeys : Object.keys(TOPICS);
    const results = await Promise.all(keys.map(key => loadTopic(key, status, force)));
    const byTicker = new Map();
    results.forEach(result => {
      result.events.forEach(event => {
        const key = event.event_ticker || `${event.series_ticker || ""}:${event.title || ""}`;
        if (!byTicker.has(key)) {
          event._topicLabels = event._topicLabels || [event._topicLabel];
          byTicker.set(key, event);
        } else {
          const current = byTicker.get(key);
          current._topicLabels = Array.from(new Set([...(current._topicLabels || [current._topicLabel]), ...(event._topicLabels || [event._topicLabel])]));
        }
      });
    });
    return {
      results,
      events: Array.from(byTicker.values()),
      errors: results.flatMap(result => result.errors),
      queried: results.some(result => result.queried),
      complete: results.length > 0 && results.every(result => result.complete)
    };
  }

  global.KalshiAPI = {
    API_ROOTS,
    TOPICS,
    get,
    paged,
    loadTopic,
    loadTopics,
    directUrl,
    seriesCategories
  };
})(window);
