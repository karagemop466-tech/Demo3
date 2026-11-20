#!/usr/bin/env python3
"""Write `catalysts/data/last_run.txt`: a one-screen health note for the ledger pipeline.

Committed by the workflow on every run (success OR failure), so the branch and the live
site show what the collector last did without anyone needing GitHub API access:

    job_status=success
    swings.json: 14 swings, 6 with candidate links
    feed_health.json: 9 of 17 feeds usable
    endpoints.json: 7 probed, 7 ok

Nothing here invents data: every number is read from the artifacts written by scan.py, and
a missing artifact is reported as MISSING (that is how a failed step becomes visible).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")


def load(name: str):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        return {"_unreadable": f"{type(exc).__name__}: {exc}"}


def lines() -> list[str]:
    out = [
        f"recorded_at={datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"workflow={os.environ.get('GITHUB_WORKFLOW', 'local')}",
        f"event={os.environ.get('GITHUB_EVENT_NAME', 'local')}",
        f"ref={os.environ.get('GITHUB_REF_NAME', os.environ.get('GIT_BRANCH', 'local'))}",
        f"sha={os.environ.get('GITHUB_SHA', 'local')}",
        f"run_url={os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}"
        f"/{os.environ.get('GITHUB_REPOSITORY', 'local')}/actions/runs/"
        f"{os.environ.get('GITHUB_RUN_ID', 'n/a')}",
    ]
    status = load("status.json")
    if status is None:
        out.append("status.json: MISSING (the scan step did not complete)")
    elif "_unreadable" in status:
        out.append(f"status.json: unreadable ({status['_unreadable']})")
    else:
        out.append(
            "status.json: "
            f"mode={status.get('mode')} finished_at={status.get('finished_at')} "
            f"requests={status.get('requests')} errors={status.get('request_errors')} "
            f"deadline_reached={status.get('deadline_reached')} "
            f"tape_rows={status.get('tape_rows')} "
            f"swings_total={status.get('swings_total')} "
            f"simulated_trades={status.get('simulated_trades_scored')}")

    swings = load("swings.json")
    if swings is None:
        out.append("swings.json: MISSING (no ledger published by this run)")
    else:
        rows = swings.get("swings") or []
        with_links = sum(1 for s in rows if s.get("catalysts"))
        resolved = sum(1 for s in rows if s.get("resolved"))
        out.append(f"swings.json: {len(rows)} swings, {with_links} with candidate links, "
                   f"{resolved} resolved; threshold >= ${swings.get('threshold_dollars')} "
                   f"from={swings.get('api_root')}")
        if swings.get("link_root_note"):
            out.append(f"  note: {swings['link_root_note']}")

    health = load("feed_health.json")
    if health is None:
        out.append("feed_health.json: MISSING (feed probe step did not complete)")
    else:
        feeds = health.get("feeds") or []
        usable = [f for f in feeds if f.get("ok") and (f.get("items_parsed") or 0) > 0]
        out.append(f"feed_health.json: {len(usable)} of {len(feeds)} feeds usable "
                   f"(mode={health.get('mode')}, checked_at={health.get('checked_at')})")
        for f in feeds:
            if not (f.get("ok") and (f.get("items_parsed") or 0) > 0):
                out.append(f"  not usable: {f.get('name')} — {str(f.get('error'))[:120]}")

    eps = load("endpoints.json")
    if eps is None:
        out.append("endpoints.json: MISSING (endpoint probe step did not complete)")
    else:
        rows = eps.get("endpoints") or []
        ok = sum(1 for r in rows if r.get("http_status") == 200)
        out.append(f"endpoints.json: {len(rows)} probed, {ok} returned HTTP 200 "
                   f"(probed_at={eps.get('probed_at')})")
        if eps.get("note"):
            out.append(f"  note: {eps['note']}")
        for r in rows:
            if r.get("filter_honoured") is False:
                out.append(f"  filter ignored by this deployment: {r.get('method')} {r.get('url')}")

    strat = load("strategies.json")
    if strat is not None:
        res = strat.get("results") or []
        out.append(f"strategies.json: {strat.get('trade_count')} simulated trade(s), "
                   f"{len(res)} categor(y/ies), {sum(1 for r in res if r.get('evaluable'))} "
                   f"above the n>={strat.get('min_n_for_a_claim')} floor")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", default="", help="job status passed by the workflow")
    ap.add_argument("--out", default=os.path.join(DATA, "last_run.txt"))
    ap.add_argument("--print", dest="do_print", action="store_true")
    args = ap.parse_args(argv)
    body = lines()
    if args.status:
        body.insert(1, f"job_status={args.status}")
    text = "\n".join(body) + "\n"
    if args.do_print:
        print(text, end="")
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
