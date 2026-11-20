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

## Run record (executed 2026-11-20, post rate-limit reset)

- **V6 — workflow_dispatch run [`44809097574`](https://github.com/karagemop466-tech/Demo3/actions/runs/44809097574)** (dispatched 20:11:31Z, head `c0cb52ba4`, job `136540733890`): **completed success at 20:21:11Z**. Every job step green:
  - Step 4 `Offline pipeline tests (mock API)` — success
  - Step 5 `Collect live demo snapshots` — success
  - Step 6 `Commit snapshots (default branch only)` — success → commit [`241c603`](https://github.com/karagemop466-tech/Demo3/commit/241c603) "collector: snapshot 2026-11-20T20:20:58Z" on `main` (verified ancestor of current main) — **the first successful snapshot commit since the 19:26Z regression**
  - Step 7 `Request Pages rebuild …` — success
- **V7 — Pages rebuild/deploy continuity:** rebuild requests are firing (Pages builds API shows builds requested at 20:21:00Z for `deea750` and 20:21:33Z for `be94f5cff`, plus later heads). The **legacy** builds currently report `errored` for the newest heads (starvation/pile-up — GitHub Pages soft build limit; diagnosed as **I-F2-07** by session `f2b0808f`, whose fix — a custom Actions publish workflow `.github/workflows/pages.yml` — is active: runs for `deea750`/`725a8497` were cancelled-by-newer and a run for `22d5160` was in progress at 20:28Z). The live site is up and serving the last successful deploy (content from the `04d1a4e`-era deploy, verified by page fetch at 19:53Z and 20:27Z); the freshest snapshot content (241c603) will publish when the active deploy path lands a run.
- **Verification limitation (flagged):** the job log of run `44809097574` (which would show the literal "pages build request HTTP <code>" line) is hosted on an Azure blob host that this sandbox cannot reach (egress allowlist), so the exact HTTP status of step 7 is UNVERIFIED; the step's own conclusion `success` is recorded instead. Everything else above is verified from API responses and page fetches.

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
