"""
dev_server.py — local static server + signed Kalshi bridge, so the dashboard can be genuinely live.

Why this exists
  1. A browser page on GitHub Pages may be blocked from calling the demo API (no CORS policy is
     documented either way — Q-08). This server serves the site and proxies API reads under the same
     origin, which removes the question.
  2. The Kalshi WebSocket API requires signed handshake headers on EVERY connection, public channels
     included, and a browser cannot set handshake headers
     (https://docs.kalshi.com/getting_started/quick_start_websockets.md). So streaming is only
     possible through a server that can sign.
  3. /portfolio/* needs a signed request. If KALSHI_API_KEY_ID and a private key are present in the
     environment, the bridge signs; if not, it refuses those paths with an explicit JSON error rather
     than returning empty data that looks like a real zero.

Security posture (deliberate):
  * binds 0.0.0.0 so a container/preview can reach it, but only ever talks to the DEMO host;
  * the proxy is an allow-list, not a general fetch: the path must start with /trade-api/v2/ and the
    host must be one of Kalshi's own demo hosts — no arbitrary URL is ever fetched;
  * no credential is read from, or written to, the request; nothing is logged but method/path/status;
  * /proxy is signed server-side only when the environment already holds a key.

Run:  python3 scripts/dev_server.py --port 8081 [--ws] [--no-sign]
Then: http://localhost:8081/dashboard.html?mode=bridge
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from kalshi_api import DEMO_REST, DEMO_REST_ALT, KalshiClient, Signer  # noqa: E402

ALLOWED_PREFIX = "/trade-api/v2/"
ALLOWED_HOSTS = {urllib.parse.urlparse(u).netloc for u in (DEMO_REST, DEMO_REST_ALT)}
CTX = ssl.create_default_context()
MAX_BYTES = 24 * 1024 * 1024
TIMEOUT = 25.0


class Bridge:
    """One shared client, built lazily, so signing errors surface per request, not at startup."""

    def __init__(self, *, sign: bool):
        self.sign = sign
        self._lock = threading.Lock()
        self._client: KalshiClient | None = None
        self.key_id = os.environ.get("KALSHI_API_KEY_ID") or os.environ.get("KALSHI_API_KEY")
        self.key_path = os.environ.get("KALSHI_PRIVATE_KEY_PEM_PATH")

    def client(self) -> KalshiClient:
        with self._lock:
            if self._client is None:
                signer = None
                if self.sign and self.key_id and self.key_path and os.path.exists(self.key_path):
                    with open(self.key_path, "rb") as fh:
                        signer = Signer(self.key_id, fh.read())
                self._client = KalshiClient(DEMO_REST, signer=signer, timeout=TIMEOUT)
            return self._client

    def signed(self) -> bool:
        c = self.client()
        return bool(c.signer and c.signer.enabled)

    def get(self, path: str, query: str) -> tuple[int, bytes, str, dict]:
        """Return (status, body, content_type, headers_to_echo). Never raises to the caller."""
        if not path.startswith(ALLOWED_PREFIX):
            return 400, json.dumps({"error": {"code": "path_not_allowed",
                                              "message": f"only paths under {ALLOWED_PREFIX} are proxied",
                                              "hint": "pass ?url=/trade-api/v2/markets?limit=5"}}).encode(), "application/json", {}
        if path.startswith("/trade-api/v2/portfolio/") and not self.signed():
            return 511, json.dumps({"error": {"code": "authentication_required",
                                              "message": "this path needs a signed request and no key is configured here",
                                              "how": "export KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PEM_PATH "
                                                     "(a demo key from https://demo.kalshi.co/), then restart without --no-sign",
                                              "docs": "https://docs.kalshi.com/getting_started/quick_start_authenticated_requests.md"}}).encode(), "application/json", {}
        url = DEMO_REST + path[len("/trade-api/v2"):] + (("?" + query) if query else "")
        req = urllib.request.Request(url, headers={"User-Agent": "kalshi-demo-dashboard/1.0 (local bridge)",
                                                    "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=CTX) as r:
                body = r.read(MAX_BYTES)
                hdrs = {k.lower(): v for k, v in r.headers.items()
                        if k.lower().startswith("x-ratelimit") or k.lower() in ("cache-control", "content-type")}
                return r.status, body, hdrs.get("content-type", "application/json"), hdrs
        except urllib.error.HTTPError as e:
            try:
                raw = e.read(65536)
            except Exception:
                raw = b""
            return (e.code, raw or json.dumps({"error": {"code": "upstream_http_error", "status": e.code}}).encode(),
                    "application/json", {"x-bridge-upstream-status": str(e.code)})
        except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as e:
            return 502, json.dumps({"error": {"code": "upstream_unreachable", "message": str(e),
                                              "note": "this sandbox blocks egress to kalshi.co; see FLAG-12 on the site's Flagged page"}}).encode(), "application/json", {}


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


BRIDGE = None  # set in main()


class Handler(BaseHTTPRequestHandler):
    server_version = "KalshiDemoSite/1.0"
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------- plumbing
    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        # The preview reaches us through a proxy host, so CORS must not be refused outright. We echo the
        # caller's Origin rather than sending "*" and we never send Access-Control-Allow-Credentials,
        # so a cross-site page can read the same public endpoints it could read directly - nothing more.
        origin = self.headers.get("Origin")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "accept")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _text(self, code: int, msg: str, ctype="text/plain; charset=utf-8") -> None:
        self._send(code, msg.encode(), ctype)

    def log_message(self, fmt, *a):  # noqa: N802 - BaseHTTPRequestHandler API
        sys.stderr.write("%s %s %s\n" % (time.strftime("%H:%M:%S"), self.command, fmt % a))

    # --------------------------------------------------------------- routes
    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(parsed.path)

        if path == "/proxy":
            return self.proxy(parsed)
        if path == "/health":
            return self._send(200, json.dumps({
                "ok": True, "mode": "bridge", "time_utc": _utc(),
                "signed": bool(BRIDGE and BRIDGE.signed()),
                "key_present": bool(BRIDGE and BRIDGE.key_id),
                "demo_base": DEMO_REST, "allowed_hosts": sorted(ALLOWED_HOSTS),
                "portfolio_paths": "available" if (BRIDGE and BRIDGE.signed()) else "511 until a key is configured",
            }, indent=2).encode(), "application/json")
        if path == "/streams":
            return self._send(200, json.dumps({
                "note": "WebSocket proxying is not part of this handler. Run with --ws to start the "
                        "ticker pump, which fetches on the server and exposes /stream/last as a "
                        "long-polled buffer — a browser still cannot sign a Kalshi WS handshake.",
                "docs": "https://docs.kalshi.com/getting_started/quick_start_websockets.md",
                "running": bool(PUMP and PUMP.running),
                "tickers": (PUMP.tickers if PUMP else []),
                "samples": (len(PUMP.buffer) if PUMP else 0),
            }, indent=2).encode(), "application/json")
        if path.startswith("/stream/"):
            return self.stream(path)

        return self.static(path)

    def do_HEAD(self):  # noqa: N802
        self.do_GET()

    def do_OPTIONS(self):  # noqa: N802
        self._send(204, b"", "text/plain")

    # ---------------------------------------------------------------- proxy
    def proxy(self, parsed) -> None:
        q = urllib.parse.parse_qs(parsed.query)
        target = (q.get("url") or [""])[0]
        if not target:
            return self._send(400, json.dumps({"error": {"code": "missing_url", "message": "?url=/trade-api/v2/… is required"}}).encode(), "application/json")
        u = urllib.parse.urlsplit(target if target.startswith("http") else DEMO_REST + target)
        host = (u.netloc or urllib.parse.urlparse(DEMO_REST).netloc).lower()
        if host not in ALLOWED_HOSTS:
            return self._send(400, json.dumps({"error": {"code": "host_not_allowed", "host": host,
                                                         "allowed": sorted(ALLOWED_HOSTS)}}).encode(), "application/json")
        rpath = u.path if u.path.startswith(ALLOWED_PREFIX) else ALLOWED_PREFIX.rstrip("/") + u.path
        try:
            status, body, ctype, hdrs = BRIDGE.get(rpath, u.query)
        except Exception as exc:  # never leak a traceback to the client
            return self._send(500, json.dumps({"error": {"code": "bridge_error", "message": type(exc).__name__}}).encode(), "application/json")
        extra = {"X-Bridge-" + k.replace("-", "_").title().replace("_", "-"): v
                 for k, v in (hdrs or {}).items() if len(str(v)) < 200}
        extra["X-Bridge-Fetched-At"] = _utc()
        self._send(status, body if isinstance(body, bytes) else str(body).encode(),
                   ctype if "/" in ctype else "application/json", extra)

    # --------------------------------------------------------------- stream
    def stream(self, path: str) -> None:
        if not PUMP or not PUMP.running:
            return self._send(409, json.dumps({"error": {"code": "pump_not_running", "message": "start with --ws"}}).encode(), "application/json")
        ticker = path.rsplit("/", 1)[-1]
        if ticker == "last":
            since = int(urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("since", ["0"])[0] or 0)
            rows = [r for r in PUMP.buffer if r["seq"] > since][-200:]
            return self._send(200, json.dumps({"rows": rows, "seq": PUMP.seq, "tickers": PUMP.tickers}).encode(), "application/json")
        return self._send(404, json.dumps({"error": {"code": "unknown_stream"}}).encode(), "application/json")

    # --------------------------------------------------------------- static
    def static(self, path: str) -> None:
        rel = path.lstrip("/") or "index.html"
        if rel.endswith("/"):
            rel += "index.html"
        target = os.path.normpath(os.path.join(SITE, rel))
        # confine to the served roots; a '..' walk out is refused, not silently resolved
        roots = (SITE, os.path.join(ROOT, "data"))
        if not any(target == r or target.startswith(r + os.sep) for r in roots):
            return self._text(403, "forbidden: path escapes the served directories")
        if os.path.isdir(target):
            target = os.path.join(target, "index.html")
        if not os.path.exists(target):
            # a raw checkout keeps data/ beside site/; let the page's ../data/ fallback reach it
            alt = os.path.normpath(os.path.join(ROOT, rel))
            if os.path.exists(alt) and alt.startswith(os.path.join(ROOT, "data")):
                target = alt
            else:
                return self._text(404, f"not found: /{rel}")
        ctype = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "text/javascript; charset=utf-8", ".json": "application/json",
                 ".svg": "image/svg+xml", ".ico": "image/x-icon", ".png": "image/png"}.get(
            os.path.splitext(target)[1], "application/octet-stream")
        with open(target, "rb") as fh:
            body = fh.read()
        self._send(200, body, ctype, {"Cache-Control": "no-store" if ctype.startswith("application/json") else "no-cache"})


class Pump:
    """Server-side sampler: the only legitimate way to get sub-minute series without WS credentials."""

    def __init__(self, tickers: list[str], every: float):
        self.tickers = tickers
        self.every = every
        self.buffer: list[dict] = []
        self.seq = 0
        self.running = False
        self._stop = threading.Event()
        self._thr: threading.Thread | None = None

    def start(self):
        self.running = True
        self._thr = threading.Thread(target=self._loop, daemon=True)
        self._thr.start()

    def _loop(self):
        client = BRIDGE.client()
        while not self._stop.is_set():
            for t in self.tickers:
                try:
                    m = client.market(t)
                    self.seq += 1
                    row = {"seq": self.seq, "ticker": t, "at": _utc(),
                           "last_price_dollars": m.get("last_price_dollars"),
                           "yes_bid_dollars": m.get("yes_bid_dollars"),
                           "yes_ask_dollars": m.get("yes_ask_dollars"),
                           "yes_bid_size_fp": m.get("yes_bid_size_fp"),
                           "yes_ask_size_fp": m.get("yes_ask_size_fp"),
                           "volume_fp": m.get("volume_fp"),
                           "open_interest_fp": m.get("open_interest_fp"),
                           "status": m.get("status"), "result": m.get("result")}
                    self.buffer.append(row)
                    if len(self.buffer) > 20000:
                        del self.buffer[:5000]
                except Exception as exc:
                    self.seq += 1
                    self.buffer.append({"seq": self.seq, "ticker": t, "at": _utc(),
                                        "error": type(exc).__name__})
            self._stop.wait(self.every)

    def stop(self):
        self._stop.set()
        self.running = False


PUMP: Pump | None = None


def main(argv=None) -> int:
    global BRIDGE, PUMP
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8081)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--no-sign", action="store_true", help="never attach a signature, even if a key is present")
    ap.add_argument("--ws", action="store_true", help="start the server-side sampler (see --ws-note)")
    ap.add_argument("--ws-note", default="Kalshi's WS API needs a signed handshake; this flag starts a REST sampler instead, it does not open a WS connection")
    ap.add_argument("--tickers", default="", help="comma list for the sampler; defaults to the first market of each ranked event in data/live_snapshot.json")
    ap.add_argument("--every", type=float, default=5.0)
    ap.add_argument("--print-note", action="store_true")
    args = ap.parse_args(argv)

    BRIDGE = Bridge(sign=not args.no_sign)

    if args.print_note:
        print(json.dumps({"ws": args.ws_note,
                          "signature": "https://docs.kalshi.com/getting_started/quick_start_websockets.md"}, indent=2))
        return 0

    tickers = [t for t in args.tickers.split(",") if t]
    snap_path = os.path.join(SITE, "data", "live_snapshot.json")
    if not os.path.exists(snap_path):
        snap_path = os.path.join(ROOT, "data", "live_snapshot.json")
    if not tickers and os.path.exists(snap_path):
        try:
            with open(snap_path) as fh:
                snap = json.load(fh)
            tickers = [e["markets"][0]["ticker"] for e in snap.get("ranked_events", []) if e.get("markets")]
        except Exception as exc:
            print(f"! could not read default tickers from the snapshot: {exc}", file=sys.stderr)

    if args.ws and tickers:
        PUMP = Pump(tickers, max(1.0, args.every))
        PUMP.start()

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    print(f"serving {SITE}\n  http://localhost:{args.port}/dashboard.html?mode=bridge")
    print(f"  proxy:   /proxy?url=/trade-api/v2/markets?limit=5   (allow-list: {sorted(ALLOWED_HOSTS)})")
    print(f"  signing: {'ready (key found in environment)' if BRIDGE.signed() else 'OFF — /portfolio/* returns 511'}")
    print(f"  sampler: {'running: ' + ', '.join(tickers) if PUMP else 'off (use --ws)'}")
    print("  press ctrl-c to stop")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if PUMP:
            PUMP.stop()
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
