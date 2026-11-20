/* Browser-local, automatic paper-strategy experiment.
 * It never calls an order endpoint. Eligible alerts create one simulated YES
 * contract per matching strategy/ticker at the observed YES ask. Resolution is
 * recorded only after GET /markets/{ticker} reports settled/finalized + yes/no.
 */
(function (root) {
  "use strict";

  var STORAGE_KEY = "kd_auto_paper_strategies_v1";
  var TRADE_LIMIT = 500;
  var STRATEGIES = [
    {
      id: "momentum-yes",
      name: "Momentum YES",
      trigger: "Buy YES after a qualifying ≥$0.10 upward move"
    },
    {
      id: "pullback-yes",
      name: "Pullback YES",
      trigger: "Buy YES after a qualifying ≥$0.10 downward move"
    }
  ];
  var trades = loadTrades();

  function finite(value) {
    if (value === null || value === undefined || value === "") return null;
    var n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  function validPrice(price) {
    return price !== null && price > 0 && price < 1;
  }

  function validMark(price) {
    return price !== null && price >= 0 && price <= 1;
  }

  function loadTrades() {
    try {
      if (!root.localStorage) return [];
      var raw = root.localStorage.getItem(STORAGE_KEY);
      var parsed = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(parsed)) return [];
      return parsed.filter(function (trade) {
        return trade && typeof trade.id === "string" &&
          typeof trade.ticker === "string" && typeof trade.strategyId === "string" &&
          Number.isFinite(Number(trade.entryPrice));
      }).slice(-TRADE_LIMIT);
    } catch (e) {
      return [];
    }
  }

  function persist() {
    try {
      if (root.localStorage) {
        trades = trades.slice(-TRADE_LIMIT);
        root.localStorage.setItem(STORAGE_KEY, JSON.stringify(trades));
      }
    } catch (e) {
      // Keep the in-memory simulator usable if storage is disabled or full.
    }
  }

  function processAlerts(alerts) {
    var added = [];
    (Array.isArray(alerts) ? alerts : []).forEach(function (alert) {
      if (!alert || !alert.screenPass || !alert.ticker) return;
      var delta = finite(alert.delta);
      var ask = finite(alert.yesAsk);
      if (delta === null || delta === 0 || !validPrice(ask)) return;

      var strategy = delta > 0 ? STRATEGIES[0] : STRATEGIES[1];
      var duplicateId = strategy.id + "|" + String(alert.id || "");
      if (trades.some(function (trade) { return trade.id === duplicateId; })) return;
      var alreadyOpen = trades.some(function (trade) {
        return trade.strategyId === strategy.id && trade.ticker === String(alert.ticker) &&
          trade.status === "open";
      });
      if (alreadyOpen) return;

      var ticker = String(alert.ticker);
      var record = {
        id: duplicateId,
        ticker: ticker,
        title: String(alert.title || ticker),
        topic: String(alert.topic || "unclassified"),
        strategyId: strategy.id,
        strategyName: strategy.name,
        trigger: strategy.trigger,
        signal: delta > 0 ? "upward move" : "downward move",
        mode: "paper",
        action: "buy",
        side: "yes",
        contracts: 1,
        entryPrice: ask,
        createdAt: String(alert.observedAt || new Date().toISOString()),
        status: "open",
        result: "",
        grossPnl: null,
        markPrice: null,
        markBasis: "",
        unrealizedGrossPnl: null,
        markedAt: "",
        sourcePath: String(alert.sourcePath || "/markets/" + encodeURIComponent(ticker)),
        settlementSourcePath: ""
      };
      trades.push(record);
      added.push(record);
    });
    if (added.length) persist();
    return added.slice();
  }

  function markToMarket(markets, timestampMs) {
    var byTicker = Object.create(null);
    (Array.isArray(markets) ? markets : []).forEach(function (market) {
      if (market && market.ticker) byTicker[String(market.ticker)] = market;
    });
    var now = finite(timestampMs);
    if (now === null) now = Date.now();
    var changed = false;
    trades.forEach(function (trade) {
      if (trade.status !== "open") return;
      var market = byTicker[trade.ticker];
      if (!market) return;
      var bid = finite(market.yb);
      var last = finite(market.last);
      var mark = validMark(bid) ? bid : (validMark(last) ? last : null);
      var basis = validMark(bid) ? "best YES bid" :
        (validMark(last) ? "last traded price" : "");
      if (mark === null) return;
      if (trade.markPrice !== mark || trade.markBasis !== basis) {
        trade.markPrice = mark;
        trade.markBasis = basis;
        trade.unrealizedGrossPnl = (mark - Number(trade.entryPrice)) *
          Number(trade.contracts || 1);
        trade.markedAt = new Date(now).toISOString();
        changed = true;
      }
    });
    if (changed) persist();
    return list();
  }

  function settle(ticker, market, timestampMs) {
    if (!market || typeof ticker !== "string") return 0;
    var status = String(market.status || "").toLowerCase();
    var result = String(market.result || "").toLowerCase();
    if ((status !== "settled" && status !== "finalized") ||
        (result !== "yes" && result !== "no")) return 0;
    var now = finite(timestampMs);
    if (now === null) now = Date.now();
    var changed = 0;
    trades.forEach(function (trade) {
      if (trade.ticker !== ticker || trade.status !== "open") return;
      trade.status = "settled";
      trade.result = result;
      trade.settledAt = new Date(now).toISOString();
      trade.grossPnl = (result === "yes" ? 1 - Number(trade.entryPrice) :
        -Number(trade.entryPrice)) * Number(trade.contracts || 1);
      trade.unrealizedGrossPnl = null;
      trade.markPrice = null;
      trade.markBasis = "settlement result";
      trade.settlementSourcePath = "/markets/" + encodeURIComponent(ticker);
      changed++;
    });
    if (changed) persist();
    return changed;
  }

  function list() {
    return trades.slice().reverse().map(function (trade) {
      return Object.assign({}, trade);
    });
  }

  function openTickers() {
    var seen = Object.create(null);
    return trades.filter(function (trade) {
      if (trade.status !== "open" || seen[trade.ticker]) return false;
      seen[trade.ticker] = true;
      return true;
    }).map(function (trade) { return trade.ticker; });
  }

  function stats() {
    var byStrategy = STRATEGIES.map(function (strategy) {
      return {
        id: strategy.id,
        name: strategy.name,
        trigger: strategy.trigger,
        trades: 0,
        open: 0,
        settled: 0,
        wins: 0,
        losses: 0,
        realizedGrossPnl: 0,
        unrealizedGrossPnl: 0
      };
    });
    var index = Object.create(null);
    byStrategy.forEach(function (row) { index[row.id] = row; });
    trades.forEach(function (trade) {
      var row = index[trade.strategyId];
      if (!row) return;
      row.trades++;
      if (trade.status === "settled") {
        row.settled++;
        var pnl = finite(trade.grossPnl);
        if (pnl !== null) {
          row.realizedGrossPnl += pnl;
          if (pnl > 0) row.wins++;
          else if (pnl < 0) row.losses++;
        }
      } else {
        row.open++;
        var unrealized = finite(trade.unrealizedGrossPnl);
        if (unrealized !== null) row.unrealizedGrossPnl += unrealized;
      }
    });
    return {
      trades: trades.length,
      open: byStrategy.reduce(function (sum, row) { return sum + row.open; }, 0),
      settled: byStrategy.reduce(function (sum, row) { return sum + row.settled; }, 0),
      realizedGrossPnl: byStrategy.reduce(function (sum, row) {
        return sum + row.realizedGrossPnl;
      }, 0),
      unrealizedGrossPnl: byStrategy.reduce(function (sum, row) {
        return sum + row.unrealizedGrossPnl;
      }, 0),
      byStrategy: byStrategy
    };
  }

  function clear() {
    trades = [];
    try {
      if (root.localStorage) root.localStorage.removeItem(STORAGE_KEY);
    } catch (e) {
      // In-memory state is still cleared.
    }
    return [];
  }

  root.KalshiPaperStrategies = {
    strategies: STRATEGIES.map(function (strategy) { return Object.assign({}, strategy); }),
    processAlerts: processAlerts,
    markToMarket: markToMarket,
    settle: settle,
    list: list,
    openTickers: openTickers,
    stats: stats,
    clear: clear
  };
})(typeof window !== "undefined" ? window : globalThis);
