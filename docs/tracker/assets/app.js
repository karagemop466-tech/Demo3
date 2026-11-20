/* Shared renderer for the Kalshi Demo Tracker. Reads verified JSON in ./data (relative to site root). */
(function () {
  var ROOT = document.body.getAttribute('data-root') || '';
  var PAGE = document.body.getAttribute('data-page') || '';
  var NAV = [
    ['../index.html', 'Main site', 'main'],
    ['index.html', 'Tracker home', 'home'],
    ['dashboard.html', 'Live dashboard', 'dashboard'],
    ['categories/gas.html', 'Gas', 'gas'],
    ['categories/elections.html', 'Elections', 'elections'],
    ['categories/culture.html', 'Culture', 'culture'],
    ['categories/crypto.html', 'Crypto', 'crypto'],
    ['categories/golf.html', 'Golf', 'golf'],
    ['resolutions.html', 'Resolutions', 'resolutions'],
    ['findings.html', 'Findings', 'findings'],
    ['portfolio.html', 'Portfolio & trades', 'portfolio'],
    ['suggestions.html', 'Suggestions', 'suggestions'],
    ['questions.html', 'Questions', 'questions'],
    ['flagged.html', 'Flagged for Review', 'flagged'],
    ['sources.html', 'Sources', 'sources']
  ];

  function esc(s) {
    return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function getJSON(path) {
    return fetch(ROOT + path, { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error(path + ' ' + r.status);
      return r.json();
    });
  }
  function money(s) {
    if (s === '' || s === null || s === undefined) return '';
    var n = Number(s);
    return isNaN(n) ? esc(s) : '$' + n.toFixed(2);
  }
  function count(s) {
    if (s === '' || s === null || s === undefined) return '';
    var n = Number(s);
    return isNaN(n) ? esc(s) : n.toLocaleString('en-US', { maximumFractionDigits: 2 });
  }
  function link(url, label) {
    if (!url) return '';
    return '<a href="' + esc(url) + '" target="_blank" rel="noopener">' + esc(label || url) + '</a>';
  }
  function vChip(ok) {
    return ok ? '<span class="chip ok">Verified</span>' : '<span class="chip warn">Unverified</span>';
  }
  function flagChip(f) {
    return f ? '<span class="chip warn">Flagged</span>' : '';
  }
  function table(headers, rows) {
    var h = '<table><thead><tr>' + headers.map(function (x) {
      return '<th' + (x[1] ? ' class="' + x[1] + '"' : '') + '>' + esc(x[0]) + '</th>';
    }).join('') + '</tr></thead><tbody>';
    if (!rows.length) {
      h += '<tr><td colspan="' + headers.length + '" class="muted">No entries.</td></tr>';
    }
    h += rows.join('') + '</tbody></table>';
    return h;
  }
  function row(cells) {
    return '<tr>' + cells.map(function (c) {
      var cls = '', val = c;
      if (c && typeof c === 'object') { cls = c.cls || ''; val = c.v; }
      return '<td' + (cls ? ' class="' + cls + '"' : '') + '>' + val + '</td>';
    }).join('') + '</tr>';
  }
  function header() {
    var items = NAV.map(function (n) {
      return '<a href="' + ROOT + n[0] + '" class="' + (n[2] === PAGE || (PAGE === 'category' && n[2] === document.body.getAttribute('data-topic')) ? 'on' : '') + '">' + n[1] + '</a>';
    }).join('');
    var el = document.querySelector('header.top');
    if (!el) {
      el = document.createElement('header');
      el.className = 'top';
      document.body.insertBefore(el, document.body.firstChild);
    }
    el.innerHTML = '<div class="bar"><a class="brand" href="' + ROOT + 'index.html">Kalshi Demo Tracker</a><nav class="menu">' + items + '</nav></div>';
    var f = document.createElement('footer');
    f.innerHTML = 'Demo environment data (mock funds). Verified against Kalshi official docs and the public demo API on 2026-11-20. Not investment advice. Values not confirmed from an official source are left blank and marked Unverified.';
    document.body.appendChild(f);
  }
  window.KT = { ROOT: ROOT, esc: esc, getJSON: getJSON, money: money, count: count, link: link, vChip: vChip, flagChip: flagChip, table: table, row: row, header: header };

  var TOPIC_LABEL = { gas: 'Gas prices', elections: 'Elections', culture: 'Culture', crypto: 'Crypto', golf: 'Golf' };

  function renderCategory(snap, topic) {
    var app = document.getElementById('app');
    var series = snap.series.filter(function (s) { return s.topic === topic; });
    var markets = snap.markets.filter(function (m) { return m.topic === topic; });
    var events = snap.events.filter(function (e) { return e.topic === topic; });
    var verified = series.filter(function (s) { return s.verified; }).length;
    var h = '<h1>' + TOPIC_LABEL[topic] + '</h1>';
    h += '<p class="lead">Series and markets for this topic, as returned by the Kalshi demo API. Every row links to the API response it came from. Volumes are contract counts (Kalshi does not report dollars here).</p>';
    h += '<div class="cards">' +
      '<div class="card"><div class="k">Series listed</div><div class="v">' + series.length + '</div></div>' +
      '<div class="card"><div class="k">Markets in snapshot</div><div class="v">' + markets.length + '</div></div>' +
      '<div class="card"><div class="k">Series verified</div><div class="v">' + verified + ' / ' + series.length + '</div></div>' +
      '<div class="card"><div class="k">Open markets</div><div class="v">' + markets.filter(function (m) { return m.status === 'active'; }).length + '</div></div></div>';
    h += '<p class="toolbar"><a href="../dashboard.html?topic=' + topic + '">Open live chart for ' + TOPIC_LABEL[topic] + ' &rarr;</a></p>';
    h += '<h2>Series</h2>';
    h += table([['Ticker'], ['Title'], ['Category / tags'], ['Volume (contracts)', 'num'], ['Frequency'], ['Last updated'], ['Settlement sources'], ['Contract terms'], ['Source (official API)'], ['Status']], series.map(function (s) {
      return row([
        { v: '<span class="mono">' + esc(s.ticker) + '</span>' },
        { v: esc(s.title) + (s.flag ? '<div class="small">' + esc(s.flag) + '</div>' : '') },
        { v: esc(s.category) + '<br>' + (s.tags && s.tags.length ? s.tags.map(function (t) { return '<span class="chip">' + esc(t) + '</span>'; }).join('') : '<span class="muted">none listed</span>') },
        { v: count(s.volume_contracts), cls: 'num' },
        { v: esc(s.frequency) },
        { v: esc(s.last_updated_ts) },
        { v: esc(s.settlement_sources) || '<span class="muted">blank (unverified)</span>' },
        { v: s.contract_terms_url ? link(s.contract_terms_url, 'PDF') : '<span class="muted">blank</span>' },
        { v: link(s.source_api, 'API response') },
        { v: vChip(s.verified) + flagChip(s.flag) }
      ]);
    }));
    h += '<h2>Events</h2>';
    h += table([['Event'], ['Sub-title'], ['Last updated'], ['Open markets found', 'num'], ['Source (official API)'], ['Status']], events.map(function (e) {
      return row([
        { v: '<span class="mono">' + esc(e.ticker) + '</span><br>' + esc(e.title) },
        { v: esc(e.sub_title) },
        { v: esc(e.last_updated_ts) },
        { v: String(e.markets_open_found), cls: 'num' },
        { v: link(e.source_api, 'API response') },
        { v: vChip(e.verified) }
      ]);
    }));
    h += '<h2>Markets (snapshot)</h2>';
    h += table([['Market'], ['Status'], ['Result'], ['Last price', 'num'], ['Yes bid', 'num'], ['Yes ask', 'num'], ['Volume (contracts)', 'num'], ['Open interest', 'num'], ['Source (official API)'], ['Check']], markets.map(function (m) {
      var res = m.result === 'yes' ? '<span class="chip ok">YES</span>' : m.result === 'no' ? '<span class="chip bad">NO</span>' : '<span class="muted">pending</span>';
      return row([
        { v: esc(m.title) + (m.option ? ' <span class="chip blue">' + esc(m.option) + '</span>' : '') + '<div class="small mono">' + esc(m.ticker) + '</div>' },
        { v: esc(m.status) },
        { v: res },
        { v: money(m.last_price_dollars), cls: 'num' },
        { v: money(m.yes_bid_dollars), cls: 'num' },
        { v: money(m.yes_ask_dollars), cls: 'num' },
        { v: count(m.volume_contracts), cls: 'num' },
        { v: count(m.open_interest_contracts), cls: 'num' },
        { v: link(m.source_api, 'API response') },
        { v: vChip(m.verified) + flagChip(m.flag) + (m.flag ? '<div class="small">' + esc(m.flag) + '</div>' : '') }
      ]);
    }));
    h += '<h2>What the data shows</h2>';
    h += '<div class="box">' + categoryFindings(topic, series, markets) + '</div>';
    app.innerHTML = h;
  }

  function categoryFindings(topic, series, markets) {
    var out = [];
    if (topic === 'gas') {
      out.push('<b>Only diesel series were found.</b> Both DIESEL (weekly) and DIESELM (monthly) show 0.00 volume and no open markets. No gasoline series was located. See <a href="../flagged.html">F-18</a> and <a href="../questions.html">Q-03</a>.');
    }
    if (topic === 'elections') {
      out.push('<b>Resolved example:</b> the three AK-AL House markets (HOUSEAKAL-26) finalized on 2026-11-19. Results: Republican YES, Democratic NO, Bill Hill NO. See <a href="../resolutions.html">Resolutions</a>.');
      out.push('<b>Thin open liquidity:</b> the Poland Sejm markets have yes bids summing to $0.06 and yes asks summing to $2.93 across three mutually exclusive outcomes (<a href="../flagged.html">F-15</a>).');
    }
    if (topic === 'culture') {
      out.push('<b>No activity:</b> both culture series show 0.00 volume, and no open markets were returned for the Grok series. Settlement-source lists include unrelated sources (<a href="../flagged.html">F-11</a>).');
    }
    if (topic === 'crypto') {
      out.push('<b>Low activity:</b> the airdrop series have small volume; AVAX has 40,427 contracts in total volume, but no open markets were returned in the checks. The Bitcoin market lists a DOT index as its settlement source (<a href="../flagged.html">F-06</a>). Perp-style product flagged (<a href="../flagged.html">F-04</a>).');
    }
    if (topic === 'golf') {
      out.push('<b>Highest series volume in the snapshot:</b> KXPGATOP40 (PGA Top 40 Finisher) with 1,791,408 contracts, yet no open markets were returned for it. Open head-to-head markets have zero volume (<a href="../flagged.html">F-14</a>); Ryder Cup quotes are stale (<a href="../flagged.html">F-13</a>).');
    }
    out.push('Coverage of this topic is partial when the series list was not fully paged (<a href="../flagged.html">F-21</a>).');
    return out.map(function (x) { return '<p style="margin:6px 0">' + x + '</p>'; }).join('');
  }

  function renderResolutions(snap) {
    var rs = snap.markets.filter(function (m) { return m.status === 'finalized'; });
    var h = '<h1>Resolutions</h1><p class="lead">Markets that have finalized on the demo API, with the result the API reports. A YES result pays $1 per YES contract and a NO result pays $1 per NO contract (<a href="https://docs.kalshi.com/getting_started/market_settlement.md" target="_blank" rel="noopener">Kalshi settlement docs</a>). The last traded price before settlement is not the payout.</p>';
    h += '<div class="cards"><div class="card"><div class="k">Finalized markets in snapshot</div><div class="v">' + rs.length + '</div></div>' +
      '<div class="card"><div class="k">Resolved YES</div><div class="v">' + rs.filter(function (m) { return m.result === 'yes'; }).length + '</div></div>' +
      '<div class="card"><div class="k">Resolved NO</div><div class="v">' + rs.filter(function (m) { return m.result === 'no'; }).length + '</div></div>' +
      '<div class="card"><div class="k">Pending (active)</div><div class="v">' + snap.markets.filter(function (m) { return m.status === 'active'; }).length + '</div></div></div>';
    h += table([['Market'], ['Topic'], ['Result'], ['Settlement value', 'num'], ['Last price before settlement', 'num'], ['Volume (contracts)', 'num'], ['Settled at (API)'], ['Source (official API)'], ['Check']], rs.map(function (m) {
      return row([
        { v: esc(m.title) + '<div class="small mono">' + esc(m.ticker) + '</div>' },
        { v: esc(TOPIC_LABEL[m.topic] || m.topic) },
        { v: m.result === 'yes' ? '<span class="chip ok">YES</span>' : '<span class="chip bad">NO</span>' },
        { v: money(m.settlement_value_dollars), cls: 'num' },
        { v: money(m.last_price_dollars), cls: 'num' },
        { v: count(m.volume_contracts), cls: 'num' },
        { v: esc(m.settlement_ts) },
        { v: link(m.source_api, 'API response') },
        { v: vChip(m.verified) + (m.flag ? '<div class="small">' + esc(m.flag) + '</div>' : '') }
      ]);
    }));
    h += '<h2>Rule text (as returned by the API)</h2><div class="box">' + rs.map(function (m) {
      return '<p style="margin:6px 0"><span class="mono">' + esc(m.ticker) + '</span>: ' + esc(m.rules_primary) + '</p>';
    }).join('') + '</div>';
    document.getElementById('app').innerHTML = h;
  }

  function renderFlags(data) {
    var h = '<h1>Flagged for Review</h1><p class="lead">Irregularities, unverified items and open limits. They are published so you can review them and request changes. None of them blocks the site from going live.</p>';
    h += table([['ID'], ['Area'], ['Item'], ['Irregularity / detail'], ['Source (official or as cited)'], ['Status']], data.flags.map(function (f) {
      return row([
        { v: '<span class="mono">' + esc(f.id) + '</span>' },
        { v: esc(f.area) },
        { v: '<b>' + esc(f.item) + '</b>' },
        { v: esc(f.irregularity) },
        { v: link(f.source, 'Source') },
        { v: '<span class="chip warn">' + esc(f.status) + '</span>' }
      ]);
    }));
    document.getElementById('app').innerHTML = h;
  }

  function renderSources(data) {
    var h = '<h1>Sources</h1><p class="lead">Kalshi official docs and demo API responses used on this site. "Fetched" means the page text was read on 2026-11-20; "Referenced" means the official page links to it but it was not read.</p>';
    h += table([['ID'], ['Title'], ['Owner'], ['Link'], ['Status']], data.sources.map(function (s) {
      return row([
        { v: '<span class="mono">' + esc(s.id) + '</span>' },
        { v: esc(s.title) },
        { v: esc(s.owner) },
        { v: link(s.url, s.url) },
        { v: s.status.indexOf('Fetched') === 0 ? '<span class="chip ok">' + esc(s.status) + '</span>' : '<span class="chip">' + esc(s.status) + '</span>' }
      ]);
    }));
    document.getElementById('app').innerHTML = h;
  }

  function renderQuestions(data) {
    var h = '<h1>Questions, information and answers</h1><p class="lead">What must be settled before a decision is reasonable: what we know (with source), what is missing, and how to get it.</p>';
    var counts = {};
    data.questions.forEach(function (q) { counts[q.status] = (counts[q.status] || 0) + 1; });
    h += '<div class="cards"><div class="card"><div class="k">Total questions</div><div class="v">' + data.questions.length + '</div></div>' +
      '<div class="card"><div class="k">Blocked</div><div class="v">' + data.questions.filter(function (q) { return q.status === 'Blocked'; }).length + '</div></div>' +
      '<div class="card"><div class="k">Open</div><div class="v">' + data.questions.filter(function (q) { return q.status === 'Open'; }).length + '</div></div>' +
      '<div class="card"><div class="k">Partial / answered</div><div class="v">' + data.questions.filter(function (q) { return q.status.indexOf('Partial') === 0 || q.status.indexOf('Answered') === 0; }).length + '</div></div></div>';
    h += table([['ID'], ['Question'], ['Known (with source)'], ['Missing'], ['How to get it'], ['Status']], data.questions.map(function (q) {
      return row([
        { v: '<span class="mono">' + esc(q.id) + '</span>' },
        { v: '<b>' + esc(q.question) + '</b>' },
        { v: esc(q.known) },
        { v: esc(q.missing) },
        { v: esc(q.how_to_get) },
        { v: '<span class="chip ' + (q.status === 'Blocked' ? 'bad' : q.status === 'Open' ? 'warn' : 'blue') + '">' + esc(q.status) + '</span>' }
      ]);
    }));
    document.getElementById('app').innerHTML = h;
  }

  function renderSuggestions(data) {
    var key = 'kt-suggestion-choices-v1';
    var saved = {};
    try { saved = JSON.parse(localStorage.getItem(key) || '{}'); } catch (e) { saved = {}; }
    var h = '<h1>Suggestions — decision board</h1><p class="lead">Improvements to decision-making. Nothing here is implemented. Pick an option for each item; choices stay in this browser only. You decide which paths go ahead before any change is made.</p>';
    h += '<div class="notice">' + esc(data.meta.note) + '</div>';
    h += '<p class="toolbar"><button id="clear-choices">Clear my choices</button><span class="muted" id="choice-count"></span></p>';
    h += table([['ID'], ['Suggestion'], ['Detail'], ['Impact'], ['Effort'], ['Risk'], ['Your choice']], data.suggestions.map(function (s) {
      var opts = s.options.map(function (o, i) {
        var id = s.id + '-' + i;
        return '<label><input type="radio" name="' + esc(s.id) + '" value="' + esc(o) + '"' + (saved[s.id] === o ? ' checked' : '') + '> ' + esc(o) + '</label>';
      }).join('');
      return row([
        { v: '<span class="mono">' + esc(s.id) + '</span>' },
        { v: '<b>' + esc(s.title) + '</b>' },
        { v: esc(s.detail) },
        { v: esc(s.impact) },
        { v: esc(s.effort) },
        { v: esc(s.risk) },
        { v: '<div class="dec">' + opts + '</div>' }
      ]);
    }));
    document.getElementById('app').innerHTML = h;
    function refresh() {
      var n = Object.keys(saved).length;
      document.getElementById('choice-count').textContent = n + ' of ' + data.suggestions.length + ' items have a choice (saved in this browser).';
    }
    document.getElementById('app').addEventListener('change', function (ev) {
      if (ev.target && ev.target.type === 'radio') {
        saved[ev.target.name] = ev.target.value;
        localStorage.setItem(key, JSON.stringify(saved));
        refresh();
      }
    });
    document.getElementById('clear-choices').addEventListener('click', function () {
      saved = {};
      localStorage.removeItem(key);
      document.querySelectorAll('input[type=radio]').forEach(function (r) { r.checked = false; });
      refresh();
    });
    refresh();
  }

  function renderHome(snap, flags) {
    var n = snap.series.length, verified = snap.series.filter(function (s) { return s.verified; }).length;
    var h = '<h1>Kalshi Demo Tracker</h1>';
    h += '<p class="lead">A plain-English dashboard for Kalshi demo-environment markets on five topics: gas prices, elections, culture, crypto and golf. Every table row links to the Kalshi API response it came from. Anything not confirmed from an official source is left blank and marked Unverified.</p>';
    h += '<div class="cards">' +
      '<div class="card"><div class="k">Series tracked</div><div class="v">' + n + '</div></div>' +
      '<div class="card"><div class="k">Series verified</div><div class="v">' + verified + ' / ' + n + '</div></div>' +
      '<div class="card"><div class="k">Markets in snapshot</div><div class="v">' + snap.markets.length + '</div></div>' +
      '<div class="card"><div class="k">Finalized (resolved)</div><div class="v">' + snap.markets.filter(function (m) { return m.status === 'finalized'; }).length + '</div></div>' +
      '<div class="card"><div class="k">Flagged for review</div><div class="v">' + flags.flags.length + '</div></div>' +
      '<div class="card"><div class="k">Trades placed</div><div class="v">0</div><div class="small"><a href="portfolio.html">Blocked: needs demo API key</a></div></div></div>';
    h += '<div class="notice bad"><b>Trading and portfolio are blocked.</b> Kalshi\'s account endpoints need a signed API key from a logged-in demo account. This session has no key, so no trades were placed and no portfolio performance is shown. See <a href="questions.html">Q-01</a>.</div>';
    h += '<div class="notice">Demo prices may not reflect real markets (Kalshi docs). Demo funds only.</div>';
    h += '<h2>Executive summary</h2><div class="box">' +
      '<p style="margin:6px 0"><b>1. What is verified.</b> 19 series and 12 markets were read from Kalshi\'s demo API on 2026-11-20. The API reports volume as contracts, not dollars.</p>' +
      '<p style="margin:6px 0"><b>2. Resolutions.</b> The AK-AL House markets (HOUSEAKAL-26) finalized on 2026-11-19: Republican YES; Democratic NO; Bill Hill NO.</p>' +
      '<p style="margin:6px 0"><b>3. Liquidity is thin.</b> Half of the 12 markets have zero or about one contract of volume (the Ryder Cup and golf head-to-head markets); the Poland Sejm yes bids sum to $0.06 across three exclusive outcomes.</p>' +
      '<p style="margin:6px 0"><b>4. Gas is the weakest topic.</b> Only diesel series exist in the snapshot, with no markets and no gasoline series found.</p>' +
      '<p style="margin:6px 0"><b>5. Trading and strategy analysis cannot be done yet.</b> The owner must provide a demo API key or decide an alternative (Q-01, Q-13).</p>' +
      '<p style="margin:6px 0"><b>6. Irregularities.</b> '+ flags.flags.length + ' items are published on the <a href="flagged.html">Flagged for Review</a> page, including placeholder values, mismatched settlement sources and stale quotes.</p>' +
      '</div>';
    h += '<h2>Browse by category</h2><div class="cards">' +
      ['gas', 'elections', 'culture', 'crypto', 'golf'].map(function (t) {
        var c = snap.series.filter(function (s) { return s.topic === t; }).length;
        return '<div class="card"><div class="k">' + TOPIC_LABEL[t] + '</div><div class="v"><a href="categories/' + t + '.html">' + c + ' series &rarr;</a></div></div>';
      }).join('') + '</div>';
    h += '<h2>Pages</h2><div class="cards">' +
      '<div class="card"><b><a href="dashboard.html">Live dashboard</a></b><div class="small">Price chart by time window, orderbook depth and liquidity. Calls the demo API from your browser.</div></div>' +
      '<div class="card"><b><a href="resolutions.html">Resolutions</a></b><div class="small">Finalized markets with YES or NO results.</div></div>' +
      '<div class="card"><b><a href="findings.html">Findings and analysis</a></b><div class="small">What the data does and does not show.</div></div>' +
      '<div class="card"><b><a href="questions.html">Questions</a></b><div class="small">What is known, what is missing, and how to get it.</div></div>' +
      '<div class="card"><b><a href="suggestions.html">Suggestions</a></b><div class="small">Improvements to choose from. Nothing is implemented without your choice.</div></div>' +
      '<div class="card"><b><a href="flagged.html">Flagged for Review</a></b><div class="small">Irregularities and unverified items with source links.</div></div>' +
      '<div class="card"><b><a href="sources.html">Sources</a></b><div class="small">Official Kalshi docs and API responses used.</div></div>' +
      '</div>';
    document.getElementById('app').innerHTML = h;
  }

  function renderFindings(snap) {
    var h = '<h1>Findings and analysis</h1><p class="lead">What the verified data shows, and what it cannot show yet. Every number links to its source in the tables.</p>';
    h += '<h2>Volume concentration</h2><div class="box">';
    var top = snap.series.slice().sort(function (a, b) { return Number(b.volume_contracts) - Number(a.volume_contracts); }).slice(0, 8);
    h += table([['Series'], ['Topic'], ['Volume (contracts)', 'num'], ['Open markets in snapshot', 'num'], ['Source (official API)']], top.map(function (s) {
      var open = snap.markets.filter(function (m) { return m.event_ticker && m.event_ticker.indexOf(s.ticker) === 0 && m.status === 'active'; }).length;
      return row([
        { v: '<span class="mono">' + esc(s.ticker) + '</span> ' + esc(s.title) },
        { v: esc(TOPIC_LABEL[s.topic]) },
        { v: count(s.volume_contracts), cls: 'num' },
        { v: String(open), cls: 'num' },
        { v: link(s.source_api, 'API response') }
      ]);
    }));
    h += '<p class="muted" style="margin-top:8px">Series volume is cumulative across all events in the series, including closed ones. The open-market count is from the markets checked; it is not a full count (<a href="flagged.html">F-21</a>).</p></div>';
    h += '<h2>Liquidity at the top of the book (Poland Sejm, PIS)</h2><div class="box">' +
      '<p>Orderbook from the demo API: YES bids at $0.01 (1.00 contract) and $0.02 (1.00 contract); NO bid at $0.01 (1.00 contract). Source: <a href="' + snap.orderbooks[0].captured_from + '" target="_blank" rel="noopener">orderbook response</a>. A YES bid at X is the same as a NO ask at 1 − X (Kalshi orderbook doc), so the YES ask here is $0.99.</p>' +
      '<p>Mutually exclusive outcomes should not sum above $1 for asks or below $1 for bids. Here, last prices sum to $1.06 and yes asks to $2.93 (<a href="flagged.html">F-15</a>). Quotes are too thin to read as probabilities.</p></div>';
    h += '<h2>Resolution behaviour</h2><div class="box"><p>Three AK-AL House markets finalized. The one with last price $0.99 (Democratic) resolved NO. The last traded price is not the payout (<a href="https://docs.kalshi.com/getting_started/market_settlement.md" target="_blank" rel="noopener">Kalshi settlement doc</a>). Any strategy test must use the result, not the last price.</p></div>';
    h += '<h2>What we cannot analyze yet</h2><div class="box"><ul style="margin:4px 0 0 18px;padding:0">' +
      '<li>Our own trades and their performance: none placed (<a href="questions.html">Q-01</a>, <a href="portfolio.html">Portfolio &amp; trades</a>).</li>' +
      '<li>Trade categories and strategy results: no trade history to categorize.</li>' +
      '<li>Dollar-value ranking: the API reports contracts only (<a href="flagged.html">F-16</a>).</li>' +
      '<li>Gasoline prices: no series found (<a href="flagged.html">F-18</a>).</li>' +
      '<li>Fees: fee type is quadratic on every series, but the fee schedule has not been read (<a href="questions.html">Q-12</a>).</li>' +
      '</ul></div>';
    document.getElementById('app').innerHTML = h;
  }

  function renderPortfolio() {
    var h = '<h1>Portfolio &amp; trades</h1>';
    h += '<div class="notice bad"><b>Blocked. No trades have been placed and no portfolio data is shown.</b></div>';
    h += '<p class="lead">Kalshi\'s portfolio, balance, order and fill endpoints require a signed API key pair. The key is created on a logged-in Kalshi demo account. This session was not given a key, so it cannot read a demo portfolio or place demo orders.</p>';
    h += '<h2>What is needed to unblock</h2><div class="box"><ol style="margin:4px 0 0 18px;padding:0">' +
      '<li>Create a demo API key on the Kalshi demo account (Account Settings → API Keys). Source: <a href="https://docs.kalshi.com/getting_started/api_keys" target="_blank" rel="noopener">API keys doc</a>.</li>' +
      '<li>Provide the key through a secure channel. It must not be pasted into the repo or chat.</li>' +
      '<li>Decide risk limits (<a href="questions.html">Q-13</a>) and the trade-execution option (<a href="suggestions.html">SG-04</a>).</li></ol></div>';
    h += '<h2>Trade categories and strategy (framework only)</h2>';
    h += table([['Category'], ['What we would record'], ['Trades so far'], ['Result'], ['Source']], [
      row([{ v: 'Gas prices' }, { v: 'Entry price, size, result, fees' }, { v: '0' }, { v: '' }, { v: link('https://docs.kalshi.com/getting_started/market_settlement.md', 'Settlement doc') }]),
      row([{ v: 'Elections' }, { v: 'Entry price, size, result, fees' }, { v: '0' }, { v: '' }, { v: link('https://docs.kalshi.com/getting_started/market_settlement.md', 'Settlement doc') }]),
      row([{ v: 'Culture' }, { v: 'Entry price, size, result, fees' }, { v: '0' }, { v: '' }, { v: link('https://docs.kalshi.com/getting_started/market_settlement.md', 'Settlement doc') }]),
      row([{ v: 'Crypto' }, { v: 'Entry price, size, result, fees' }, { v: '0' }, { v: '' }, { v: link('https://docs.kalshi.com/getting_started/market_settlement.md', 'Settlement doc') }]),
      row([{ v: 'Golf' }, { v: 'Entry price, size, result, fees' }, { v: '0' }, { v: '' }, { v: link('https://docs.kalshi.com/getting_started/market_settlement.md', 'Settlement doc') }])
    ]);
    h += '<p class="muted" style="margin-top:8px">Results are blank because no trades exist. No strategy performance is claimed.</p>';
    document.getElementById('app').innerHTML = h;
  }

  function renderHomeLoad() {
    Promise.all([getJSON('data/snapshot.json'), getJSON('data/flags.json')]).then(function (r) {
      renderHome(r[0], r[1]);
    }).catch(showErr);
  }
  function showErr(e) {
    document.getElementById('app').innerHTML = '<div class="notice bad">Could not load data: ' + esc(e.message) + '</div>';
  }

  document.addEventListener('DOMContentLoaded', function () {
    header();
    var app = document.getElementById('app');
    if (!app) return;
    if (PAGE === 'home') return renderHomeLoad();
    if (PAGE === 'category') return getJSON('data/snapshot.json').then(function (s) { renderCategory(s, document.body.getAttribute('data-topic')); }).catch(showErr);
    if (PAGE === 'resolutions') return getJSON('data/snapshot.json').then(renderResolutions).catch(showErr);
    if (PAGE === 'findings') return getJSON('data/snapshot.json').then(renderFindings).catch(showErr);
    if (PAGE === 'flagged') return getJSON('data/flags.json').then(renderFlags).catch(showErr);
    if (PAGE === 'sources') return getJSON('data/sources.json').then(renderSources).catch(showErr);
    if (PAGE === 'questions') return getJSON('data/questions.json').then(renderQuestions).catch(showErr);
    if (PAGE === 'suggestions') return getJSON('data/suggestions.json').then(renderSuggestions).catch(showErr);
    if (PAGE === 'portfolio') return renderPortfolio();
  });
})();
