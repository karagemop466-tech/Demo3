/* Kalshi Demo Dashboard — shared API client + charts.
 * All data comes live from the Kalshi Demo Trade API (browser -> Kalshi).
 * No server, no build step, no third-party libraries.
 * Endpoint facts verified against https://docs.kalshi.com (see api-reference.html).
 */
(function () {
  "use strict";
  var BASE = "https://external-api.demo.kalshi.co/trade-api/v2";
  var WS_URL = "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2";

  /* ---------- tiny fetch helper with rate-limit backoff ---------- */
  var backoffMs = 0, lastReq = 0;
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  async function apiGet(path, params) {
    var url = BASE + path;
    if (params) {
      var qs = Object.keys(params).filter(function (k) {
        return params[k] !== undefined && params[k] !== null && params[k] !== "";
      }).map(function (k) {
        return encodeURIComponent(k) + "=" + encodeURIComponent(params[k]);
      }).join("&");
      if (qs) url += "?" + qs;
    }
    // Respect unauthenticated rate limits: keep >= 400ms between requests,
    // back off exponentially on 429 (docs: "back off on 429").
    var now = Date.now();
    var wait = Math.max(0, 400 - (now - lastReq)) + backoffMs;
    if (wait > 0) await sleep(wait);
    lastReq = Date.now();
    var res = await fetch(url, { headers: { "Accept": "application/json" } });
    if (res.status === 429) {
      backoffMs = Math.min(backoffMs ? backoffMs * 2 : 2000, 30000);
      throw new Error("429 Too Many Requests — backing off " + backoffMs + "ms. " +
        "See https://docs.kalshi.com/getting_started/rate_limits");
    }
    backoffMs = 0;
    var text = await res.text();
    var json;
    try { json = JSON.parse(text); } catch (e) {
      throw new Error("Non-JSON response (" + res.status + ") from " + path + ": " +
        text.slice(0, 200));
    }
    if (!res.ok) {
      var msg = (json && (json.message || json.code)) || text.slice(0, 200);
      throw new Error("HTTP " + res.status + " on " + path + ": " + msg);
    }
    return json;
  }
  async function apiGetAll(path, params, maxPages) {
    var out = [], cursor = "", pages = 0;
    params = params || {};
    do {
      var p = Object.assign({}, params);
      if (cursor) p.cursor = cursor;
      var j = await apiGet(path, p);
      var key = Object.keys(j).find(function (k) { return Array.isArray(j[k]); });
      if (key) out = out.concat(j[key]);
      cursor = j.cursor || "";
      pages++;
    } while (cursor && pages < (maxPages || 10));
    return out;
  }

  /* ---------- topic discovery (no hard-coded series tickers) ----------
   * GET /series returns every series with title/tags/categories. We classify
   * by keyword match and show the matched keyword for transparency.
   * Verified: https://docs.kalshi.com/api-reference/market/get-series-list */
  var TOPICS = [
    { id: "gas", label: "Gas prices",
      keywords: ["gas price", "gasoline", "petrol", "gas prices", "fuel price"] },
    { id: "elections", label: "Elections",
      keywords: ["election", "president", "senate", "governor", "congress",
                 "mayor", "ballot", "referendum", "house control", "senate control",
                 "presidential", "midterm", "primary election", "vote"] },
    { id: "culture", label: "Culture",
      keywords: ["oscar", "grammy", "emmy", "tony award", "film", "movie",
                 "album", "song of", "celebrity", "entertainment", "tv show",
                 "reality", "novel", "book of the year", "met gala", "billboard",
                 "box office", "cannes", "super bowl halftime", "culture",
                 "streaming", "tiktok", "youtube", "spotify"] },
    { id: "crypto", label: "Crypto",
      keywords: ["bitcoin", "ethereum", "crypto", "btc", "eth ", "solana",
                 "dogecoin", "xrp", "cardano", "coinbase", "blockchain",
                 "stablecoin", "defi"] },
    { id: "golf", label: "Golf",
      keywords: ["golf", "pga", "masters tournament", "ryder cup", "liv golf",
                 "us open golf", "the open championship", "pga championship"] }
  ];
  function classifySeries(s) {
    var hay = ((s.title || "") + " " + (s.ticker || "") + " " +
      (s.tags || []).join(" ") + " " + (s.categories || []).join(" ") + " " +
      (s.category || "")).toLowerCase();
    for (var i = 0; i < TOPICS.length; i++) {
      for (var j = 0; j < TOPICS[i].keywords.length; j++) {
        if (hay.indexOf(TOPICS[i].keywords[j]) !== -1) {
          return { topic: TOPICS[i].id, matched: TOPICS[i].keywords[j] };
        }
      }
    }
    return { topic: null, matched: null };
  }
  async function discoverSeries() {
    var j = await apiGet("/series", {});
    var list = j.series || [];
    return list.map(function (s) {
      var c = classifySeries(s);
      return { ticker: s.ticker, title: s.title, category: s.category,
        categories: s.categories || [], tags: s.tags || [],
        frequency: s.frequency, volume_fp: s.volume_fp,
        topic: c.topic, matched: c.matched };
    });
  }

  /* ---------- formatting ---------- */
  function num(x, d) {
    if (x === null || x === undefined || x === "" || isNaN(Number(x))) return "—";
    return Number(x).toLocaleString("en-US",
      { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 });
  }
  function money(x) {
    if (x === null || x === undefined || x === "" || isNaN(Number(x))) return "—";
    return "$" + Number(x).toLocaleString("en-US",
      { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function cents(x) { // contract price dollars -> cents label (API precision kept to 0.01¢)
    if (x === null || x === undefined || x === "" || isNaN(Number(x))) return "—";
    return (Number(x) * 100).toFixed(2) + "¢";
  }
  /* Per-row API source link (verification requirement): links the exact request URL. */
  function srcLink(path, label) {
    var href = path.indexOf("http") === 0 ? path : BASE + path;
    return "<a class='src' href='" + esc(href) + "' target='_blank' rel='noopener'>" +
      esc(label || "source") + "</a>";
  }
  function timeStr(ts) {
    if (!ts) return "—";
    var d = new Date(ts * 1000);
    return d.toLocaleTimeString("en-GB") + " " + d.toLocaleDateString("en-GB");
  }
  function esc(s) {
    return String(s === null || s === undefined ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  /* Dollar estimates: API reports contracts (volume_fp / open_interest_fp) and
   * per-contract price (last_price_dollars). Estimated dollars = contracts ×
   * price. This is an estimate, not an exchange-reported dollar figure. */
  function estDollars(contracts, price) {
    if (contracts === null || contracts === undefined || price === null ||
        price === undefined || isNaN(Number(contracts)) || isNaN(Number(price))) {
      return null;
    }
    return Number(contracts) * Number(price);
  }

  /* ---------- canvas line chart (X=time, Y=price) ---------- */
  function drawPriceChart(canvas, points, opts) {
    opts = opts || {};
    var dpr = window.devicePixelRatio || 1;
    var W = canvas.clientWidth, H = canvas.clientHeight;
    if (!W || !H) return;
    canvas.width = W * dpr; canvas.height = H * dpr;
    var ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, W, H);
    var padL = 52, padR = 10, padT = 12, padB = 28;
    var pw = W - padL - padR, ph = H - padT - padB;
    ctx.font = "11px " + getComputedStyle(document.body).fontFamily;
    if (!points || points.length < 2) {
      ctx.fillStyle = "#5b6577";
      ctx.fillText("Not enough data yet — waiting for samples…", padL, padT + 20);
      return;
    }
    var t0 = points[0].t, t1 = points[points.length - 1].t;
    if (t1 === t0) t1 = t0 + 1;
    var ys = [];
    points.forEach(function (p) {
      ys.push(p.price);
      if (p.bid !== null && p.bid !== undefined) ys.push(p.bid);
      if (p.ask !== null && p.ask !== undefined) ys.push(p.ask);
    });
    var yMin = Math.min.apply(null, ys), yMax = Math.max.apply(null, ys);
    if (yMax - yMin < 0.02) { yMin -= 0.01; yMax += 0.01; }
    yMin = Math.max(0, yMin); yMax = Math.min(1, yMax);
    function X(t) { return padL + (t - t0) / (t1 - t0) * pw; }
    function Y(v) { return padT + (1 - (v - yMin) / (yMax - yMin)) * ph; }
    // grid + Y labels
    ctx.strokeStyle = "#e2e6ee"; ctx.fillStyle = "#5b6577";
    for (var i = 0; i <= 4; i++) {
      var v = yMin + (yMax - yMin) * i / 4, y = Y(v);
      ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL + pw, y); ctx.stroke();
      ctx.fillText((v * 100).toFixed(0) + "¢", 6, y + 4);
    }
    // X labels (5 ticks) — format matches the window: seconds, minutes, or date
    var span = t1 - t0;
    for (var k = 0; k <= 4; k++) {
      var t = t0 + (t1 - t0) * k / 4;
      var lbl;
      if (span <= 3600) lbl = timeStr(t).slice(0, 8);        // HH:MM:SS
      else if (span <= 86400) lbl = timeStr(t).slice(0, 5);  // HH:MM
      else lbl = timeStr(t).slice(9).trim();                 // dd/mm/yyyy
      ctx.fillText(lbl, X(t) - 14, H - 8);
    }
    // bid/ask band
    function line(key, color, width) {
      ctx.strokeStyle = color; ctx.lineWidth = width; ctx.beginPath();
      var started = false;
      points.forEach(function (p) {
        if (p[key] === null || p[key] === undefined) return;
        if (!started) { ctx.moveTo(X(p.t), Y(p[key])); started = true; }
        else ctx.lineTo(X(p.t), Y(p[key]));
      });
      ctx.stroke(); ctx.lineWidth = 1;
    }
    line("bid", "#9db8d2", 1); line("ask", "#9db8d2", 1);
    line("price", "#0a7a4b", 2);
    // last point dot + label
    var last = points[points.length - 1];
    ctx.fillStyle = "#0a7a4b";
    ctx.beginPath(); ctx.arc(X(last.t), Y(last.price), 3, 0, 7); ctx.fill();
    ctx.fillText(cents(last.price) + " @ " + timeStr(last.t), padL + 4, padT + 12);
    if (opts.windowLabel) ctx.fillText(opts.windowLabel, padL + pw - 90, padT + 12);
    /* Swing-event annotations (opts.annotations: [{t, label, dir}]).
     * Additive & optional — no effect when omitted. Marks >=$0.10 swing points
     * with the related event ticker; the clickable event/source links live in
     * the caption beneath the chart (dashboard.js) and in the alert chats. */
    if (opts.annotations && opts.annotations.length) {
      ctx.font = "10px " + getComputedStyle(document.body).fontFamily;
      opts.annotations.forEach(function (an) {
        var x = X(an.t);
        if (x < padL || x > padL + pw) return;
        ctx.strokeStyle = "rgba(178,106,0,.45)";
        ctx.setLineDash([3, 3]);
        ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, padT + ph); ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = an.dir === "down" ? "#b23a2a" : "#9a6a00";
        ctx.fillText(an.label || "",
          Math.max(padL, Math.min(x - 26, padL + pw - 40)), padT + ph - 6);
      });
    }
  }

  /* ---------- canvas depth chart (contracts per price level) ---------- */
  function drawDepthChart(canvas, yesLevels, noLevels) {
    var dpr = window.devicePixelRatio || 1;
    var W = canvas.clientWidth, H = canvas.clientHeight;
    if (!W || !H) return;
    canvas.width = W * dpr; canvas.height = H * dpr;
    var ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, W, H);
    var padL = 52, padR = 10, padT = 12, padB = 28;
    var pw = W - padL - padR, ph = H - padT - padB;
    ctx.font = "11px " + getComputedStyle(document.body).fontFamily;
    var all = (yesLevels || []).concat(noLevels || []);
    if (!all.length) {
      ctx.fillStyle = "#5b6577";
      ctx.fillText("Order book is empty (no resting bids).", padL, padT + 20);
      return;
    }
    var maxC = Math.max.apply(null, all.map(function (l) { return l.count; }));
    function bar(levels, color) {
      levels.forEach(function (l) {
        var x = padL + l.price * pw, w = Math.max(1, pw / 100);
        var h = (l.count / maxC) * ph;
        ctx.fillStyle = color;
        ctx.fillRect(x, padT + ph - h, w, h);
      });
    }
    // grid
    ctx.strokeStyle = "#e2e6ee"; ctx.fillStyle = "#5b6577";
    for (var i = 0; i <= 4; i++) {
      var y = padT + ph * i / 4;
      ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL + pw, y); ctx.stroke();
      ctx.fillText(num(maxC * (1 - i / 4), 0), 6, y + 4);
    }
    for (var k = 0; k <= 4; k++) {
      ctx.fillText((k * 25) + "¢", padL + pw * k / 4 - 8, H - 8);
    }
    bar(yesLevels || [], "rgba(10,122,75,.75)");
    bar(noLevels || [], "rgba(157,184,210,.9)");
    ctx.fillStyle = "#0a7a4b"; ctx.fillText("YES bids", padL + 4, padT + 12);
    ctx.fillStyle = "#5b6577"; ctx.fillText("NO bids", padL + 70, padT + 12);
  }

  /* ---------- authenticated client (optional demo API key) ----------
   * Signs timestamp+METHOD+fullPath (incl. /trade-api/v2, no query) per
   * https://docs.kalshi.com/getting_started/api_keys
   * Ed25519 (PKCS#8) preferred; RSA-PSS SHA-256 (salt = digest length) fallback.
   * Key stays in this browser. */
  var Auth = {
    keyId: null, cryptoKey: null, alg: null,
    async load(keyId, pem) {
      this.keyId = keyId;
      var der = pemToDer(pem);
      var subtle = window.crypto.subtle;
      try {
        this.cryptoKey = await subtle.importKey("pkcs8", der,
          { name: "Ed25519" }, false, ["sign"]);
        this.alg = "Ed25519";
      } catch (e1) {
        try {
          this.cryptoKey = await subtle.importKey("pkcs8", der,
            { name: "RSA-PSS", hash: "SHA-256" }, false, ["sign"]);
          this.alg = "RSA-PSS";
        } catch (e2) {
          throw new Error("Could not import private key. Use a PKCS#8 PEM " +
            "(\"BEGIN PRIVATE KEY\"). For RSA keys convert first: " +
            "openssl pkcs8 -topk8 -nocrypt -in kalshi.key -out kalshi-pkcs8.key. " +
            "Ed25519 keys from Kalshi are already PKCS#8. " +
            "Browser Ed25519 support: Chrome 137+, otherwise use an RSA key.");
        }
      }
      return this.alg;
    },
    async headers(method, path) {
      var ts = String(Date.now());
      /* Official signing spec (docs.kalshi.com/getting_started/api_keys):
       * base64(sign(timestamp + method + path)) where path is the FULL request
       * path including /trade-api/v2, WITHOUT query parameters. */
      var fullPath = path.indexOf("/trade-api/v2") === 0 ? path : "/trade-api/v2" + path;
      fullPath = fullPath.split("?")[0];
      var msg = new TextEncoder().encode(ts + method + fullPath);
      var sig;
      if (this.alg === "Ed25519") {
        sig = await window.crypto.subtle.sign("Ed25519", this.cryptoKey, msg);
      } else {
        sig = await window.crypto.subtle.sign(
          { name: "RSA-PSS", saltLength: 32 }, this.cryptoKey, msg);
      }
      return {
        "KALSHI-ACCESS-KEY": this.keyId,
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "KALSHI-ACCESS-SIGNATURE": b64(sig),
        "Content-Type": "application/json"
      };
    },
    async request(method, path, params, body) {
      var url = BASE + path;
      if (params) {
        var qs = Object.keys(params).filter(function (k) {
          return params[k] !== undefined && params[k] !== null && params[k] !== "";
        }).map(function (k) {
          return encodeURIComponent(k) + "=" + encodeURIComponent(params[k]);
        }).join("&");
        if (qs) url += "?" + qs;
      }
      var h = await this.headers(method, path);
      var res = await fetch(url, {
        method: method, headers: h,
        body: body ? JSON.stringify(body) : undefined
      });
      var text = await res.text();
      var json;
      try { json = JSON.parse(text); } catch (e) {
        throw new Error("Non-JSON response (" + res.status + "): " + text.slice(0, 200));
      }
      if (!res.ok) {
        throw new Error("HTTP " + res.status + " on " + method + " " + path + ": " +
          ((json && (json.message || json.code)) || text.slice(0, 200)));
      }
      return json;
    }
  };
  function pemToDer(pem) {
    var b64 = pem.replace(/-----BEGIN [^-]+-----/g, "").replace(/-----END [^-]+-----/g, "")
      .replace(/\s+/g, "");
    var bin = atob(b64), bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return bytes.buffer;
  }
  function b64(buf) {
    var bin = "";
    var bytes = new Uint8Array(buf);
    for (var i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin);
  }

  window.KalshiDemo = {
    BASE: BASE, WS_URL: WS_URL, TOPICS: TOPICS,
    apiGet: apiGet, apiGetAll: apiGetAll,
    discoverSeries: discoverSeries, classifySeries: classifySeries,
    num: num, money: money, cents: cents, timeStr: timeStr, esc: esc,
    estDollars: estDollars, srcLink: srcLink,
    drawPriceChart: drawPriceChart, drawDepthChart: drawDepthChart,
    Auth: Auth
  };
})();
