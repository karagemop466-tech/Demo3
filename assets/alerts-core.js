/* Kalshi Demo Tracker — swing-alert core (pure functions, no DOM, no network).
 *
 * Price fields in the Kalshi API are dollar strings per contract, e.g. "0.3500" = $0.35
 * (official: https://docs.kalshi.com/api-reference/market/get-markets, fields
 * last_price_dollars / yes_bid_dollars / yes_ask_dollars / volume_fp / result).
 * All comparisons use integer units of $0.0001 (the API's 4-decimal precision), so a
 * $0.10 move is exactly 1000 units and float rounding cannot change a threshold decision.
 *
 * The "high-ROI" screen is a RULE-BASED placeholder (no predictive model exists in this
 * repository). Its thresholds are assumptions and are flagged for owner review.
 */
(function (root) {
  "use strict";

  var UNIT = 10000;             // 1 unit = $0.0001
  var SWING_UNITS = 1000;       // $0.10 — the brief's alert threshold (either direction)
  var ROI_SPREAD_MAX = 200;     // $0.02 — rule-based screen: two-sided quote must be this tight

  function toUnits(v) {
    if (v === null || v === undefined || v === "") return null;
    var n = Number(v);
    if (!isFinite(n)) return null;
    return Math.round(n * UNIT);
  }

  function fmtUnits(u) {
    if (u === null || u === undefined || isNaN(u)) return "—";
    return "$" + (u / UNIT).toFixed(4);
  }

  function fmtDelta(u) {
    if (u === null || u === undefined || isNaN(u)) return "—";
    var sign = u > 0 ? "+" : (u < 0 ? "−" : "±");
    return sign + "$" + (Math.abs(u) / UNIT).toFixed(4);
  }

  /** A swing exists when |current − previous| ≥ threshold (inclusive), in either direction. */
  function swingBetween(prevUnits, curUnits, thresholdUnits) {
    var th = thresholdUnits || SWING_UNITS;
    if (prevUnits === null || prevUnits === undefined || curUnits === null || curUnits === undefined) {
      return null;
    }
    var d = curUnits - prevUnits;
    if (Math.abs(d) < th) return null;
    return { from: prevUnits, to: curUnits, delta: d, dir: d > 0 ? "up" : "down" };
  }

  /** Rule-based ROI screen on a market-like object (prices already in units). */
  function roiScreen(m) {
    var reasons = [];
    if (m.yes_bid === null || m.yes_bid === undefined || m.yes_ask === null || m.yes_ask === undefined) {
      reasons.push("no two-sided quote");
    } else if (m.yes_ask - m.yes_bid > ROI_SPREAD_MAX) {
      reasons.push("spread above $0.02");
    }
    if (!(Number(m.volume) > 0)) reasons.push("no traded volume");
    return { pass: reasons.length === 0, reasons: reasons };
  }

  /**
   * Arithmetic payoff of buying YES at the ask if it settles at $1.00 (notional_value_dollars
   * observed as 1.0000 on binary demo markets), BEFORE fees. Not a probability forecast.
   * Returns a fraction (1.857 = +185.7%) or null when the ask is not strictly inside (0, $1).
   */
  function payoffFraction(askUnits) {
    if (askUnits === null || askUnits === undefined) return null;
    if (askUnits <= 0 || askUnits >= UNIT) return null;
    return (UNIT - askUnits) / askUnits;
  }

  /** Parse JSONL text; malformed lines are skipped and counted. */
  function parseJsonl(text) {
    var rows = [], bad = 0;
    String(text || "").split("\n").forEach(function (line) {
      line = line.trim();
      if (!line) return;
      try { rows.push(JSON.parse(line)); } catch (e) { bad++; }
    });
    return { rows: rows, bad: bad };
  }

  /** Normalize one collector snapshot row (data/history/prices.jsonl) into the common shape. */
  function fromSnapshotRow(r) {
    return {
      ticker: r.ticker,
      topic: r.topic || "",
      ts: r.ts,
      last: toUnits(r.last_price_dollars),
      yes_bid: toUnits(r.yes_bid_dollars),
      yes_ask: toUnits(r.yes_ask_dollars),
      volume: Number(r.volume_fp || 0),
      result: ""
    };
  }

  /** Normalize one live market object from GET /markets. */
  function fromLiveMarket(m, ts) {
    return {
      ticker: m.ticker,
      title: m.title || m.ticker,
      event_ticker: m.event_ticker || "",
      ts: ts,
      last: toUnits(m.last_price_dollars),
      yes_bid: toUnits(m.yes_bid_dollars),
      yes_ask: toUnits(m.yes_ask_dollars),
      volume: Number(m.volume_fp || 0),
      status: m.status || "",
      result: m.result || ""
    };
  }

  /**
   * Swings between consecutive collector snapshots for each ticker (chronological).
   * Each swing carries the interval it spans so the reader sees the 10-minute gap.
   */
  function snapshotSwings(rows, thresholdUnits) {
    var byTicker = {};
    rows.forEach(function (r) {
      if (!r || !r.ticker) return;
      (byTicker[r.ticker] = byTicker[r.ticker] || []).push(fromSnapshotRow(r));
    });
    var out = [];
    Object.keys(byTicker).forEach(function (t) {
      var series = byTicker[t].sort(function (a, b) { return a.ts < b.ts ? -1 : (a.ts > b.ts ? 1 : 0); });
      for (var i = 1; i < series.length; i++) {
        var prev = series[i - 1], cur = series[i];
        var sw = swingBetween(prev.last, cur.last, thresholdUnits);
        if (!sw) continue;
        out.push({
          kind: "swing", source: "snapshot", ticker: t, topic: cur.topic, ts: cur.ts,
          prev_ts: prev.ts, from: sw.from, to: sw.to, delta: sw.delta, dir: sw.dir,
          roi: roiScreen(cur), payoff: payoffFraction(cur.yes_ask), result: ""
        });
      }
    });
    out.sort(function (a, b) { return a.ts < b.ts ? -1 : (a.ts > b.ts ? 1 : 0); });
    return out;
  }

  /**
   * Stateful live tracker. ingest(market) compares each poll with the previous observed price
   * for that ticker. The first observation only sets a baseline (no alert on first sight).
   * Resolution is reported once per ticker when the API result is "yes" or "no".
   */
  function LiveTracker(thresholdUnits) {
    this.threshold = thresholdUnits || SWING_UNITS;
    this.prev = {};
    this.resolved = {};
  }
  LiveTracker.prototype.ingest = function (market, ts) {
    var cur = fromLiveMarket(market, ts);
    var events = [];
    var prev = this.prev[cur.ticker];
    if (prev && cur.last !== null && prev.last !== null) {
      var sw = swingBetween(prev.last, cur.last, this.threshold);
      if (sw) {
        events.push({
          kind: "swing", source: "live", ticker: cur.ticker, title: cur.title,
          event_ticker: cur.event_ticker, ts: ts, prev_ts: prev.ts,
          from: sw.from, to: sw.to, delta: sw.delta, dir: sw.dir,
          roi: roiScreen(cur), payoff: payoffFraction(cur.yes_ask), result: ""
        });
      }
    }
    if ((cur.result === "yes" || cur.result === "no") && !this.resolved[cur.ticker]) {
      this.resolved[cur.ticker] = true;
      events.push({
        kind: "resolved", source: "live", ticker: cur.ticker, title: cur.title,
        event_ticker: cur.event_ticker, ts: ts, result: cur.result
      });
    }
    this.prev[cur.ticker] = cur;
    return events;
  };

  var api = {
    UNIT: UNIT, SWING_UNITS: SWING_UNITS, ROI_SPREAD_MAX: ROI_SPREAD_MAX,
    toUnits: toUnits, fmtUnits: fmtUnits, fmtDelta: fmtDelta,
    swingBetween: swingBetween, roiScreen: roiScreen, payoffFraction: payoffFraction,
    parseJsonl: parseJsonl, snapshotSwings: snapshotSwings, LiveTracker: LiveTracker,
    fromLiveMarket: fromLiveMarket, fromSnapshotRow: fromSnapshotRow
  };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; }
  root.KalshiAlerts = api;
})(typeof window !== "undefined" ? window : globalThis);
