/* Live price-swing alert engine.
 * Observations are made only from the markets returned by the dashboard scan. The
 * first successful observation seeds a baseline; later observations alert at an
 * absolute price change of at least $0.10. This is sampled REST polling, not a
 * continuous feed or a claim that a particular news item caused the move.
 */
(function (root) {
  "use strict";

  var STORAGE_KEY = "kd_swing_alerts_v1";
  var HISTORY_LIMIT = 120;
  var DELTA_THRESHOLD = 0.10;
  var SCREEN_MAX_SPREAD = 0.05;
  var previousByTicker = Object.create(null);
  var history = loadHistory();

  function finite(value) {
    if (value === null || value === undefined || value === "") return null;
    var n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  function validBinaryPrice(value) {
    return value !== null && value >= 0 && value <= 1;
  }

  function observedPrice(market) {
    var bid = finite(market.yb);
    var ask = finite(market.ya);
    if (validBinaryPrice(bid) && validBinaryPrice(ask) && bid <= ask) {
      return { price: (bid + ask) / 2, basis: "YES quote midpoint" };
    }
    var last = finite(market.last);
    if (validBinaryPrice(last)) return { price: last, basis: "last traded price" };
    return null;
  }

  function screen(market) {
    var bid = finite(market.yb);
    var ask = finite(market.ya);
    var volume = finite(market.vol);
    var validQuotes = validBinaryPrice(bid) && validBinaryPrice(ask) && bid <= ask;
    var spread = validQuotes ? ask - bid : null;
    var reason;
    if (!validQuotes) reason = "valid YES bid/ask unavailable";
    else if (spread > SCREEN_MAX_SPREAD + 1e-9) reason = "YES spread wider than 5¢";
    else if (volume === null || volume <= 0) reason = "reported volume is zero or unavailable";
    else reason = "10¢+ move, YES spread ≤5¢, reported volume >0";
    return {
      pass: validQuotes && spread <= SCREEN_MAX_SPREAD + 1e-9 &&
        volume !== null && volume > 0,
      spread: spread,
      reason: reason
    };
  }

  function observe(markets, timestampMs) {
    var now = finite(timestampMs);
    if (now === null) now = Date.now();
    var emitted = [];

    (Array.isArray(markets) ? markets : []).forEach(function (market) {
      if (!market || !market.ticker) return;
      var ticker = String(market.ticker);
      var current = observedPrice(market);
      if (!current) {
        // Do not compare across a gap where no valid price was observed.
        delete previousByTicker[ticker];
        return;
      }
      var previous = previousByTicker[ticker];
      previousByTicker[ticker] = { price: current.price, basis: current.basis, at: now };
      if (!previous || previous.basis !== current.basis) return;

      var delta = current.price - previous.price;
      if (Math.abs(delta) + 1e-9 < DELTA_THRESHOLD) return;

      var screened = screen(market);
      var previousPrice = previous.price;
      emitted.push({
        id: ticker + "|" + now + "|" + previousPrice.toFixed(6) + "|" +
          current.price.toFixed(6),
        ticker: ticker,
        eventTicker: market.event_ticker ? String(market.event_ticker) : "",
        title: String(market.title || ticker),
        topic: String(market.topic || "unclassified"),
        previousPrice: previousPrice,
        currentPrice: current.price,
        delta: delta,
        basis: current.basis,
        elapsedSeconds: Math.max(0, (now - previous.at) / 1000),
        observedAt: new Date(now).toISOString(),
        yesBid: finite(market.yb),
        yesAsk: finite(market.ya),
        spread: screened.spread,
        volume: finite(market.vol),
        openInterest: finite(market.oi),
        sourcePath: "/markets/" + encodeURIComponent(ticker),
        screenPass: screened.pass,
        screenReason: screened.reason
      });
    });

    return emitted;
  }

  function loadHistory() {
    try {
      if (!root.localStorage) return [];
      var raw = root.localStorage.getItem(STORAGE_KEY);
      var parsed = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(parsed)) return [];
      return parsed.filter(function (entry) {
        return entry && typeof entry.id === "string" &&
          typeof entry.ticker === "string" && typeof entry.sourcePath === "string" &&
          Number.isFinite(Number(entry.delta));
      }).slice(0, HISTORY_LIMIT);
    } catch (e) {
      return [];
    }
  }

  function persist() {
    try {
      if (root.localStorage) root.localStorage.setItem(STORAGE_KEY, JSON.stringify(history));
    } catch (e) {
      // The live in-memory feed still works if browser storage is unavailable.
    }
  }

  function append(entries) {
    var ids = Object.create(null);
    history.forEach(function (entry) { ids[entry.id] = true; });
    var fresh = (Array.isArray(entries) ? entries : []).filter(function (entry) {
      if (!entry || typeof entry.id !== "string" || ids[entry.id]) return false;
      ids[entry.id] = true;
      return true;
    });
    if (fresh.length) {
      history = fresh.concat(history).slice(0, HISTORY_LIMIT);
      persist();
    }
    return history.slice();
  }

  function clearHistory() {
    history = [];
    try {
      if (root.localStorage) root.localStorage.removeItem(STORAGE_KEY);
    } catch (e) {
      // In-memory history is still cleared.
    }
    return [];
  }

  function getHistory() {
    return history.slice();
  }

  root.KalshiAlerts = {
    threshold: DELTA_THRESHOLD,
    screenMaxSpread: SCREEN_MAX_SPREAD,
    observe: observe,
    append: append,
    history: getHistory,
    clearHistory: clearHistory
  };
})(typeof window !== "undefined" ? window : globalThis);
