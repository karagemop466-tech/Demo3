"""Minimal, dependency-free REST client for the Kalshi Trade API.

Only the public demo environment is used by this pipeline. Every fact encoded here is
taken from an official Kalshi documentation page, linked next to the code that uses it:

* Environments / base URLs:
  https://docs.kalshi.com/getting_started/api_environments
  (Demo recommended `https://external-api.demo.kalshi.co/trade-api/v2`;
   also supported `https://demo-api.kalshi.co/trade-api/v2`.)
* Public market data needs no API key:
  https://docs.kalshi.com/getting_started/quick_start_market_data
* Unauthenticated requests are separately rate limited and clients must back off on
  HTTP 429: https://docs.kalshi.com/getting_started/rate_limits
* Signed requests (only used when repo secrets exist) sign
  `timestamp + METHOD + path` where path is the full path from the API root, including
  `/trade-api/v2`, WITHOUT the query string:
  https://docs.kalshi.com/getting_started/api_keys

Nothing here invents values: a missing field stays missing in the JSON this client
returns, and callers must render it blank + flagged instead of guessing.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

DEMO_ROOT = "https://external-api.demo.kalshi.co/trade-api/v2"
DEMO_ROOT_ALT = "https://demo-api.kalshi.co/trade-api/v2"

SOURCES = {
    "api_environments": "https://docs.kalshi.com/getting_started/api_environments",
    "market_data": "https://docs.kalshi.com/getting_started/quick_start_market_data",
    "rate_limits": "https://docs.kalshi.com/getting_started/rate_limits",
    "api_keys": "https://docs.kalshi.com/getting_started/api_keys",
    "market_settlement": "https://docs.kalshi.com/getting_started/market_settlement",
    "get_markets": "https://docs.kalshi.com/api-reference/market/get-markets",
    "get_events": "https://docs.kalshi.com/api-reference/events/get-events",
    "get_candlesticks": "https://docs.kalshi.com/api-reference/market/get-market-candlesticks",
    "get_orderbook": "https://docs.kalshi.com/api-reference/market/get-market-orderbook",
    "get_trades": "https://docs.kalshi.com/api-reference/market/get-trades",
    "get_series": "https://docs.kalshi.com/api-reference/market/get-series-list",
}


class KalshiHTTPError(RuntimeError):
    def __init__(self, url: str, status: int, body: str):
        self.url, self.status, self.body = url, status, body
        super().__init__(f"HTTP {status} {url}: {body[:300]}")


class Client:
    """Throttled public client with 429 backoff and a request counter."""

    def __init__(self, root: str = DEMO_ROOT, min_interval: float = 0.12,
                 timeout: float = 25.0, retries: int = 2,
                 log=None):
        self.root = root.rstrip("/")
        self.min_interval = min_interval
        self.timeout = timeout
        self.retries = retries
        self.log = log or (lambda m: None)
        self.requests = 0
        self.errors: list[str] = []
        self._last = 0.0
        self._backoff = 0.0

    # -- core ---------------------------------------------------------------
    def url(self, path: str, params: Optional[dict] = None) -> str:
        u = self.root + path
        if params:
            qs = urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None and v != ""})
            if qs:
                u += "?" + qs
        return u

    def get(self, path: str, params: Optional[dict] = None) -> Any:
        u = self.url(path, params)
        last_err: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            wait = self.min_interval - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            if self._backoff:
                time.sleep(self._backoff)
            self._last = time.time()
            self.requests += 1
            req = urllib.request.Request(u, headers={
                "Accept": "application/json",
                "User-Agent": "Demo3-alerts-pipeline/1.0 (+https://karagemop466-tech.github.io/Demo3/)",
            })
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    body = r.read().decode("utf-8", "replace")
                self._backoff = 0.0
                return json.loads(body)
            except urllib.error.HTTPError as exc:
                # 429 -> exponential backoff, per official rate-limit docs.
                if exc.code == 429:
                    self._backoff = min(self._backoff * 2 or 2.0, 30.0)
                    self.log(f"429 on {path}; backing off {self._backoff:.1f}s")
                    last_err = KalshiHTTPError(u, exc.code, exc.read()[:300].decode("utf-8", "replace"))
                    continue
                body = exc.read()[:300].decode("utf-8", "replace")
                err = KalshiHTTPError(u, exc.code, body)
                self.errors.append(str(err))
                if exc.code >= 500 and attempt < self.retries:
                    last_err = err
                    time.sleep(1.0 + attempt)
                    continue
                raise err
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_err = exc
                self.errors.append(f"{type(exc).__name__} {u}: {exc}")
                if attempt < self.retries:
                    time.sleep(1.0 + attempt)
                    continue
                raise
        raise last_err if last_err else RuntimeError(f"request failed: {u}")


# ---------------------------------------------------------------------------
# Field parsing helpers. The API returns fixed-point strings (e.g. "0.9500",
# "120.50"); anything missing or non-numeric becomes None, never 0 or a guess.
# ---------------------------------------------------------------------------
def num(value) -> Optional[float]:
    if value is None or value == "" or value == "null":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def price(market: dict, key: str = "last_price_dollars") -> Optional[float]:
    """Contract price in dollars (0..1). Falls back to the legacy cents field only
    when the dollars field is absent, and reports that fallback to the caller by
    returning the dollars value in both cases (never silently mixes units)."""
    v = num(market.get(key))
    if v is not None:
        return v
    legacy = key.replace("_dollars", "")
    v = num(market.get(legacy))
    if v is not None:
        return v / 100.0
    return None
