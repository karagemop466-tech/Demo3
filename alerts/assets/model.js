/* High-ROI SCREEN for the alert feed (stand-in rules).
 *
 * PLACEHOLDER. The owner's model was not supplied to this session, so this file
 * applies fixed, transparent checks to official market fields. It does NOT
 * estimate probabilities, expected value or return, and it is not investment
 * advice. To use a real model, replace AlertModel.screen with a function that
 * returns { pass: boolean, checks: [{name, pass}] } for an alert object.
 *
 * Fields used (official Kalshi market object, see docs.kalshi.com get-markets):
 * yes_bid_dollars, yes_ask_dollars, last_price_dollars, open_interest_fp.
 */
(function (root) {
  "use strict";

  var RULES = {
    minMoveCents: 10,        // alert already requires |move| >= $0.10
    maxSpreadCents: 3,       // yes_ask - yes_bid <= $0.03 (tight quotes)
    minPriceCents: 15,       // avoid near-certain prices (very small payouts)
    maxPriceCents: 85,
    minOpenInterest: 1000    // contracts open
  };

  function screen(alert) {
    var checks = [
      { name: "move of at least $0.10", pass: Math.abs(alert.delta_cents) >= RULES.minMoveCents },
      { name: "spread of at most $0.03", pass: alert.spread_cents !== null && alert.spread_cents <= RULES.maxSpreadCents },
      { name: "current price between $0.15 and $0.85",
        pass: alert.to_cents !== null && alert.to_cents >= RULES.minPriceCents && alert.to_cents <= RULES.maxPriceCents },
      { name: "at least 1,000 contracts open", pass: (alert.open_interest || 0) >= RULES.minOpenInterest }
    ];
    return {
      pass: checks.every(function (c) { return c.pass; }),
      checks: checks,
      passed: checks.filter(function (c) { return c.pass; }).length,
      total: checks.length
    };
  }

  // Arithmetic only: gross payout per $1 risked if YES is bought at the ask, before fees.
  // Fee schedule not verified in this session, so no fee is subtracted.
  function grossPayoutRatio(askCents) {
    if (askCents === null || askCents === undefined || askCents <= 0) return null;
    return (100 - askCents) / askCents;
  }

  root.AlertModel = { RULES: RULES, screen: screen, grossPayoutRatio: grossPayoutRatio };
})(typeof window !== "undefined" ? window : globalThis);
