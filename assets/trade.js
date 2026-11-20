/* Kalshi Demo Tracker — trade execution (live + paper), journal, categorization,
 * strategy analysis. Paper mode is the default and is labeled everywhere; it sends
 * nothing to Kalshi. Live mode requires a demo API key (see dashboard panel).
 * Order endpoint: POST /trade-api/v2/portfolio/events/orders
 *   — https://docs.kalshi.com/api-reference/orders/create-order-v2
 * Signing: timestamp + method + path (full path, no query) — KalshiDemo.Auth.
 */
(function () {
  "use strict";
  var K = window.KalshiDemo;
  var $ = function (id) { return document.getElementById(id); };
  var FILL_KEY = "kd_fills_v1", JOURNAL_KEY = "kd_journal", AUTO_KEY = "kd_automation_v1";

  function load(key, def) {
    try { return JSON.parse(localStorage.getItem(key) || "null") || def; }
    catch (e) { return def; }
  }
  function save(key, val) {
    try { localStorage.setItem(key, JSON.stringify(val)); } catch (e) { /* quota */ }
  }
  var VALID_STRATEGIES = ["momentum", "mean_reversion", "breakout"];
  function normalizeAuto(a) {
    a = a || {};
    // Backward-compatible: an older persisted "rule" becomes "strategy".
    if (!a.strategy && a.rule) a.strategy = a.rule;
    if (VALID_STRATEGIES.indexOf(a.strategy) === -1) a.strategy = "momentum";
    a.maxPerDay = Number(a.maxPerDay) || 20;
    a.fired = Number(a.fired) || 0;
    return a;
  }

  var Trade = {
    fills: load(FILL_KEY, []),
    journal: load(JOURNAL_KEY, []),
    live: false,
    /* Automation runs in paper/SIMULATED mode only and is OFF by default.
     * It is a mechanism demo, not a verified strategy: no model is defined in
     * this repo, so nothing here is presented as profitable or as ROI.
     * strategy is the paper rule applied on each swing signal:
     *   momentum       — trade in the direction of the swing
     *   mean_reversion — trade against the swing (expect reversion)
     *   breakout       — trade with the swing, only when it is large (>= $0.20) */
    automation: normalizeAuto(load(AUTO_KEY, { enabled: false, strategy: "momentum",
      rule: "momentum", maxPerDay: 20, fired: 0, day: "" })),

    /* ---------- ticket ---------- */
    mountTicket: function (el, opts) {
      if (!el) return;
      opts = opts || {};
      el.innerHTML =
        "<p><label>Ticker <input id='tradeTicker' size='26' class='mono'></label> " +
        "<label>Side <select id='tradeSide'><option value='yes'>YES</option>" +
        "<option value='no'>NO</option></select></label> " +
        "<label>Action <select id='tradeAction'><option value='buy'>Buy</option>" +
        "<option value='sell'>Sell</option></select></label> " +
        "<label>Contracts <input id='tradeCount' type='number' min='1' value='10'></label> " +
        "<label>Limit price (¢) <input id='tradePrice' type='number' min='1' max='99' step='0.1' value='50'></label> " +
        "<label>TIF <select id='tradeTif'><option value='gtc'>GTC</option>" +
        "<option value='ioc'>IOC</option><option value='fok'>FOK</option></select></label> " +
        "<label>Role <select id='tradeRole'><option value='taker'>Taker (cross spread)</option>" +
        "<option value='maker'>Maker (post only)</option></select></label></p>" +
        "<p><label><input type='checkbox' id='tradePostOnly'> Post-only (maker)</label> " +
        "<button class='btn' id='placeOrderBtn'>Place order</button> " +
        "<label>Cancel order ID <input id='cancelOrderId' size='16' class='mono'></label> " +
        "<button class='btn secondary' id='cancelOrderBtn'>Cancel</button></p>" +
        "<p class='small muted'>Paper mode fills instantly at the limit price (labeled SIMULATED). " +
        "Live mode sends the order to the Kalshi demo exchange — a 201 means accepted, not " +
        "necessarily filled. Sources: " +
        "<a href='https://docs.kalshi.com/api-reference/orders/create-order-v2' target='_blank' rel='noopener'>Create Order V2</a> · " +
        "<a href='https://docs.kalshi.com/api-reference/orders/cancel-order-v2' target='_blank' rel='noopener'>Cancel Order V2</a>.</p>";
      var place = $("placeOrderBtn");
      if (place) place.addEventListener("click", function () { Trade.place(); });
      var cancel = $("cancelOrderBtn");
      if (cancel) cancel.addEventListener("click", function () { Trade.cancel(); });
    },

    _ticketBody: function () {
      return {
        ticker: ($("tradeTicker") || {}).value || "",
        side: ($("tradeSide") || {}).value || "yes",
        action: ($("tradeAction") || {}).value || "buy",
        count: Number(($("tradeCount") || {}).value || 0),
        priceCents: Number(($("tradePrice") || {}).value || 0),
        tif: ($("tradeTif") || {}).value || "gtc",
        post_only: !!(($("tradePostOnly") || {}).checked),
        role: ($("tradeRole") || {}).value || "taker"
      };
    },

    result: function (kind, msg) {
      var el = $("tradeResult");
      if (el) el.innerHTML = "<div class='" + (kind || "ok") + "'>" + msg + "</div>";
    },

    place: async function () {
      var b = Trade._ticketBody();
      if (!b.ticker || !b.count || !b.priceCents) {
        Trade.result("error", "<strong>Ticker, contracts and price are required.</strong>");
        return;
      }
      var price = b.priceCents / 100;
      if (price <= 0 || price >= 1) {
        Trade.result("error", "<strong>Price must be between 0 and 100 cents.</strong>");
        return;
      }
      if (Trade.live && K.Auth && K.Auth.keyId) {
        var body = {
          ticker: b.ticker,
          action: b.action,
          side: b.side,
          count: b.count,
          type: "limit",
          yes_price: Math.round(b.priceCents * 100),   // API expects cents in V1; V2 uses dollars fields
          price: price,
          time_in_force: b.tif,
          self_trade_prevention_type: "taker_at_cross",
          post_only: b.post_only
        };
        try {
          var res = await K.Auth.request("POST", "/portfolio/events/orders", {}, body);
          Trade.journal.push({ ts: Math.floor(Date.now() / 1000), kind: "live-order",
            body: b, response: res });
          save(JOURNAL_KEY, Trade.journal);
          Trade.result("ok", "<strong>Order accepted by the demo exchange (201 = accepted, " +
            "not necessarily filled).</strong> " + K.esc(JSON.stringify(res)));
          if ($("portfolioBody")) { try { await refreshLivePortfolio(); } catch (e) { /* */ } }
          Trade.renderAll();
        } catch (e) {
          Trade.result("error", "<strong>Live order failed:</strong> " + K.esc(e.message || e));
        }
        return;
      }
      // Paper mode — simulated fill at the limit price against live quotes (labeled).
      var fill = Trade._addPaperFill(b, false);
      Trade.result("ok", "<strong>SIMULATED fill (paper mode)</strong> — " +
        esc(b.action + " " + b.count + " × " + b.side.toUpperCase() + " @ " + b.priceCents + "¢ " + b.ticker) +
        ". Nothing was sent to Kalshi. Connect a demo key for live execution.");
      Trade.renderAll();
    },

    cancel: async function () {
      var id = (($("cancelOrderId") || {}).value || "").trim();
      if (!id) { Trade.result("error", "Enter an order ID to cancel."); return; }
      if (Trade.live && K.Auth && K.Auth.keyId) {
        try {
          var ticker = (($("tradeTicker") || {}).value || "").trim();
          await K.Auth.request("DELETE", "/portfolio/events/orders/" + encodeURIComponent(id),
            { market_ticker: ticker });
          Trade.result("ok", "<strong>Cancel sent.</strong> " + esc(id));
        } catch (e) {
          Trade.result("error", "Cancel failed: " + K.esc(e.message || e));
        }
      } else {
        Trade.result("ok", "<strong>Paper mode:</strong> no server-side order exists to cancel " +
          "(simulated fills are immediate).");
      }
    },

    /* ---------- automated simulated trades (paper only) ---------- */
    setAutomation: function (on) {
      this.automation.enabled = !!on;
      save(AUTO_KEY, this.automation);
      this.renderAll();
      return this.automation.enabled;
    },
    setStrategy: function (s) {
      if (VALID_STRATEGIES.indexOf(s) === -1) return this.automation.strategy;
      this.automation.strategy = s;
      save(AUTO_KEY, this.automation);
      this.renderAll();
      return this.automation.strategy;
    },
    _addPaperFill: function (b, automated) {
      var price = b.priceCents / 100;
      var fill = {
        id: (automated ? "A" : "P") + Date.now(), ts: Math.floor(Date.now() / 1000),
        ticker: b.ticker, side: b.side, action: b.action,
        count: b.count, price: price, role: b.post_only ? "maker" : b.role,
        mode: "paper", fee: 0, result: "", automated: !!automated,
        strategy: b.strategy || "manual"
      };
      Trade.fills.push(fill);
      save(FILL_KEY, Trade.fills);
      Trade.journal.push({ ts: fill.ts, kind: automated ? "auto-paper-fill" : "paper-fill",
        body: b, response: { fill_id: fill.id, automated: !!automated } });
      save(JOURNAL_KEY, Trade.journal);
      return fill;
    },
    onSwingAlert: function (alert) {
      // Entry point called by alerts.js when a >= $0.10 swing fires.
      // Paper/SIMULATED only. Direction depends on the chosen strategy
      // (unverified paper rules, labeled everywhere).
      var a = this.automation;
      if (!a || !a.enabled) return;
      var today = new Date().toISOString().slice(0, 10);
      if (a.day !== today) { a.day = today; a.fired = 0; }
      if (a.fired >= (a.maxPerDay || 20)) return;
      var strat = a.strategy || "momentum";
      var up = alert.dir === "up", down = alert.dir === "down";
      // breakout only acts on large swings (>= $0.20); the rest trade the signal.
      var large = Math.abs(Number(alert.change)) >= 0.20 - 1e-9;
      var withMove, againstMove;
      if (strat === "mean_reversion") { withMove = !up && !down; againstMove = (up || down); }
      else { withMove = (up || down); againstMove = false; }
      if (strat === "breakout" && !large) return;
      var action;
      if (withMove) action = up ? "buy" : "sell";
      else if (againstMove) action = up ? "sell" : "buy";
      else return;
      var b = {
        ticker: alert.ticker, side: "yes", action: action,
        count: 10, priceCents: Math.round(alert.newPrice * 100),
        tif: "ioc", post_only: false, role: "taker"
      };
      var fill = this._addPaperFill(b, true);
      fill.strategy = strat;
      a.fired += 1;
      save(AUTO_KEY, this.automation);
      this.renderAll();
    },
    automationStatus: function () {
      var a = this.automation || {};
      return { enabled: !!a.enabled, strategy: a.strategy || "momentum",
        fired: a.fired || 0, maxPerDay: a.maxPerDay || 20 };
    },

    /* ---------- analysis ---------- */
    markResolutions: function (resolutions) {
      // resolutions: [{ticker, result, ...}] with result 'yes' | 'no'
      var byT = {};
      (resolutions || []).forEach(function (r) {
        if (r && r.ticker && r.result) byT[r.ticker] = String(r.result).toLowerCase();
      });
      var changed = false;
      Trade.fills.forEach(function (f) {
        if (!f.result && byT[f.ticker]) { f.result = byT[f.ticker]; changed = true; }
      });
      if (changed) save(FILL_KEY, Trade.fills);
    },

    pnl: function (f) {
      // binary contract: buy side X at p -> settle X: (1-p)*count, else -p*count; sell inverts
      if (!f.result) return null;
      var win = f.result === f.side;
      var per = win ? (1 - f.price) : -f.price;
      return (f.action === "sell" ? -per : per) * f.count - (f.fee || 0);
    },

    perf: function () {
      var staked = 0, realized = 0, wins = 0, losses = 0, open = 0, fees = 0;
      Trade.fills.forEach(function (f) {
        staked += f.price * f.count;
        fees += f.fee || 0;
        var p = Trade.pnl(f);
        if (p === null) open++;
        else {
          realized += p;
          if (p > 0) wins++; else losses++;
        }
      });
      return { fills: Trade.fills.length, staked: staked, realized: realized,
        wins: wins, losses: losses, open: open, fees: fees,
        winRate: (wins + losses) ? wins / (wins + losses) : null };
    },

    categories: function () {
      var rows = {};
      Trade.fills.forEach(function (f) {
        var band = f.price < 0.3 ? "cheap (<30¢)" : (f.price <= 0.7 ? "mid (30–70¢)" : "expensive (>70¢)");
        var strat = f.strategy ? f.strategy + " · " : "";
        var key = (f.topic || topicOf(f.ticker)) + " · " + f.side.toUpperCase() + " · " +
          band + " · " + f.role + (strat ? " · " + strat : "");
        var r = rows[key] || (rows[key] = { key: key, fills: 0, contracts: 0, fees: 0,
          pnl: 0, wins: 0, losses: 0 });
        r.fills++;
        r.contracts += f.count;
        r.fees += f.fee || 0;
        var p = Trade.pnl(f);
        if (p !== null) {
          r.pnl += p;
          if (p > 0) r.wins++; else r.losses++;
        }
      });
      return Object.keys(rows).map(function (k) { return rows[k]; })
        .sort(function (a, b) { return b.fills - a.fills; });
    },

    strategyNotes: function () {
      var notes = [];
      var cats = Trade.categories();
      var perf = Trade.perf();
      if (!Trade.fills.length) {
        notes.push("No trades recorded yet. Use the ticket (paper mode works without credentials) " +
          "or connect a demo key. Evidence: https://docs.kalshi.com/getting_started/demo_env");
        return notes;
      }
      cats.forEach(function (c) {
        var tot = c.wins + c.losses;
        if (tot >= 3) {
          if (c.pnl > 0) notes.push("Candidate strategy: keep <strong>" + K.esc(c.key) +
            "</strong> — positive realized P&amp;L " + K.money(c.pnl) + " over " + tot +
            " settled fills (win rate " + Math.round(100 * c.wins / tot) + "%).");
          else notes.push("Review <strong>" + K.esc(c.key) + "</strong> — realized P&amp;L " +
            K.money(c.pnl) + " over " + tot + " settled fills. Consider smaller size or " +
            "tighter entry (see Suggestions page before changing anything).");
        }
      });
      if (perf.winRate !== null && (perf.wins + perf.losses) >= 5) {
        notes.push("Overall win rate " + Math.round(100 * perf.winRate) + "% over " +
          (perf.wins + perf.losses) + " settled fills; realized P&amp;L " +
          K.money(perf.realized) + " on " + K.money(perf.staked) + " staked.");
      }
      notes.push("Demo prices may not reflect real markets — validate any strategy against " +
        "historical data before production: https://docs.kalshi.com/getting_started/demo_env");
      return notes;
    },

    /* ---------- rendering (shared by dashboard / portfolio / trades pages) ---------- */
    renderPerf: function () {
      var el = $("perfSummary");
      if (!el) return;
      var p = Trade.perf();
      el.innerHTML = "<div class='grid'>" +
        card("Mode", Trade.live ? "LIVE (demo exchange)" : "PAPER (simulated)") +
        card("Fills", String(p.fills)) +
        card("Staked", K.money(p.staked)) +
        card("Realized P&amp;L", K.money(p.realized)) +
        card("Win rate", p.winRate === null ? "—" : Math.round(100 * p.winRate) + "%") +
        card("Settled / open", (p.wins + p.losses) + " / " + p.open) +
        "</div><p class='small muted'>P&amp;L for binary contracts: buy side X at price p, " +
        "settle X → + (1−p) × contracts; else −p × contracts. Source: " +
        "<a href='https://docs.kalshi.com/getting_started/market_settlement' target='_blank' rel='noopener'>Market settlement</a>.</p>";
      function card(label, val) {
        return "<div class='card'><div class='muted'>" + label + "</div><div class='stat'>" +
          val + "</div></div>";
      }
    },

    renderStrategy: function () {
      var el = $("strategyBody");
      if (!el) return;
      var cats = Trade.categories();
      var html = "<table><thead><tr><th>Category (topic · side · band · role)</th>" +
        "<th class='num'>Fills</th><th class='num'>Contracts</th><th class='num'>Fees</th>" +
        "<th class='num'>Wins</th><th class='num'>Losses</th><th class='num'>Realized P&amp;L</th>" +
        "</tr></thead><tbody>";
      if (!cats.length) {
        html += "<tr><td colspan='7' class='muted'>No fills yet — place a paper trade from " +
          "<a href='trades.html'>Trades</a> or the dashboard ticket.</td></tr>";
      }
      cats.forEach(function (c) {
        html += "<tr><td>" + K.esc(c.key) + "</td><td class='num'>" + c.fills + "</td>" +
          "<td class='num'>" + K.num(c.contracts, 0) + "</td><td class='num'>" +
          K.num(c.fees, 2) + "</td><td class='num'>" + c.wins + "</td><td class='num'>" +
          c.losses + "</td><td class='num'>" + K.money(c.pnl) + "</td></tr>";
      });
      html += "</tbody></table><h3>Strategy notes (derived from the table above)</h3><ul class='small'>";
      Trade.strategyNotes().forEach(function (n) { html += "<li>" + n + "</li>"; });
      html += "</ul><p class='small muted'>Categorization source: fills recorded by this tracker; " +
        "settlement semantics: <a href='https://docs.kalshi.com/getting_started/market_settlement' target='_blank' rel='noopener'>market settlement</a>.</p>";
      el.innerHTML = html;
    },

    renderJournal: function () {
      var el = $("journalBody");
      if (!el) return;
      var rows = Trade.fills.slice().reverse();
      var html = "<table><thead><tr><th>Time</th><th>Mode</th><th>Ticker</th><th>Action</th>" +
        "<th>Side</th><th class='num'>Count</th><th class='num'>Price</th><th>Result</th>" +
        "<th class='num'>P&amp;L</th></tr></thead><tbody>";
      if (!rows.length) {
        html += "<tr><td colspan='9' class='muted'>No fills yet.</td></tr>";
      }
      rows.forEach(function (f) {
        var p = Trade.pnl(f);
        html += "<tr><td>" + K.timeStr(f.ts) + "</td><td>" +
          (f.mode === "paper" ? "<span class='pill warn'>SIMULATED" +
            (f.automated ? " &middot; auto" + (f.strategy ? " &middot; " + K.esc(f.strategy) : "") : "") +
            "</span>" : "<span class='pill'>live</span>") + "</td><td class='mono'>" + K.esc(f.ticker) +
          "</td><td>" + K.esc(f.action) + "</td><td>" + K.esc(f.side) + "</td><td class='num'>" +
          K.num(f.count, 0) + "</td><td class='num'>" + K.cents(f.price) + "</td><td>" +
          (f.result ? "<span class='pill'>" + K.esc(f.result) + "</span>" : "open") +
          "</td><td class='num'>" + (p === null ? "—" : K.money(p)) + "</td></tr>";
      });
      html += "</tbody></table><p class='small muted'>Every paper fill is labeled SIMULATED. " +
        "Live fills come from the demo exchange (" +
        "<a href='https://docs.kalshi.com/api-reference/portfolio/get-fills' target='_blank' rel='noopener'>Get Fills</a>).</p>";
      el.innerHTML = html;
    },

    syncAutomationControl: function () {
      // `dashboard.js` calls renderAll during startup before enabling the control.
      // Reflect the persisted setting so the visible switch cannot silently say OFF
      // while onSwingAlert is still running the saved paper strategy.
      var control = $("autoTrade");
      if (control) control.checked = !!(Trade.automation && Trade.automation.enabled);
    },

    renderAll: function () {
      Trade.syncAutomationControl();
      Trade.renderPerf();
      Trade.renderStrategy();
      Trade.renderJournal();
    }
  };

  function esc(s) { return K ? K.esc(s) : String(s); }
  function topicOf(ticker) {
    if (!K || !K.TOPICS) return "unknown";
    // lightweight classifier fallback: classify by ticker keywords via shared helper
    if (K.classifySeries) {
      var c = K.classifySeries({ ticker: ticker, title: ticker, tags: [], categories: [] });
      return c.topic || "unknown";
    }
    return "unknown";
  }
  // live portfolio refresh helper (used when connected)
  async function refreshLivePortfolio() {
    if (!K.Auth || !K.Auth.keyId) return;
    var bal = await K.Auth.request("GET", "/portfolio/balance", {});
    var pos = await K.Auth.request("GET", "/portfolio/positions",
      { settlement_status: "all", limit: 200 });
    var fills = await K.Auth.request("GET", "/portfolio/fills", { limit: 200 });
    var el = $("portfolioBody");
    if (el) {
      el.innerHTML = "<p><strong>Balance:</strong> " +
        K.money(bal.balance_dollars !== undefined ? bal.balance_dollars : (bal.balance / 100)) +
        " · <strong>Portfolio value:</strong> " +
        K.money((bal.portfolio_value_dollars !== undefined ? bal.portfolio_value_dollars :
          (bal.portfolio_value || 0) / 100)) + " · <strong>Positions:</strong> " +
        ((pos.market_positions || []).length) + " · <strong>Fills:</strong> " +
        ((fills.fills || []).length) + "</p>" +
        "<p class='small muted'>Source: <a href='https://docs.kalshi.com/api-reference/portfolio/get-balance' target='_blank' rel='noopener'>Get Balance</a> · " +
        "<a href='https://docs.kalshi.com/api-reference/portfolio/get-positions' target='_blank' rel='noopener'>Get Positions</a> · " +
        "<a href='https://docs.kalshi.com/api-reference/portfolio/get-fills' target='_blank' rel='noopener'>Get Fills</a> (live, demo account).</p>";
    }
    (fills.fills || []).slice(0, 50).forEach(function (f) {
      var t = f.ticker || f.market_ticker || "";
      if (!Trade.fills.some(function (x) { return x.id === (f.fill_id || f.order_id || t); })) {
        Trade.fills.push({
          id: f.fill_id || f.order_id || ("L" + Date.now() + Math.random()),
          ts: f.created_ts ? Math.floor(f.created_ts) : Math.floor(Date.now() / 1000),
          ticker: t, side: f.outcome_side || f.side || "yes",
          action: f.action || "buy", count: Number(f.count_fp || f.count || 0),
          price: Number(f.yes_price_dollars !== undefined ? f.yes_price_dollars :
            (f.yes_price || 0)), role: f.is_taker ? "taker" : "maker",
          mode: "live", fee: Number(f.fee_cost || f.fee_dollars || 0), result: ""
        });
      }
    });
    save(FILL_KEY, Trade.fills);
    Trade.renderAll();
  }

  window.KalshiTrade = Trade;
  window.KalshiTrade.refreshLivePortfolio = refreshLivePortfolio;
  window.KalshiTrade.setLive = function (on) {
    Trade.live = !!on;
    var cs = document.querySelectorAll("#connStatus");
    Array.prototype.forEach.call(cs, function (el) {
      el.innerHTML = on ? "<span class='pill'>Connected — LIVE demo</span>" :
        "<span class='pill warn'>Paper mode</span>";
    });
    Trade.renderAll();
  };
})();
