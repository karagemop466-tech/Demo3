# Verification — c2aac20e expectancy study, recomputed on `main` data (session d8f4577a, 2026-11-21)

**Status: recomputed, NOT quoted.** These are demo-exchange figures. Historical expectancy does not
predict future results. Nothing on the site may present them as edge, profitability, or advice.

## What was done

The preserved `expectancy.json` was computed by session `c2aac20e` on 2026-11-20 over 12,521 settled
demo markets (`data/resolutions-compact.json`, present only on that branch) and was flagged
**UNVERIFIED on `main`** (see `README.md` in this folder). This pass recomputes the same formulas over
`data/latest/markets_settled.json` — 20,783 `finalized` demo markets, each row carrying its replayable
official demo-API URL in `source_url` (retrieved_at 2026-11-21T07:08:56+00:00; per-row re-verification by
`scripts/verify_rows.py`: 725 checks, 0 drift notices, 0 hard failures, verified_at
2026-11-21T07:11:01+00:00, see `data/latest/verification_report.json`).

- Script: `recompute_expectancy.py` (stdlib only, deterministic given the same input).
- Reproduction:
  `python3 data/legacy/c2aac20e_expectancy/recompute_expectancy.py`
  (writes `expectancy.recomputed.json` next to this file).
- Rows used: `result ∈ {yes, no}` and `0 ≤ last_price_dollars ≤ 1` — all 20,783 rows qualify
  (`rows_excluded: {}`). Scalar/other results: none present in this snapshot.

## Method and definitions (all explicit)

- Buckets: `<=0.10` is `p ≤ 0.10`; every later bucket is `(lo, hi]`; the last is `> 0.99`.
  Boundary rule differs from the preserved file, which wrote `">=0.99"` without stating whether 0.99
  itself was inside `0.90-0.99` or `>=0.99` (see F-D8F-01).
- `win_rate_yes = yes / n`; `avg_yes_price = mean(last_price_dollars)`.
- `yes_expectancy = win_rate_yes − avg_yes_price`; `no_expectancy = (1 − win_rate_yes) − (1 − avg_yes_price)`. Per $1 contract, **fees excluded** (fee fields exist per series — `fee_type`/`fee_multiplier` — but were not applied).
- `volume_weighted_win_rate` = Σ volume_fp of YES-settled rows in the group ÷ Σ volume_fp of all rows in the group. The preserved file's internal definition is **not recoverable** from this repo (F-D8F-03).
- `contracts_traded` = Σ volume_fp.
- Favourite band = `0.80 ≤ p ≤ 0.99`; longshot band = `0.01 ≤ p ≤ 0.20` (explicit ranges from the names).
- Per-topic extension is labeled as extension output; it is not part of the preserved study.

## Headline comparison (preserved vs recomputed)

| Group | Preserved (n, win, avg ¢, YES exp.) | Recomputed (n, win, avg ¢, YES exp.) |
|---|---|---|
| all rows | 12,521 · 19.50% · 14.77¢ · **+4.72¢** | 20,783 · 5.82% · 2.98¢ · **+2.84¢** |
| favourite 0.80–0.99 | 929 · 82.13% · 97.49¢ · **−15.36¢** | 497 · 14.49% · 96.15¢ · **−81.66¢** |
| longshot 0.01–0.20 | 1,820 · 1.65% · 3.22¢ · **−1.58¢** | 968 · 4.24% · 3.88¢ · **+0.35¢** |

| Bucket | Recomputed n | win% | avg ¢ | YES exp. ¢ |
|---|---|---|---|---|
| <=0.10 | 19,967 | 5.43 | 0.13 | +5.30 |
| 0.10-0.20 | 98 | 3.06 | 15.00 | −11.94 |
| 0.20-0.40 | 112 | 16.96 | 29.58 | −12.62 |
| 0.40-0.60 | 48 | 33.33 | 50.38 | −17.04 |
| 0.60-0.80 | 63 | 23.81 | 70.71 | −46.90 |
| 0.80-0.90 | 65 | 16.92 | 86.98 | −70.06 |
| 0.90-0.99 | 428 | 14.02 | 97.69 | −83.67 |
| >0.99 | 2 | 100.0 | 99.60 | +0.40 |

Per-topic (recomputed): elections n=25 win 4.0% · golf n=3,890 win 4.7% · **crypto n=14,008 win 0.0%**
· culture n=166 win 19.9% · gas n=1,959 win 36.7% · other n=735 win 37.4%.

## Findings (honest reading)

1. **The demo settled sweep is dominated by crypto price markets that all settled NO.**
   `KXBTC`, `KXBTCD`, `KXETH`, `KXETHD`, `KXXRP`, `KXXRPD`, `KXDOGE` each contribute exactly 2,000 rows
   (collector cap per series), 14,008 of 20,783 rows overall, **zero YES settlements**. Demo crypto
   markets do not reflect real price discovery; they are the dominant term in every aggregate above.
   Any expectancy quoted from this sweep is an artifact of the demo exchange, not a market relationship.
2. **The one directional consistency across both datasets:** YES in the high-price favourite band loses
   money on the demo sweep (preserved −15.36¢; recomputed −81.66¢, driven by finding 1).
   Longshot sign flips (preserved −1.58¢ → recomputed +0.35¢, both statistically small bands in these
   samples). Gas-topic win rate (36.7%) is the only topic where NO did not dominate.
3. **Neither dataset supports a strategy claim.** Demo prices may not reflect real markets
   (https://docs.kalshi.com/getting_started/demo_env), `last_price_dollars` is a last-trade print, not a
   fill price, fees are excluded, and samples are capped per series (2,000/series observed) and not
   exhaustive.
4. The preserved `expectancy.json` is internally irreproducible on this repo: its favourite/longshot
   band counts are not the union of its preserved buckets (323 ≠ 929; 10,621 ≠ 1,820), and its
   `volume_weighted_win_rate` definition is undocumented here (F-D8F-01/03). The recomputed file fixes
   both by stating definitions explicitly; it does **not** "correct" the preserved file, which is kept
   intact for provenance.

## Irregularities flagged for review (non-blocking; for the Flagged for Review page — logged as change request for the final integration session)

- **F-D8F-01 (data method):** preserved `expectancy.json` band counts do not decompose into its own
  buckets; bucket/band boundary rules undocumented (`>=0.99` vs `0.90-0.99` ambiguity). Recomputed output
  states boundaries explicitly.
- **F-D8F-02 (data quality, high impact):** 14,008/20,783 (67.4%) of the settled sweep is crypto test-style
  price markets, 100% settled NO; aggregate expectancy is not economically meaningful. Any site text quoting
  "demo expectancy" must carry this caveat. Evidence: series prefix counts from
  `data/latest/markets_settled.json` (this file's "What was done" section).
- **F-D8F-03 (method):** preserved `volume_weighted_win_rate` internal definition not recoverable from the repo.
- **F-D8F-04 (data drift, expected):** input snapshot differs from the preserved study's (12,521 → 20,783
  rows; retrieved_at differs). Figures are not comparable point-for-point; bands are compared only on
  direction.
- **F-D8F-05 (coverage):** settled sweep is capped per series (2,000 observed) and not exhaustive;
  `data/latest/resolutions.json` (1,000 most recent) overlaps this set partially.

## Sources

- Input data (per-row `source_url`, official demo API): `data/latest/markets_settled.json`, e.g.
  `https://external-api.demo.kalshi.co/trade-api/v2/markets?tickers=KXGOVCA-26-CBIA`
- Settlement semantics (`market.result` yes/no): https://docs.kalshi.com/getting_started/market_settlement
- Demo-environment caveat: https://docs.kalshi.com/getting_started/demo_env
- Row-level re-verification of stored rows (725 checks, 0 hard failures): `data/latest/verification_report.json`
- Preserved study under review: `expectancy.json`, `STRATEGY.md`, `order-rules.json` (this folder, untouched)

*Prepared by session d8f4577a (`arena/d8f4577a-demo3`), 2026-11-21. Reproducible with the script above.
No values were inferred; gaps are stated as gaps.*
