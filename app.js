(() => {
  'use strict';
  const API = 'https://external-api.demo.kalshi.co/trade-api/v2';
  const DOCS = {
    markets: 'https://docs.kalshi.com/api-reference/market/get-markets',
    events: 'https://docs.kalshi.com/api-reference/events/get-events',
    book: 'https://docs.kalshi.com/api-reference/market/get-market-orderbook'
  };
  const TOPICS = ['Gas prices', 'Elections', 'Culture', 'Crypto', 'Golf'];
  const state = { markets: [], settled: [], events: new Map(), selectedTicker: '', selectedSnapshot: null, filter: 'All', search: '', history: new Map(), marketFetchOk: false, resolvedFetchOk: false, eventsFetchOk: false, chartTimer: null, toastTimer: null };
  const $ = (id) => document.getElementById(id);
  const escapeHTML = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const isSet = (v) => v !== null && v !== undefined && v !== '';
  const money = (value) => isSet(value) && Number.isFinite(Number(value)) ? '$' + Number(value).toFixed(2) : '—';
  const count = (value) => isSet(value) && Number.isFinite(Number(value)) ? Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 }) : '—';
  const officialMarketURL = (ticker) => `${API}/markets/${encodeURIComponent(ticker)}`;
  const sourceLink = (href, label = 'API ↗') => `<a class="source-link" href="${escapeHTML(href)}" target="_blank" rel="noreferrer">${label}</a>`;
  const marketTicker = (m) => m.ticker || '';
  const marketTitle = (m) => m.title || m.subtitle || m.ticker || 'Untitled market';
  const eventFor = (m) => state.events.get(m.event_ticker) || {};

  function topicFor(m) {
    const ev = eventFor(m);
    const words = `${ev.category || ''} ${ev.title || ''} ${ev.sub_title || ''} ${m.title || ''} ${m.subtitle || ''} ${m.ticker || ''} ${m.event_ticker || ''}`.toLowerCase();
    if (/\b(golf|pga|masters tournament|ryder cup|lpga)\b/.test(words)) return 'Golf';
    if (/\b(bitcoin|btc|ethereum|ether|crypto|cryptocurrency|solana|dogecoin|blockchain)\b/.test(words)) return 'Crypto';
    if (/\b(election|president|presidential|senate|senator|governor|congress|ballot|primary|vote|electoral)\b/.test(words)) return 'Elections';
    if (/\b(gas prices?|gasoline|regular gas|unleaded|henry hub|natural gas|gas pump)\b/.test(words)) return 'Gas prices';
    if (/\b(culture|pop culture|entertainment|celebrity|music|album|movie|film|television|tv show|box office|grammy|oscar|emmy|taylor swift|streaming)\b/.test(words)) return 'Culture';
    return '';
  }

  function getMarketArray(data) {
    return Array.isArray(data?.markets) ? data.markets : [];
  }
  function getEventArray(data) {
    return Array.isArray(data?.events) ? data.events : [];
  }
  async function getJSON(path) {
    const res = await fetch(`${API}${path}`, { headers: { Accept: 'application/json' }, cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }
  async function fetchPages(path, key, maxPages = 5) {
    const rows = [];
    let cursor = '';
    for (let i = 0; i < maxPages; i += 1) {
      const query = new URLSearchParams({ limit: '100' });
      if (cursor) query.set('cursor', cursor);
      const separator = path.includes('?') ? '&' : '?';
      const data = await getJSON(`${path}${separator}${query}`);
      rows.push(...(key === 'markets' ? getMarketArray(data) : getEventArray(data)));
      cursor = data.cursor || '';
      if (!cursor) break;
    }
    return rows;
  }
  async function loadEvents() {
    try {
      const events = await fetchPages('/events?status=open', 'events', 3);
      state.events.clear();
      const nested = [];
      events.forEach((event) => {
        if (event.event_ticker) state.events.set(event.event_ticker, event);
        if (Array.isArray(event.markets)) nested.push(...event.markets.map((m) => ({ ...m, event_ticker: m.event_ticker || event.event_ticker })));
      });
      state.eventsFetchOk = events.length > 0;
      return nested;
    } catch (_) {
      state.eventsFetchOk = false;
      return [];
    }
  }
  async function loadMarkets() {
    setConnection('checking');
    try {
      const [nested, markets] = await Promise.all([
        loadEvents(),
        fetchPages('/markets?status=open', 'markets', 5)
      ]);
      // Use the market endpoint as the canonical source for open market status and price fields;
      // event data is joined only for category/title discovery and never replaces market values.
      state.markets = markets;
      state.marketFetchOk = true;
      if (!state.events.size && nested.length) nested.forEach((m) => { if (m.event_ticker && !state.events.has(m.event_ticker)) state.events.set(m.event_ticker, { event_ticker: m.event_ticker, title: m.title, category: m.category }); });
      setConnection('connected');
      toast(`Updated ${markets.length.toLocaleString()} open market records from the demo API.`);
    } catch (error) {
      state.marketFetchOk = false;
      state.markets = [];
      setConnection('offline');
      toast(`Could not load demo market data: ${error.message}. Check browser access/CORS.`);
    }
    render();
  }
  async function loadResolved() {
    const pages = await Promise.allSettled([
      fetchPages('/markets?status=settled', 'markets', 2),
      fetchPages('/markets?status=closed', 'markets', 2)
    ]);
    const rows = [];
    state.resolvedFetchOk = pages.some((p) => p.status === 'fulfilled');
    pages.forEach((p) => { if (p.status === 'fulfilled') rows.push(...p.value); });
    const unique = new Map();
    rows.forEach((m) => { if (m.ticker && !unique.has(m.ticker)) unique.set(m.ticker, m); });
    state.settled = Array.from(unique.values());
    renderResolved();
  }
  function setConnection(status) {
    const el = $('connection-label');
    const dot = document.querySelector('.green-pulse');
    if (status === 'connected') { el.textContent = 'Demo API · connected'; dot.style.background = '#45c99b'; }
    else if (status === 'offline') { el.textContent = 'Demo API · unavailable'; dot.style.background = '#e3a34c'; }
    else { el.textContent = 'Demo API · checking'; dot.style.background = '#7c91a6'; }
  }
  function topicMarkup(m) {
    const topic = topicFor(m);
    return topic ? `<span class="topic-tag">${escapeHTML(topic)}</span>` : '<span class="topic-tag">Unmatched</span>';
  }
  function filteredMarkets() {
    const search = state.search.trim().toLowerCase();
    return state.markets.filter((m) => {
      const topic = topicFor(m);
      if (state.filter !== 'All' && topic !== state.filter) return false;
      if (!search) return true;
      const ev = eventFor(m);
      return `${marketTitle(m)} ${m.ticker} ${ev.title || ''} ${ev.category || ''}`.toLowerCase().includes(search);
    });
  }
  function sortByVolume(rows) {
    return [...rows].sort((a, b) => {
      const av = isSet(a.volume_24h_fp) ? Number(a.volume_24h_fp) : NaN;
      const bv = isSet(b.volume_24h_fp) ? Number(b.volume_24h_fp) : NaN;
      if (!Number.isFinite(av)) return Number.isFinite(bv) ? 1 : 0;
      if (!Number.isFinite(bv)) return -1;
      return bv - av;
    });
  }
  function marketRows(rows, detailed = false) {
    if (!rows.length) return `<tr><td colspan="${detailed ? 9 : 8}" class="empty-state">${state.marketFetchOk ? 'No matching open records in the API pages currently loaded.' : 'No official API market data received. Check the network and retry.'} ${sourceLink(DOCS.markets, 'Market API docs ↗')}</td></tr>`;
    return rows.map((m) => {
      const t = marketTicker(m);
      const title = marketTitle(m);
      const ev = eventFor(m);
      const link = officialMarketURL(t);
      const status = m.status || '';
      const openInterest = detailed ? `<td class="volume-cell">${count(m.open_interest_fp)}</td>` : '';
      return `<tr class="market-row" data-ticker="${escapeHTML(t)}" tabindex="0" aria-label="Select ${escapeHTML(title)}"><td><span class="market-name">${escapeHTML(title)}</span><span class="market-sub">${escapeHTML(t)}${ev.title ? ` · ${escapeHTML(ev.title)}` : ''}</span></td><td>${topicMarkup(m)}</td><td class="price-cell">${money(m.yes_bid_dollars)}</td><td class="price-cell">${money(m.yes_ask_dollars)}</td><td class="price-cell">${money(m.last_price_dollars)}</td><td class="volume-cell">${count(m.volume_24h_fp)}</td>${openInterest}<td><span class="status-tag ${status === 'open' ? 'status-open' : status === 'settled' ? 'status-settled' : 'status-closed'}">${escapeHTML(status || '—')}</span></td><td>${sourceLink(link)}</td></tr>`;
    }).join('');
  }
  function render() {
    const categorized = state.markets.filter((m) => TOPICS.includes(topicFor(m)));
    const openCount = state.markets.length;
    $('stat-open').textContent = state.marketFetchOk ? count(openCount) : '—';
    $('stat-open-note').textContent = state.marketFetchOk ? 'API records in loaded pages' : 'Awaiting official API data';
    $('stat-cats').textContent = state.marketFetchOk ? `${new Set(categorized.map(topicFor)).size} / 5` : '—';
    const ordered = sortByVolume(categorized);
    $('top-markets').innerHTML = marketRows(ordered.slice(0, 8), false);
    $('market-count-note').textContent = state.marketFetchOk ? `${categorized.length.toLocaleString()} tracked-topic matches · up to 500 open markets fetched` : 'No API data received';
    const filtered = sortByVolume(filteredMarkets());
    $('all-markets').innerHTML = marketRows(filtered, true);
    $('all-count-note').textContent = state.marketFetchOk ? `${filtered.length.toLocaleString()} records shown · ${state.markets.length.toLocaleString()} open records loaded` : 'No API data received';
    const options = [...categorized];
    if (state.selectedSnapshot && !options.some((m) => m.ticker === state.selectedSnapshot.ticker)) options.push(state.selectedSnapshot);
    $('chart-market').innerHTML = '<option value="">Select from live markets</option>' + options.map((m) => `<option value="${escapeHTML(m.ticker)}">${escapeHTML(marketTitle(m))} · ${escapeHTML(m.ticker)}${m.status && m.status !== 'open' ? ` (${escapeHTML(m.status)})` : ''}</option>`).join('');
    if (state.selectedTicker && options.some((m) => m.ticker === state.selectedTicker)) $('chart-market').value = state.selectedTicker;
    attachMarketRows();
    renderChart();
    renderResolved();
  }
  function attachMarketRows() {
    document.querySelectorAll('tr.market-row').forEach((row) => {
      const activate = () => selectMarket(row.dataset.ticker);
      row.addEventListener('click', activate);
      row.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); activate(); } });
    });
  }
  async function selectMarket(ticker) {
    if (!ticker) return;
    state.selectedTicker = ticker;
    $('chart-market').value = ticker;
    const market = state.markets.find((m) => m.ticker === ticker) || state.selectedSnapshot;
    state.selectedSnapshot = market || { ticker };
    $('book-title').textContent = market ? marketTitle(market) : ticker;
    $('book-status').textContent = 'Loading official order book…';
    $('yes-book').innerHTML = '<tr><td colspan="2" class="blank-cell">Loading…</td></tr>';
    $('no-book').innerHTML = '<tr><td colspan="2" class="blank-cell">Loading…</td></tr>';
    try {
      const data = await getJSON(`/markets/${encodeURIComponent(ticker)}/orderbook`);
      const book = data.orderbook_fp || data.orderbook || {};
      renderBookSide('yes-book', book.yes_dollars || book.yes || []);
      renderBookSide('no-book', book.no_dollars || book.no || []);
      $('book-status').textContent = `Updated ${new Date().toLocaleTimeString()}`;
      recordPrice(market?.last_price_dollars);
    } catch (error) {
      $('book-status').textContent = 'API unavailable';
      $('yes-book').innerHTML = '<tr><td colspan="2" class="blank-cell">Order book unavailable</td></tr>';
      $('no-book').innerHTML = '<tr><td colspan="2" class="blank-cell">Order book unavailable</td></tr>';
      toast(`Order book unavailable: ${error.message}`);
    }
    configureChartTimer();
    renderChart();
  }
  function renderBookSide(id, levels) {
    if (!Array.isArray(levels) || !levels.length) { const source = `${API}/markets/${encodeURIComponent(state.selectedTicker)}/orderbook`; $(id).innerHTML = `<tr><td colspan="3" class="blank-cell">No bid levels reported · ${sourceLink(source)}</td></tr>`; return; }
    const bestFirst = [...levels].reverse();
    const source = `${API}/markets/${encodeURIComponent(state.selectedTicker)}/orderbook`;
    $(id).innerHTML = bestFirst.map(([price, qty]) => `<tr><td class="price-cell">${money(price)}</td><td class="volume-cell">${count(qty)}</td><td>${sourceLink(source)}</td></tr>`).join('');
  }
  async function recordSelectedPrice() {
    if (!state.selectedTicker) return;
    try {
      const data = await getJSON(`/markets/${encodeURIComponent(state.selectedTicker)}`);
      const m = data.market || data;
      const price = m.last_price_dollars;
      recordPrice(price);
      state.selectedSnapshot = { ...(state.selectedSnapshot || {}), ...m };
      const idx = state.markets.findIndex((x) => x.ticker === state.selectedTicker);
      if (idx >= 0) state.markets[idx] = { ...state.markets[idx], ...m };
      if (m.status === 'closed' || m.status === 'settled') {
        const existing = state.settled.findIndex((x) => x.ticker === m.ticker);
        if (existing >= 0) state.settled[existing] = { ...state.settled[existing], ...m };
        else state.settled.unshift(m);
        renderResolved();
        $('book-status').textContent = m.status === 'settled' ? `Resolved · ${String(m.result || 'result not reported').toUpperCase()}` : 'Closed · awaiting reported settlement';
      }
      $('last-sample').textContent = isSet(price) ? `Last: ${money(price)} · ${new Date().toLocaleTimeString()}` : 'Latest price unavailable';
      renderChart();
    } catch (_) {
      $('last-sample').textContent = 'Price sample unavailable';
    }
  }
  async function refreshSelectedLifecycle() {
    if (!state.selectedTicker) return;
    try {
      const data = await getJSON(`/markets/${encodeURIComponent(state.selectedTicker)}`);
      const market = data.market || data;
      state.selectedSnapshot = { ...(state.selectedSnapshot || {}), ...market };
      if (market.status === 'closed' || market.status === 'settled') {
        const existing = state.settled.findIndex((x) => x.ticker === market.ticker);
        if (existing >= 0) state.settled[existing] = { ...state.settled[existing], ...market };
        else state.settled.unshift(market);
        $('book-status').textContent = market.status === 'settled' ? `Resolved · ${String(market.result || 'result not reported').toUpperCase()}` : 'Closed · awaiting reported settlement';
        renderResolved();
        render();
      }
    } catch (_) { /* A failed poll is shown as unavailable by the next price sample; do not infer status. */ }
  }
  function recordPrice(price) {
    if (!isSet(price) || !Number.isFinite(Number(price))) return;
    const arr = state.history.get(state.selectedTicker) || [];
    arr.push({ time: Date.now(), price: Number(price) });
    state.history.set(state.selectedTicker, arr.slice(-5000));
    $('chart-empty').style.display = 'none';
  }
  function configureChartTimer() {
    if (state.chartTimer) clearInterval(state.chartTimer);
    if (!state.selectedTicker) return;
    const unit = $('chart-unit').value;
    const ms = unit === 'seconds' ? 15000 : unit === 'minutes' ? 60000 : 300000;
    state.chartTimer = setInterval(recordSelectedPrice, ms);
  }
  function drawChart() {
    const canvas = $('price-chart');
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, rect.width * dpr);
    canvas.height = Math.max(1, rect.height * dpr);
    ctx.scale(dpr, dpr);
    const w = rect.width, h = rect.height;
    const pad = { l: 42, r: 10, t: 17, b: 25 };
    const plotW = w - pad.l - pad.r, plotH = h - pad.t - pad.b;
    ctx.font = '9px DM Sans, sans-serif'; ctx.fillStyle = '#9aa5b2'; ctx.strokeStyle = '#e9edf2'; ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i += 1) {
      const y = pad.t + plotH * i / 4;
      ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(w - pad.r, y); ctx.stroke();
      ctx.fillText(`$${(1 - i / 4).toFixed(2)}`, 2, y + 3);
    }
    const range = Number($('chart-range').value) * 1000;
    const now = Date.now();
    const rows = (state.history.get(state.selectedTicker) || []).filter((p) => now - p.time <= range);
    const unit = $('chart-unit').value;
    const divisions = 4;
    for (let i = 0; i <= divisions; i += 1) {
      const x = pad.l + plotW * i / divisions;
      const tickTime = new Date(now - (range * (divisions - i) / divisions));
      const options = unit === 'seconds'
        ? { hour: '2-digit', minute: '2-digit', second: '2-digit' }
        : unit === 'minutes'
          ? { hour: '2-digit', minute: '2-digit' }
          : { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' };
      const label = new Intl.DateTimeFormat(undefined, options).format(tickTime);
      ctx.fillText(label, Math.max(0, Math.min(w - 42, x - 18)), h - 5);
    }
    if (rows.length < 1) { $('chart-empty').style.display = ''; return; }
    $('chart-empty').style.display = 'none';
    ctx.beginPath(); ctx.strokeStyle = '#39b5c2'; ctx.lineWidth = 2;
    rows.forEach((point, i) => {
      const x = pad.l + ((point.time - (now - range)) / range) * plotW;
      const y = pad.t + (1 - Math.max(0, Math.min(1, point.price))) * plotH;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
    const last = rows[rows.length - 1];
    const lastX = pad.l + ((last.time - (now - range)) / range) * plotW;
    const lastY = pad.t + (1 - Math.max(0, Math.min(1, last.price))) * plotH;
    ctx.fillStyle = '#39b5c2'; ctx.beginPath(); ctx.arc(lastX, lastY, 3, 0, Math.PI * 2); ctx.fill();
  }
  function renderChart() { requestAnimationFrame(drawChart); }
  function renderResolved() {
    const rows = state.settled;
    $('stat-resolved').textContent = rows.length ? String(rows.filter((m) => ['yes', 'no'].includes(String(m.result || '').toLowerCase())).length) : state.resolvedFetchOk ? '0' : '—';
    if (!rows.length) {
      $('resolved-markets').innerHTML = `<tr><td colspan="7" class="empty-state">${state.resolvedFetchOk ? 'No settled/closed market records in the fetched pages; this sample is not exhaustive.' : 'No resolution API data received. Refresh to retry.'} ${sourceLink(DOCS.markets, 'Market API docs ↗')}</td></tr>`;
      $('resolved-count-note').textContent = state.resolvedFetchOk ? 'No records returned in the fetched pages' : 'No API data received';
      return;
    }
    $('resolved-markets').innerHTML = rows.map((m) => {
      const result = String(m.result || '').toLowerCase();
      const resultCell = ['yes', 'no'].includes(result) ? `<span class="status-tag ${result === 'yes' ? 'status-open' : 'status-closed'}">${result.toUpperCase()}</span>` : '<span class="topic-tag">Unverified / blank</span>';
      const marketSource = officialMarketURL(m.ticker);
      return `<tr><td><span class="market-name">${escapeHTML(marketTitle(m))}</span><span class="market-sub">${escapeHTML(m.ticker || '')}</span></td><td>${topicMarkup(m)}</td><td><span class="status-tag ${m.status === 'settled' ? 'status-settled' : 'status-closed'}">${escapeHTML(m.status || '—')}</span></td><td>${resultCell}</td><td>${escapeHTML(m.settlement_ts || '—')}</td><td>${sourceLink(marketSource, m.rules_primary ? 'API rules ↗' : 'Schema ↗')}</td><td>${sourceLink(marketSource)}</td></tr>`;
    }).join('');
    $('resolved-count-note').textContent = `${rows.length} settled/closed records in fetched pages · outcome shown only when API field is YES/NO`;
  }
  function toast(text) {
    const el = $('toast'); el.textContent = text; el.classList.add('show');
    clearTimeout(state.toastTimer); state.toastTimer = setTimeout(() => el.classList.remove('show'), 4200);
  }
  const PAGES = ['overview', 'markets', 'portfolio', 'resolved', 'strategies', 'suggestions', 'review'];
  function navigate(name) {
    if (!PAGES.includes(name)) name = 'overview';
    document.querySelectorAll('.page').forEach((p) => p.classList.toggle('active', p.id === name));
    document.querySelectorAll('.nav-link').forEach((a) => a.classList.toggle('active', a.dataset.nav === name));
    $('crumb-current').textContent = ({ overview: 'Overview', markets: 'Live markets', portfolio: 'Portfolio', resolved: 'Resolution log', strategies: 'Trade analysis', suggestions: 'Suggestions', review: 'Flagged for review' })[name];
    if (location.hash !== `#${name}`) history.replaceState(null, '', `#${name}`);
    if (name === 'resolved' && !state.settled.length) loadResolved();
    if (name === 'markets') render();
  }
  document.querySelectorAll('[data-nav]').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); navigate(a.dataset.nav); }));
  document.querySelectorAll('[data-go]').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); navigate(a.dataset.go); }));
  document.querySelectorAll('[data-filter]').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); state.filter = a.dataset.filter; document.querySelectorAll('.filter-pill').forEach((b) => b.classList.toggle('active', b.dataset.topic === state.filter)); navigate('markets'); render(); }));
  document.querySelectorAll('.filter-pill').forEach((b) => b.addEventListener('click', () => { state.filter = b.dataset.topic; document.querySelectorAll('.filter-pill').forEach((x) => x.classList.toggle('active', x === b)); render(); }));
  $('market-search').addEventListener('input', (e) => { state.search = e.target.value; render(); });
  $('chart-market').addEventListener('change', (e) => { if (e.target.value) selectMarket(e.target.value); else { state.selectedTicker = ''; if (state.chartTimer) clearInterval(state.chartTimer); $('chart-empty').style.display = ''; renderChart(); } });
  $('chart-unit').addEventListener('change', configureChartTimer);
  $('chart-range').addEventListener('change', renderChart);
  $('refresh-button').addEventListener('click', () => { loadMarkets(); loadResolved(); });
  $('markets-refresh').addEventListener('click', loadMarkets);
  $('resolved-refresh').addEventListener('click', loadResolved);
  window.addEventListener('resize', renderChart);
  window.addEventListener('hashchange', () => navigate(location.hash.replace('#', '') || 'overview'));
  let chosenSuggestion = '';
  try { chosenSuggestion = window.localStorage.getItem('kalshi-demo-review-choice') || ''; } catch (_) { chosenSuggestion = ''; }
  const updateSuggestionChoices = () => document.querySelectorAll('.suggestion-select').forEach((button) => {
    const selected = button.dataset.suggestion === chosenSuggestion;
    button.classList.toggle('selected', selected);
    button.setAttribute('aria-pressed', String(selected));
    button.textContent = selected ? 'Selected for review ✓' : 'Choose this option for review';
  });
  document.querySelectorAll('.suggestion-select').forEach((button) => button.addEventListener('click', () => {
    chosenSuggestion = chosenSuggestion === button.dataset.suggestion ? '' : button.dataset.suggestion;
    try {
      if (chosenSuggestion) window.localStorage.setItem('kalshi-demo-review-choice', chosenSuggestion);
      else window.localStorage.removeItem('kalshi-demo-review-choice');
    } catch (_) { /* The choice still updates for this page session if storage is disabled. */ }
    updateSuggestionChoices();
    toast(chosenSuggestion ? `Suggestion ${chosenSuggestion} selected for review only.` : 'Review selection cleared.');
  }));
  updateSuggestionChoices();
  const dateNode = document.querySelector('.eyebrow');
  if (dateNode) {
    const date = new Intl.DateTimeFormat('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }).format(new Date()).toUpperCase();
    dateNode.firstChild.textContent = date + ' ';
  }
  const initial = location.hash.replace('#', '');
  navigate(PAGES.includes(initial) ? initial : 'overview');
  loadMarkets();
  loadResolved();
  setInterval(() => { loadMarkets(); refreshSelectedLifecycle(); }, 60000);
})();
