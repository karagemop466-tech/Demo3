/* Kalshi Demo Tracker — page enhancements shared by the static pages:
 *  * live exchange-status widget (index)
 *  * suggestions review workflow (decision + note per row, localStorage, JSON export)
 *  * small quality-of-life helpers
 */
(function () {
  "use strict";
  var K = window.KalshiDemo;

  /* ---------- live status widget ---------- */
  async function liveStatus() {
    var el = document.getElementById("liveStatus");
    if (!el) return;
    try {
      var res = await fetch(K.BASE + "/exchange/status",
        { headers: { "Accept": "application/json" } });
      var j = await res.json();
      el.textContent = (j.trading_active ? "LIVE · trading active" : "paused") + " (demo)";
    } catch (e) {
      el.textContent = "static snapshot (browser fetch blocked)";
      el.className = "stat";
    }
  }

  /* ---------- suggestions review workflow ---------- */
  var DEC_KEY = "kd_decisions_v1";
  function loadDecisions() {
    try { return JSON.parse(localStorage.getItem(DEC_KEY) || "{}"); }
    catch (e) { return {}; }
  }
  function saveDecisions(d) {
    try { localStorage.setItem(DEC_KEY, JSON.stringify(d)); } catch (e) { /* */ }
  }
  function updateSummary() {
    var el = document.getElementById("decisionSummary");
    if (!el) return;
    var d = loadDecisions(), counts = {};
    Object.keys(d).forEach(function (k) {
      var v = d[k].decision || "Proposed";
      counts[v] = (counts[v] || 0) + 1;
    });
    var parts = Object.keys(counts).map(function (k) {
      return counts[k] + " " + k.toLowerCase();
    });
    el.textContent = parts.length ?
      "Decisions saved in this browser: " + parts.join(" · ") +
      " — export the JSON and attach it to a change request before implementing." :
      "No decisions saved yet — every suggestion is still Proposed. " +
      "Choose a decision per row before implementing any change.";
  }
  function wireDecisions() {
    var table = document.getElementById("suggestionTable");
    if (!table) return;
    var d = loadDecisions();
    Array.prototype.forEach.call(table.querySelectorAll(".decision"), function (sel) {
      var sid = sel.getAttribute("data-sid");
      if (d[sid]) {
        sel.value = d[sid].decision || "Proposed";
        var note = table.querySelector('.decision-note[data-sid="' + sid + '"]');
        if (note) note.value = d[sid].note || "";
      }
      sel.addEventListener("change", function () {
        d[sid] = d[sid] || {};
        d[sid].decision = sel.value;
        d[sid].updated = new Date().toISOString();
        saveDecisions(d);
        updateSummary();
      });
    });
    Array.prototype.forEach.call(table.querySelectorAll(".decision-note"), function (inp) {
      inp.addEventListener("change", function () {
        var sid = inp.getAttribute("data-sid");
        d[sid] = d[sid] || {};
        d[sid].note = inp.value;
        d[sid].updated = new Date().toISOString();
        saveDecisions(d);
        updateSummary();
      });
    });
    var exp = document.getElementById("exportDecisions");
    if (exp) exp.addEventListener("click", function () {
      var payload = {
        exported: new Date().toISOString(),
        decisions: loadDecisions(),
        note: "Review workflow export — nothing is implemented from these decisions automatically."
      };
      var blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      var a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "kalshi-suggestion-decisions.json";
      a.click();
    });
    var rst = document.getElementById("resetDecisions");
    if (rst) rst.addEventListener("click", function () {
      if (confirm("Clear all saved decisions and notes?")) {
        saveDecisions({});
        Array.prototype.forEach.call(table.querySelectorAll(".decision"),
          function (s) { s.value = "Proposed"; });
        Array.prototype.forEach.call(table.querySelectorAll(".decision-note"),
          function (s) { s.value = ""; });
        updateSummary();
      }
    });
    updateSummary();
  }

  function init() {
    liveStatus();
    wireDecisions();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else { init(); }
})();
