#!/usr/bin/env python3
"""
kalshi_client.py — Authenticated client for the Kalshi DEMO Trade API.

The request-signing implementation follows the official starter code line by
line (https://github.com/Kalshi/kalshi-starter-code-python, file clients.py):
  signature payload = str(timestamp_ms) + METHOD + path_without_query
  signature         = RSA-PSS(MGF1-SHA256, salt=digest-len) over SHA-256, base64
  headers           = KALSHI-ACCESS-KEY / KALSHI-ACCESS-SIGNATURE / KALSHI-ACCESS-TIMESTAMP

Signing rules cross-checked against official docs:
  https://docs.kalshi.com/getting_started/api_environments  (sign full path from API root, no query)
  https://docs.kalshi.com/getting_started/api_keys
  https://docs.kalshi.com/getting_started/quick_start_authenticated_requests

Credentials come from environment variables only (never committed):
  KALSHI_KEY_ID       - API key ID
  KALSHI_PRIVATE_KEY  - PEM-encoded RSA private key
"""

from __future__ import annotations

import base64
import json
import os
import time
from typing import Any, Optional

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

# Recommended demo REST host per
# https://docs.kalshi.com/getting_started/api_environments
DEMO_BASE = "https://external-api.demo.kalshi.co"


class KalshiClient:
    def __init__(self, key_id: Optional[str] = None, pem: Optional[str] = None,
                 base_url: str = DEMO_BASE):
        self.key_id = key_id or os.environ["KALSHI_KEY_ID"]
        pem = pem or os.environ["KALSHI_PRIVATE_KEY"]
        self.private_key = serialization.load_pem_private_key(
            pem.encode("utf-8") if isinstance(pem, str) else pem, password=None)
        self.base_url = base_url
        self.last_call = 0.0

    # -- signing (mirrors official starter code) ----------------------------
    def _sign(self, timestamp_ms: str, method: str, path_no_query: str) -> str:
        msg = (timestamp_ms + method + path_no_query).encode("utf-8")
        sig = self.private_key.sign(
            msg,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256())
        return base64.b64encode(sig).decode("utf-8")

    def _headers(self, method: str, path: str) -> dict:
        ts = str(int(time.time() * 1000))
        path_no_query = path.split("?")[0]
        return {
            "Content-Type": "application/json",
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-SIGNATURE": self._sign(ts, method, path_no_query),
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }

    def _throttle(self) -> None:
        dt = time.time() - self.last_call
        if dt < 0.12:
            time.sleep(0.12 - dt)
        self.last_call = time.time()

    # -- verbs -------------------------------------------------------------
    def get(self, path: str, params: Optional[dict] = None) -> Any:
        self._throttle()
        r = requests.get(self.base_url + path, params=params or {},
                         headers=self._headers("GET", path), timeout=30)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, body: dict) -> Any:
        self._throttle()
        r = requests.post(self.base_url + path, json=body,
                          headers=self._headers("POST", path), timeout=30)
        r.raise_for_status()
        return r.json()

    def delete(self, path: str) -> Any:
        self._throttle()
        r = requests.delete(self.base_url + path,
                            headers=self._headers("DELETE", path), timeout=30)
        r.raise_for_status()
        return r.json()

    # -- portfolio (all verified shapes from official docs) ----------------
    def get_balance(self) -> dict:
        return self.get("/trade-api/v2/portfolio/balance")

    def get_positions(self, **params) -> dict:
        return self.get("/trade-api/v2/portfolio/positions", params)

    def get_orders(self, **params) -> dict:
        return self.get("/trade-api/v2/portfolio/orders", params)

    def get_fills(self, **params) -> dict:
        return self.get("/trade-api/v2/portfolio/fills", params)

    def get_settlements(self, **params) -> dict:
        return self.get("/trade-api/v2/portfolio/settlements", params)

    # -- order placement (official quick start) ----------------------------
    # https://docs.kalshi.com/getting_started/quick_start_create_order
    def place_order(self, ticker: str, side: str, count: str, price: str,
                    client_order_id: str, time_in_force: str = "good_till_canceled") -> dict:
        body = {
            "ticker": ticker,
            "side": side,              # "bid" (buy) or "ask" (sell)
            "count": count,            # contracts as integer string
            "price": price,            # dollars, 4dp e.g. "0.0100"
            "time_in_force": time_in_force,
            "self_trade_prevention_type": "taker_at_cross",
            "client_order_id": client_order_id,
        }
        return self.post("/trade-api/v2/portfolio/orders", body)

    def cancel_order(self, order_id: str) -> Any:
        return self.delete(f"/trade-api/v2/portfolio/orders/{order_id}")


if __name__ == "__main__":  # smoke test: read-only balance
    import sys
    c = KalshiClient()
    print(json.dumps(c.get_balance(), indent=2))
    sys.exit(0)
