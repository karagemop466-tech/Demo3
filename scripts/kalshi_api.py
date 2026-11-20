"""
kalshi_api.py — Kalshi Trade API v2 client (demo + production), stdlib-first.

Public market-data endpoints need no auth. Everything under /portfolio and every
WebSocket handshake needs a signed request:

    message   = f"{timestamp_ms}{METHOD}{path_without_query}"   # path includes /trade-api/v2
    signature = RSA-PSS(SHA-256, salt_len = digest_len) -> base64   # Ed25519 keys sign directly
    headers   = KALSHI-ACCESS-KEY / KALSHI-ACCESS-TIMESTAMP / KALSHI-ACCESS-SIGNATURE

Sources (read 2026-11-20):
  signing            https://docs.kalshi.com/getting_started/quick_start_authenticated_requests.md
  signed WS path     https://docs.kalshi.com/getting_started/quick_start_websockets.md
  environments       https://docs.kalshi.com/getting_started/api_environments.md
  429 / no Retry-After, X-RateLimit-* headers
                     https://docs.kalshi.com/getting_started/rate_limits.md
  order endpoints    https://docs.kalshi.com/api-reference/orders/create-order-v2.md

No third-party dependency is required: signing uses `cryptography` when installed and
falls back to the `openssl` CLI otherwise.
"""

from __future__ import annotations

import base64
import json
import os
import random
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable, Iterator

DEMO_REST = "https://external-api.demo.kalshi.co/trade-api/v2"
DEMO_REST_ALT = "https://demo-api.kalshi.co/trade-api/v2"
PROD_REST = "https://external-api.kalshi.com/trade-api/v2"
DEMO_WS = "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2"
PROD_WS = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"

API_PREFIX = "/trade-api/v2"

USER_AGENT = "Demo3-kalshi-dashboard/1.0 (+https://github.com/karagemop466-tech/Demo3)"

# Endpoints that provably do not require credentials. Anything else is signed if a key
# is configured, and sent unsigned otherwise (the API answers 401, which we surface).
PUBLIC_PREFIXES = (
    "/exchange/",
    "/series",
    "/events",
    "/markets",
    "/search/",
    "/milestones",
    "/structured_targets",
    "/multivariate_event_collections",
    "/live_data",
)


class KalshiError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, body: str = "", code: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body
        self.code = code


def _is_public(path: str) -> bool:
    return path.startswith(PUBLIC_PREFIXES)


class Signer:
    """Produces the three KALSHI-ACCESS-* headers for a (method, signed_path) pair."""

    def __init__(self, key_id: str | None = None, private_key_pem: bytes | None = None):
        self.key_id = key_id or os.environ.get("KALSHI_API_KEY_ID", "")
        pem = private_key_pem
        if pem is None:
            env_pem = os.environ.get("KALSHI_PRIVATE_KEY_PEM", "")
            path = os.environ.get("KALSHI_PRIVATE_KEY_PEM_PATH", "")
            if env_pem:
                pem = env_pem.encode()
            elif path and os.path.exists(path):
                pem = open(path, "rb").read()
        self.private_key_pem = pem
        self._crypto_key = None
        if pem:
            try:
                from cryptography.hazmat.primitives import serialization  # type: ignore

                self._crypto_key = serialization.load_pem_private_key(pem, password=None)
            except ImportError:
                self._crypto_key = None

    @property
    def enabled(self) -> bool:
        return bool(self.key_id and self.private_key_pem)

    def headers(self, method: str, signed_path: str) -> dict[str, str]:
        ts = str(int(time.time() * 1000))
        message = f"{ts}{method.upper()}{signed_path}".encode("utf-8")
        sig = self._sign(message)
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": sig,
        }

    def _sign(self, message: bytes) -> str:
        if self._crypto_key is not None:
            from cryptography.hazmat.primitives import hashes  # type: ignore
            from cryptography.hazmat.primitives.asymmetric import padding  # type: ignore
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # type: ignore

            if isinstance(self._crypto_key, Ed25519PrivateKey):
                return base64.b64encode(self._crypto_key.sign(message)).decode("ascii")
            signature = self._crypto_key.sign(
                message,
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
                hashes.SHA256(),
            )
            return base64.b64encode(signature).decode("ascii")
        return self._sign_with_openssl(message)

    def _sign_with_openssl(self, message: bytes) -> str:
        """Fallback: RSA-PSS/SHA-256 with salt = digest length, via the openssl CLI.

        `rsa_pss_saltlen:digest` == the SHA-256 digest length (32 bytes), matching
        padding.PSS.DIGEST_LENGTH used by the official example.
        """
        with tempfile.NamedTemporaryFile("wb", delete=False) as fh:
            fh.write(message)
            msg_path = fh.name
        try:
            proc = subprocess.run(
                [
                    "openssl", "dgst", "-sha256",
                    "-sigopt", "rsa_padding_mode:pss",
                    "-sigopt", "rsa_pss_saltlen:digest",
                    "-sign", self._keyfile(),
                ],
                stdin=open(msg_path, "rb"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if proc.returncode != 0:
                raise KalshiError(f"openssl signing failed: {proc.stderr.decode(errors='replace')[:400]}")
            return base64.b64encode(proc.stdout).decode("ascii")
        finally:
            os.unlink(msg_path)

    def _keyfile(self) -> str:
        # openssl needs a path, not bytes; keep it private and reuse it for the process life.
        if not hasattr(self, "_keyfile_path"):
            fd, path = tempfile.mkstemp(prefix="kalshi-key-", suffix=".pem")
            with os.fdopen(fd, "wb") as fh:
                fh.write(self.private_key_pem)
            os.chmod(path, 0o600)
            self._keyfile_path = path
        return self._keyfile_path


class KalshiClient:
    def __init__(
        self,
        base_url: str = DEMO_REST,
        *,
        signer: Signer | None = None,
        timeout: float = 20.0,
        max_retries: int = 4,
    ):
        self.base_url = base_url.rstrip("/")
        self.signer = signer or Signer()
        self.timeout = timeout
        self.max_retries = max_retries
        self.calls = 0
        self.http_errors: list[dict[str, Any]] = []

    # ----------------------------------------------------------------- transport
    def url_for(self, path: str, params: dict[str, Any] | None = None) -> str:
        url = self.base_url + path if path.startswith("/") else path
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url += ("&" if "?" in url else "?") + urllib.parse.urlencode(clean)
        return url

    def request(self, method: str, path: str, *, params=None, body: dict | None = None) -> Any:
        signed_path = urllib.parse.urlparse(self.base_url + path).path
        url = self.url_for(path, params)
        data = None
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if not _is_public(path) and self.signer.enabled:
            headers.update(self.signer.headers(method, signed_path))

        attempt = 0
        while True:
            attempt += 1
            self.calls += 1
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8")
                    for k, v in resp.headers.items():
                        if k.lower().startswith("x-ratelimit"):
                            headers.setdefault("_observed", {})[k] = v
                    return json.loads(raw) if raw.strip() else {}
            except urllib.error.HTTPError as exc:
                payload = exc.read().decode("utf-8", errors="replace")
                code = ""
                try:
                    code = json.loads(payload).get("error", {}).get("code", "")
                except Exception:
                    pass
                # 429 carries no Retry-After (documented) -> exponential backoff + jitter
                if exc.code == 429 and attempt <= self.max_retries:
                    time.sleep(min(2 ** attempt * 0.25, 8.0) * (1 + random.random() * 0.25))
                    continue
                self.http_errors.append({"status": exc.code, "url": url, "code": code})
                raise KalshiError(
                    f"{method} {path} -> HTTP {exc.code}" + (f" ({code})" if code else ""),
                    status=exc.code,
                    body=payload[:2000],
                    code=code,
                ) from exc
            except urllib.error.URLError as exc:
                if attempt <= self.max_retries and "timed out" in str(exc.reason).lower():
                    time.sleep(0.5 * attempt)
                    continue
                raise KalshiError(f"{method} {path} -> network error: {exc.reason}") from exc

    # ------------------------------------------------------------- public reads
    def exchange_status(self) -> dict:
        return self.request("GET", "/exchange/status")

    def tags_by_categories(self) -> dict:
        return self.request("GET", "/search/tags_by_categories")

    def series(self, *, category: str | None = None, tags: str | None = None, include_volume: bool = True) -> list[dict]:
        params = {
            "category": category,
            "tags": tags,
            "include_volume": "true" if include_volume else "false",
        }
        # NOTE: /series exposes no limit/cursor (verified 2026-11-20); do not paginate it.
        return self.request("GET", "/series", params=params).get("series", [])

    def events(
        self,
        *,
        status: str | None = None,
        series_ticker: str | None = None,
        tickers: str | None = None,
        with_nested_markets: bool = False,
        min_updated_ts: int | None = None,
        max_pages: int = 25,
    ) -> Iterator[dict]:
        cursor = ""
        for _ in range(max_pages):
            params = {
                "limit": 200,  # documented maximum for /events
                "cursor": cursor or None,
                "status": status,
                "series_ticker": series_ticker,
                "tickers": tickers,
                "with_nested_markets": "true" if with_nested_markets else None,
                "min_updated_ts": min_updated_ts,
            }
            data = self.request("GET", "/events", params=params)
            yield from data.get("events", [])
            cursor = data.get("cursor") or ""
            if not cursor:
                return

    def markets(self, **params: Any) -> Iterator[dict]:
        cursor = ""
        for _ in range(params.pop("max_pages", 25)):
            data = self.request("GET", "/markets", params={**params, "limit": 200, "cursor": cursor or None})
            yield from data.get("markets", [])
            cursor = data.get("cursor") or ""
            if not cursor:
                return

    def market(self, ticker: str) -> dict:
        return self.request("GET", f"/markets/{ticker}").get("market", {})

    def orderbook(self, ticker: str, *, depth: int | None = None) -> dict:
        return self.request("GET", f"/markets/{ticker}/orderbook", params={"depth": depth})

    def trades(self, *, ticker: str | None = None, min_ts: int | None = None, max_ts: int | None = None,
               pages: int = 10, limit: int = 1000) -> Iterator[dict]:
        cursor = ""
        for _ in range(pages):
            data = self.request(
                "GET",
                "/markets/trades",
                params={"ticker": ticker, "min_ts": min_ts, "max_ts": max_ts, "limit": limit, "cursor": cursor or None},
            )
            yield from data.get("trades", [])
            cursor = data.get("cursor") or ""
            if not cursor:
                return

    def candlesticks(self, series_ticker: str, ticker: str, start_ts: int, end_ts: int, period_interval: int = 60) -> list[dict]:
        if period_interval not in (1, 60, 1440):
            raise ValueError("period_interval must be 1, 60 or 1440 (documented enum)")
        if (end_ts - start_ts) / period_interval > 5000:
            raise ValueError("a candlestick request may span at most 5,000 periods")
        data = self.request(
            "GET",
            f"/series/{series_ticker}/markets/{ticker}/candlesticks",
            params={"start_ts": start_ts, "end_ts": end_ts, "period_interval": period_interval},
        )
        return data.get("candlesticks", [])

    def trades_for_event(self, event_ticker: str, *, pages: int = 2, limit: int = 1000) -> list[dict]:
        """Trades of every market in an event — the exact input for event dollar volume."""
        out: list[dict] = []
        for mkt in self.markets(event_ticker=event_ticker, max_pages=1, limit=None):
            out.extend(self.trades(ticker=mkt["ticker"], pages=pages, limit=limit))
        return out

    # ----------------------------------------------------------- portfolio reads
    def _require_auth(self) -> None:
        if not self.signer.enabled:
            raise KalshiError(
                "No demo credentials configured. Set KALSHI_API_KEY_ID and "
                "KALSHI_PRIVATE_KEY_PEM_PATH (create both at https://demo.kalshi.co/). "
                "Docs: https://docs.kalshi.com/getting_started/demo_env.md"
            )

    def balance(self, *, exchange_index: int | None = None, subaccount: int | None = None) -> dict:
        self._require_auth()
        return self.request("GET", "/portfolio/balance", params={"exchange_index": exchange_index, "subaccount": subaccount})

    def positions(self, **params: Any) -> list[dict]:
        self._require_auth()
        return self.request("GET", "/portfolio/positions", params=params).get("positions", [])

    def fills(self, **params: Any) -> list[dict]:
        self._require_auth()
        return self.request("GET", "/portfolio/fills", params=params).get("fills", [])

    def orders(self, **params: Any) -> list[dict]:
        self._require_auth()
        return self.request("GET", "/portfolio/orders", params=params).get("orders", [])

    def settlements(self, **params: Any) -> list[dict]:
        self._require_auth()
        return self.request("GET", "/portfolio/settlements", params=params).get("settlements", [])

    def account_limits(self) -> dict:
        self._require_auth()
        return self.request("GET", "/account/limits")


# --------------------------------------------------------------------- helpers
def fp(value: Any) -> float:
    """Fixed-point string -> float. Every money/size field in v2 is a decimal string."""
    if value is None or value == "":
        return 0.0
    return float(value)


def trade_notional(trade: dict) -> float:
    """USD notionally traded on one tape record.

    Derived, not an API field: taker pays yes_price when long YES, no_price when long NO.
    Field semantics: https://docs.kalshi.com/api-reference/market/get-trades.md
    """
    side = trade.get("taker_outcome_side") or trade.get("taker_side") or "yes"
    price = trade.get("no_price_dollars") if side == "no" else trade.get("yes_price_dollars")
    return fp(trade.get("count_fp")) * fp(price)


def implied_ask_from_best_no_bid(best_no_bid: float) -> float:
    """YES ask = $1.00 - best NO bid. The API never returns asks."""
    return round(1.0 - best_no_bid, 6)


def book_levels(book: dict, side: str) -> list[tuple[float, float]]:
    key = "yes_dollars" if side == "yes" else "no_dollars"
    return [(fp(p), fp(c)) for p, c in (book.get("orderbook_fp", {}).get(key) or [])]


def best_bid(book: dict, side: str) -> float | None:
    lv = book_levels(book, side)
    return lv[-1][0] if lv else None


def depth_at_or_above(book: dict, side: str, price: float) -> float:
    """Contracts resting at `price` or better — 'how many contracts are available at a given price'."""
    return sum(c for p, c in book_levels(book, side) if p >= price)


def main(argv: Iterable[str]) -> int:  # tiny CLI for smoke-testing
    args = list(argv)
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        print("\ncommands:\n  status | series <category> [tag] | trades <n> | market <ticker> | "
              "book <ticker> | auth-check | signed-path-check")
        return 0
    cmd = args[0]
    c = KalshiClient(DEMO_REST if len(args) < 3 or args[-1] != "prod" else PROD_REST)
    if cmd == "status":
        print(json.dumps(c.exchange_status(), indent=2))
    elif cmd == "series":
        tag = args[2] if len(args) > 2 else None
        rows = c.series(category=args[1], tags=tag)
        rows.sort(key=lambda r: fp(r.get("volume_fp")), reverse=True)
        for r in rows[:25]:
            print(f"{r['ticker']:<24} {fp(r.get('volume_fp')):>18,.2f}  {r.get('title','')}")
        print(f"{len(rows)} series")
    elif cmd == "trades":
        n = int(args[1]) if len(args) > 1 else 20
        for t in c.trades(pages=1, limit=min(n, 1000)):
            print(f"{t['created_time']} {t['ticker']:<34} {trade_notional(t):>12,.2f}")
    elif cmd == "market":
        print(json.dumps(c.market(args[1]), indent=2))
    elif cmd == "book":
        print(json.dumps(c.orderbook(args[1]), indent=2))
    elif cmd == "auth-check":
        try:
            c.signer.enabled and print(c.balance()) or print("credentials not configured")
        except KalshiError as e:
            print(f"{type(e).__name__}: {e}")
    elif cmd == "signed-path-check":
        from urllib.parse import urlparse

        url = "https://external-api.kalshi.com/trade-api/v2/portfolio/orders?limit=5"
        print("sign:", urlparse(url).path, "| send:", url)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
