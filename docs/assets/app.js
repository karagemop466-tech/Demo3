/* Kalshi demo dashboard - shared page logic.
 * Snapshot tables come from data/verified.json (every row has a source link).
 * Live panels call the public Kalshi Trade API from the browser (no key needed for
 * market data per https://docs.kalshi.com/getting_started/quick_start_market_data.md).
 * If the browser cannot reach the API, the panels show a banner and keep the snapshot. */
(function () {
  'use strict';

  var API = 'https://external-api.demo.kalshi.co/trade-api/v2'; /* demo endpoint recommended by the
   * project brief; official list: https://docs.kalshi.com/getting_started/api_environments */
  var ROOT = document.body.getAttribute('data-root') || './';
  var PAGE = document.body.getAttribute('data-page') || '';
  var WATCH_KEY = 'kalshi_watchlist_v1';
  var DECIDE_KEY = 'kalshi_decisions_v1';

  var NAV = [
    ['index.html', 'Home', 'home'],
    ['dashboard.html', 'Live dashboard', 'dashboard'],
    ['categories/gas.html', 'Gas prices', 'gas'],
    ['categories/elections.html', 'Elections', 'elections'],
    ['categories/culture.html', 'Culture', 'culture'],
    ['categories/crypto.html', 'Crypto', 'crypto'],
    ['categories/golf.html', 'Golf', 'golf'],
    ['resolved.html', 'Resolved', 'resolved'],
    ['findings.html', 'Findings', 'findings'],
    ['portfolio.html', 'Portfolio & trades', 'portfolio'],
    ['questions.html', 'Questions', 'questions'],
    ['suggestions.html', 'Suggestions', 'suggestions'],
    ['flagged.html', 'Flagged for review', 'flagged'],
    ['sources.html', 'Sources', 'sources']
  ];

  var CATS = {
    gas: {label: 'Gas prices', lists: [{cat: 'Economics'}],
      match: function (s) { return s.category === 'Economics' && /gas/i.test((s.title || '') + ' ' + (s.ticker || '')); }},
    elections: {label: 'Elections', lists: [{cat: 'Elections'}],
      match: function (s) { return s.category === 'Elections'; }},
    culture: {label: 'Culture', lists: [{cat: 'Culture'}],
      match: function (s) { return s.category === 'Culture'; }},
    crypto: {label: 'Crypto', lists: [{cat: 'Crypto'}],
      match: function (s) { return s.category === 'Crypto'; }},
    golf: {label: 'Golf', lists: [{cat: 'Sports', tags: 'Golf'}],
      match: function (s) { return s.category === 'Sports' && (s.tags || []).indexOf('Golf') !== -1; }}
  };
  var CAT_ORDER = ['gas', 'elections', 'culture', 'crypto', 'golf'];
  var TOP_SERIES = 6;      // series per category pulled for live markets
  var LIVE_EVERY = 60000;  // ms between live table refreshes
  var WATCH_EVERY = 15000; // ms between watchlist refreshes

  var DATA = null;
  var state = {
    seriesByCat: {},     // key -> [series]
    liveByCat: {},       // key -> [market]
    liveError: null,
    liveUpdated: null,
    markets: {},         // ticker -> market (latest known)
    detail: {ticker: null, series: null, mode: 'minutes', len: null, buffer: {}},
    chartTimer: null
  };

  /* ---------- helpers ---------- */
  function esc(s) {
    return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
    });
  }
  function num(v) { var n = parseFloat(v); return isNaN(n) ? null : n; }
  function fmtNum(v, d) {
    var n = num(v); if (n === null) return '';
    return n.toLocaleString('en-US', {minimumFractionDigits: d || 0, maximumFractionDigits: d || 0});
  }
  function fmtPrice(v) { var n = num(v); return n === null ? '' : '$' + n.toFixed(2); }
  function fmtTime(ms) { return new Date(ms).toLocaleString('en-US', {hour12: false}); }
  function link(url, text) {
    if (!url) return '<span class="flag unv">unverified - no link</span>';
    return '<a href="' + esc(url) + '" target="_blank" rel="noopener">' + esc(text || 'source') + '</a>';
  }
  function sevFlag(sev) {
    var cls = sev === 'high' ? 'bad' : (sev === 'medium' ? '' : 'ok');
    return '<span class="flag ' + cls + '">' + esc(sev) + '</span>';
  }
  function flagChip(f) { return f ? '<span class="flag">' + esc(f) + '</span>' : ''; }
  function table(headers, rows, numCols) {
    numCols = numCols || [];
    var h = headers.map(function (x, i) {
      return '<th' + (numCols.indexOf(i) !== -1 ? ' class="num"' : '') + '>' + esc(x) + '</th>';
    }).join('');
    var b = rows.map(function (r) {
      return '<tr>' + r.map(function (c, i) {
        return '<td' + (numCols.indexOf(i) !== -1 ? ' class="num"' : '') + '>' + c + '</td>';
      }).join('') + '</tr>';
    }).join('');
    if (!rows.length) b = '<tr><td colspan="' + headers.length + '" class="muted">No rows.</td></tr>';
    return '<div class="tablewrap"><table><thead><tr>' + h + '</tr></thead><tbody>' + b + '</tbody></table></div>';
  }
  function getJSON(path, params) {
    var url = new URL(API + path);
    if (params) Object.keys(params).forEach(function (k) { url.searchParams.set(k, params[k]); });
    return fetch(url.toString(), {headers: {Accept: 'application/json'}}).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status + ' ' + url.pathname);
      return r.json();
    });
  }
  function seriesOf(ticker) { return (ticker || '').split('-')[0]; }
  function kalshiUrl(series) { return 'https://kalshi.com/markets/' + String(series || '').toLowerCase(); }
  function setBanner(id, kind, html) {
    var el = document.getElementById(id); if (!el) return;
    el.className = 'banner' + (kind === 'ok' ? ' ok' : '');
    el.innerHTML = html;
  }
  function loadWatch() { try { return JSON.parse(localStorage.getItem(WATCH_KEY) || '[]'); } catch (e) { return []; } }
  function saveWatch(w) { localStorage.setItem(WATCH_KEY, JSON.stringify(w)); }
  function isWatched(t) { return loadWatch().some(function (w) { return w.ticker === t; }); }
  function toggleWatch(m) {
    var w = loadWatch();
    if (w.some(function (x) { return x.ticker === m.ticker; })) {
      w = w.filter(function (x) { return x.ticker !== m.ticker; });
    } else {
      w.push({ticker: m.ticker, series: m._series || seriesOf(m.ticker), title: m.title || m.ticker,
              cat: m._cat || '', added: new Date().toISOString()});
    }
    saveWatch(w);
    renderAllLive(); renderWatchlist();
  }
  function outcomeChip(m) {
    if (!m) return '<span class="flag unv">not loaded</span>';
    if (m.result === 'yes' || m.result === 'no') {
      return '<span class="flag ' + (m.result === 'yes' ? 'ok' : 'bad') + '">Resolved: ' + m.result.toUpperCase() + '</span>';
    }
    if (m.status === 'finalized' || m.status === 'determined') return '<span class="flag">' + esc(m.status) + ' (result pending)</span>';
    return '<span class="flag">' + esc(m.status || 'unknown') + '</span>';
  }

  /* ---------- nav + snapshot rendering ---------- */
  function renderNav() {
    var host = document.getElementById('site-nav'); if (!host) return;
    var items = NAV.map(function (n) {
      return '<a href="' + ROOT + n[0] + '" class="' + (n[2] === PAGE ? 'active' : '') + '">' + esc(n[1]) + '</a>';
    }).join('');
    host.innerHTML = '<div class="bar"><a class="brand" href="' + ROOT + 'index.html">Kalshi demo dashboard</a>' +
      '<nav class="menu">' + items + '</nav></div>';
  }

  function renderSeries(catKey) {
    var rows = DATA.series.filter(function (s) { return !catKey || s.cat === catKey; }).map(function (s) {
      return [
        link(s.source, s.ticker),
        esc(s.title), esc(s.frequency), esc(s.tags),
        esc(s.volume_contracts), esc(s.settlement_source),
        s.settlement_url ? link(s.settlement_url, 'settlement page') : '',
        flagChip(s.flags), link(s.source, 'API data')
      ];
    });
    return table(['Series', 'Title', 'Frequency', 'Tags', 'Volume (contracts, snapshot)', 'Settlement source', 'Settlement link', 'Flags', 'Source'], rows, [4]);
  }

  function renderVolumeRanking() {
    var rows = DATA.series.filter(function (s) { return s.volume_contracts !== ''; })
      .slice().sort(function (a, b) { return num(b.volume_contracts) - num(a.volume_contracts); })
      .map(function (s, i) {
        return [String(i + 1), esc(s.ticker), esc(s.title), esc(s.cat), esc(s.volume_contracts), link(s.source, 'API data')];
      });
    return table(['Rank', 'Series', 'Title', 'Category', 'Volume (contracts)', 'Source'], rows, [0, 4]);
  }

  function renderResolved(catKey) {
    var prefix = {gas: 'KXAAAGAS'}[catKey];
    var rows = DATA.resolved.filter(function (r) { return !prefix || r.ticker.indexOf(prefix) === 0; }).map(function (r) {
      return [esc(r.ticker), esc(r.title), esc(r.floor_strike), '<b>' + esc(r.result.toUpperCase()) + '</b>',
        esc(r.expiration_value), esc(r.settlement_value_dollars), esc(r.status), esc(r.settlement_ts),
        esc(r.volume_contracts), flagChip(r.flags), link(r.source, 'API data')];
    });
    return table(['Market', 'Title', 'Strike', 'Result', 'Expiration value', 'Settlement value ($)', 'Status', 'Settled (UTC)', 'Volume (contracts)', 'Flags', 'Source'], rows, [2, 4, 5, 8]);
  }

  function renderIrregularities() {
    var rows = DATA.irregularities.map(function (i) {
      return [esc(i.id), esc(i.area), esc(i.item), sevFlag(i.severity), link(i.source, 'source')];
    });
    return table(['ID', 'Area', 'Irregularity', 'Severity', 'Source'], rows);
  }

  function renderUnverified() {
    var rows = DATA.unverified.map(function (u) {
      return [esc(u.item), esc(u.reason), '<span class="flag unv">unverified</span>'];
    });
    return table(['Item', 'Why it is unverified', 'Status'], rows);
  }

  function renderQuestions() {
    var rows = DATA.questions.map(function (q, i) {
      return [String(i + 1), '<b>' + esc(q.q) + '</b>', esc(q.known), esc(q.missing), link(q.source, 'source')];
    });
    return table(['#', 'Question', 'What we know (sourced)', 'What is missing', 'Source'], rows, []);
  }

  function renderFindings() {
    var items = DATA.findings.map(function (f) {
      return '<li>' + esc(f.text) + ' ' + link(f.source, 'source') + '</li>';
    }).join('');
    return '<ul>' + items + '</ul>';
  }

  function renderSources() {
    var rows = DATA.sources.map(function (s) {
      return [esc(s.name), link(s.url, s.url), esc(s.used_for)];
    });
    return table(['Source', 'URL', 'Used for'], rows);
  }

  function renderRepo() {
    var rows = DATA.repo_review.map(function (r) {
      return [esc(r.item), esc(r.detail), r.source ? link(r.source, 'source') : '<span class="flag unv">none</span>'];
    });
    return table(['Item', 'Finding', 'Source'], rows);
  }

  function renderDecisions() {
    var saved = {}; try { saved = JSON.parse(localStorage.getItem(DECIDE_KEY) || '{}'); } catch (e) {}
    var html = DATA.suggestions.map(function (s) {
      var cur = saved[s.id] || '';
      var opts = s.options.map(function (o, idx) {
        var letter = o.charAt(0);
        return '<label><input type="radio" name="' + s.id + '" value="' + esc(letter) + '"' +
          (cur === letter ? ' checked' : '') + '> ' + esc(o) + '</label>';
      }).join('');
      return '<div class="card"><h3>' + esc(s.id) + ' - ' + esc(s.title) + '</h3>' +
        '<p class="small">' + esc(s.detail) + ' ' + link(s.source, 'source') + '</p>' +
        '<div class="opts">' + opts + '</div>' +
        '<p class="note">Decision status: ' + (cur ? 'chosen ' + esc(cur) + ' (not implemented)' : 'pending your choice') + '</p></div>';
    }).join('');
    return html;
  }

  function renderPortfolioSchema() {
    var rows = [
      ['Market category', 'Series category field (Crypto, Elections, Culture, Sports, Economics)', 'https://external-api.kalshi.com/trade-api/v2/series?category=Crypto&include_volume=true'],
      ['Strike type and strike value', 'strike_type, floor_strike (for example "greater")', 'https://docs.kalshi.com/api-reference/market/get-market.md'],
      ['Time to close', 'open_time, close_time, expected_expiration_time', 'https://docs.kalshi.com/getting_started/market_lifecycle.md'],
      ['Entry price bucket', 'Price at entry (yes_ask_dollars or no_ask_dollars), $0.01 steps', 'https://docs.kalshi.com/api-reference/market/get-market.md'],
      ['Liquidity bucket', 'yes_bid_size_fp, yes_ask_size_fp, open_interest_fp', 'https://docs.kalshi.com/api-reference/market/get-market.md'],
      ['Side', 'YES or NO (binary markets)', 'https://docs.kalshi.com/getting_started/orderbook_responses.md'],
      ['Outcome', 'result (yes, no, scalar) once determined; settlement pays $1 per winning contract', 'https://docs.kalshi.com/getting_started/market_settlement.md'],
      ['Settlement source quality', 'Official vs non-official source, from settlement_sources (see Flagged for review)', 'https://external-api.kalshi.com/trade-api/v2/series?category=Culture&include_volume=true']
    ];
    return table(['Trade category field', 'What it records', 'Source'], rows.map(function (r) {
      return [esc(r[0]), esc(r[1]), link(r[2], 'source')];
    }));
  }

  function renderSnapshots() {
    document.querySelectorAll('[data-render]').forEach(function (el) {
      var what = el.getAttribute('data-render'), cat = el.getAttribute('data-cat');
      var html = '';
      if (what === 'series') html = renderSeries(cat);
      if (what === 'resolved') html = renderResolved(cat);
      if (what === 'volume') html = renderVolumeRanking();
      if (what === 'irregularities') html = renderIrregularities();
      if (what === 'unverified') html = renderUnverified();
      if (what === 'questions') html = renderQuestions();
      if (what === 'findings') html = renderFindings();
      if (what === 'sources') html = renderSources();
      if (what === 'repo') html = renderRepo();
      if (what === 'decisions') html = renderDecisions();
      if (what === 'schema') html = renderPortfolioSchema();
      if (what === 'top-events') { renderTopEvents(el); return; }
      if (what === 'pipeline-markets') { renderPipelineMarkets(el, cat); return; }
      if (what === 'pipeline-resolved') { renderPipelineResolved(el); return; }
      if (what === 'portfolio-state') { renderPortfolioState(el); return; }
      if (what === 'strategies') html = renderStrategies();
      if (what === 'order-ticket') html = renderOrderTicket();
      if (what === 'pipeline-flags') html = renderPipelineFlags();
      if (what === 'pipeline-sources') { renderPipelineSources(el); return; }
      if (what === 'verify-report') { renderVerifyReport(el); return; }
      if (what === 'counts') {
        html = '<div class="grid">' +
          kpi(DATA.series.length, 'series in verified snapshot') +
          kpi(Object.keys(CATS).length, 'categories tracked') +
          kpi(DATA.resolved.length, 'resolved markets (yes/no) recorded') +
          kpi(DATA.irregularities.length, 'irregularities flagged') +
          kpi(DATA.unverified.length, 'items unverified') + '</div>';
      }
      el.innerHTML = html;
    });
  }
  function kpi(v, label) { return '<div class="kpi"><b>' + esc(v) + '</b><span>' + esc(label) + '</span></div>'; }

  /* ---------- live: category markets ---------- */
  function loadSeriesFor(catKey) {
    if (state.seriesByCat[catKey]) return Promise.resolve(state.seriesByCat[catKey]);
    var cfg = CATS[catKey];
    var lists = cfg.lists.map(function (l) {
      var p = {category: l.cat, include_volume: 'true'}; if (l.tags) p.tags = l.tags;
      return getJSON('/series', p);
    });
    return Promise.all(lists).then(function (res) {
      var seen = {}, out = [];
      res.forEach(function (r) { (r.series || []).forEach(function (s) {
        if (!seen[s.ticker] && cfg.match(s)) { seen[s.ticker] = 1; out.push(s); }
      }); });
      out.sort(function (a, b) { return (num(b.volume_fp) || 0) - (num(a.volume_fp) || 0); });
      state.seriesByCat[catKey] = out;
      return out;
    });
  }

  function loadLiveCat(catKey) {
    return loadSeriesFor(catKey).then(function (series) {
      var top = series.slice(0, TOP_SERIES);
      return Promise.all(top.map(function (s) {
        return getJSON('/events', {series_ticker: s.ticker, status: 'open', with_nested_markets: 'true', limit: '200'})
          .then(function (r) {
            var out = [];
            (r.events || []).forEach(function (ev) {
              (ev.markets || []).forEach(function (m) {
                if (m.status !== 'active') return;
                m._series = s.ticker; m._cat = catKey; m._event = ev.title || ev.event_ticker;
                out.push(m);
              });
            });
            return out;
          });
      })).then(function (lists) {
        var all = [].concat.apply([], lists);
        all.sort(function (a, b) { return (num(b.volume_fp) || 0) - (num(a.volume_fp) || 0); });
        state.liveByCat[catKey] = all;
        all.forEach(function (m) { state.markets[m.ticker] = m; });
      });
    });
  }

  function refreshLive() {
    var keys = CAT_ORDER.filter(function (k) { return document.querySelector('[data-live~="' + k + '"]'); });
    if (!keys.length) return;
    setBanner('live-status', 'info', 'Loading live data from the Kalshi public API...');
    var ok = 0, errs = [];
    return keys.reduce(function (p, k) {
      return p.then(function () {
        return loadLiveCat(k).then(function () { ok++; }).catch(function (e) { errs.push(k + ': ' + e.message); });
      });
    }, Promise.resolve()).then(function () {
      state.liveUpdated = new Date();
      if (ok === 0) {
        setBanner('live-status', 'warn',
          '<b>Live data unavailable in this browser.</b> The Kalshi API could not be read (' + esc(errs[0] || 'network/CORS') +
          '). Tables below show the verified snapshot only. This is flagged as unverified in Flagged for review.');
      } else {
        setBanner('live-status', 'ok', 'Live: connected to the public Kalshi API. Last update ' +
          esc(state.liveUpdated.toLocaleTimeString('en-US', {hour12: false})) + ' (refreshes every 60 s).' +
          (errs.length ? ' Some categories failed: ' + esc(errs.join('; ')) : ''));
      }
      renderAllLive();
      renderDetailSelect();
    });
  }

  function renderAllLive() {
    document.querySelectorAll('[data-live]').forEach(function (el) {
      var keys = el.getAttribute('data-live').split(/\s+/).filter(Boolean);
      var limit = parseInt(el.getAttribute('data-limit') || '25', 10);
      var rows = [];
      keys.forEach(function (k) { rows = rows.concat(state.liveByCat[k] || []); });
      rows.sort(function (a, b) { return (num(b.volume_fp) || 0) - (num(a.volume_fp) || 0); });
      rows = rows.slice(0, limit);
      if (!rows.length) {
        el.innerHTML = '<p class="muted">No live rows loaded yet for this view.</p>';
        return;
      }
      var body = rows.map(function (m, i) {
        return [
          String(i + 1), esc(CATS[m._cat] ? CATS[m._cat].label : m._cat),
          '<b>' + esc(m.yes_sub_title || m.title || m.ticker) + '</b><div class="note">' + esc(m._event || m.title) + '</div>',
          link(API + '/markets/' + m.ticker, m.ticker),
          fmtPrice(m.yes_bid_dollars), fmtPrice(m.yes_ask_dollars), fmtPrice(m.last_price_dollars),
          fmtNum(m.volume_fp), fmtNum(m.volume_24h_fp), fmtNum(m.open_interest_fp),
          '<button data-pick="' + esc(m.ticker) + '">Chart</button> ' +
          '<button data-track="' + esc(m.ticker) + '"' + (isWatched(m.ticker) ? ' class="primary"' : '') + '>' +
          (isWatched(m.ticker) ? 'Tracking' : 'Track') + '</button>'
        ];
      });
      el.innerHTML = '<div class="note">Ranked by contracts traded (volume_fp). Dollar volume is not provided by the API. Market page: ' +
        '<a href="https://kalshi.com/markets" target="_blank" rel="noopener">kalshi.com/markets</a>.</div>' +
        table(['#', 'Category', 'Market', 'Ticker (source)', 'YES bid', 'YES ask', 'Last', 'Volume (contracts)', 'Volume 24h', 'Open interest', 'Actions'],
          body, [0, 4, 5, 6, 7, 8, 9]);
    });
    document.querySelectorAll('[data-track]').forEach(function (b) {
      b.addEventListener('click', function () { var m = state.markets[b.getAttribute('data-track')]; if (m) toggleWatch(m); });
    });
    document.querySelectorAll('[data-pick]').forEach(function (b) {
      b.addEventListener('click', function () { pickDetail(b.getAttribute('data-pick')); });
    });
  }

  /* ---------- watchlist ---------- */
  function renderWatchlist() {
    var el = document.getElementById('watchlist'); if (!el) return;
    var w = loadWatch();
    if (!w.length) { el.innerHTML = '<p class="muted">Nothing tracked yet. Click "Track" on a live market to follow it until it resolves.</p>'; return; }
    var rows = w.map(function (x) {
      var m = state.markets[x.ticker] || {};
      return [
        link(API + '/markets/' + x.ticker, x.ticker), esc(x.title), esc(x.cat),
        fmtPrice(m.last_price_dollars), fmtPrice(m.yes_bid_dollars), fmtPrice(m.yes_ask_dollars),
        outcomeChip(m.ticker ? m : null), esc(m.settlement_ts || ''),
        '<button data-pick="' + esc(x.ticker) + '">Chart</button> <button data-untrack="' + esc(x.ticker) + '">Remove</button>'
      ];
    });
    el.innerHTML = table(['Ticker (source)', 'Market', 'Category', 'Last', 'YES bid', 'YES ask', 'Status / result', 'Settled (UTC)', 'Actions'], rows, [3, 4, 5]);
    el.querySelectorAll('[data-untrack]').forEach(function (b) {
      b.addEventListener('click', function () {
        saveWatch(loadWatch().filter(function (x) { return x.ticker !== b.getAttribute('data-untrack'); }));
        renderWatchlist(); renderAllLive();
      });
    });
    el.querySelectorAll('[data-pick]').forEach(function (b) {
      b.addEventListener('click', function () { pickDetail(b.getAttribute('data-pick')); });
    });
  }

  function refreshWatch() {
    var w = loadWatch(); if (!w.length) { renderWatchlist(); return Promise.resolve(); }
    return Promise.all(w.map(function (x) {
      return getJSON('/markets/' + x.ticker).then(function (r) {
        var m = r.market; m._series = x.series; m._cat = x.cat; state.markets[x.ticker] = m;
      }).catch(function () {});
    })).then(renderWatchlist);
  }

  /* ---------- detail chart + liquidity ---------- */
  var LENGTHS = {
    seconds: [['5 min', 300], ['15 min', 900], ['60 min', 3600]],
    minutes: [['1 hour', 3600], ['3 hours', 10800], ['24 hours', 86400]],
    hours: [['24 hours', 86400], ['7 days', 604800], ['30 days', 2592000]]
  };
  var PERIOD = {minutes: 1, hours: 60};

  function renderDetailSelect() {
    var sel = document.getElementById('detail-pick'); if (!sel) return;
    var cur = state.detail.ticker;
    var list = Object.keys(state.markets).map(function (t) { return state.markets[t]; });
    list.sort(function (a, b) { return (num(b.volume_fp) || 0) - (num(a.volume_fp) || 0); });
    sel.innerHTML = '<option value="">Choose a market...</option>' + list.map(function (m) {
      return '<option value="' + esc(m.ticker) + '"' + (m.ticker === cur ? ' selected' : '') + '>' +
        esc(m.ticker) + ' - ' + esc((m.yes_sub_title || m.title || '')).slice(0, 70) + '</option>';
    }).join('');
  }

  function pickDetail(ticker) {
    var m = state.markets[ticker] || {};
    var series = m._series || seriesOf(ticker);
    state.detail.ticker = ticker; state.detail.series = series;
    if (!state.detail.buffer[ticker]) state.detail.buffer[ticker] = [];
    var sel = document.getElementById('detail-pick'); if (sel) sel.value = ticker;
    var h = document.getElementById('detail-title'); if (h) h.textContent = ticker + ' - ' + (m.title || '');
    document.getElementById('detail')?.scrollIntoView({behavior: 'smooth', block: 'start'});
    loadDetail();
  }

  function setupDetailControls() {
    var root = document.getElementById('detail'); if (!root) return;
    renderDetailSelect();
    document.getElementById('detail-pick').addEventListener('change', function (e) {
      if (e.target.value) pickDetail(e.target.value);
    });
    root.querySelectorAll('[data-mode]').forEach(function (b) {
      b.addEventListener('click', function () {
        state.detail.mode = b.getAttribute('data-mode');
        state.detail.len = null;
        root.querySelectorAll('[data-mode]').forEach(function (x) { x.classList.toggle('on', x === b); });
        fillLengths(); loadDetail();
      });
    });
    document.getElementById('detail-len').addEventListener('change', function () { loadDetail(); });
    root.querySelector('[data-mode="minutes"]').classList.add('on');
    fillLengths();
    if (state.chartTimer) clearInterval(state.chartTimer);
    state.chartTimer = setInterval(function () {
      if (!state.detail.ticker) return;
      if (state.detail.mode === 'seconds') sampleSeconds(); else loadCandles();
    }, 5000);
    setInterval(function () { if (state.detail.ticker) loadLiquidity(); }, 10000);
  }

  function fillLengths() {
    var sel = document.getElementById('detail-len'); if (!sel) return;
    var opts = LENGTHS[state.detail.mode];
    sel.innerHTML = opts.map(function (o, i) {
      return '<option value="' + o[1] + '"' + (i === 0 ? ' selected' : '') + '>' + esc(o[0]) + '</option>';
    }).join('');
  }

  function selectedLen() { return parseInt(document.getElementById('detail-len').value, 10); }

  function sampleSeconds() {
    var t = state.detail.ticker; if (!t) return;
    getJSON('/markets/' + t).then(function (r) {
      var m = r.market; state.markets[t] = m;
      var p = num(m.last_price_dollars);
      if (p !== null) {
        var buf = state.detail.buffer[t] || (state.detail.buffer[t] = []);
        buf.push({t: Date.now(), p: p});
        var cut = Date.now() - 3600 * 1000;
        while (buf.length && buf[0].t < cut) buf.shift();
      }
      drawChart(state.detail.buffer[t] || []);
      renderDetailStats(m);
    }).catch(function (e) { drawMessage('Could not read market: ' + e.message); });
  }

  function loadCandles() {
    var t = state.detail.ticker; if (!t) return;
    var mode = state.detail.mode, period = PERIOD[mode], len = selectedLen();
    var end = Math.floor(Date.now() / 1000), start = end - len;
    getJSON('/series/' + state.detail.series + '/markets/' + t + '/candlesticks',
      {start_ts: String(start), end_ts: String(end), period_interval: String(period)})
      .then(function (r) {
        var pts = (r.candlesticks || []).filter(function (c) { return c.price && c.price.close_dollars; })
          .map(function (c) { return {t: c.end_period_ts * 1000, p: num(c.price.close_dollars)}; });
        drawChart(pts, 'Candles: ' + (period === 1 ? '1 minute' : '60 minutes') + ' (close price)');
      })
      .catch(function (e) { drawMessage('Could not load candlesticks: ' + e.message + ' (CORS or API issue).'); });
    getJSON('/markets/' + t).then(function (r) { state.markets[t] = r.market; renderDetailStats(r.market); }).catch(function () {});
  }

  function loadDetail() {
    if (!state.detail.ticker) return;
    if (state.detail.mode === 'seconds') { sampleSeconds(); }
    else { loadCandles(); }
    loadLiquidity();
  }

  function renderDetailStats(m) {
    var el = document.getElementById('detail-stats'); if (!el || !m) return;
    el.innerHTML = kpi(fmtPrice(m.last_price_dollars) || '-', 'last YES price') +
      kpi(fmtPrice(m.yes_bid_dollars) || '-', 'YES bid') +
      kpi(fmtPrice(m.yes_ask_dollars) || '-', 'YES ask') +
      kpi(fmtNum(m.volume_fp) || '-', 'volume (contracts)') +
      kpi(fmtNum(m.open_interest_fp) || '-', 'open interest') +
      '<div class="kpi"><b>' + outcomeChip(m) + '</b><span>status</span></div>';
  }

  function loadLiquidity() {
    var t = state.detail.ticker; var el = document.getElementById('liquidity'); if (!el || !t) return;
    getJSON('/markets/' + t + '/orderbook', {depth: '10'}).then(function (r) {
      var ob = r.orderbook_fp || {};
      var yes = (ob.yes_dollars || []).slice().reverse();  // best bid first
      var no = (ob.no_dollars || []).slice().reverse();
      var bids = yes.map(function (lv) { return ['YES buy at ' + fmtPrice(lv[0]), fmtNum(lv[1], 2)]; });
      var asks = no.map(function (lv) { return ['YES sell at $' + (1 - num(lv[0])).toFixed(2), fmtNum(lv[1], 2)]; });
      var n = Math.max(bids.length, asks.length), rows = [];
      for (var i = 0; i < n; i++) rows.push([bids[i] ? bids[i][0] : '', bids[i] ? bids[i][1] : '', asks[i] ? asks[i][0] : '', asks[i] ? asks[i][1] : '']);
      el.innerHTML = '<p class="note">Contracts resting at each price, best first. YES sell prices are implied from NO bids (1 - NO bid), as documented at ' +
        '<a href="https://docs.kalshi.com/getting_started/orderbook_responses.md" target="_blank" rel="noopener">docs.kalshi.com orderbook responses</a>. ' +
        'Source: <a href="' + API + '/markets/' + esc(t) + '/orderbook" target="_blank" rel="noopener">orderbook API</a>.</p>' +
        table(['YES bids (contracts)', 'Contracts', 'YES asks (implied)', 'Contracts'], rows, [1, 3]);
    }).catch(function (e) {
      el.innerHTML = '<p class="muted">Liquidity unavailable: ' + esc(e.message) + '</p>';
    });
  }

  function drawMessage(msg) {
    var svg = document.getElementById('chart'); if (!svg) return;
    svg.innerHTML = '<text x="50%" y="50%" text-anchor="middle" fill="#5b6474" font-size="14">' + esc(msg) + '</text>';
  }

  function drawChart(pts, caption) {
    var svg = document.getElementById('chart'); if (!svg) return;
    var cap = document.getElementById('chart-caption');
    if (cap) cap.textContent = caption || (state.detail.mode === 'seconds'
      ? 'Live samples taken in this browser every 5 s since the page opened (last price)'
      : 'Candles from the Kalshi candlestick endpoint');
    var W = 960, H = 320, L = 60, R = 20, T = 14, B = 40;
    if (!pts.length) { drawMessage('No price points yet.'); return; }
    var t0 = pts[0].t, t1 = pts[pts.length - 1].t; if (t1 === t0) t1 = t0 + 1000;
    var ps = pts.map(function (q) { return q.p; });
    var lo = Math.max(0, Math.min.apply(null, ps) - 0.02), hi = Math.min(1, Math.max.apply(null, ps) + 0.02);
    if (hi - lo < 0.05) { var mid = (hi + lo) / 2; lo = Math.max(0, mid - 0.025); hi = Math.min(1, mid + 0.025); }
    function x(t) { return L + (t - t0) / (t1 - t0) * (W - L - R); }
    function y(p) { return T + (1 - (p - lo) / (hi - lo)) * (H - T - B); }
    var g = '';
    for (var k = 0; k <= 4; k++) {
      var pv = lo + (hi - lo) * k / 4, yy = y(pv);
      g += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + yy + '" y2="' + yy + '" stroke="#e2e6ee"/>';
      g += '<text x="' + (L - 6) + '" y="' + (yy + 4) + '" text-anchor="end" font-size="11" fill="#5b6474">$' + pv.toFixed(2) + '</text>';
    }
    for (var j = 0; j <= 4; j++) {
      var tv = t0 + (t1 - t0) * j / 4, xx = x(tv);
      g += '<text x="' + xx + '" y="' + (H - 14) + '" text-anchor="middle" font-size="11" fill="#5b6474">' + esc(tickLabel(tv)) + '</text>';
    }
    var d = pts.map(function (q, i) { return (i ? 'L' : 'M') + x(q.t).toFixed(1) + ' ' + y(q.p).toFixed(1); }).join(' ');
    var last = pts[pts.length - 1];
    svg.innerHTML = g +
      '<text x="14" y="' + (H / 2) + '" font-size="11" fill="#5b6474" transform="rotate(-90 14 ' + (H / 2) + ')" text-anchor="middle">YES contract price ($)</text>' +
      '<text x="' + (W / 2) + '" y="' + (H - 1) + '" font-size="11" fill="#5b6474" text-anchor="middle">time (' + esc(state.detail.mode) + ')</text>' +
      '<path d="' + d + '" fill="none" stroke="#1f6feb" stroke-width="2"/>' +
      '<circle cx="' + x(last.t) + '" cy="' + y(last.p) + '" r="4" fill="#1f6feb"/>';
  }

  function tickLabel(ms) {
    var d = new Date(ms), pad = function (n) { return (n < 10 ? '0' : '') + n; };
    if (state.detail.mode === 'seconds') return pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
    if (state.detail.mode === 'minutes') return pad(d.getHours()) + ':' + pad(d.getMinutes());
    return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + pad(d.getHours()) + ':00';
  }

  /* ---------- automated pipeline renderers (data/latest/** by CI collector) ---------- */
  function pipelineUrl(name) { return ROOT + '../data/latest/' + name; }
  function getPipeline(name) {
    return fetch(pipelineUrl(name)).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status + ' ' + name);
      return r.json();
    });
  }
  function pipelineFail(el, e, name) {
    el.innerHTML = '<p class="muted">Pipeline data unavailable (' + esc(name) + '): ' + esc(e.message) +
      '. The collector publishes it twice hourly to <code>data/latest/</code> on the main branch.</p>';
  }

  function renderTopEvents(el) {
    getPipeline('top_events.json').then(function (d) {
      var rows = (d.overall || []).map(function (e, i) {
        return [String(i + 1), esc(e.topic), esc(e.event_ticker), esc(e.title), String(e.market_count),
          fmtNum(e.volume_dollars_derived, 2), fmtNum(e.volume_24h_dollars_derived, 2),
          fmtNum(e.open_interest_dollars_derived, 2), link(e.source_url, 'API request')];
      });
      var html = table(['Rank', 'Topic', 'Event', 'Title', 'Markets',
        'Volume $ (derived)', 'Volume 24h $ (derived)', 'Open interest $ (derived)', 'Source'],
        rows, [0, 4, 5, 6, 7]);
      html += '<h3>Top events per topic</h3>';
      ['gas', 'elections', 'culture', 'crypto', 'golf'].forEach(function (t) {
        var tr = ((d.by_topic || {})[t] || []).slice(0, 10).map(function (e, i) {
          return [String(i + 1), esc(e.event_ticker), esc(e.title),
            fmtNum(e.volume_dollars_derived, 2), link(e.source_url, 'API request')];
        });
        html += '<h4>' + esc(t) + '</h4>' + table(
          ['Rank', 'Event', 'Title', 'Volume $ (derived)', 'Source'], tr, [0, 3]);
      });
      html += '<p class="note">Ranking metric: <code>' + esc(d.ranking_metric || '') + '</code>. ' +
        'Snapshot collected ' + esc(d.retrieved_at || '') + ' UTC from the official demo API. ' +
        'Derived values are arithmetic on the two linked API fields; nothing is inferred.</p>';
      el.innerHTML = html;
    }).catch(function (e) { pipelineFail(el, e, 'top_events.json'); });
  }

  function renderPipelineMarkets(el, cat) {
    if (!cat) { el.innerHTML = ''; return; }
    getPipeline('topic_' + cat + '.json').then(function (d) {
      var rows = (d.markets || []).slice(0, 40).map(function (m) {
        return [link(m.source_url, m.ticker), esc(m.title), fmtPrice(m.last_price_dollars),
          fmtPrice(m.yes_bid_dollars) + ' / ' + fmtPrice(m.yes_ask_dollars),
          fmtNum(m.volume_fp), fmtNum(m.open_interest_fp), outcomeChip(m), link(m.source_url, 'API request')];
      });
      el.innerHTML = '<p class="note">Topic <b>' + esc(cat) + '</b>: ' + esc(String(d.count || 0)) +
        ' open markets at snapshot ' + esc(d.retrieved_at || '') + ' UTC. Classification rule is stored per row in ' +
        '<a href="' + pipelineUrl('topic_' + cat + '.json') + '" target="_blank" rel="noopener">topic_' + esc(cat) + '.json</a>.</p>' +
        table(['Market', 'Title', 'Last', 'YES bid / ask', 'Volume (contracts)', 'Open interest', 'Status', 'Source'],
          rows, [2, 4, 5]);
    }).catch(function (e) { pipelineFail(el, e, 'topic_' + cat + '.json'); });
  }

  function renderPipelineResolved(el) {
    getPipeline('resolutions.json').then(function (d) {
      var rows = (d.resolutions || []).map(function (r) {
        return [link(r.source_url, r.ticker), esc(r.title), esc(r.topic),
          '<b>' + esc(String(r.result || '').toUpperCase()) + '</b>',
          esc(r.settlement_ts), esc(r.settlement_value_dollars), link(r.source_url, 'API request')];
      });
      el.innerHTML = table(['Market', 'Title', 'Topic', 'Result', 'Settled (UTC)',
        'Settlement value ($)', 'Source'], rows, [5]);
    }).catch(function (e) { pipelineFail(el, e, 'resolutions.json'); });
  }

  function renderPortfolioState(el) {
    getPipeline('portfolio.json').then(function (p) {
      var html = '';
      if (p.status !== 'ok') {
        html += '<div class="banner"><b>Not connected (' + esc(p.status || 'unknown') + '). ' +
          esc(p.note || '') + '</b></div>' +
          table(['Endpoint', 'Status', 'Source'],
            [['balance / positions / orders / fills / settlements',
              '<span class="flag unv">blank - credentials missing</span>',
              link('https://docs.kalshi.com/getting_started/api_keys', 'api_keys docs')],
             ['request signing (RSA-PSS SHA-256, official starter code)',
              '<span class="flag">implemented in scripts/kalshi_client.py</span>',
              link('https://github.com/Kalshi/kalshi-starter-code-python', 'starter code')],
             ['scheduled pull workflow',
              '<span class="flag">.github/workflows/kalshi-portfolio.yml (runs when secrets exist)</span>',
              link('https://docs.kalshi.com/getting_started/demo_env', 'demo env docs')]]);
        html += '<p class="note">To activate: create a demo-account API key (' +
          link('https://docs.kalshi.com/getting_started/demo_env', 'demo env guide') + '), then add repository secrets ' +
          '<code>KALSHI_KEY_ID</code> and <code>KALSHI_PRIVATE_KEY</code>. The hourly workflow fills these tables ' +
          'automatically. Values are never fabricated.</p>';
        el.innerHTML = html;
        return;
      }
      html += '<div class="banner ok">Connected to the demo account. Snapshot ' + esc(p.retrieved_at || '') + ' UTC.</div>';
      html += kpi(fmtNum(p.balance && p.balance.balance, 2) || '-', 'balance ($)');
      html += kpi((p.positions || []).length, 'positions');
      html += kpi((p.fills || []).length, 'fills');
      html += kpi((p.settlements || []).length, 'settlements');
      var posRows = (p.positions || []).map(function (o) {
        return [esc(o.ticker || o.market_ticker || ''), fmtNum(o.position || o.count || o.quantity),
          fmtNum(o.exposure), fmtPrice(o.market_exposure_dollars),
          link('https://external-api.demo.kalshi.co/trade-api/v2/portfolio/positions', 'API request')];
      });
      html += '<h3>Positions</h3>' + table(['Market', 'Net position', 'Exposure', 'Market exposure $', 'Source'], posRows, [1, 2, 3]);
      var catTotals = {};
      var fillRows = (p.fills || []).map(function (f) {
        var c = f.categorization || {};
        var bucket = c.price_bucket || 'unverified';
        catTotals[bucket] = (catTotals[bucket] || 0) + (num(f.count || f.count_fp) || 0);
        return [esc(f.fill_id || ''), esc(f.ticker || ''), esc(f.side || ''),
          fmtPrice(f.yes_price || f.yes_price_dollars), esc(f.count || f.count_fp),
          esc(c.price_bucket), esc(c.direction), esc(c.topic),
          link(f.source_url || 'https://external-api.demo.kalshi.co/trade-api/v2/portfolio/fills', 'API request')];
      });
      html += '<h3>Fills with automatic categorisation</h3>' +
        table(['Fill', 'Market', 'Side', 'YES price', 'Count', 'Price bucket', 'Direction', 'Topic', 'Source'],
          fillRows, [4]);
      var catRows = Object.keys(catTotals).map(function (k) { return [esc(k), fmtNum(catTotals[k])]; });
      html += '<h3>Volume by price bucket</h3>' + table(['Bucket', 'Contracts'], catRows, [1]);
      el.innerHTML = html;
    }).catch(function (e) { pipelineFail(el, e, 'portfolio.json'); });
  }

  function renderStrategies() {
    var S = [
      ['S1', 'Directional favorite', 'price_bucket=favorite (entry &gt; $0.90)',
       'Buy YES on high-probability outcomes near close; collect the $1 settlement on winners.',
       'Small edge per contract; a single loss wipes ~10 wins. Cap per-event exposure.',
       'https://docs.kalshi.com/getting_started/market_settlement'],
      ['S2', 'Longshot basket', 'price_bucket=longshot (entry &lt; $0.10)',
       'Buy many cheap YES contracts across events; positive skew, most expire worthless.',
       'Position size 1/10 of S1 per event. Only with settlement sources rated official.',
       'https://docs.kalshi.com/getting_started/market_settlement'],
      ['S3', 'Momentum on 1-minute candles', 'price movement &gt; 5c within 15 min with rising volume',
       'Enter in the move direction using the candlesticks feed; exit on the first opposite candle.',
       'Whipsaw risk in thin books. Require book depth &ge; 1,000 contracts at best price.',
       'https://docs.kalshi.com/api-reference/market/get-market-candlesticks'],
      ['S4', 'Liquidity provision', 'spread &ge; 3c and depth &le; 500 contracts at best bid',
       'Rest a bid 1c above best bid, capture the spread as the market converges.',
       'Adverse selection around news. Use self-trade prevention and cancel on status change.',
       'https://docs.kalshi.com/getting_started/orderbook_responses'],
      ['S5', 'Hold-to-settlement vs sell-before-close', 'topic + days-to-close buckets',
       'Compare realised results of holding to settlement against selling at last price.',
       'Settlement timing irregularities (see I-05/I-11). Prefer can_close_early markets.',
       'https://docs.kalshi.com/getting_started/market_lifecycle'],
      ['S6', 'Category rotation on dollar-volume rank', 'topic top-decile by derived dollar volume',
       'Concentrate risk in the most active events each day using the pipeline ranking.',
       'Volume is not direction. Combine with S1-S3 entries only.',
       'https://docs.kalshi.com/getting_started/quick_start_market_data']
    ];
    var rows = S.map(function (s) {
      return [esc(s[0]), esc(s[1]), esc(s[2]), esc(s[3]), esc(s[4]),
        '<span class="flag unv">proposed - not implemented</span>', link(s[5], 'source')];
    });
    return table(['ID', 'Strategy', 'Trade type / trigger', 'Rule', 'Risk controls', 'Status', 'Source'], rows);
  }

  function renderOrderTicket() {
    return '<div class="card" id="order-ticket">' +
      '<p class="note"><b>Dry run only.</b> This form composes the documented request body; it never sends anything. ' +
      'To execute on the demo account run <code>python scripts/trade_runner.py --dry-run</code> first, then without the flag ' +
      'once the strategy is approved (see the script header for its safety rules).</p>' +
      '<div class="controls">' +
      '<input id="ot-ticker" placeholder="market ticker, e.g. KXAAAGASW-26NOV26-GAS325" size="42">' +
      '<select id="ot-side"><option value="bid">bid (buy)</option><option value="ask">ask (sell)</option></select>' +
      '<input id="ot-count" type="number" min="1" value="1" style="width:80px" title="contracts">' +
      '<input id="ot-price" value="0.0100" style="width:90px" title="limit price, dollars">' +
      '<select id="ot-tif"><option>good_till_canceled</option><option>immediate_or_cancel</option><option>fill_or_kill</option></select>' +
      '</div>' +
      '<pre id="ot-preview" class="small"></pre>' +
      '<p class="note">Endpoint: <code>POST /trade-api/v2/portfolio/orders</code> with headers ' +
      '<code>KALSHI-ACCESS-KEY</code>, <code>KALSHI-ACCESS-SIGNATURE</code> (RSA-PSS SHA-256 base64 over ' +
      '<code>timestamp + &quot;POST&quot; + &quot;/trade-api/v2/portfolio/orders&quot;</code>), ' +
      '<code>KALSHI-ACCESS-TIMESTAMP</code> (ms). ' +
      link('https://docs.kalshi.com/getting_started/quick_start_create_order', 'order quick start') + ' ' +
      link('https://docs.kalshi.com/getting_started/api_environments', 'signing rules') + ' ' +
      link('https://docs.kalshi.com/getting_started/order_errors', 'error codes') + '</p></div>';
  }
  function setupOrderTicket() {
    var pre = document.getElementById('ot-preview'); if (!pre) return;
    function upd() {
      var body = {
        ticker: document.getElementById('ot-ticker').value || '&lt;ticker&gt;',
        side: document.getElementById('ot-side').value,
        count: document.getElementById('ot-count').value || '1',
        price: document.getElementById('ot-price').value || '0.0100',
        time_in_force: document.getElementById('ot-tif').value,
        self_trade_prevention_type: 'taker_at_cross',
        client_order_id: '(generate a fresh UUID per order)'
      };
      pre.textContent = 'POST ' + API + '/portfolio/orders\n\n' + JSON.stringify(body, null, 2);
    }
    ['ot-ticker', 'ot-side', 'ot-count', 'ot-price', 'ot-tif'].forEach(function (id) {
      var elx = document.getElementById(id); if (elx) elx.addEventListener('input', upd);
    });
    upd();
  }

  function renderPipelineFlags() {
    var rows = [
      ['I-11', 'API', 'The candlesticks endpoint at the older path shape /markets/{ticker}/candlesticks returns 404 on the demo deployment. The working official path is /series/{series_ticker}/markets/{ticker}/candlesticks with period_interval in minutes (1, 60, 1440). Verified live both ways 2026-11-20.', 'high',
        'https://docs.kalshi.com/api-reference/market/get-market-candlesticks'],
      ['I-12', 'Portfolio', 'Portfolio, fill, and order endpoints reject unauthenticated access. No demo API credentials were supplied to this project, so all account values remain blank and flagged. Discovery path: create demo API keys, add repo secrets KALSHI_KEY_ID / KALSHI_PRIVATE_KEY; the hourly workflow then fills the tables.', 'high',
        'https://docs.kalshi.com/getting_started/api_keys'],
      ['I-13', 'WebSockets', 'WebSocket connections require KALSHI-ACCESS-* auth headers at handshake. Browsers cannot attach headers to a WebSocket handshake, so a static page cannot stream WS data without a signed proxy. The dashboard therefore uses public REST polling (market data needs no auth) plus CI snapshots, and its banner says which mode is active.', 'medium',
        'https://docs.kalshi.com/getting_started/quick_start_websockets'],
      ['I-14', 'Environments', 'The verified snapshot in docs/data/verified.json was collected from the production endpoint, while the project brief specifies the demo endpoint. Both are official. The live panels and the automated pipeline now use the demo endpoint; the earlier snapshot rows keep their original production source links as provenance.', 'medium',
        'https://docs.kalshi.com/getting_started/api_environments'],
      ['I-15', 'Demo data', 'The demo exchange contains synthetic exchange-test series (for example KXDEMOFUTHOURLY hourly BTC demo markets and KXQUICKSETTLE test markets such as "1+1 = 2"). They rank high by volume in demo snapshots and must not be read as real-world markets.', 'medium',
        'https://external-api.demo.kalshi.co/trade-api/v2/markets?tickers=KXQUICKSETTLE-20NOV26H0530-2'],
      ['I-16', 'Ranking metric', 'The brief asks for highest dollar amount. The API publishes no dollar-volume field. The dashboard shows both the verbatim contracts ranking (verified snapshot) and a clearly labelled derived dollar volume (volume_fp x notional_value_dollars). The intended definition is an open question (Q on the Questions page).', 'medium',
        'https://docs.kalshi.com/api-reference/market/get-market-candlesticks']
    ];
    return table(['ID', 'Area', 'Finding', 'Severity', 'Source'], rows.map(function (r) {
      return [esc(r[0]), esc(r[1]), esc(r[2]), sevFlag(r[3]), link(r[4], 'source')];
    }));
  }

  function renderPipelineSources(el) {
    getPipeline('meta.json').then(function (m) {
      var rows = Object.keys(m.official_docs || {}).map(function (k) {
        return [esc(k), link(m.official_docs[k], m.official_docs[k]), 'official documentation'];
      });
      rows.unshift(['demo Trade API base', link(m.base_url, m.base_url),
        'all market-data rows in data/latest/ (collector request log: ' + (m.api_calls || '?') + ' calls this run)']);
      rows.push(['collector request log', link(pipelineUrl('meta.json'), 'data/latest/meta.json'),
        'every URL requested by the latest run, with status codes']);
      el.innerHTML = table(['Source', 'URL', 'Used for'], rows) +
        '<p class="note">Topic classification this run: ' + esc(JSON.stringify(m.topic_counts || {})) +
        (m.truncated ? ' | pagination truncation flags: ' + esc(JSON.stringify(m.truncated)) : '') + '</p>';
    }).catch(function (e) { pipelineFail(el, e, 'meta.json'); });
  }

  function renderVerifyReport(el) {
    getPipeline('verification_report.json').then(function (v) {
      var s = v.summary || {};
      var html = '<div class="grid">' +
        kpi(s.checked || 0, 'checks run') + kpi(s.passed || 0, 'passed') +
        kpi(s.hard_failures || 0, 'hard failures') + kpi(s.drift_notices || 0, 'price drift notices') + '</div>';
      if ((v.hard_failures || []).length) {
        html += table(['Check', 'Detail'], (v.hard_failures || []).map(function (f) {
          return [esc(f.check), esc(f.detail)];
        }));
      } else {
        html += '<p class="banner ok">Latest CI re-verification found no hard failures: every checked row matched the live API on its static fields and settlement results.</p>';
      }
      html += '<p class="note">Policy: ' + esc((v.policy && v.policy.static_fields) || '') + ' | ' +
        esc((v.policy && v.policy.dynamic_fields) || '') + '</p>';
      el.innerHTML = html;
    }).catch(function (e) { pipelineFail(el, e, 'verification_report.json'); });
  }

  /* ---------- decisions (suggestions page) ---------- */
  function setupDecisions() {
    document.querySelectorAll('.opts input[type=radio]').forEach(function (r) {
      r.addEventListener('change', function () {
        var saved = {}; try { saved = JSON.parse(localStorage.getItem(DECIDE_KEY) || '{}'); } catch (e) {}
        saved[r.name] = r.value; localStorage.setItem(DECIDE_KEY, JSON.stringify(saved));
        renderSnapshots();
        setupDecisions();
      });
    });
    var btn = document.getElementById('copy-decisions');
    if (btn) btn.addEventListener('click', function () {
      var saved = localStorage.getItem(DECIDE_KEY) || '{}';
      if (navigator.clipboard) navigator.clipboard.writeText(saved);
      btn.textContent = 'Copied decisions JSON';
    });
  }

  /* ---------- boot ---------- */
  function boot() {
    renderNav();
    fetch(ROOT + 'data/verified.json').then(function (r) { return r.json(); }).then(function (d) {
      DATA = d;
      renderSnapshots();
      setupDecisions();
      setupOrderTicket();
      var stamp = document.getElementById('snapshot-date');
      if (stamp) stamp.textContent = d.meta.snapshot_date_utc;
      if (document.getElementById('detail')) setupDetailControls();
      renderWatchlist();
      if (document.querySelector('[data-live]')) {
        refreshLive();
        setInterval(refreshLive, LIVE_EVERY);
      }
      refreshWatch();
      setInterval(refreshWatch, WATCH_EVERY);
    }).catch(function (e) {
      var el = document.getElementById('site-nav'); if (el) el.insertAdjacentHTML('afterend', '<p class="banner">Could not load verified data: ' + esc(e.message) + '</p>');
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
