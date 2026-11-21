/* Scripted flows: the handful of clicks a trader would make on a page, with the
 * resulting on-screen state recorded verbatim. A flow never decides pass/fail by
 * itself — it records what the page showed so the report can be read against the
 * brief. Selectors are the ids the pages ship today; a missing element is recorded
 * as null, not worked around.
 */

async function text(page, sel) {
  return page.evaluate((s) => {
    const el = document.querySelector(s);
    return el ? el.textContent.trim().replace(/\s+/g, " ").slice(0, 400) : null;
  }, sel).catch(() => null);
}
async function count(page, sel) {
  return page.evaluate((s) => document.querySelectorAll(s).length, sel).catch(() => null);
}
async function canvasInk(page, sel) {
  // how much of a canvas is drawn, and with how many colours (a chart with a price
  // line, grid and labels has more than an empty-state caption)
  return page.evaluate((s) => {
    const c = document.querySelector(s);
    if (!c) return null;
    try {
      const ctx = c.getContext("2d");
      const d = ctx.getImageData(0, 0, c.width, c.height).data;
      let n = 0; const seen = new Set();
      for (let i = 0; i < d.length; i += 4) {
        if (d[i + 3] !== 0) { n++; if (seen.size < 256) seen.add((d[i] << 16) | (d[i + 1] << 8) | d[i + 2]); }
      }
      return { w: c.width, h: c.height, painted_pixels: n, distinct_colors: seen.size };
    } catch (e) { return { error: String(e) }; }
  }, sel).catch(() => null);
}
async function rowsOf(page, sel, n) {
  return page.evaluate(([s, k]) => [...document.querySelectorAll(s)].slice(0, k).map((tr) =>
    [...tr.querySelectorAll("td")].map((td) => td.textContent.trim().replace(/\s+/g, " ").slice(0, 90))),
  [sel, n]).catch(() => null);
}

export const FLOWS = {
  /* Root live dashboard: discovery -> ranking -> track a market -> chart windows -> alerts */
  "dashboard.html": async (page, { sleep, shoot }) => {
    const out = {};
    const t0 = Date.now();
    try {
      await page.waitForSelector("#rankingTable button[data-ticker]", { timeout: 150000 });
      out.ranking_appeared_after_settle_ms = Date.now() - t0;
    } catch (e) { out.ranking_appeared_after_settle_ms = null; }
    out.discovery_status = await text(page, "#discoveryStatus");
    out.scan_status = await text(page, "#scanStatus");
    out.banner = await text(page, "#banner");
    out.ranking_rows = await count(page, "#rankingTable tbody tr");
    out.ranking_topics = await page.evaluate(() => {
      const m = {};
      document.querySelectorAll("#rankingTable tbody tr td:nth-child(2)").forEach((td) => {
        const k = td.textContent.trim(); m[k] = (m[k] || 0) + 1;
      });
      return m;
    }).catch(() => null);
    out.ranking_top5 = await rowsOf(page, "#rankingTable tbody tr", 5);
    out.discovery_headings = await page.evaluate(() =>
      [...document.querySelectorAll("#discoveryTable h3")].map((h) => h.textContent.trim())).catch(() => null);
    await shoot("1_ranking");
    if (out.ranking_rows) {
      await page.click("#rankingTable button[data-ticker]").catch((e) => { out.track_click_error = String(e).slice(0, 200); });
      try {
        await page.waitForFunction(() => {
          const el = document.querySelector("#obSummary");
          return el && el.textContent.trim().length > 0;
        }, null, { timeout: 40000 });
      } catch (e) { out.orderbook_timeout = true; }
      out.detail_title = await text(page, "#detailTitle");
      out.detail_meta = await text(page, "#detailMeta");
      out.ob_summary = await text(page, "#obSummary");
      out.ob_rows = await count(page, "#obTable tbody tr");
      out.trades_rows = await count(page, "#tradesTable tbody tr");
      await sleep(20000);
      out.chart_1h = await canvasInk(page, "#priceChart");
      out.depth_chart = await canvasInk(page, "#depthChart");
      await page.evaluate(() => document.querySelector("#priceChart").scrollIntoView({ block: "center" })).catch(() => {});
      await shoot("2_detail_1h");
      await page.click('[data-window="30"]').catch(() => {});
      await sleep(35000);
      out.chart_30s = await canvasInk(page, "#priceChart");
      await shoot("3_detail_30s");
      await page.click('[data-window="86400"]').catch(() => {});
      await sleep(8000);
      out.chart_24h = await canvasInk(page, "#priceChart");
      await shoot("4_detail_24h");
    }
    out.alert_count = await text(page, "#alertCount");
    out.alerts_all_rows = await count(page, "#alertsAll tr, #alertsAll .alert-row, #alertsAll li");
    out.alerts_roi_rows = await count(page, "#alertsROI tr, #alertsROI .alert-row, #alertsROI li");
    out.alerts_all_text = await text(page, "#alertsAll");
    out.res_poll_status = await text(page, "#resPollStatus");
    out.resolutions_logged_rows = await count(page, "#resolutionsTable tbody tr");
    out.seeded_resolution_rows = await count(page, "#seededResolutions tbody tr");
    await page.evaluate(() => { const a = document.querySelector("#alerts"); if (a) a.scrollIntoView({ block: "start" }); }).catch(() => {});
    await shoot("5_alerts");
    out.elapsed_ms = Date.now() - t0;
    return out;
  },

  /* Swing-alert console: two chat feeds. Records the state a first-time visitor gets,
   * then presses Start and records what three poll cycles produce. */
  "alerts.html": async (page, { sleep, shoot }) => {
    const out = {};
    out.before_start = {
      engine_status: await text(page, "#engineStatus"),
      run_button: await text(page, "#runBtn"),
      counts: await text(page, "#counts"),
      last_poll: await text(page, "#lastPoll"),
      universe_status: await text(page, "#universeStatus"),
      model_status: await text(page, "#modelStatus"),
      catalyst_status: await text(page, "#catalystStatus"),
      ci_status: await text(page, "#ciStatus"),
      banner: await text(page, "#banner"),
    };
    await shoot("1_first_visit");
    if (out.before_start.run_button === "Start") {
      await page.click("#runBtn").catch((e) => { out.start_click_error = String(e).slice(0, 200); });
    }
    await sleep(35000);
    out.after_35s = {
      engine_status: await text(page, "#engineStatus"),
      poll_note: await text(page, "#pollNote"),
      counts: await text(page, "#counts"),
      last_poll: await text(page, "#lastPoll"),
      count_all: await text(page, "#countAll"),
      count_roi: await text(page, "#countRoi"),
      feed_all_items: await count(page, "#feedAll > *"),
      feed_roi_items: await count(page, "#feedRoi > *"),
      feed_all_first: await text(page, "#feedAll > *:first-child"),
      feed_roi_first: await text(page, "#feedRoi > *:first-child"),
      universe_rows: await count(page, "#universeTables table tbody tr"),
      resolution_rows: await count(page, "#resolutionTable tbody tr"),
      backtest_rows: await count(page, "#backtestTable tbody tr"),
    };
    // open the first tracked market: chart + liquidity ladder + fills
    const clicked = await page.evaluate(() => {
      const el = document.querySelector("#universeTables table tbody tr [data-ticker], #universeTables table tbody tr a[href='#detail'], #universeTables table tbody tr button, #universeTables table tbody tr");
      if (!el) return null;
      el.click();
      return el.tagName + (el.getAttribute("data-ticker") ? ":" + el.getAttribute("data-ticker") : "");
    }).catch(() => null);
    out.detail_clicked = clicked;
    await sleep(12000);
    out.detail = {
      title: await text(page, "#detailTitle"),
      meta: await text(page, "#detailMeta"),
      chart: await canvasInk(page, "#chart"),
      chart_note: await text(page, "#chartNote"),
      depth: await canvasInk(page, "#depth"),
      depth_rows: await count(page, "#depthTable tbody tr"),
      depth_note: await text(page, "#depthNote"),
      trades_rows: await count(page, "#tradesTable tbody tr"),
      catalysts: await text(page, "#catalysts"),
    };
    await page.evaluate(() => { const d = document.querySelector("#feedAll"); if (d) d.scrollIntoView({ block: "center" }); }).catch(() => {});
    await shoot("2_feeds_after_start");
    await page.evaluate(() => { const d = document.querySelector("#detail"); if (d) d.scrollIntoView({ block: "start" }); }).catch(() => {});
    await shoot("3_detail");
    return out;
  },

  /* Data tracking page: live events -> select one -> chart ranges + ladders + resolutions */
  "data-tracking.html": async (page, { sleep, shoot }) => {
    const out = {};
    out.status_pill = await text(page, "#statusPill");
    out.status_body = await text(page, "#statusBody");
    out.event_rows = await count(page, "#eventsBody tr");
    out.first_rows = await rowsOf(page, "#eventsBody tr", 3);
    const clicked = await page.evaluate(() => {
      const el = document.querySelector("#eventsBody tr button, #eventsBody tr a[data-ticker], #eventsBody tr [data-ticker], #eventsBody tr");
      if (!el) return null;
      el.click();
      return el.tagName;
    }).catch(() => null);
    out.row_clicked = clicked;
    await sleep(10000);
    out.detail_title = await text(page, "#detailTitle");
    out.detail_meta = await text(page, "#detailMeta");
    out.chart_note = await text(page, "#chartNote");
    out.chart_default = await canvasInk(page, "#priceChart");
    out.range_buttons = await page.evaluate(() =>
      [...document.querySelectorAll("#rangeBtns button")].map((b) => b.textContent.trim())).catch(() => null);
    const nBtn = (out.range_buttons || []).length;
    out.chart_by_range = {};
    for (let i = 0; i < Math.min(nBtn, 4); i++) {
      await page.evaluate((k) => { const b = document.querySelectorAll("#rangeBtns button")[k]; if (b) b.click(); }, i).catch(() => {});
      await sleep(5000);
      out.chart_by_range[out.range_buttons[i]] = { ink: await canvasInk(page, "#priceChart"), note: await text(page, "#chartNote") };
    }
    out.yes_ladder_rows = await count(page, "#yesLadder tr");
    out.no_ladder_rows = await count(page, "#noLadder tr");
    out.resolution_rows = await count(page, "#resBody tr");
    out.portfolio_rows = await count(page, "#portfolioBody tr");
    out.trade_rows = await count(page, "#tradesBody tr");
    out.strategy_rows = await count(page, "#stratBody tr");
    out.flag_box = await text(page, "#flagBox");
    await page.evaluate(() => { const d = document.querySelector("#detailPane"); if (d) d.scrollIntoView({ block: "start" }); }).catch(() => {});
    await shoot("1_detail");
    return out;
  },

  /* Catalyst ledger: run status, in-browser watch, chart of a swing with its candidate links */
  "catalysts/index.html": async (page, { sleep, shoot }) => {
    const out = {};
    out.status_chips = await text(page, "#statusChips");
    out.status_note = await text(page, "#statusNote");
    out.last_run = await text(page, "#lastRun");
    out.ledger_rows = await count(page, "#ledger tbody tr");
    out.row_count_label = await text(page, "#rowCount");
    out.feed_rows = await count(page, "#feeds tbody tr");
    out.endpoint_rows = await count(page, "#endpoints tbody tr");
    out.strategy_rows = await count(page, "#strategies tbody tr");
    out.watch_state_before = await text(page, "#watchState");
    await page.click("#pollNow").catch((e) => { out.poll_click_error = String(e).slice(0, 200); });
    await sleep(15000);
    out.watch_state_after = await text(page, "#watchState");
    out.watch_log = await text(page, "#watchLog");
    out.watch_alerts = await text(page, "#watchAlerts");
    out.chart_title = await text(page, "#chartTitle");
    out.chart_state = await text(page, "#chartState");
    out.chart = await canvasInk(page, "#priceChart");
    out.chart_catalysts = await text(page, "#chartCatalysts");
    out.book_box = await text(page, "#bookBox");
    await page.click("#candlesBtn").catch(() => {});
    await sleep(8000);
    out.chart_state_after_candles = await text(page, "#chartState");
    out.chart_after_candles = await canvasInk(page, "#priceChart");
    await page.evaluate(() => { const d = document.querySelector("#chartCard"); if (d) d.scrollIntoView({ block: "start" }); }).catch(() => {});
    await shoot("1_chart");
    return out;
  },

  /* Trade ticket in paper mode: place one simulated order and read the journal back */
  "trades.html": async (page, { sleep, shoot }) => {
    const out = {};
    out.conn_status = await text(page, "#connStatus");
    out.banner = await text(page, "#banner");
    out.ticket_present = (await count(page, "#tradeTicker")) > 0;
    out.journal_rows_before = await count(page, "#journalBody tr");
    const ticker = await page.evaluate(async () => {
      try {
        const r = await fetch("data/latest/top_events.json", { cache: "no-store" });
        const j = await r.json();
        for (const evs of Object.values(j.by_topic || {})) for (const ev of evs || []) {
          for (const m of ev.top_markets || []) if (m.ticker) return m.ticker;
        }
      } catch (e) { return null; }
      return null;
    }).catch(() => null);
    out.ticker_used = ticker;
    if (out.ticket_present && ticker) {
      await page.fill("#tradeTicker", ticker).catch(() => {});
      await page.fill("#tradeCount", "3").catch(() => {});
      await page.fill("#tradePrice", "42").catch(() => {});
      await page.click("#placeOrderBtn").catch((e) => { out.place_click_error = String(e).slice(0, 200); });
      await sleep(3000);
      out.trade_result = await text(page, "#tradeResult");
      out.journal_rows_after = await count(page, "#journalBody tr");
      out.journal_first = await rowsOf(page, "#journalBody tr", 1);
      out.strategy_rows = await count(page, "#strategyBody tr");
      out.strategy_text = await text(page, "#strategyBody");
      // the journal must survive a reload (it is the only record of the simulated trade)
      await page.reload({ waitUntil: "domcontentloaded" }).catch(() => {});
      await sleep(5000);
      out.journal_rows_after_reload = await count(page, "#journalBody tr");
    }
    await shoot("1_after_paper_order");
    return out;
  },

  "portfolio.html": async (page) => ({
    conn_status: await text(page, "#connStatus"),
    banner: await text(page, "#banner"),
    perf_summary: await text(page, "#perfSummary"),
    strategy_rows: await count(page, "#strategyBody tr"),
    portfolio_body: await text(page, "#portfolioBody"),
  }),

  "live/index.html": async (page) => ({
    live_status: await text(page, "#liveStatus"),
    stat_grid: await text(page, "#statGrid"),
    coverage_note: await text(page, "#coverageNote"),
  }),
};
