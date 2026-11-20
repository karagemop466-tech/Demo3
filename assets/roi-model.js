/* Kalshi Demo Tracker — published high-ROI screen + measured demo context.
 *
 * Loads data/latest/roi_model.json (built by model/build_roi_model.py from the committed
 * demo snapshots only) and exposes KD.roiScore(alert) for the two alert chats.
 *
 * What this is: a deterministic, documented screen for which swing alerts a trader should
 * look at first, plus the measured frequencies behind it on the demo data.
 * What this is NOT: a validated return model. The snapshot cannot support calibration
 * (see calibration_feasibility in the JSON) and the demo environment is mock funds.
 * The chat says so on every row; nothing here is presented as a forecast.
 *
 * Field semantics: https://docs.kalshi.com/api-reference/market/get-markets
 * Settlement/payout: https://docs.kalshi.com/getting_started/market_settlement
 */
(function () {
  "use strict";
  var KD = window.KD = window.KD || {};
  var MODEL_URL = "data/latest/roi_model.json";
  var DEFAULTS = { min_abs_swing_dollars: 0.10, min_move_pct_of_prior: 0.10 };

  function num(x) {
    var v = Number(x);
    return (x === null || x === undefined || x === "" || isNaN(v)) ? null : v;
  }

  function bandFor(model, prior) {
    var bands = (model.measured && model.measured.up_swing_by_prior_band) || [];
    for (var i = 0; i < bands.length; i++) {
      var b = bands[i], lo = b.prior_band[0], hi = b.prior_band[1];
      if (prior >= lo && prior < hi) return b;
    }
    return null;
  }
  function topicFor(model, topic) {
    var rows = (model.measured && model.measured.by_topic) || [];
    for (var i = 0; i < rows.length; i++) { if (rows[i].topic === topic) return rows[i]; }
    return null;
  }

  /**
   * Score one swing alert. Returns { signal, basis, stats, id }.
   * `basis` is rendered verbatim in the chat, so it states the rule and the measured
   * frequency it came from - and never claims an expected return.
   */
  function score(alert, model) {
    var params = (model.screen && model.screen.params) || DEFAULTS;
    var minAbs = num(params.min_abs_swing_dollars);
    var minPct = num(params.min_move_pct_of_prior);
    if (minAbs === null) minAbs = DEFAULTS.min_abs_swing_dollars;
    if (minPct === null) minPct = DEFAULTS.min_move_pct_of_prior;

    var change = num(alert.change);
    var prior = num(alert.oldPrice);
    if (change === null) return { signal: false, basis: "no price change recorded", stats: null };
    var abs = Math.abs(change);
    var pct = prior ? abs / prior : 0;
    // Float-safe: an exact $0.10 move is 0.09999999999999998 in IEEE-754 dollars.
    var passAbs = abs >= minAbs - 1e-9;          // the brief's hard >= $0.10 condition
    var passPct = prior === null ? false : pct >= minPct - 1e-9;
    var up = change > 0;

    var m = model.measured || {};
    var side = up ? m.up_swing : m.down_swing;
    var band = up ? bandFor(model, prior) : null;
    var topicRow = topicFor(model, alert.topic);
    var stats = {
      base_p_yes: m.base_rate_all_settled ? m.base_rate_all_settled.p_yes : null,
      base_n: m.base_rate_all_settled ? m.base_rate_all_settled.n : null,
      side: up ? "up" : (change < 0 ? "down" : "flat"),
      side_p_yes: side && side.p_yes !== null && side.p_yes !== undefined ? side.p_yes : null,
      side_n: side ? side.n : 0,
      band_reported: band && band.reported ? band : null,
      topic_n_swing: topicRow ? topicRow.n_swing : null,
      n_swing_all: m.swing_market_counts ? m.swing_market_counts.n_swing : null
    };

    var basis = "screen " + (model.screen ? model.screen.id : "?") +
      ": |swing| ≥ $" + minAbs.toFixed(2) + " and ≥ " + Math.round(minPct * 100) + "% of prior" +
      (passPct ? "" : " — fails the 10% test") +
      "; measured on the demo snapshot: P(resolves yes | ≥$0.10 late " +
      (up ? "up" : "down") + "-move) = " +
      (stats.side_p_yes === null ? "n/a (n=" + stats.side_n + ")"
        : stats.side_p_yes + " (n=" + stats.side_n + ")") +
      " vs base " + (stats.base_p_yes === null ? "n/a" : stats.base_p_yes) +
      " (n=" + stats.base_n + "). Descriptive, not a forecast.";

    if (stats.band_reported) {
      basis += " Prior-price band " + stats.band_reported.prior_band[0] + "–" +
        stats.band_reported.prior_band[1] + ": n=" + stats.band_reported.n +
        ", P(yes)=" + stats.band_reported.p_yes + ".";
    }
    return {
      signal: passAbs && passPct,
      basis: basis,
      id: model.screen ? model.screen.id : "roi-screen",
      stats: stats
    };
  }

  /** Fetch the published model once per page load; degrade quietly if it is absent. */
  function load() {
    return fetch(MODEL_URL, { headers: { Accept: "application/json" } })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (model) {
        KD.roiModel = model;
        KD.roiScore = function (alert) { return score(alert, model); };
        KD.roiModelStatus = "loaded: " + MODEL_URL + " · screen " +
          (model.screen ? model.screen.id : "?") + " · " +
          (model.calibration_feasibility ? model.calibration_feasibility.conclusion : "");
        return model;
      })
      .catch(function (e) {
        // No model file -> KD.roiScore stays undefined and alerts.js labels its rows as
        // the fallback heuristic. The absence is reported, never hidden.
        KD.roiModel = null;
        KD.roiModelStatus = "model unavailable (" + (e && e.message ? e.message : "fetch failed") +
          ") — the chat falls back to the labelled heuristic";
        return null;
      });
  }
  KD.roiModelLoad = load;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", load);
  } else {
    load();
  }
})();
