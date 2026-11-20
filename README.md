# Kalshi demo dashboard (Demo3)

A live, source-linked dashboard for the **highest-dollar events on Kalshi's demo exchange** in five
topics only — **gas prices, elections, culture, crypto and golf** — tracking each market until it
settles (yes/no), with a price/depth chart, portfolio analysis, and a strategy section that was
tested against 12,521 settled markets rather than asserted.

**Live site:** https://karagemop466-tech.github.io/Demo3/
(entry point `index.html`, which hands off to the dashboard at `docs/index.html`)

**One rule everywhere:** a number is published only if an official Kalshi page or a stored Kalshi
API response supports it, and every table row links to its source. If a value cannot be confirmed
it stays blank and is listed on the **Flagged for review** page. Nothing is inferred.

---

## What you can do on the site

| Page | What it answers |
|---|---|
| [Root portal](index.html) | Where to start; how the four earlier builds were consolidated. |
| [Overview](docs/index.html) | KPIs, the top markets under four different size metrics, topic cards, portfolio state. |
| [All-topic table](docs/dashboard.html) | Which events are biggest, sortable by contracts, 24h activity, open interest, resting liquidity or production. |
| [Gas](docs/categories/gas.html) · [Elections](docs/categories/elections.html) · [Culture](docs/categories/culture.html) · [Crypto](docs/categories/crypto.html) · [Golf](docs/categories/golf.html) | Which series match the topic and why (prefix, category, tag or title), the series table, resolution counts. |
| [Price &amp; liquidity](docs/liquidity.html) | Contract price over a window you choose (60 s → 30 d), bid/ask/close series, order-book ladder, contracts available at each price. |
| [Resolutions](docs/resolutions.html) | How each tracked market settled, by topic and by month; scalar markets kept separate. |
| [Portfolio](docs/portfolio.html) | Balance, positions, fills and three separate P&amp;L components — or an explicit "not configured" state. |
| [Strategy](docs/strategy.html) | Four rules, their measured edge and their costs, the candidates the rules produce, and the 50 markets they skipped. |
| [Suggestions](docs/suggestions.html) | 14 proposals you can accept, defer or reject; choices persist locally and export as JSON. |
| [Open questions](docs/questions.html) | Every decision that needs an answer, what is missing, and how to close it. |
| [Flagged for review](docs/flagged.html) | 16 irregularities with evidence and the action taken. |
| [Sources](docs/sources.html) | 23 official Kalshi pages plus the stored API responses behind the tables. |

## The headline findings

- **Fading longshots is the only edge that survived.** Of 12,521 settled markets, the 0.01–0.20 band
  won 1.65% of the time at an average price of 0.0323 — buying NO there returned **+0.0158** per
  contract before fees.
- **Buying favourites loses money.** The 0.80–0.99 band won 82.26% at an average price of 0.975,
  which is **−0.1523** per contract. The popular "buy near-certainties" strategy is negative at the
  prices actually paid.
- **The numbers are narrow, fee-free and mostly one month.** 12,004 of 12,567 settled rows are from
  November 2026 and fees are excluded, so every table carries that caveat and the site does not
  claim predictive power. See flagged item F9.
- **"Highest dollar amount" is ambiguous and the candidate metrics disagree.** The biggest markets
  by contracts traded are 1–5¢ longshots with no resting bids, while the deepest book sampled holds
  $4.24 M. Four labelled metrics are published instead of one silent choice (F8, decision D1).
- **The order API reported on one published page was stale.** Kalshi's V2 page confirms legacy
  `/portfolio/orders` writes now return `410 Gone`; the code was corrected before shipping (F13).

## Repository layout

```
index.html            root portal (this site's front door)
docs/                 THE published site: pages, assets, and the artifacts they read (docs/data/)
  categories/         one page per topic
  assets/app.css      theme
  assets/app.js       shared runtime: formatting, chrome, chart, JSON loading
  data/               copies of data/*.json published for the browser
collector/
  collect.py          v2 collector: series-first, top 14 series per topic by volume
  portfolio.py        signed demo-account reads and V2 order placement (gated, production refused)
  topics.json         topic definitions and matching rules
  fixtures/, tests/   16 offline tests, including Kalshi's own order-book worked example
analysis/
  build.py            builds data/dashboard.json, expectancy.json, resolutions-*.json, REPORT.md
  expectancy.py       settled-market study
  strategies.py       R1–R4 rules, price-grid snapping, candidate generation
  settle_check.py     independent settlement cross-check
data/                 committed artifacts (the site reads copies under docs/data/)
tools/
  check_site.py       links, citation hosts, required pages, per-row source discipline
  render_test.js      renders all 15 pages in jsdom against real data; fails on empty tables
legacy/               every earlier build, preserved verbatim — see legacy/README.md
.github/workflows/    checks.yml, collect.yml, portfolio.yml
COORDINATION.md       the shared multi-session task board
```

## How the data is produced

1. **Collect** (`collect.yml`, hourly): a GitHub Actions runner calls the Kalshi **demo** REST API.
   It selects at most 14 series per topic by series volume, pulls open and settled markets, order
   books and 1m/60m/1440m candlesticks, and commits a compact artifact. The runner is used because
   this development sandbox has no network route to `*.kalshi.co` (F3).
2. **Analyse** (`analysis/build.py`): per-topic aggregates, the settlement study, liquidity and
   spread statistics, and the strategy candidates. It refuses to overwrite committed artifacts when
   its inputs are empty — a guard added after an incident that briefly emptied `dashboard.json` (F6).
3. **Check** (`checks.yml`): `tools/check_site.py` verifies every local link, restricts citations to
   an allow-list of official hosts and requires a source on every data row; `tools/render_test.js`
   then loads all 15 pages in jsdom and fails if a table renders empty or a script throws.
4. **Publish**: GitHub Pages serves the root of `main`, so `index.html` and `docs/` go live directly.

## Demo vs production, and what is deliberately blank

The demo environment is the primary source because that is what the brief names. Kalshi states that
demo prices may not reflect real markets, so a labelled production snapshot appears only as a
comparison column (F10). No demo credentials exist in this environment, so **no portfolio, fill or
P&amp;L figures are published** — the portfolio page explains the two repository secrets that would
enable them instead of showing zeros (F4). Order execution code is present, refuses production, and
requires both `ALLOW_DEMO_TRADING` and an explicit confirmation string.

## Running it locally

```bash
python3 -m http.server 8080 --directory docs   # the site
python3 tools/check_site.py                    # link + citation + data checks
python3 -m unittest discover -s collector/tests -v
npm install jsdom@25 && node tools/render_test.js
```

`analysis/build.py` needs a live collector artifact that is not committed (it is git-ignored), so a
local run without one prints a skip line rather than rewriting the published data.

## Documentation beyond the site

`EXECUTIVE_SUMMARY.md`, `FLAGGED.md`, `SUGGESTIONS.md`, `COORDINATION.md` and `legacy/README.md`
hold the narrative versions of the same material. Nothing in this repository is investment advice.
