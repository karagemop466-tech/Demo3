# Real-browser end-to-end check (`e2e/`)

Session `3528551d`, task K3. Every other test in this repository exercises the pages either
with jsdom and a mocked API, or by fetching the HTML without running its JavaScript. Neither
can show what a visitor's browser actually gets from the live Kalshi **demo** API on the real
GitHub Pages origin. This harness does exactly that and nothing more.

## What it records (per page)

| Recorded | Why |
|---|---|
| HTTP status of the document | page exists on Pages |
| Uncaught script exceptions and `console.error` lines | broken scripts are invisible in jsdom-with-mocks |
| Every response from a Kalshi host, by status and host | proves the demo API is reachable from the browser (CORS), shows HTTP 429s, and reports any call to a **production** host |
| Failed / blocked requests | CORS or network failures |
| Table rows, rows without a link, empty tables | "all entries in simple tables, every row with a source link" |
| Canvases that are actually painted | charts that never draw |
| Text still saying "Loading…/Checking…" after the settle time | panels that never finish |
| Same-origin links that do not resolve | broken links |
| Scripted flows (`flows.mjs`) | what a trader clicks: track a market, change the chart window, start the alert console, place a paper trade |

Nothing is asserted that the browser did not observe; an empty table is reported as empty.
The run never fails the job on findings — it writes them down.

## Modes

| `E2E_MODE` | What the browser loads |
|---|---|
| `local` | this checkout, served to the browser **as** `https://karagemop466-tech.github.io/Demo3/` through request interception, so API calls carry the real Pages `Origin` — a branch can be checked before it is merged |
| `deployed` | whatever GitHub Pages is serving at that moment |

## Run

It needs network egress to the demo API. GitHub Actions has it; the build sandbox does not.

```bash
cd e2e && npm ci && npx playwright install --with-deps chromium
E2E_MODE=deployed node run.mjs          # report in e2e/report/deployed/
E2E_MODE=local E2E_PAGES=dashboard.html,alerts.html node run.mjs
```

In CI: `.github/workflows/e2e.yml` (manual dispatch, or edit `e2e/trigger.txt` and push).
Output: `report/<mode>/report.json` (everything), `report/<mode>/summary.md` (readable),
`report/<mode>/shots/*.jpg` (a few screenshots of the pages a trader works in).

Live pages are opened one at a time (`E2E_LIVE_CONCURRENCY=1`): one page is one visitor, so a
429 in the report is the site's own request rate, not the harness's.

## Sources

- Demo environment and hosts: https://docs.kalshi.com/getting_started/demo_env
- Public market data needs no key: https://docs.kalshi.com/getting_started/quick_start_market_data
- Rate limits: https://docs.kalshi.com/getting_started/rate_limits
- Playwright (browser automation): https://playwright.dev/docs/api/class-page
