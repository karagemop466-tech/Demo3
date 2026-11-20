/* Live dashboard: calls the Kalshi DEMO public REST API from the visitor's browser.
   Public endpoints only (no keys). If the calls fail (CORS, network), falls back to the verified snapshot. */
(function () {
  var API = 'https://external-api.demo.kalshi.co/trade-api/v2';
  var REFRESH_MS = 15000;
  var WINDOWS = {
    '1h': { secs: 3600, period: 1, label: '1 minute candles' },
    '6h': { secs: 21600, period: 1, label: '1 minute candles' },
    '24h': { secs: 86400, period: 1, label: '1 minute candles' },
    '7d': { secs: 604800, period: 60, label: '1 hour candles' },
    '30d': { secs: 2592000, period: 60, label: '1 hour candles' }
  };
  var TOPICS = [['gas', 'Gas prices'], ['elections', 'Elections'], ['culture', 'Culture'], ['crypto', 'Crypto'], ['golf', 'Golf']];
  var S = { snap: null, topic: 'elections', markets: [], sel: null, win: '24h', live: true, source: '', timer: null, auto: true, loadedAt: null };

  function $(id) { return document.getElementById(id); }
  function esc(s) { return KT.esc(s); }
  function fmtP(s) { return (s === null || s === undefined || s === '') ? '—' : '$' + Number(s).toFixed(2); }
  function fmtPraw(s) { return (s === null || s === undefined || s === '') ? '—' : '$' + String(s); }
  function fmtN(s) { var n = Number(s); return isNaN(n) ? '—' : n.toLocaleString('en-US', { maximumFractionDigits: 2 }); }
  function fetchJSON(url) {
    return fetch(url, { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error(r.status + ' ' + url);
      return r.json();
    });
  }
  function status(msg, cls) {
    var el = $('status');
    el.className = 'notice ' + (cls || '');
    el.innerHTML = msg;
  }

  function topicSeries(topic) {
    return S.snap.series.filter(function (s) { return s.topic === topic; });
  }

  function loadMarkets() {
    var series = topicSeries(S.topic);
    var calls = series.map(function (s) {
      var url = API + '/markets?series_ticker=' + encodeURIComponent(s.ticker) + '&status=open&limit=100';
      return fetchJSON(url).then(function (j) {
        return (j.markets || []).map(function (m) { m._series = s.ticker; m._url = url; return m; });
      });
    });
    return Promise.all(calls.map(function (p) { return p.then(function (v) { return { ok: true, v: v }; }, function (e) { return { ok: false, e: e }; }); }))
      .then(function (res) {
        var oks = res.filter(function (r) { return r.ok; });
        if (!oks.length && series.length) throw new Error('all series calls failed');
        var all = [];
        oks.forEach(function (r) { all = all.concat(r.v); });
        S.source = 'live';
        return all;
      })
      .catch(function () {
        S.source = 'snapshot';
        return S.snap.markets.filter(function (m) { return m.topic === S.topic && m.status === 'active'; }).map(function (m) {
          var series = m.event_ticker.split('-')[0];
          return {
            ticker: m.ticker, title: m.title, yes_sub_title: m.option || '', last_price_dollars: m.last_price_dollars,
            yes_bid_dollars: m.yes_bid_dollars, yes_ask_dollars: m.yes_ask_dollars, volume_fp: m.volume_contracts,
            open_interest_fp: m.open_interest_contracts, updated_time: '', _series: series, _snapshot: true
          };
        });
      });
  }

  function renderMarkets() {
    var rows = S.markets.slice().sort(function (a, b) { return Number(b.volume_fp || 0) - Number(a.volume_fp || 0); });
    var h = '<table><thead><tr><th>Market</th><th>Ticker</th><th class="num">Last</th><th class="num">Yes bid</th><th class="num">Yes ask</th><th class="num">Volume (contracts)</th><th class="num">Open interest</th><th>Source</th></tr></thead><tbody>';
    if (!rows.length) {
      var series = topicSeries(S.topic).map(function (s) { return s.ticker; }).join(', ');
      h += '<tr><td colspan="8" class="muted">No open markets were returned for: ' + esc(series) + '. Checked ' + new Date().toISOString().slice(0, 16).replace('T', ' ') + ' UTC.</td></tr>';
    }
    rows.forEach(function (m) {
      var sel = S.sel && S.sel.ticker === m.ticker ? ' sel' : '';
      var src = m._snapshot ? '<span class="chip warn">snapshot</span>' : '<a href="' + esc(m._url) + '" target="_blank" rel="noopener">API response</a>';
      h += '<tr class="sel-row' + sel + '" data-ticker="' + esc(m.ticker) + '" data-series="' + esc(m._series) + '">' +
        '<td>' + esc(m.title) + (m.yes_sub_title ? ' <span class="chip blue">' + esc(m.yes_sub_title) + '</span>' : '') + '</td>' +
        '<td class="mono">' + esc(m.ticker) + '</td>' +
        '<td class="num">' + fmtP(m.last_price_dollars) + '</td>' +
        '<td class="num">' + fmtP(m.yes_bid_dollars) + '</td>' +
        '<td class="num">' + fmtP(m.yes_ask_dollars) + '</td>' +
        '<td class="num">' + fmtN(m.volume_fp) + '</td>' +
        '<td class="num">' + fmtN(m.open_interest_fp) + '</td>' +
        '<td>' + src + '</td></tr>';
    });
    h += '</tbody></table>';
    $('markets').innerHTML = h;
  }

  function selectMarket(ticker, series) {
    var m = S.markets.filter(function (x) { return x.ticker === ticker; })[0];
    if (!m) return;
    S.sel = m;
    S.sel._series = series || m._series;
    renderMarkets();
    $('sel-title').textContent = m.title + (m.yes_sub_title ? ' — ' + m.yes_sub_title : '') + '  [' + m.ticker + ']';
    loadChart();
    loadBook();
  }

  function loadChart() {
    var m = S.sel;
    if (!m) return;
    var w = WINDOWS[S.win];
    $('chart-meta').textContent = 'Granularity: ' + w.label + '. Y = YES contract price in dollars (0–1). X = time (UTC).';
    if (m._snapshot) {
      drawChart([], 'Chart needs the live API. Snapshot shows no price history.');
      return;
    }
    var end = Math.floor(Date.now() / 1000), start = end - w.secs;
    var url = API + '/series/' + encodeURIComponent(m._series) + '/markets/' + encodeURIComponent(m.ticker) +
      '/candlesticks?start_ts=' + start + '&end_ts=' + end + '&period_interval=' + w.period;
    fetchJSON(url).then(function (j) {
      var pts = (j.candlesticks || []).map(function (c) {
        var p = c.price || {};
        return {
          t: c.end_period_ts * 1000,
          c: p.close_dollars === null || p.close_dollars === undefined ? null : Number(p.close_dollars),
          hi: p.high_dollars === null || p.high_dollars === undefined ? null : Number(p.high_dollars),
          lo: p.low_dollars === null || p.low_dollars === undefined ? null : Number(p.low_dollars),
          vol: c.volume_fp
        };
      }).filter(function (p) { return p.c !== null; });
      drawChart(pts, pts.length ? '' : 'No trades in this window (no candles with a price).');
      $('chart-src').innerHTML = 'Source: <a href="' + esc(url) + '" target="_blank" rel="noopener">candlestick API response</a>';
    }).catch(function (e) {
      drawChart([], 'Could not load candles from this browser (' + esc(e.message) + '). The API may block cross-origin calls.');
    });
  }

  function drawChart(pts, msg) {
    var W = 820, H = 340, L = 60, R = 16, T = 14, B = 44;
    var svg = ['<svg viewBox="0 0 ' + W + ' ' + H + '" width="100%" height="340" role="img" aria-label="YES price over time">'];
    var x0 = L, x1 = W - R, y0 = H - B, y1 = T;
    function yOf(v) { return y0 - (v * (y0 - y1)); }
    [0, 0.25, 0.5, 0.75, 1].forEach(function (v) {
      svg.push('<line x1="' + x0 + '" x2="' + x1 + '" y1="' + yOf(v) + '" y2="' + yOf(v) + '" stroke="#e3e7ee"/>');
      svg.push('<text x="' + (x0 - 8) + '" y="' + (yOf(v) + 4) + '" text-anchor="end">$' + v.toFixed(2) + '</text>');
    });
    svg.push('<line x1="' + x0 + '" x2="' + x0 + '" y1="' + y1 + '" y2="' + y0 + '" stroke="#9aa4b2"/>');
    svg.push('<line x1="' + x0 + '" x2="' + x1 + '" y1="' + y0 + '" y2="' + y0 + '" stroke="#9aa4b2"/>');
    svg.push('<text x="14" y="' + ((y0 + y1) / 2) + '" transform="rotate(-90 14 ' + ((y0 + y1) / 2) + ')" text-anchor="middle">YES price ($)</text>');
    if (pts.length) {
      var tmin = pts[0].t, tmax = pts[pts.length - 1].t;
      if (tmax === tmin) tmax = tmin + 60000;
      function xOf(t) { return x0 + (t - tmin) / (tmax - tmin) * (x1 - x0); }
      var fmt = S.win === '7d' || S.win === '30d' ? { month: 'short', day: 'numeric', hour: '2-digit' } : { hour: '2-digit', minute: '2-digit' };
      for (var i = 0; i <= 4; i++) {
        var t = tmin + (tmax - tmin) * i / 4;
        svg.push('<text x="' + xOf(t) + '" y="' + (y0 + 16) + '" text-anchor="middle">' + new Date(t).toLocaleString('en-GB', Object.assign({ timeZone: 'UTC' }, fmt)) + '</text>');
      }
      svg.push('<text x="' + ((x0 + x1) / 2) + '" y="' + (H - 6) + '" text-anchor="middle">Time (UTC)</text>');
      var band = pts.filter(function (p) { return p.hi !== null && p.lo !== null; });
      if (band.length) {
        var up = band.map(function (p) { return xOf(p.t) + ',' + yOf(p.hi); });
        var dn = band.slice().reverse().map(function (p) { return xOf(p.t) + ',' + yOf(p.lo); });
        svg.push('<polygon points="' + up.concat(dn).join(' ') + '" fill="#0b7a5a" opacity="0.12"/>');
      }
      var line = pts.map(function (p) { return xOf(p.t) + ',' + yOf(p.c); }).join(' ');
      svg.push('<polyline points="' + line + '" fill="none" stroke="#0b7a5a" stroke-width="2"/>');
      pts.forEach(function (p) { svg.push('<circle cx="' + xOf(p.t) + '" cy="' + yOf(p.c) + '" r="2.2" fill="#0b7a5a"/>'); });
      var last = pts[pts.length - 1];
      svg.push('<text x="' + (x1 - 4) + '" y="' + (yOf(last.c) - 8) + '" text-anchor="end" style="fill:#1d2330;font-weight:600">' + fmtP(last.c) + '</text>');
    }
    if (msg) svg.push('<text x="' + ((x0 + x1) / 2) + '" y="' + ((y0 + y1) / 2) + '" text-anchor="middle" style="font-size:14px;fill:#5b6474">' + esc(msg) + '</text>');
    svg.push('</svg>');
    $('chart').innerHTML = svg.join('');
  }

  function loadBook() {
    var m = S.sel;
    if (!m) return;
    if (m._snapshot) {
      $('book').innerHTML = '<p class="muted">Orderbook needs the live API. The only verified orderbook is in the <a href="findings.html">Findings</a> page.</p>';
      return;
    }
    var url = API + '/markets/' + encodeURIComponent(m.ticker) + '/orderbook?depth=15';
    fetchJSON(url).then(function (j) {
      var ob = j.orderbook_fp || {};
      var yes = (ob.yes_dollars || []).map(function (l) { return { p: l[0], q: Number(l[1]) }; }).reverse(); // best (highest) first
      var no = (ob.no_dollars || []).map(function (l) { return { p: l[0], q: Number(l[1]) }; }).reverse();
      var totYes = yes.reduce(function (a, b) { return a + b.q; }, 0), totNo = no.reduce(function (a, b) { return a + b.q; }, 0);
      var bestBid = yes.length ? yes[0].p : null, bestAskFromNo = no.length ? (1 - Number(no[0].p)).toFixed(4) : null;
      var rows = [];
      var n = Math.max(yes.length, no.length);
      if (!n) {
        $('book').innerHTML = '<p class="muted">No orders resting on this market right now (empty book).</p>' +
          '<p class="small">Source: <a href="' + esc(url) + '" target="_blank" rel="noopener">orderbook API response</a></p>';
        return;
      }
      var h = '<table><thead><tr><th class="num">YES bid (buy YES) price</th><th class="num">YES bid contracts</th><th class="num">YES ask price (= 1 − NO bid)</th><th class="num">YES ask contracts (= NO bid contracts)</th></tr></thead><tbody>';
      for (var i = 0; i < n; i++) {
        var yb = yes[i], nb = no[i];
        h += '<tr><td class="num">' + (yb ? fmtPraw(yb.p) : '') + '</td><td class="num">' + (yb ? fmtN(yb.q) : '') + '</td>' +
          '<td class="num">' + (nb ? '$' + (1 - Number(nb.p)).toFixed(4) : '') + '</td><td class="num">' + (nb ? fmtN(nb.q) : '') + '</td></tr>';
      }
      h += '</tbody></table>';
      h += '<p style="margin:8px 0 0"><b>Total contracts resting:</b> YES bids ' + fmtN(totYes) + ' · NO bids ' + fmtN(totNo) +
        (bestBid !== null ? ' · best YES bid ' + fmtPraw(bestBid) : '') + (bestAskFromNo !== null ? ' · best YES ask $' + bestAskFromNo : '') + '</p>';
      h += '<p class="small">Ask prices are derived as 1 − NO bid, as described in the <a href="https://docs.kalshi.com/api-reference/market/get-market-orderbook.md" target="_blank" rel="noopener">orderbook doc</a>. Top 15 levels per side. <a href="' + esc(url) + '" target="_blank" rel="noopener">API response</a></p>';
      $('book').innerHTML = h;
    }).catch(function (e) {
      $('book').innerHTML = '<p class="muted">Could not load the orderbook from this browser (' + esc(e.message) + ').</p>';
    });
  }

  function refresh() {
    status('Loading ' + TOPICS.filter(function (t) { return t[0] === S.topic; })[0][1] + ' markets from the Kalshi demo API…', '');
    return loadMarkets().then(function (ms) {
      S.markets = ms;
      S.loadedAt = new Date();
      if (S.sel) {
        var still = ms.filter(function (m) { return m.ticker === S.sel.ticker; })[0];
        if (!still) S.sel = null;
      }
      renderMarkets();
      if (S.source === 'live') {
        status('Live: ' + ms.length + ' open markets from the Kalshi demo API. Last refresh ' + S.loadedAt.toISOString().slice(11, 19) + ' UTC. Auto-refresh ' + (S.auto ? 'every 15 s' : 'off') + '.', 'ok');
      } else {
        status('Live calls from this browser failed (cross-origin or network). Showing the verified snapshot instead. Chart and orderbook need live access.', 'bad');
      }
      if (S.sel) { loadChart(); loadBook(); }
    });
  }

  function startTimer() {
    clearInterval(S.timer);
    if (S.auto) S.timer = setInterval(refresh, REFRESH_MS);
  }

  function init() {
    KT.getJSON('data/snapshot.json').then(function (snap) {
      S.snap = snap;
      var q = new URLSearchParams(location.search).get('topic');
      if (q && TOPICS.some(function (t) { return t[0] === q; })) S.topic = q;
      var tsel = $('topic');
      tsel.innerHTML = TOPICS.map(function (t) { return '<option value="' + t[0] + '">' + t[1] + '</option>'; }).join('');
      tsel.value = S.topic;
      tsel.addEventListener('change', function () { S.topic = tsel.value; S.sel = null; $('sel-title').textContent = 'Select a market above'; $('chart').innerHTML = ''; $('book').innerHTML = ''; refresh(); });
      $('win').addEventListener('change', function (e) { S.win = e.target.value; loadChart(); });
      $('auto').addEventListener('change', function (e) { S.auto = e.target.checked; startTimer(); refresh(); });
      $('refresh').addEventListener('click', refresh);
      $('markets').addEventListener('click', function (e) {
        var tr = e.target.closest('tr.sel-row');
        if (tr) selectMarket(tr.getAttribute('data-ticker'), tr.getAttribute('data-series'));
      });
      $('chart-meta').textContent = '';
      $('sel-title').textContent = 'Select a market above';
      refresh().then(startTimer);
    }).catch(function (e) { status('Could not load the snapshot: ' + esc(e.message), 'bad'); });
  }
  document.addEventListener('DOMContentLoaded', init);
})();
