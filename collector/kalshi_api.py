"""Thin REST client for the Kalshi Trade API (demo/production).

Sources (official Kalshi documentation, verified 2026-11-20):
- Environments:   https://docs.kalshi.com/getting_started/api_environments.md
- Public data:    https://docs.kalshi.com/getting_started/quick_start_market_data.md
- Auth/signing:   https://docs.kalshi.com/getting_started/quick_start_authenticated_requests.md

Notes verified from those pages:
- Public market-data endpoints (series, events, markets, orderbook, candlesticks, trades)
  require no authentication.
- Signed requests use headers KALSHI-ACCESS-KEY / KALSHI-ACCESS-TIMESTAMP (milliseconds) /
  KALSHI-ACCESS-SIGNATURE (base64). The signed message is f"{timestamp}{METHOD}{path}" where
  path is the full URL path from the API root WITHOUT query parameters. Ed25519 keys sign the
  message directly; RSA keys use RSA-PSS with SHA-256 (MGF1-SHA256, salt length = digest length).
- Demo REST root (recommended): https://external-api.demo.kalshi.co/trade-api/v2
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, Optional
from urllib.parse import urlparse

DEMO_REST_ROOT = "https://external-api.demo.kalshi.co/trade-api/v2"
PROD_REST_ROOT = "https://external-api.kalshi.com/trade-api/v2"
# Both demo hosts are officially supported; we use the recommended `external-api` host
# and record the fallback for manual review.
DEMO_REST_ROOT_ALT = "https://demo-api.kalshi.co/trade-api/v2"


class KalshiError(RuntimeError):
    def __init__(self, url: str, status: int, body: str):
        self.url, self.status, self.body = url, status, body
        super().__init__(f"HTTP {status} for {url}: {body[:300]}")


class KalshiClient:
    """Public (and optionally signed) client with polite throttling and retries."""

    def __init__(
        self,
        root: str = DEMO_REST_ROOT,
        min_interval: float = 0.15,
        retries: int = 3,
        timeout: float = 20.0,
        logger: Optional[Callable[[str], None]] = None,
    ):
        self.root = root.rstrip("/")
        self.min_interval = min_interval
        self.retries = retries
        self.timeout = timeout
        self.log = logger or (lambda msg: None)
        self._last_request_ts = 0.0
        self.request_count = 0
        self.error_count = 0
        # Signed-request material (loaded lazily by load_private_key when needed).
        self.private_key = None  # cryptography object (Ed25519 or RSA)

    # ------------------------------------------------------------------ core
    def _throttle(self) -> None:
        wait = self.min_interval - (time.time() - self._last_request_ts)
        if wait > 0:
            time.sleep(wait)
        self._last_request_ts = time.time()

    def request(self, method: str, path: str, params: Optional[dict] = None,
                body: Optional[dict] = None) -> Any:
        """GET/POST/DELETE a Trade API path like `/events` (root prefix added here).

        `path` must NOT include the `/trade-api/v2` root. Query params are appended here
        but are EXCLUDED from the signature (per official signing rules).
        """
        query = ""
        if params:
            from urllib.parse import urlencode
            query = "?" + urlencode({k: v for k, v in params.items() if v is not None})
        url = self.root + path + query
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if self.private_key is not None:
            self._sign_request(method, url, headers)

        last_err: Exception = RuntimeError("no attempt made")
        for attempt in range(1, self.retries + 1):
            self._throttle()
            self.request_count += 1
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode() if body is not None else None,
                headers=headers,
                method=method,
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = resp.read().decode("utf-8", "replace")
                    return json.loads(payload) if payload else {}
            except urllib.error.HTTPError as exc:
                err_body = ""
                try:
                    err_body = exc.read().decode("utf-8", "replace")
                except Exception:
                    pass
                self.error_count += 1
                last_err = KalshiError(url, exc.code, err_body)
                # 4xx (except 429) will not improve with retries — surface immediately.
                if 400 <= exc.code < 500 and exc.code != 429:
                    raise last_err
                self.log(f"HTTP {exc.code} on {url} (attempt {attempt}/{self.retries}): {err_body[:200]}")
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                self.error_count += 1
                last_err = exc
                self.log(f"Network/parse error on {url} (attempt {attempt}/{self.retries}): {exc}")
            time.sleep(0.5 * attempt)
        raise last_err

    # ---------------------------------------------------------------- signing
    def load_private_key(self, pem_text: str) -> None:
        """Load an API private key (Ed25519 or RSA PEM) for signed requests."""
        from cryptography.hazmat.primitives import serialization
        self.private_key = serialization.load_pem_private_key(
            pem_text.encode(), password=None)

    def _sign_request(self, method: str, url: str, headers: dict) -> None:
        import base64 as b64
        import os

        key_id = os.environ.get("KALSHI_DEMO_API_KEY_ID", "")
        if not key_id:
            raise RuntimeError("Signed request attempted but KALSHI_DEMO_API_KEY_ID is not set")
        timestamp = str(int(time.time() * 1000))
        # Sign the full URL path from the API root, WITHOUT query parameters
        # (official rule; see quick_start_authenticated_requests.md).
        sign_path = urlparse(url).path
        message = f"{timestamp}{method.upper()}{sign_path}".encode()
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        if isinstance(self.private_key, Ed25519PrivateKey):
            signature = self.private_key.sign(message)
        else:
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import padding
            signature = self.private_key.sign(
                message,
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                            salt_length=padding.PSS.DIGEST_LENGTH),
                hashes.SHA256(),
            )
        headers["KALSHI-ACCESS-KEY"] = key_id
        headers["KALSHI-ACCESS-TIMESTAMP"] = timestamp
        headers["KALSHI-ACCESS-SIGNATURE"] = b64.b64encode(signature).decode()

    # ------------------------------------------------------------- pagination
    def paginate(self, path: str, params: Optional[dict] = None,
                 list_key: str = "items", max_pages: int = 50) -> Iterator[dict]:
        """Yield items across cursor-paginated responses.

        Kalshi pagination (https://docs.kalshi.com/getting_started/pagination.md):
        responses carry `cursor`; pass it back as the `cursor` query param until the
        returned cursor is empty. `params` must not itself contain `cursor`/`limit`.
        """
        params = dict(params or {})
        cursor: Optional[str] = None
        for page in range(max_pages):
            page_params = dict(params)
            page_params["limit"] = 200
            if cursor:
                page_params["cursor"] = cursor
            data = self.request("GET", path, params=page_params)
            items = data.get(list_key) or []
            for item in items:
                yield item
            cursor = data.get("cursor") or ""
            if not cursor or not items:
                return
        self.log(f"paginate({path}): hit max_pages={max_pages}; results may be truncated")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
