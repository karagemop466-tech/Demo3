# Demo3 — Kalshi Demo Market Tracker

Collects, organizes, and analyzes live **Kalshi demo-exchange** prediction-market data
(gas prices, elections, culture, crypto, golf), tracks events through to resolution
(yes/no), tracks a demo-account portfolio, and publishes a live interactive dashboard
to GitHub Pages.

- **API**: https://external-api.demo.kalshi.co/trade-api/v2 (official demo REST base; documented at https://docs.kalshi.com/getting_started/api_environments.md)
- **Live site**: https://karagemop466-tech.github.io/Demo3/
- **Task board**: [COORDINATION.md](COORDINATION.md)
- **Executive summary**: [EXECUTIVE_SUMMARY.md](EXECUTIVE_SUMMARY.md)
- **API verification table**: [docs/API_VERIFICATION.md](docs/API_VERIFICATION.md)
- **Flagged for review**: [docs/FLAGGED.md](docs/FLAGGED.md) (also a site page)

## Layout

| Path | Purpose |
|---|---|
| `site/` | Static dashboard published to GitHub Pages (no build step) |
| `collector/` | Python pipeline that snapshots live demo-API data into `data/` |
| `trading/` | Demo-account auth, portfolio snapshots, order execution, trade categorization & strategies |
| `data/` | Committed JSON snapshots produced by the collector (refreshed on schedule) |
| `docs/` | Verification tables, methodology, suggestions, open questions, flagged items |
| `.github/workflows/` | `collect.yml` (scheduled snapshots), `deploy.yml` (Pages), `trade.yml` (manual demo trades) |

## Automation

- **Collector** runs every 10 minutes (and on manual dispatch): pulls tracked events/markets,
  orderbooks for the top markets by estimated dollar volume, 1-min/60-min/1440-min candlesticks,
  and settled markets (resolutions), commits them to `data/`, and records a CORS-header test.
- **Deploy** publishes `site/` to GitHub Pages on every push to `main`.
- **Trade** (manual `workflow_dispatch` only) places demo orders and snapshots the demo portfolio
  using repository secrets `KALSHI_DEMO_API_KEY_ID` and `KALSHI_DEMO_PRIVATE_KEY`
  (Ed25519 or RSA PEM; demo keys only work against demo endpoints — see
  https://docs.kalshi.com/getting_started/quick_start_authenticated_requests.md). Without the
  secrets it exits with a clear flag instead of guessing.

## Verification policy

Every table row on the site carries a source link. Values that cannot be confirmed from an
official source are left blank and flagged — never inferred. See
[docs/METHODOLOGY.md](docs/METHODOLOGY.md).
