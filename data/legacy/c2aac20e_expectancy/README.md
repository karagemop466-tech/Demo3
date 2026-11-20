# Expectancy study — preserved from session c2aac20e (PR #23)

These artifacts were produced by session `c2aac20e` on branch `arena/c2aac20e-demo3`
(PR #23, created 2026-11-20T12:23:47Z, not merged). Final integration (session
`996e3e28`) extracted them before closing the PR so the work is not discarded;
the full branch remains in the repository.

| File | What it is |
|---|---|
| `expectancy.json` | Per-band expectancy over 12,521 settled demo markets (`data/resolutions-compact.json` on that branch): favourite band 0.80–0.99 (n=929): YES win rate 82.13%, avg price 97.49¢ → **−15.36¢ per YES contract** (fees excluded); longshot band 0.01–0.20 (n=1,820): YES win rate 1.65% at 3.22¢ → **−1.58¢ YES / +1.58¢ NO per contract** |
| `order-rules.json` | Candidate strategy rules derived by that session (policy, candidates, skips, simulation) |
| `STRATEGY.md` | The session's strategy write-up |

**Verification status: UNVERIFIED on `main`.** The figures were computed by that
session on its own branch snapshot (`generated_at_utc: 2026-11-20T12:15:15Z`) and
have not been recomputed on `main`'s data; treat them as a review artifact, not a
published result. Its own caveats apply: `last_price_dollars` is the last traded
price, not the average price paid; fees excluded; only markets settled inside its
collection window; historical expectancy does not predict future results.

Sources: computed from the official demo API settle sweep (per-row API URLs on the
originating branch, e.g. `https://external-api.demo.kalshi.co/trade-api/v2/markets?…&status=settled`);
settlement semantics per https://docs.kalshi.com/getting_started/market_settlement.
Re-verification path: recompute the same formula over `data/latest/resolutions.json`
(1,000 most recent) or extend the collector sweep, then publish with per-row sources.
