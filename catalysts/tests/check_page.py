#!/usr/bin/env python3
"""Publish gate for the swing + catalyst layer (used by CI, runs offline too).

Checks the committed artifacts and this subsite's markup, and fails on anything that
would put an unverified number, an unexplained link or a broken href on the live site:

1.  JSON artifacts parse, and every published swing is internally consistent:
    the recorded move equals `to - from` in exact decimal dollars, is >= $0.10, and
    its direction matches the sign.
2.  Every swing links an official demo-API market URL (https, known host), and every
    catalyst link carries a publisher URL, a feed URL and a parseable publish time.
3.  A swing with no qualifying item must say why (machine-readable match_status) and
    must not be marked "matched" — the fail-closed rule, enforced after the fact.
4.  Local href/src in catalysts/index.html resolve to real files; external links are
    https and stay on documented hosts (Kalshi docs/demo hosts) or on the feed/publisher
    hosts recorded in the data, so a reviewer can open every citation.
5.  No placeholder text ("TODO", "FIXME", "lorem ipsum", "coming soon") in the shipped markup.

Run: python3 catalysts/tests/check_page.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
from decimal import Decimal, InvalidOperation

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.abspath(os.path.join(HERE, ".."))
REPO = os.path.abspath(os.path.join(SITE, ".."))
DATA = os.path.join(SITE, "data")

DEMO_HOSTS = {"external-api.demo.kalshi.co", "demo-api.kalshi.co"}
ALLOWED_EXTERNAL = {
    "docs.kalshi.com", "kalshi.com", "demo.kalshi.co", "external-api.demo.kalshi.co",
    "demo-api.kalshi.co", "github.com", "karagemop466-tech.github.io",
}
THRESHOLD = Decimal("0.10")
MATCH_STATUSES = {"matched", "items_in_window_but_no_keyword_overlap",
                  "no_feed_item_in_window", "no_feed_items_available",
                  "feeds_not_polled_offline"}

failures: list[str] = []
notes: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)


def is_https(url: str) -> bool:
    try:
        p = urllib.parse.urlparse(url)
    except ValueError:
        return False
    return p.scheme == "https" and bool(p.netloc)


def load_json(path: str, required: bool = True):
    if not os.path.exists(path):
        if required:
            fail(f"missing artifact: {os.path.relpath(path, REPO)}")
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        fail(f"{os.path.relpath(path, REPO)} is not valid JSON: {exc}")
        return None


def check_swings() -> dict:
    doc = load_json(os.path.join(DATA, "swings.json"))
    stats = {"swings": 0, "with_links": 0, "resolved": 0, "links": 0}
    if not doc:
        return stats
    for key in ("generated_at", "api_root", "threshold_dollars", "swings", "docs", "disclaimer"):
        if key not in doc:
            fail(f"swings.json missing required key '{key}'")
    if str(doc.get("threshold_dollars")) not in ("0.10", "0.1"):
        fail(f"swings.json threshold must be 0.10, got {doc.get('threshold_dollars')!r}")
    for s in doc.get("swings") or []:
        stats["swings"] += 1
        label = s.get("id") or s.get("ticker") or "?"
        for k in ("ticker", "direction", "from", "to"):
            if not s.get(k):
                fail(f"swing {label}: missing '{k}'")
        try:
            d0 = Decimal(str(s["from"]["last_price_dollars"]))
            d1 = Decimal(str(s["to"]["last_price_dollars"]))
        except (InvalidOperation, KeyError, TypeError):
            fail(f"swing {label}: from/to prices are not decimal dollars")
            continue
        delta = d1 - d0
        if abs(delta) < THRESHOLD:
            fail(f"swing {label}: |{delta}| is below the $0.10 threshold — it must not be published")
        recorded = s.get("abs_delta_dollars")
        try:
            if Decimal(str(recorded)) != abs(delta):
                fail(f"swing {label}: abs_delta_dollars {recorded} != |{d1} - {d0}| = {abs(delta)}")
        except InvalidOperation:
            fail(f"swing {label}: abs_delta_dollars {recorded!r} is not a decimal string")
        want_dir = "up" if delta > 0 else "down"
        if s.get("direction") != want_dir:
            fail(f"swing {label}: direction {s.get('direction')!r} contradicts sign of {delta}")
        for side in ("from", "to"):
            ts = (s.get(side) or {}).get("ts") or ""
            if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", ts):
                fail(f"swing {label}: {side}.ts {ts!r} is not an ISO-8601 Z timestamp")
        links = s.get("links") or {}
        market_url = links.get("market_api_url") or ""
        if not market_url:
            fail(f"swing {label}: no market_api_url — a row without a source link cannot ship")
        else:
            host = urllib.parse.urlparse(market_url).netloc
            if host not in DEMO_HOSTS:
                fail(f"swing {label}: market_api_url host {host!r} is not an official demo host")
            if f"/markets/{s.get('ticker')}" not in market_url:
                fail(f"swing {label}: market_api_url does not point at its own ticker")
        stats["links"] += 1
        cats = s.get("catalysts") or []
        if cats:
            stats["with_links"] += 1
        for c in cats:
            for k in ("link", "feed_url", "published_ts", "title"):
                if not c.get(k):
                    fail(f"swing {label}: catalyst item missing '{k}' — links must be auditable")
            if c.get("link") and not is_https(c["link"]):
                fail(f"swing {label}: catalyst link is not https: {c.get('link')}")
            if c.get("published_ts") and not re.match(
                    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", c["published_ts"]):
                fail(f"swing {label}: catalyst published_ts {c['published_ts']!r} is not ISO Z")
            if not (c.get("matched_keywords") or []):
                fail(f"swing {label}: catalyst item without matched_keywords (opaque match)")
        match = s.get("catalyst_match") or {}
        status = match.get("match_status")
        if status not in MATCH_STATUSES:
            fail(f"swing {label}: unknown match_status {status!r}")
        if cats and status != "matched":
            fail(f"swing {label}: has catalyst items but match_status {status!r}")
        if not cats and status == "matched":
            fail(f"swing {label}: match_status 'matched' with no items (would be a fabricated claim)")
        if s.get("resolved"):
            stats["resolved"] += 1
            if s.get("tracking") != "stopped_resolved":
                fail(f"swing {label}: resolved but tracking is {s.get('tracking')!r}")
            if s.get("result") not in ("yes", "no", ""):
                fail(f"swing {label}: result {s.get('result')!r} is not yes/no")
    return stats


def check_status() -> None:
    st = load_json(os.path.join(DATA, "status.json"))
    if not st:
        return
    for key in ("status", "finished_at", "mode", "requests", "swings_total"):
        if key not in st:
            fail(f"status.json missing '{key}'")
    if st.get("mode") not in ("live", "offline", "offline(no-network)", "live(alt-root)"):
        fail(f"status.json has an unexpected mode {st.get('mode')!r}")
    if st.get("swings_total") is not None and st.get("swings_new") is not None:
        if int(st["swings_total"]) < int(st["swings_new"]):
            fail("status.json: swings_total is smaller than swings_new")


def check_probes() -> None:
    health = load_json(os.path.join(DATA, "feed_health.json"), required=False)
    if health:
        cfg = load_json(os.path.join(SITE, "feeds.json")) or {}
        urls = {f.get("url") for f in (cfg.get("feeds") or []) if f.get("enabled", True)}
        seen = {f.get("url") for f in (health.get("feeds") or [])}
        missing = urls - seen
        if missing:
            fail(f"feed_health.json does not cover every enabled feed: {sorted(missing)[:3]}")
        for f in health.get("feeds") or []:
            if f.get("ok") and not (f.get("items_parsed") or 0):
                fail(f"feed {f.get('name')}: ok=true with zero items parsed")
            if not f.get("ok") and f.get("error") in (None, ""):
                fail(f"feed {f.get('name')}: not ok but no error text recorded")
    eps = load_json(os.path.join(DATA, "endpoints.json"), required=False)
    if eps and eps.get("endpoints"):
        for e in eps["endpoints"]:
            if e.get("http_status") is None and not e.get("error"):
                fail(f"endpoint {e.get('url')}: no status and no error text")
            for key in ("method", "url", "purpose", "doc"):
                if not e.get(key):
                    fail(f"endpoint row missing '{key}'")


def check_strategies() -> dict:
    """Arithmetic gate for the simulated-strategy snapshot.

    A strategy number may only be published if it reproduces exactly from the stored
    wins/losses and per-trade PnLs; anything else fails the build.
    """
    stats = {"categories": 0, "evaluable": 0, "trades": 0}
    doc = load_json(os.path.join(DATA, "strategies.json"), required=False)
    if not doc:
        notes.append("no strategies.json yet (first scheduled run will create it)")
        return stats
    for key in ("strategies", "results", "disclaimer", "min_n_for_a_claim"):
        if key not in doc:
            fail(f"strategies.json missing '{key}'")
    if "gross of fees" not in (doc.get("disclaimer") or "").lower():
        fail("strategies.json must state that the figures are gross of fees")
    known = {s.get("id") for s in doc.get("strategies") or []}
    total_n = 0
    for r in doc.get("results") or []:
        stats["categories"] += 1
        label = f"{r.get('strategy')}/{r.get('category')}"
        if r.get("strategy") not in known:
            fail(f"strategy result {label}: strategy id not declared in strategies[]")
        n, w, l, p = (int(r.get("n") or 0), int(r.get("wins") or 0),
                      int(r.get("losses") or 0), int(r.get("pushes") or 0))
        if w + l + p != n:
            fail(f"strategy {label}: wins+losses+pushes {w}+{l}+{p} != n={n}")
        try:
            net = Decimal(str(r.get("net_pnl_dollars_per_contract")))
            mean = Decimal(str(r.get("mean_pnl_dollars_per_contract")))
        except InvalidOperation:
            fail(f"strategy {label}: net/mean are not decimal strings")
            continue
        if n and (net / n).quantize(Decimal("0.0001")) != mean:
            fail(f"strategy {label}: mean {mean} != net/n {(net / n).quantize(Decimal('0.0001'))}")
        if bool(r.get("evaluable")) != (n >= int(doc.get("min_n_for_a_claim") or 0)):
            fail(f"strategy {label}: evaluable flag contradicts n vs min_n_for_a_claim")
        if not r.get("evaluable") and abs(mean) > 0 and r.get("markets") is None:
            fail(f"strategy {label}: unpublished sample but no per-market audit list")
        for m in r.get("markets") or []:
            url = m.get("market_api_url") or ""
            if urllib.parse.urlparse(url).netloc not in DEMO_HOSTS:
                fail(f"strategy {label}: audit row {m.get('ticker')} has no official demo-API link")
        total_n += n
        stats["trades"] += n
        stats["evaluable"] += 1 if r.get("evaluable") else 0
    pf = doc.get("portfolio") or {}
    if "books" not in pf:
        fail("strategies.json portfolio block is missing its books")
    for strategy, b in (pf.get("books") or {}).items():
        label = f"portfolio/{strategy}"
        try:
            bank = Decimal(str(b.get("starting_bankroll_dollars")))
            end = Decimal(str(b.get("ending_equity_dollars")))
            real = Decimal(str(b.get("realized_pnl_dollars")))
            dd = Decimal(str(b.get("max_drawdown_dollars")))
        except InvalidOperation:
            fail(f"{label}: bankroll/equity/pnl are not decimal strings")
            continue
        if bank + real != end:
            fail(f"{label}: bankroll {bank} + realized {real} != equity {end}")
        if int(b.get("wins") or 0) + int(b.get("losses") or 0) > int(b.get("n") or 0):
            fail(f"{label}: wins+losses exceed n={b.get('n')}")
        if dd < 0:
            fail(f"{label}: negative max drawdown is impossible")
        curve = b.get("equity_curve") or []
        if len(curve) > int(b.get("n") or 0):
            fail(f"{label}: equity curve has {len(curve)} points for {b.get('n')} positions")
        run = bank
        for pt in curve:
            run += Decimal(str(pt.get("pnl_dollars")))
            if Decimal(str(pt.get("equity_dollars"))) != run:
                fail(f"{label}: curve point at {pt.get('ts')} says {pt.get('equity_dollars')} "
                     f"but the trades accumulate to {run}")
        if curve and Decimal(str(curve[-1]["equity_dollars"])) != end:
            fail(f"{label}: curve ends at {curve[-1]['equity_dollars']} but equity says {end}")
        for m in curve:
            if urllib.parse.urlparse(m.get("market_api_url") or "").netloc not in DEMO_HOSTS:
                fail(f"{label}: curve point {m.get('ticker')} has no official demo-API link")
        if bool(b.get("evaluable")) != (int(b.get("n") or 0) >= int(doc.get("min_n_for_a_claim") or 0)):
            fail(f"{label}: evaluable flag contradicts n vs the floor")
        topic_n = sum(int(v.get("n") or 0) for v in (b.get("by_topic") or {}).values())
        if topic_n != int(b.get("n") or 0):
            fail(f"{label}: by_topic covers {topic_n} of {b.get('n')} positions")
    declared = doc.get("trade_count")
    if declared is not None and total_n > int(declared):
        fail(f"strategies.json: results cover {total_n} trades but trade_count says {declared}")
    return stats


def check_html() -> None:
    index = os.path.join(SITE, "index.html")
    if not os.path.exists(index):
        fail("catalysts/index.html is missing")
        return
    html = open(index, encoding="utf-8").read()
    for bad in ("TODO", "FIXME", "XXX", "lorem ipsum", "coming soon", "insert value here"):
        if bad in html or bad.lower() in html.lower():
            fail(f"catalysts/index.html contains placeholder text {bad!r}")
    targets = re.findall(r'(?:href|src)="([^"]+)"', html)
    local = 0
    for t in targets:
        if t.startswith("#") or t.startswith("mailto:"):
            continue
        if t.startswith("http://"):
            fail(f"insecure link in index.html: {t}")
            continue
        if t.startswith("https://"):
            host = urllib.parse.urlparse(t).netloc
            if host in ALLOWED_EXTERNAL:
                continue
            # publisher/feed hosts are allowed only when the data lists them
            if host in _data_hosts():
                continue
            fail(f"index.html links an unrecorded host: {t}")
            continue
        rel = t.split("#", 1)[0]
        path = os.path.normpath(os.path.join(SITE, rel))
        if not os.path.exists(path):
            fail(f"broken local link in index.html: {t} -> {os.path.relpath(path, REPO)}")
        else:
            local += 1
    notes.append(f"{local} local link targets exist")
    js = os.path.join(SITE, "assets", "catalysts.js")
    css = os.path.join(SITE, "assets", "catalysts.css")
    for p in (js, css):
        if not os.path.exists(p):
            fail(f"missing asset {os.path.relpath(p, REPO)}")
    if os.path.exists(js):
        text = open(js, encoding="utf-8").read()
        if "innerHTML" in text and "esc(" not in text:
            fail("catalysts.js writes innerHTML without an escaper")
        if re.search(r"https?://(?!external-api\.demo\.kalshi\.co|demo-api\.kalshi\.co|"
                     r"docs\.kalshi\.com|demo\.kalshi\.co)[a-z0-9.-]+", text):
            bad = sorted({m.group(0) for m in re.finditer(
                r"https?://[a-z0-9.-]+\.[a-z]{2,}", text)
                if urllib.parse.urlparse(m.group(0)).netloc not in
                (DEMO_HOSTS | {"docs.kalshi.com", "demo.kalshi.co"})})
            if bad:
                fail(f"catalysts.js hard-codes a non-Kalshi URL: {bad[:3]}")


def _data_hosts() -> set:
    hosts = set()
    for name in ("feed_health.json", "swings.json"):
        doc = load_json(os.path.join(DATA, name), required=False)
        if not doc:
            continue
        blob = json.dumps(doc)
        for m in re.finditer(r'https://([^/"\\s]+)', blob):
            hosts.add(m.group(1))
    return hosts


def main() -> int:
    stats = check_swings()
    check_status()
    check_probes()
    strat = check_strategies()
    check_html()
    print(f"check_page: strategies: {strat['categories']} categor(y/ies), "
          f"{strat['trades']} simulated trade(s), {strat['evaluable']} above the evaluation floor")
    print(f"check_page: {stats['swings']} swings, {stats['with_links']} with candidate links, "
          f"{stats['resolved']} resolved, {stats['links']} rows with an official source link")
    for n in notes:
        print("  note:", n)
    if failures:
        print(f"check_page: FAILED ({len(failures)} problem(s))")
        for f in failures[:40]:
            print("  -", f)
        return 1
    print("check_page: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
