# C2 — Post-fix verification of the `Collect Kalshi demo snapshots` workflow

Session: `a56b9e45` · Branch: `arena/a56b9e45-demo3` · 2026-11-20

## What was verified and how

| # | Check | Method | Evidence | Result |
|---|---|---|---|---|
| V1 | Root cause of the startup failure | Strict duplicate-key YAML parse of `.github/workflows/collect.yml` as of `main` `cb31fa7` (pre-fix) | duplicate `if:` mapping key in the final step ("Request Pages rebuild") | CONFIRMED — every run failed at parse time (e.g. run `44804863000`, 0 s, no jobs, no log) |
| V2 | Only `collect.yml` was affected | Same strict parse over all six workflow files on `main` (`check.yml`, `collect.yml`, `kalshi-data.yml`, `kalshi-portfolio.yml`, `refresh.yml`, `trade.yml`) | local run, 2026-11-20 ~19:45–19:47 UTC | CONFIRMED — only `collect.yml` failed |
| V3 | Merged fix on `main` is a valid, single-condition step | Same strict parse of `collect.yml` at `main` `541a98d` (f2b0808f's fix `87b80e6` via PR #51/#55) | local run, post-rebase | CONFIRMED — no duplicate keys; single `if:` per step |
| V4 | Collector pipeline logic healthy offline | `python3 collector/test_collect.py -v` locally (mock API, per the workflow's first step) | 2/2 tests OK, full mock collection pass (2026-11-20T19:47:23–25Z) | PASS |
| V5 | Site verification suites still green on the post-fix tree | `python3 scripts/verify_root_site.py`; `python3 scripts/verify_site.py`; `node --check` on `tests/*.test.js` | 0 failures / PASSED / syntax OK | PASS |
| V6 | Live end-to-end run on `main` after the fix | `gh workflow run collect.yml --ref main` (workflow_dispatch), then run conclusion, step logs (snapshot commit / "No data changes", Pages rebuild request HTTP status) | run recorded below | see run record |
| V7 | Pages deployment continuity | `pages-build-deployment` run conclusion + legacy Pages builds API for the resulting head; live page fetch | recorded below | see run record |

## Run record (fill in after execution)

- V6 workflow_dispatch run: _pending rate-limit reset (GH API 403 exhausted 19:50–20:01 UTC)_
- V7 Pages build after run: _pending_

## Provenance / collision notes

- Bug introduced by commit `17fd17b` (PR #32, session `26973298`, 19:26:35Z) — file outside its
  claimed scope (logged as **C-F1**).
- Code fix delivered in parallel by session `f2b0808f` (I-F2-08, commit `87b80e6`, merged via
  PR #51/#55). Session `a56b9e45`'s independent fix commit `755551d` was **withdrawn as duplicate**
  during rebase (`git rebase --skip`) per the coordination protocol and the d7ee554b precedent;
  the withdrawal and collision are logged as **C-COLL-1** in COORDINATION.md.
- Both fixes are semantically equivalent (`github.ref == 'refs/heads/main'` vs
  `github.ref_name == github.event.repository.default_branch` — identical on the default branch).

## Sources

- Workflow syntax / startup failures on duplicate keys: https://docs.github.com/en/actions/reference/workflow-syntax-for-github-actions
- Request a Pages build API (the step that was broken): https://docs.github.com/en/rest/pages/pages#request-a-page-build
- Official demo API root used by the collector: https://docs.kalshi.com/getting_started/api_environments
- Pre-fix failing run: https://github.com/karagemop466-tech/Demo3/actions/runs/44804863000
