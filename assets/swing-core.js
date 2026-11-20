/* Loader: <script src="assets/swing-core.js"></script> sets window.KalshiSwingCore.
 * Classic script (no ESM) so `node --check` and the repo's verifiers parse it as-is;
 * tests load it in a vm context (tests/swing_core.test.js). */
var KalshiSwingCore = (function () {
  "use strict";

  var BIT = 10000;
  var THRESHOLD_BITS = 1000;   // $0.10 — the owner brief's number
  var REARM_BITS = 500;        // $0.05 — suppresses alert spam on a one-way run

  function toBits(value) {
    if (value === null || value === undefined || value === "") return null;
    var n = typeof value === "number" ? value : parseFloat(value);
    if (!isFinite(n)) return null;
    return Math.round(n * BIT);
  }

  function toDollars(bits, dp) {
    if (bits === null || bits === undefined) return null;
    return Number((bits / BIT).toFixed(dp === undefined ? 4 : dp));
  }

  function clamp01(x) { return x <= 0 ? 0 : (x >= 1 ? 1 : x); }

  /* ------------------------------------------------------------- price model */
  /* Market -> the three fields the alert rule needs (documented on get-markets).
   * `price` = last_price_dollars (last trade); bid/ask = yes_bid_dollars / yes_ask_dollars. */
  function quoteOf(market) {
    if (!market) return null;
    var price = toBits(market.last_price_dollars);
    var bid = toBits(market.yes_bid_dollars);
    var ask = toBits(market.yes_ask_dollars);
    var mid = (bid !== null && ask !== null && ask >= bid) ? Math.round((bid + ask) / 2) : price;
    var spread = (bid !== null && ask !== null && ask >= bid) ? (ask - bid) : null;
    if (price === null && mid === null) return null;
    return {
      price: price, bid: bid, ask: ask, mid: mid, spread: spread,
      reference: toBits(market.previous_price_dollars),
      bidSize: toBitsFixed(market.yes_bid_size_fp),
      askSize: toBitsFixed(market.yes_ask_size_fp),
      volumeFp: toBitsFixed(market.volume_fp),
      volume24hFp: toBitsFixed(market.volume_24h_fp),
      openInterestFp: toBitsFixed(market.open_interest_fp),
    };
  }

  function toBitsFixed(value) {
    if (value === null || value === undefined || value === "") return null;
    var n = typeof value === "number" ? value : parseFloat(value);
    return isFinite(n) ? n : null;
  }

  /* ------------------------------------------------------------ live tracker */
  /**
   * createTracker(windowMinutes, opts) — rolling sample window per market.
   *
   * Rule (identical to the CI backtest scripts/scan_swings.py::detect_swings):
   *   up-alert   when  price - min(price over the trailing window) >= threshold
   *   down-alert when  max(price over the trailing window) - price >= threshold
   * Re-arm: after firing, silence until price returns within `rearm` of the anchor used.
   * Samples older than `windowMinutes` (or `maxAgeMs`, whichever is larger) are dropped.
   */
  function createTracker(windowMinutes, opts) {
    var o = opts || {};
    return {
      // floor is 30 *seconds*, not 30 minutes: Math.max(30, minutes) * 60000 would make a
      // 5-minute selection silently behave like 30 minutes (caught by tests/alert_console.test.js)
      windowMs: Math.max(30 * 1000, (windowMinutes || 10) * 60 * 1000),
      thresholdBits: o.thresholdBits === undefined ? THRESHOLD_BITS : o.thresholdBits,
      rearmBits: o.rearmBits === undefined ? REARM_BITS : o.rearmBits,
      maxSamples: o.maxSamples || 2000,
      series: Object.create(null),
    };
  }

  /**
   * observe(tracker, key, sample) -> alert | null
   * sample: {ts (ms), price (bits), bid, ask, raw (optional market)}
   */
  function observe(tracker, key, sample) {
    // 0 is a legal epoch-ish ts, so an explicit undefined/null check (a falsy test here
    // silently kept the very first sample forever -- caught by tests/swing_core.test.js).
    var ts = (sample.ts === undefined || sample.ts === null) ? Date.now() : sample.ts;
    var price = sample.price;
    if (price === null || price === undefined) return null;
    var st = tracker.series[key];
    if (!st) st = tracker.series[key] = { pts: [], armed: true, anchor: null, fired: null };
    st.pts.push({ ts: ts, price: price, bid: sample.bid === undefined ? null : sample.bid,
                  ask: sample.ask === undefined ? null : sample.ask });
    var cutoff = ts - Math.max(tracker.windowMs, 0);
    while (st.pts.length && st.pts[0].ts < cutoff) st.pts.shift();
    if (st.pts.length > tracker.maxSamples) st.pts.splice(0, st.pts.length - tracker.maxSamples);

    // need at least 2 points, and the window must actually contain a prior point
    if (st.pts.length < 2) return null;
    var prior = st.pts.slice(0, -1).map(function (p) { return p.price; });
    var hi = Math.max.apply(null, prior);
    var lo = Math.min.apply(null, prior);
    var upMove = price - lo;      // rise measured off the window low
    var dnMove = hi - price;      // fall measured off the window high

    if (!st.armed) {
      if (st.anchor !== null && Math.abs(price - st.anchor) <= tracker.rearmBits) {
        st.armed = true; st.anchor = null;
      }
      return null;
    }
    var direction = null, anchor = null, delta = 0;
    if (upMove >= dnMove) {
      if (upMove >= tracker.thresholdBits) { direction = "up"; anchor = lo; delta = upMove; }
    } else if (dnMove >= tracker.thresholdBits) { direction = "down"; anchor = hi; delta = dnMove; }
    if (!direction) return null;
    st.armed = false; st.anchor = anchor;
    var alert = {
      key: key, direction: direction,
      fromBits: anchor, toBits: price, deltaBits: delta,
      from: toDollars(anchor), to: toDollars(price), deltaDollars: toDollars(delta),
      deltaPct: anchor > 0 ? delta / anchor : null,
      ts: ts, bid: sample.bid === undefined ? null : sample.bid,
      ask: sample.ask === undefined ? null : sample.ask,
      windowMinutes: Math.round(tracker.windowMs / 60000),
    };
    st.fired = alert;
    return alert;
  }

  /* ------------------------------------------------------- historical mirror */
  /**
   * detectSwings(series, opts) — same rule applied to a closed candle/price array, so a
   * backtest and the live poller cannot drift. series: [{ts (seconds), price (bits)}].
   */
  function detectSwings(series, opts) {
    var o = opts || {};
    var threshold = o.thresholdBits === undefined ? THRESHOLD_BITS : o.thresholdBits;
    var rearm = o.rearmBits === undefined ? REARM_BITS : o.rearmBits;
    var winMs = Math.max(60000, (o.windowMinutes || 60) * 60 * 1000);
    var out = [];
    var window = [];
    var armed = true, anchor = null;
    for (var i = 0; i < series.length; i++) {
      var pt = series[i];
      var tsMs = (pt.ts || 0) * 1000;
      while (window.length && window[0].ts < tsMs - winMs) window.shift();
      if (window.length) {
        var hi = -Infinity, lo = Infinity;
        for (var j = 0; j < window.length; j++) {
          if (window[j].price > hi) hi = window[j].price;
          if (window[j].price < lo) lo = window[j].price;
        }
        var upMove = pt.price - lo, dnMove = hi - pt.price;
        var leg = upMove >= dnMove ? ["up", lo, upMove] : ["down", hi, dnMove];
        if (!armed) {
          if (anchor !== null && Math.abs(pt.price - anchor) <= rearm) { armed = true; anchor = null; }
        } else if (leg[2] >= threshold) {
          out.push(mkHit(pt, leg[1], leg[0], leg[2], window.length)); armed = false; anchor = leg[1];
        }
      }
      window.push({ ts: tsMs, price: pt.price });
    }
    return out;
  }

  function mkHit(pt, anchor, direction, delta, windowSize) {
    return { ts: pt.ts, direction: direction, fromBits: anchor, toBits: pt.price,
             deltaBits: delta, from: toDollars(anchor), to: toDollars(pt.price),
             deltaDollars: toDollars(delta), deltaPct: anchor > 0 ? delta / anchor : null,
             windowSamples: windowSize };
  }

  /** candlesticks -> series, using price.close_dollars (documented candlestick field). */
  function candleSeries(candlesticks, field) {
    var key = field || "close";
    return (candlesticks || []).slice()
      .sort(function (a, b) { return (a.end_period_ts || 0) - (b.end_period_ts || 0); })
      .map(function (c) {
        var block = (key === "bid") ? c.yes_bid : (key === "ask") ? c.yes_ask : c.price;
        var v = block ? block[key + "_dollars"] : null;
        return { ts: c.end_period_ts, price: toBits(v), raw: c };
      })
      .filter(function (r) { return r.price !== null && r.ts; });
  }

  /* ------------------------------------------------------------- ROI model */
  var PRICE_BANDS = [[0, 500, "0-5c"], [500, 2000, "5-20c"], [2000, 5000, "20-50c"],
                     [5000, 8000, "50-80c"], [8000, 9500, "80-95c"], [9500, 10100, "95-100c"]];
  var MOVE_BANDS = [[1000, 2000, "10-20c"], [2000, 4000, "20-40c"], [4000, Infinity, ">40c"]];
  var TTC_BANDS = [[0, 2, "<2h"], [2, 24, "2-24h"], [24, 336, "1-14d"], [336, Infinity, ">14d"]];

  function bandOf(value, table) {
    if (value === null || value === undefined || !isFinite(value)) return "unclassified";
    for (var i = 0; i < table.length; i++) {
      if (value >= table[i][0] && value < table[i][1]) return table[i][2];
    }
    return "unclassified";
  }

  function bucketKey(topic, fromBits, deltaBits, hoursToClose) {
    return [topic || "unclassified", bandOf(fromBits, PRICE_BANDS),
            bandOf(deltaBits, MOVE_BANDS), bandOf(hoursToClose, TTC_BANDS)].join("|");
  }

  /**
   * roiScore(market, alert, model, now) -> {score, components, pass, reasons, bucket, evidence}
   *
   * Five weighted components, each in [0,1], weights + calibration come from
   * alerts/model.json (produced by scripts/scan_swings.py from live demo candlesticks):
   *   calibrated_edge    what the backtest says a fade is worth in THIS bucket
   *   relative_move      swing size measured against the price it moved from
   *   executability      quoted spread at the moment of the alert
   *   liquidity_depth    contracts standing at the touch (min of bid/ask size)
   *   time_to_resolution log-symmetric around ~6h to close (needs room to revert,
   *                      but theta and information flow hurt very long-dated names)
   * `pass` additionally requires: both sides quoted, a non-empty book at the touch, not an
   * excluded (demo-synthetic / MVE combo) series, and bucket evidence that is sufficient.
   */
  function roiScore(market, alert, model, now) {
    var m = model || {};
    var roi = m.roi_model || {};
    var w = roi.weights || { calibrated_edge: 0.35, relative_move: 0.2, executability: 0.2,
                             liquidity_depth: 0.15, time_to_resolution: 0.1 };
    var q = quoteOf(market) || {};
    var deltaBits = alert.deltaBits !== undefined ? alert.deltaBits : toBits(alert.deltaDollars);
    var fromBits = alert.fromBits !== undefined ? alert.fromBits : toBits(alert.from);
    var closeISO = market && (market.latest_expiration_time || market.close_time ||
                              market.expected_expiration_time);
    var hoursToClose = null;
    if (closeISO) {
      var t = Date.parse(closeISO);
      if (!isNaN(t)) hoursToClose = (t - (now || Date.now())) / 3600000;
    }
    var bucket = bucketKey(market && market.__topic, fromBits, deltaBits, hoursToClose);
    var cal = (roi.buckets || {})[bucket] || null;
    var reasons = [];

    var edge = 0.5, bestNet = null, bestName = null;
    if (cal && cal.evidence === "sufficient") {
      // The backtest measures four exits; the edge is the BEST one this bucket supports,
      // so a bucket where momentum works and fading does not is still a pick (for momentum).
      bestNet = cal.best_mean_net_dollars;
      bestName = cal.best_strategy || "fade60";
      if ((cal.strategies && cal.strategies[bestName]) || bestNet !== null && bestNet !== undefined) {
        // direction only pays if the model takes the side the measured strategy takes
        var wantsUp = bestName.indexOf("momo") === 0;
        var aligned = wantsUp ? alert.direction === "up" : alert.direction === "down" ||
          alert.direction === "up";   // fades work from either side
        if (!aligned) reasons.push(bestName + " is the measured edge but not for this direction");
      }
      var fadeComp = (bestNet === null || bestNet === undefined) ? 0.5 : clamp01(0.5 + bestNet / 0.2);
      var revComp = cal.reversion_rate_shrunk === null || cal.reversion_rate_shrunk === undefined
        ? 0.5 : clamp01(cal.reversion_rate_shrunk);
      edge = clamp01(0.6 * fadeComp + 0.4 * revComp);
      if (bestNet !== null && bestNet !== undefined && bestNet <= 0) {
        reasons.push("no measured strategy has positive expectancy after fees in this bucket (" +
          bestName + " " + (bestNet >= 0 ? "+" : "") + bestNet.toFixed(4) + "$/contract), so this is not a pick");
      } else {
        reasons.push("bucket n=" + cal.n_swings + "/" + cal.n_markets + "m | best=" + bestName +
          " " + (bestNet === null || bestNet === undefined ? "n/a" : (bestNet >= 0 ? "+$" : "-$") +
          Math.abs(bestNet).toFixed(4) + "/contract") + " | reversion<=60m " +
          (cal.reversion_rate * 100).toFixed(0) + "%");
      }
    } else {
      reasons.push(cal ? "bucket evidence insufficient (n=" + cal.n_swings + "/" +
        cal.n_markets + "m)" : "no calibrated bucket for this setup");
    }

    var relMove = (fromBits && fromBits > 0) ? deltaBits / fromBits : (deltaBits / 500);
    var relScore = clamp01(relMove / 2);

    var exec = 0;
    if (q.bid !== null && q.bid !== undefined && q.ask !== null && q.ask !== undefined && q.ask >= q.bid && q.mid > 0) {
      exec = clamp01(1 - (q.spread / q.mid) * 4);
    } else { reasons.push("no two-sided quote"); }

    var depth = Math.min(q.bidSize === null || q.bidSize === undefined ? Infinity : q.bidSize,
                         q.askSize === null || q.askSize === undefined ? Infinity : q.askSize);
    if (!isFinite(depth)) depth = 0;
    var depthScore = clamp01(Math.log(1 + Math.max(0, depth)) / Math.log(1 + 500));
    if (depth <= 0) reasons.push("no size at the touch");

    var ttcScore = 0;
    if (hoursToClose !== null && hoursToClose > 0) {
      ttcScore = clamp01(1 - Math.abs(Math.log(hoursToClose / 6)) / 2.5);
    } else if (hoursToClose !== null && hoursToClose <= 0) {
      reasons.push("market already at/past close time");
    } else { reasons.push("close time unknown"); }

    var score = w.calibrated_edge * edge + w.relative_move * relScore + w.executability * exec +
                w.liquidity_depth * depthScore + w.time_to_resolution * ttcScore;
    score = Math.round(score * 1000) / 1000;

    var excluded = isExcluded(market, roi.excluded_series_prefixes || []);
    if (excluded) reasons.push("excluded series (" + excluded + ") — demo synthetic/combo");
    var hasEdge = bestNet !== null && bestNet !== undefined && bestNet > 0;
    var pass = score >= (roi.pass_threshold_score === undefined ? 0.6 : roi.pass_threshold_score)
      && exec > 0 && depth > 0 && !excluded
      && !!cal && cal.evidence === "sufficient" && hasEdge;

    return {
      score: score, pass: pass, bucket: bucket, evidence: cal ? cal.evidence : "none",
      best_strategy: bestName, best_net_dollars: bestNet, calibrated_edge: r3(edge),
      hoursToClose: hoursToClose === null ? null : Math.round(hoursToClose * 10) / 10,
      components: {
        calibrated_edge: r3(edge), relative_move: r3(relScore), executability: r3(exec),
        liquidity_depth: r3(depthScore), time_to_resolution: r3(ttcScore),
      },
      measured: { spread_dollars: toDollars(q.spread), depth_at_touch: isFinite(depth) ? depth : null,
                  rel_move: r3(relMove) },
      reasons: reasons,
    };
  }

  function r3(x) { return Math.round(x * 1000) / 1000; }

  var FEE_SCALE = 1e10, CENT_SCALE = 1e8;

  /** 0.07 x C x P x (1-P); exact integer numerator over 1e10 dollars (see below). */
  function feeModelDollarsAt(priceBits, contracts) {
    return 7 * contracts * priceBits * (10000 - priceBits) / FEE_SCALE;
  }

  /**
   * Exact integer cent alignment (mirrors scripts/scan_swings.py::_num_units):
   *   dollars * 1e10 = C*Pbits*1e6  +/-  7*C*Pbits*(1e4-Pbits)
   * Buyer's debit aligns UP (ceil to cent), seller's credit aligns DOWN (floor to cent),
   * per https://docs.kalshi.com/getting_started/fee_rounding.md. Guarded so the product
   * stays inside Number.MAX_SAFE_INTEGER (2^53 ~ 9.0e15): C <= 8000 contracts at any price.
   */
  function numUnits(priceBits, contracts, sign) {
    if (!(contracts > 0) || contracts > 8000) {
      throw new Error("fee math guard: contracts must be 1..8000 (got " + contracts + ")");
    }
    return contracts * priceBits * 1e6 + sign * 7 * contracts * priceBits * (10000 - priceBits);
  }

  function buyCostDollars(priceBits, contracts) {
    var n = contracts === undefined ? 100 : contracts;
    return Math.ceil(numUnits(priceBits, n, 1) / CENT_SCALE) / 100;
  }

  function sellProceedsDollars(priceBits, contracts) {
    var n = contracts === undefined ? 100 : contracts;
    return Math.floor(numUnits(priceBits, n, -1) / CENT_SCALE) / 100;
  }

  /** net $ per 1 contract for a block round trip (same definition as the CI backtest). */
  function netRoundTripDollars(buyBits, sellBits, contracts) {
    var n = contracts === undefined ? 100 : contracts;
    var cost = buyCostDollars(buyBits, n);
    var proceeds = sellProceedsDollars(sellBits, n);
    return Math.round(((proceeds - cost) / n) * 1e6) / 1e6;
  }

  function isExcluded(market, prefixes) {
    if (!market) return null;
    var series = market.series_ticker || market.__series || "";
    var ticker = market.ticker || "";
    if (market.mve_collection_ticker) return "mve-combo";
    for (var i = 0; i < (prefixes || []).length; i++) {
      var p = prefixes[i];
      if (p === "KXMVE" && (String(series).indexOf("KXMVE") === 0 || String(ticker).indexOf("KXMVE") === 0)) return p;
      if (p !== "KXMVE" && String(series).indexOf(p) === 0) return p;
    }
    return null;
  }

  /* --------------------------------------------------------------- ranking */
  /** Estimated dollar volume — LABELLED estimate; the API has no dollar-volume field. */
  function estDollarVolume(market) {
    var vol = toBitsFixed(market && market.volume_fp);
    var price = toBits(market && market.last_price_dollars);
    var notional = toBits(market && market.notional_value_dollars);
    if (vol === null) return null;
    var per = notional !== null ? notional : price;
    if (per === null) return null;
    return Math.round(vol * (per / BIT) * 100) / 100;
  }

  /** Topic classifier: same rule table the collector publishes, so ranking is comparable. */
  var TOPIC_PATTERNS = {
    gas: /(^KXGAS|^KXAAAGAS)/i,
    elections: /(^KX(PRES|SENATE|HOUSE|GOV|MAYOR|PRIMARY|ELECTION|FRENCHPRES|NEXT[A-Z]*PRES|POLIT|PARTISAN|NOMD|NATOSECGEN|KNESS|PARL|SYM|MAIDEN|TRUMP|SPEAKER|CONGRESS|SWITZERLAND|AUSTRIA|BRAZIL|FEDRESERVE))/i,
    crypto: /(^KX(BTC|ETH|SOL|XRP|AVAX|DOGE|CRYPTO|BTC|ETH)[A-Z0-9]*$|^KX(BTC|ETH|SOL|XRP|AVAX|DOGE))/i,
    golf: /(^KX(PGA|GOLF|MASTERS|USOPEN|OPENCHAMP|BRITISH|SOLOHEIM|RYDER|TOURCHAMP|GOLFTOUR|GOLFMAJOR))/i,
    culture: /(^KX(TIMEPOY|BOXOFFICE|GRAMMY|EMMY|OSCARS|OSCAR|ALBUM|MOVIE|SHOW|TV|SING|ARTIST|BILLBOARD|NOBEL|GAMING|ESPORT|FILM|STREAK|SQUAD|SPOTIFY|YOUTUBE|SUBSCRIBERS|GTA|MOVIEBOX|SHOWENDS|TIMEPERSON))/i,
  };

  function classify(market) {
    var series = (market && (market.series_ticker || market.__series)) || "";
    var title = (market && (market.event_title || market.title)) || "";
    var keys = Object.keys(TOPIC_PATTERNS);
    for (var i = 0; i < keys.length; i++) {
      if (TOPIC_PATTERNS[keys[i]].test(series)) return keys[i];
    }
    if (/\bgas price/i.test(title)) return "gas";
    if (/\b(nominee|president|election|senate|house of representatives|mayor|prime minister|parliament)\b/i.test(title)) return "elections";
    if (/\b(bitcoin|ethereum|solana|xrp|dogecoin|crypto)\b/i.test(title)) return "crypto";
    if (/\b(mastercard|pga|golf|ryder cup|solheim|the open|us open|majors?)\b/i.test(title)) return "golf";
    if (/\b(album|box office|grammy|emmy|oscars|time person|netflix|spotify|youtube|movie)\b/i.test(title)) return "culture";
    return null;
  }

  return {
    BIT: BIT, THRESHOLD_BITS: THRESHOLD_BITS, REARM_BITS: REARM_BITS,
    toBits: toBits, toDollars: toDollars, clamp01: clamp01,
    quoteOf: quoteOf, createTracker: createTracker, observe: observe,
    detectSwings: detectSwings, candleSeries: candleSeries,
    bucketKey: bucketKey, roiScore: roiScore, isExcluded: isExcluded,
    estDollarVolume: estDollarVolume, classify: classify,
    PRICE_BANDS: PRICE_BANDS, MOVE_BANDS: MOVE_BANDS, TTC_BANDS: TTC_BANDS,
    windowCandlesFor: function (windowMinutes, intervalMinutes) {
      return Math.max(1, Math.round(windowMinutes / Math.max(1, intervalMinutes)));
    },
    /* Fee model — mirrors scripts/scan_swings.py exactly.
     * formula 0.07 x C x P x (1-P): https://kalshi.com/docs/kalshi-fee-schedule.pdf
     * cash aligned to the member's cent grid per
     * https://docs.kalshi.com/getting_started/fee_rounding.md (buyer rounds up, seller down).
     * 100-contract block by default so the cent alignment is realistic, not a rounding bug. */
    feeModelDollars: function (priceBits, contracts) {
      var p = priceBits / BIT;
      return 0.07 * (contracts === undefined ? 100 : contracts) * p * (1 - p);
    },
    buyCostDollars: buyCostDollars,
    sellProceedsDollars: sellProceedsDollars,
    netRoundTripDollars: netRoundTripDollars,
    roundTripFeesDollars: function (buyBits, sellBits, contracts) {
      var n = contracts === undefined ? 100 : contracts;
      var paid = buyCostDollars(buyBits, n) - n * (buyBits / BIT);
      var kept = n * (sellBits / BIT) - sellProceedsDollars(sellBits, n);
      return Math.round((paid + kept) * 1e6) / 1e6;
    },
  };
}());
if (typeof globalThis !== "undefined") { globalThis.KalshiSwingCore = KalshiSwingCore; }
