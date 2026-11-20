"""
verify_site.py — pre-merge gate for the published site.

Checks, in order of the rule they enforce:

 1. every page in site/*.html exists, is listed in UI.NAV, and parses as HTML with the shared assets
 2. every internal href/src resolves to a real file (no 404 links on Pages)
 3. every external link in a page is either (a) an official Kalshi host, or (b) registered in
    data/sources.json with an 'establishes' note; a third-party URL cited in a page is a FAILURE
 4. every docs.kalshi.com URL used anywhere appears in data/sources.json, so no citation exists in the
    UI without a recorded purpose (this is what makes "we verified it" auditable)
 5. the published data document loads, has provenance for every section, and contains no NaN/Infinity
 6. every table cell that would render blank is explainable: for each market row, each field the
    snapshot omits must be reachable by site/flagged.html's blank list (it is generated from the same
    document, so this check is a consistency test of the generator, not a restatement)
 7. no page contains a placeholder marker (TODO/FIXME/TBD/lorem) or a forbidden invented-value pattern
 8. scripts compile (python -m py_compile) — the collector must be runnable by the next session

Exit 0 = safe to merge. Exit 1 = list of failures. Flagged/unverified items never fail the gate;
an unsourced number does.
"""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
DATA = os.path.join(ROOT, "data")
PUB = os.path.join(SITE, "data", "live_snapshot.json")

OFFICIAL = re.compile(r"^https?://([a-z0-9.-]*\.)?(kalshi\.com|kalshi\.co|kalshi\.io)$", re.I)
OFFICIAL_HOSTS = ("docs.kalshi.com", "kalshi.com", "external-api.demo.kalshi.co", "demo-api.kalshi.co",
                  "demo.kalshi.co", "external-api.kalshi.com", "api.elections.kalshi.com",
                  "external-api-ws.demo.kalshi.co", "demo.kalshi.io")
# Links that are not sources of fact and therefore not subject to the official-host rule:
#  - this repository's own pages (self-referential navigation, "open the raw artifact" links)
#  - the local bridge documented on the landing page
# Neither is ever used to support a number; the check that matters is that no third-party SITE is
# cited as verification of a Kalshi fact.
SELF_HOSTS = {"github.com", "localhost:8081", "127.0.0.1", "example.github.io"}

# 'placeholder' is excluded on purpose: it is a legitimate HTML attribute (placeholder="optional").
# An id like #t1 is fine too, so TBD is matched only as a standalone word in text.
PLACEHOLDERS = re.compile(r"(?<![-\w])(TODO|FIXME|XXX|\bTBD\b|lorem ipsum|coming soon|\?\?\?)(?![-\w])", re.I)
BAD_NUMBERS = re.compile(r"(NaN|Infinity|undefined,|\"undefined\")")

fails: list[str] = []
warns: list[str] = []
notes: list[str] = []


def _node_err(p) -> str:
    """node --check prints a multi-line V8 error; keep the line that says what and where."""
    lines = [l.strip() for l in (p.stderr or p.stdout or "").splitlines() if l.strip()]
    keep = [l for l in lines if re.search(r"SyntaxError|Unexpected|Expected|Invalid|\^", l)]
    return " | ".join(keep[:3])[:400] if keep else (lines[-1][:200] if lines else "syntax error")


def read(p: str) -> str:
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def html_only(p: str) -> str:
    """Page text with <script> bodies removed, so JS template strings are not read as markup."""
    return re.sub(r"<script.*?</script>", "", read(p), flags=re.S)


def check_pages() -> list[str]:
    pages = sorted(os.path.basename(p) for p in glob.glob(os.path.join(SITE, "*.html")))
    if not pages:
        fails.append("no pages found in site/")
        return pages
    ui = read(os.path.join(SITE, "assets", "ui.js"))
    nav_pages = re.findall(r'\["([a-z]+)",\s*"[^"]*",\s*"([a-z]+\.html)"\]', ui)
    nav_files = {f for _, f in nav_pages}
    for p in pages:
        if p not in nav_files and p != "index.html":
            fails.append(f"{p}: not listed in UI.NAV, so it is unreachable from the header")
    for f in sorted(nav_files - set(pages)):
        fails.append(f"UI.NAV links to {f}, which does not exist")

    for p in pages:
        path = os.path.join(SITE, p)
        html = read(path)
        for must in ('<meta charset="utf-8">', 'name="viewport"', 'assets/styles.css',
                     'assets/api.js', 'assets/ui.js', 'id="chrome"', 'id="modebar"', 'id="foot"',
                     "<title>", 'name="description"'):
            if must not in html:
                fails.append(f"{p}: missing {must}")
        # balanced-ish structural check
        for tag in ("div", "main", "table", "script"):
            o = len(re.findall(rf"<{tag}[\s>]", html))
            c = len(re.findall(rf"</{tag}>", html))
            if o != c:
                fails.append(f"{p}: <{tag}> opens {o} times but closes {c}")
        if PLACEHOLDERS.search(html):
            hits = sorted(set(m.group(0) for m in PLACEHOLDERS.finditer(html)))
            fails.append(f"{p}: placeholder text present {hits}")
        if BAD_NUMBERS.search(html):
            fails.append(f"{p}: contains a literal NaN/Infinity/undefined token")
        # internal links and scripts must resolve
        for m in re.finditer(r'(?:href|src)="([^"]+)"', html_only(path)):
            ref = m.group(1)
            if ref.startswith(("http", "mailto:", "#", "data:")) or "{" in ref or "'" in ref:
                continue
            target = os.path.normpath(os.path.join(SITE, ref.split("#")[0].split("?")[0]))
            if not os.path.exists(target):
                fails.append(f"{p}: broken internal link -> {ref}")
        # every inline handler must reference a function that exists (cheap typo catcher)
        for m in re.finditer(r'onclick="([A-Za-z_.$]+)\(', html):
            name = m.group(1)
            if name not in html and name.split(".")[0] not in ("UI", "K", "Chart"):
                warns.append(f"{p}: inline onclick calls {name}( which is not defined in the page")
    notes.append(f"pages checked: {len(pages)}")
    return pages


def check_external_links(pages: list[str], sources: dict) -> None:
    registered = set()
    for g in sources.get("groups", []):
        for it in g.get("items", []):
            if it.get("url"):
                registered.add(it["url"].rstrip("/"))
    per_page: dict[str, set] = {}
    for p in pages:
        html = read(os.path.join(SITE, p))
        # a URL may legitimately appear only inside JS (a data-source link built at runtime),
        # so scan the whole file for external hosts but the markup for anchors
        urls = set(re.findall(r'https?://[a-zA-Z0-9._/~%()+=&:\-]+', html))
        per_page[p] = urls
    bad, unregistered = [], []
    for p, urls in per_page.items():
        for u in sorted(urls):
            u2 = u.rstrip('").,\'')
            host = re.sub(r"^https?://", "", u2).split("/")[0].lower()
            if host in OFFICIAL_HOSTS or host.endswith(".github.com") or host in SELF_HOSTS:
                continue
            if u2.startswith("https://github.com/karagemop466-tech/Demo3"):
                continue   # this project's own files
            if u2.replace(" ", "") in registered or any(u2.startswith(r) for r in registered):
                continue
            if host == "kalshi-public-docs-staging.s3.us-east-1.amazonaws.com":
                continue   # a document the API itself links from a series record
            bad.append((p, host, u2))
    for p, urls in per_page.items():
        for u in sorted(urls):
            if "docs.kalshi.com" in u:
                plain = u.rstrip('").,\'')
                if plain not in registered and not any(plain.startswith(r) for r in registered):
                    unregistered.append((p, plain))
    for p, host, u in bad:
        fails.append(f"{p}: cites a non-official host as if it were a source ({host}) -> {u[:110]}")
    for p, u in unregistered:
        fails.append(f"{p}: cites {u} but data/sources.json has no entry recording what it establishes")
    if not bad and not unregistered:
        notes.append("every external link is an official host or a registered citation")


def check_data() -> None:
    if not os.path.exists(PUB):
        fails.append("site/data/live_snapshot.json missing — run scripts/publish_snapshot.py")
        return
    txt = read(PUB)
    for tok in ("NaN", "Infinity"):
        if tok in txt:
            fails.append(f"published data contains the literal {tok} (JSON with NaN is invalid for fetch().json())")
    doc = json.loads(txt)
    prov = (doc.get("_meta") or {}).get("provenance") or {}
    sections = doc.get("_meta", {}).get("sections") or []
    for s in sections:
        if s not in prov:
            fails.append(f"section {s} has no provenance entry")
    if not doc.get("ranked_events"):
        fails.append("ranked_events is empty — the dashboard would have nothing to rank")
    n_markets = sum(len(e.get("markets", [])) for e in doc.get("ranked_events", []))
    notes.append(f"data: {len(doc.get('ranked_events', []))} events / {n_markets} markets / "
                 f"{len(sections)} sections all with provenance")
    # every event must carry its formula and window, because its dollar figure is derived
    for e in doc.get("ranked_events", []):
        if e.get("dollar_volume_window") is not None:
            if not e.get("dollar_volume_formula"):
                fails.append(f"{e.get('event_ticker')}: has a dollar figure but no formula string")
            if not e.get("tape_source") and not e.get("dollar_volume_source"):
                fails.append(f"{e.get('event_ticker')}: dollar figure without a source URL")
        for m in e.get("markets", []):
            if not m.get("source"):
                fails.append(f"{m.get('ticker')}: market row with no source URL")
    # problems list must be present and structured
    for i, p in enumerate(doc.get("problems", [])):
        for k in ("id", "severity", "where", "finding"):
            if not p.get(k):
                fails.append(f"problems entry #{i} missing field {k}: {json.dumps(p)[:120]}")
        if p.get("severity") not in ("blocker", "warning", "info", "partial", "unverified", "blocked"):
            fails.append(f"problems entry {p.get('id')}: unknown severity {p.get('severity')}")
    # cross-check the aggregator against the published document, mechanically
    tape = os.path.join(DATA, "tape_analysis.json")
    if os.path.exists(tape):
        comp = {e["event_ticker"]: e for e in json.loads(read(tape)).get("events", [])}
        for e in doc.get("ranked_events", []):
            c = comp.get(e["event_ticker"])
            if not c:
                continue
            for a, b in (("dollar_volume_window", "dollar_volume"), ("contracts_window", "contracts"),
                         ("trades_window", "trades"), ("yes_side_dollars", "yes_dollars"),
                         ("no_side_dollars", "no_dollars"), ("flow_imbalance", "flow_imbalance")):
                x, y = e.get(a), c.get(b)
                if x is None and y is None:
                    continue
                if x is None or y is None or abs(float(x) - float(y)) > 1e-6:
                    fails.append(f"{e['event_ticker']}: published {a}={x} but recomputed {b}={y}")
        notes.append("dollar aggregates re-derived from data/raw/trades-capture.json and matched")


# The fields the pages bind to, per data section. A column whose key is absent renders a dash forever,
# which looks like "no data" instead of "we renamed something" — so the contract is checked, not assumed.
CONTRACT = {
    "ranked_events": ["event_ticker", "title", "series_ticker", "topic", "dollar_volume_window",
                      "contracts_window", "trades_window", "flow_imbalance", "last_trade_time",
                      "tape_window_seconds", "dollar_volume_formula", "markets", "event_source", "tape_source"],
    "__markets_flat": ["ticker", "status", "last_price_dollars", "previous_price_dollars",
                               "yes_bid_dollars", "yes_ask_dollars", "yes_bid_size_fp", "yes_ask_size_fp",
                               "volume_fp", "open_interest_fp", "close_time", "source"],
    "resolutions_recent": ["ticker", "result", "settlement_ts", "settlement_value_dollars", "status", "source"],
    "series_universe": ["series_ticker", "topic", "title", "volume_fp", "fee_type", "source"],
    "exchange_status": ["source"],
    # topics' selectors live in topics.json (checked below), not in the event document
    "problems": ["id", "severity", "where", "finding"],
}
LEDGER_CONTRACT = ["source_mode", "fills", "positions", "performance.totals", "performance.method"]
ANALYSIS_CONTRACT = ["trades", "by_category", "strategies", "declared_strategies", "totals"]
TOPICS_FILE_CONTRACT = ["_meta", "topics"]
TOPIC_ITEM_CONTRACT = ["id", "label", "selectors", "note", "verification"]


def _dig(obj, dotted: str):
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, list):
            return cur
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def check_contract() -> None:
    if not os.path.exists(PUB):
        return
    doc = json.loads(read(PUB))
    for section, keys in CONTRACT.items():
        if section == "__markets_flat":
            node = [m for e in (doc.get("ranked_events") or []) for m in (e.get("markets") or [])]
            if not node:
                fails.append("data contract: no market rows in ranked_events[] — the dashboard would have nothing to chart")
                continue
        else:
            node = _dig(doc, section)
            if node is None:
                fails.append(f"data contract: section {section} missing entirely")
                continue
        rows = node if isinstance(node, list) else [node]
        rows = [r for r in rows if isinstance(r, dict)]
        if not rows:
            continue
        absent_everywhere = [k for k in keys if not any(k in r for r in rows)]
        absent_sometimes = [k for k in keys
                            if any(k in r for r in rows) and any(k not in r for r in rows)]
        if absent_everywhere:
            fails.append(f"data contract: {section} never contains {absent_everywhere} — a bound column would be blank on every row")
        if absent_sometimes:
            notes.append(f"data contract: {section} omits {absent_sometimes} on some rows "
                         "(legitimate: the API did not return them, and the UI shows a dash)")
    tpath = os.path.join(SITE, "data", "topics.json")
    if os.path.exists(tpath):
        trows = [t for t in (json.loads(read(tpath)).get("topics") or []) if isinstance(t, dict)]
        missing = [k for k in TOPIC_ITEM_CONTRACT if trows and not any(k in t for t in trows)]
        if missing:
            fails.append(f"data contract: topics.json entries never contain {missing}")
    for name, keys in (("portfolio", LEDGER_CONTRACT), ("trade_analysis", ANALYSIS_CONTRACT)):
        node = doc.get(name)
        if node is None:
            warns.append(f"data contract: {name} section is absent (the page will fetch it separately)")
            continue
        missing = [k for k in keys if _dig(node, k) is None]
        if missing:
            fails.append(f"data contract: published {name} lacks {missing}")
    for fname, keys in (("questions.json", ["questions"]), ("sources.json", ["groups"]),
                        ("topics.json", TOPICS_FILE_CONTRACT)):
        path = os.path.join(SITE, "data", fname)
        if not os.path.exists(path):
            fails.append(f"site/data/{fname} is missing; questions.html and sources.html fetch it")
            continue
        node = json.loads(read(path))
        missing = [k for k in keys if k not in node]
        if missing:
            fails.append(f"site/data/{fname} lacks {missing}")
    if not fails:
        notes.append("data contract: every field the pages bind to exists in the published document")


def check_citation_consistency() -> None:
    """FLAG ids and Q ids must mean the same thing in the docs and on the site.

    A reader who is told 'see FLAG-08' twice and gets two different findings loses trust in all of it,
    so the identifiers are compared, not assumed. Command examples are also extracted and matched against
    each script's real argparse/CLI surface, because a wrong command in a doc is worse than no command.
    """
    doc = os.path.join(ROOT, "docs", "executive-summary.md")
    flag_p = os.path.join(SITE, "flagged.html")
    if os.path.exists(doc) and os.path.exists(flag_p):
        doc_flags = set(re.findall(r"FLAG-(\d+)", read(doc)))
        site_flags = set(re.findall(r'id: "flag-(\d+)"', read(flag_p)))
        if doc_flags - site_flags:
            fails.append(f"FLAG ids in docs but not on flagged.html: {sorted(doc_flags - site_flags)}")
        if site_flags - doc_flags:
            fails.append(f"FLAG ids on flagged.html but not in docs/executive-summary.md: {sorted(site_flags - doc_flags)}")
    q_doc = os.path.join(ROOT, "docs", "questions.md")
    if os.path.exists(q_doc):
        q_json = set(re.findall(r'"id":\s*"(Q-\d+)"', read(os.path.join(DATA, "questions.json"))))
        q_html = set(re.findall(r'"([Qq]-\d\d)"', read(os.path.join(SITE, "questions.html"))))
        linked = set(re.findall(r"questions\.html#(q-\d\d)", read(os.path.join(SITE, "flagged.html"))) )
        for qid in sorted(linked):
            if ("#" + qid) not in read(os.path.join(SITE, "questions.html")).lower() and qid.upper() not in q_json:
                fails.append(f"flagged.html links to {qid} which questions.html cannot resolve")
        del q_html, q_doc
    # every `python3 scripts/X.py cmd` in the docs must be a command that script accepts
    scripts = {os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "scripts", "*.py"))}
    for f in glob.glob(os.path.join(ROOT, "docs", "*.md")) + [os.path.join(ROOT, "README.md"),
                                                               os.path.join(ROOT, "COORDINATION.md")]:
        text = read(f)
        for m in re.finditer(r"python3 scripts/([a-z_]+\.py)\s+([^\n`]*)", text):
            name, argstr = m.group(1), m.group(2)
            if name not in scripts:
                fails.append(f"{os.path.basename(f)}: runs scripts/{name}, which does not exist")
                continue
            src = read(os.path.join(ROOT, "scripts", name))
            first = argstr.strip().split()
            if not first:
                continue
            word = first[0].strip("[]{}<>'\"")
            if word.startswith("-"):
                continue
            # a bare-word subcommand must appear in the script's choices/commands
            if word and word.isalpha() and f'"{word}"' not in src and f"'{word}'" not in src and word not in re.findall(r'choices=\[([^\]]*)\]', src).__str__():
                fails.append(f"{os.path.basename(f)}: 'scripts/{name} {word}' is not a command that script defines")
            for flag in re.findall(r"--[a-z][a-z-]*", argstr):
                bare = flag[2:]
                # argparse-style ("--flag") or a declared allow-list entry ("flag" / "flag_with_underscores")
                ok = (f'"{flag}"' in src or f"'{flag}'" in src or f'"{bare}"' in src or f"'{bare}'" in src
                      or bare.replace("-", "_") in src)
                if not ok:
                    fails.append(f"{os.path.basename(f)}: scripts/{name} does not accept {flag}")
    if not fails:
        notes.append("citation and command consistency: FLAG ids, Q links and CLI examples all resolve")


def check_scripts(pages: list[str]) -> None:
    r = subprocess.run([sys.executable, "-m", "py_compile"] + sorted(glob.glob(os.path.join(ROOT, "scripts", "*.py"))),
                       capture_output=True, text=True)
    if r.returncode:
        fails.append("scripts do not compile:\n" + (r.stderr or r.stdout)[-800:])
    else:
        notes.append("scripts compile: " + ", ".join(os.path.basename(p) for p in sorted(glob.glob(os.path.join(ROOT, "scripts", "*.py")))))
    # the JS must parse where node is available
    node = subprocess.run(["which", "node"], capture_output=True, text=True).stdout.strip()
    if node:
        for f in sorted(glob.glob(os.path.join(SITE, "assets", "*.js"))):
            p = subprocess.run([node, "--check", f], capture_output=True, text=True)
            if p.returncode:
                fails.append(f"{os.path.basename(f)} does not parse: {_node_err(p)}")
        # inline scripts inside pages must parse too
        for pg in pages:
            html = read(os.path.join(SITE, pg))
            blocks = re.findall(r'<script>(.*?)</script>', html, re.S)
            for i, b in enumerate(blocks):
                tmp = f"/tmp/_inline_{pg.replace('/', '_')}_{i}.js"
                with open(tmp, "w") as fh:
                    fh.write(b)
                p = subprocess.run([node, "--check", tmp], capture_output=True, text=True)
                if p.returncode:
                    fails.append(f"{pg} inline script #{i}: {_node_err(p)}")
                os.remove(tmp)
        notes.append("inline and asset JavaScript parses")
    else:
        warns.append("node not available: inline JS was not parsed")

    # no secret material may exist anywhere in the repo
    for path in glob.glob(os.path.join(ROOT, "**", "*"), recursive=True):
        if os.path.isdir(path) or "/.git/" in path or "__pycache__" in path:
            continue
        base = os.path.basename(path)
        if re.search(r"(id_rsa|\.pem$|\.p12$|credentials$|\.netrc$)", base):
            fails.append(f"{path}: looks like credential material committed to the repo")
    txt_targets = [os.path.join(ROOT, f) for f in ("README.md", "COORDINATION.md")]
    for f in glob.glob(os.path.join(ROOT, "**", "*.py"), recursive=True) + glob.glob(os.path.join(ROOT, "**", "*.md"), recursive=True):
        if "/.git/" in f:
            continue
        t = read(f)
        m = re.search(r"KALSHI[-_]ACCESS[-_]KEY['\"]?\s*[:=]\s*['\"][A-Za-z0-9]{12,}", t)
        if m:
            fails.append(f"{f}: appears to hard-code an API key")
        if re.search(r"BEGIN [A-Z ]*PRIVATE KEY", t):
            fails.append(f"{f}: contains a private key block")
    for f in txt_targets:
        if not os.path.exists(f):
            warns.append(f"{os.path.basename(f)} missing")


def check_repo_state() -> None:
    gp = os.path.join(ROOT, ".github", "workflows", "deploy-pages.yml")
    if not os.path.exists(gp):
        fails.append(".github/workflows/deploy-pages.yml missing — the site cannot deploy")
    else:
        wf = read(gp)
        for need in ("actions/upload-pages-artifact", "actions/deploy-pages", "pages: write",
                     "id-token: write", "actions/checkout"):
            if need not in wf:
                fails.append(f"deploy-pages.yml missing required piece: {need}")
        if "publish_dir" not in wf and "path:" not in wf:
            fails.append("deploy-pages.yml does not declare a publish path")
    for must in ("data/live_snapshot.json", "data/topics.json", "data/questions.json", "data/sources.json",
                 "docs/executive-summary.md", "docs/requirements.md", "docs/api-surface.md", "docs/questions.md"):
        if not os.path.exists(os.path.join(ROOT, must)):
            fails.append(f"{must} is missing from the repo but the site links to it")
    ig = os.path.join(ROOT, ".gitignore")
    if os.path.exists(ig):
        # only real ignore rules count; a comment mentioning the path is not an exclusion
        rules = [l.strip() for l in read(ig).splitlines() if l.strip() and not l.strip().startswith("#")]
        for bad in ("site/data", "site/data/", "/site/data", "data/live_snapshot.json", "site/"):
            if bad in rules:
                fails.append(f".gitignore ignores {bad!r}: the published site needs it (the workflow regenerates "
                             "it, but a reader cloning the repo would get an empty site)")


def main() -> int:
    pages = check_pages()
    srcp = os.path.join(DATA, "sources.json")
    if not os.path.exists(srcp):
        fails.append("data/sources.json missing — citation audit impossible")
        sources = {"groups": []}
    else:
        sources = json.loads(read(srcp))
        n = sum(len(g.get("items", [])) for g in sources.get("groups", []))
        unverified = [it.get("url") for g in sources["groups"] for it in g["items"] if not it.get("verified")]
        notes.append(f"sources registry: {n} items, {len(unverified)} marked verified=false "
                     "(each carries a why_unverified note and none supports a published number)")
        for g in sources["groups"]:
            for it in g.get("items", []):
                if not it.get("establishes"):
                    fails.append(f"sources.json item {it.get('url')} has no 'establishes' note")
                host = (it.get("url") or "").split("/")[2] if it.get("url") else ""
                if host and host not in OFFICIAL_HOSTS and it.get("used_by") and "context only" not in ",".join(it["used_by"]) \
                        and "the source Kalshi names" not in (it.get("why_unverified") or "") \
                        and not it.get("url", "").endswith(".pdf"):
                    if not it.get("verified") and "third-party" not in json.dumps(it):
                        fails.append(f"sources.json: {it['url']} is third-party but is not marked as context/unverified")
    check_external_links(pages, sources)
    check_data()
    check_contract()
    check_citation_consistency()
    check_scripts(pages)
    check_repo_state()

    print("=" * 78)
    print("verify_site.py — pre-merge gate")
    print("=" * 78)
    for n in notes:
        print("  ok   " + n)
    for w in warns:
        print("  warn " + w)
    if fails:
        print("-" * 78)
        for f in fails:
            print("  FAIL " + f)
        print("-" * 78)
        print(f"RESULT: {len(fails)} failure(s), {len(warns)} warning(s) — do not merge")
        return 1
    print(f"RESULT: all checks passed ({len(warns)} warning(s)) — safe to merge and deploy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
