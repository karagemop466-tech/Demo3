#!/usr/bin/env python3
"""Kalshi Demo Trade API CLI — read-only without a key; trading needs a demo key.

Endpoints verified against https://docs.kalshi.com (see ../api-reference.html).
Demo base: https://external-api.demo.kalshi.co/trade-api/v2

Usage:
  python3 scripts/kalshi_demo.py discover
  python3 scripts/kalshi_demo.py scan [--topic gas|elections|culture|crypto|golf]
  python3 scripts/kalshi_demo.py orderbook TICKER
  python3 scripts/kalshi_demo.py trades TICKER [--limit 50]
  python3 scripts/kalshi_demo.py candles SERIES_TICKER TICKER --minutes 60
  # Authenticated (env: KALSHI_DEMO_KEY_ID, KALSHI_DEMO_PRIVATE_KEY=path to PEM):
  python3 scripts/kalshi_demo.py balance
  python3 scripts/kalshi_demo.py positions
  python3 scripts/kalshi_demo.py fills [--limit 100]
  python3 scripts/kalshi_demo.py place-order TICKER --side bid --count 10 --price 0.50
  python3 scripts/kalshi_demo.py cancel-order ORDER_ID --ticker TICKER

Requires: pip install cryptography  (only for authenticated commands)
"""
import argparse
import base64
import json
import os
import sys
import time
import urllib.parse
import urllib.request

BASE = "https://external-api.demo.kalshi.co/trade-api/v2"

TOPICS = {
    "gas": ["gas price", "gasoline", "petrol", "gas prices", "fuel price"],
    "elections": ["election", "president", "senate", "governor", "congress",
                  "mayor", "ballot", "referendum", "house control",
                  "senate control", "presidential", "midterm",
                  "primary election", "vote"],
    "culture": ["oscar", "grammy", "emmy", "tony award", "film", "movie",
                "album", "song of", "celebrity", "entertainment", "tv show",
                "reality", "novel", "book of the year", "met gala", "billboard",
                "box office", "cannes", "super bowl halftime", "culture",
                "streaming", "tiktok", "youtube", "spotify"],
    "crypto": ["bitcoin", "ethereum", "crypto", "btc", "eth ", "solana",
               "dogecoin", "xrp", "cardano", "coinbase", "blockchain",
               "stablecoin", "defi"],
    "golf": ["golf", "pga", "masters tournament", "ryder cup", "liv golf",
             "us open golf", "the open championship", "pga championship"],
}


def http(method, path, params=None, body=None, headers=None):
    url = BASE + path
    if params:
        qs = urllib.parse.urlencode(
            {k: v for k, v in params.items() if v not in (None, "")})
        if qs:
            url += "?" + qs
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers=headers or {"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        raise SystemExit(f"HTTP {e.code} on {method} {path}: {detail}")


def get_all(path, params, max_pages=10):
    out, cursor = [], ""
    for _ in range(max_pages):
        p = dict(params or {})
        if cursor:
            p["cursor"] = cursor
        j = http("GET", path, p)
        for v in j.values():
            if isinstance(v, list):
                out.extend(v)
                break
        cursor = j.get("cursor") or ""
        if not cursor:
            break
    return out


def classify(series):
    hay = " ".join([series.get("title", ""), series.get("ticker", ""),
                    " ".join(series.get("tags") or []),
                    " ".join(series.get("categories") or []),
                    series.get("category", "")]).lower()
    for topic, kws in TOPICS.items():
        for kw in kws:
            if kw in hay:
                return topic, kw
    return None, None


def cmd_discover(_):
    j = http("GET", "/series", {})
    rows = []
    for s in j.get("series", []):
        topic, kw = classify(s)
        if topic:
            rows.append((topic, s["ticker"], s.get("title", ""), kw))
    rows.sort()
    print(f"{'topic':<10} {'series':<24} {'matched':<18} title")
    for topic, ticker, title, kw in rows:
        print(f"{topic:<10} {ticker:<24} {kw:<18} {title}")
    print(f"\n{len(rows)} matched series.")


def cmd_scan(args):
    j = http("GET", "/series", {})
    wanted = [s for s in j.get("series", [])
              if (classify(s)[0] and
                  (not args.topic or classify(s)[0] == args.topic))]
    markets = []
    for s in wanted[:15]:  # rate-limit guard
        for m in get_all("/markets", {"series_ticker": s["ticker"],
                                      "status": "open", "limit": 200}, 3):
            m["_topic"] = classify(s)[0]
            markets.append(m)
    def est(m, key):
        try:
            return float(m.get(key, 0)) * float(m.get("last_price_dollars", 0))
        except (TypeError, ValueError):
            return 0.0
    markets.sort(key=lambda m: (est(m, "volume_fp"), est(m, "open_interest_fp")),
                 reverse=True)
    print(f"{'#':<3} {'topic':<10} {'est $vol':>12} {'last':>6} "
          f"{'vol':>10} {'OI':>10}  title (ticker)")
    for i, m in enumerate(markets[:25], 1):
        print(f"{i:<3} {m['_topic']:<10} {est(m, 'volume_fp'):>12,.2f} "
              f"{float(m.get('last_price_dollars', 0)) * 100:>5.1f}¢ "
              f"{float(m.get('volume_fp', 0)):>10,.0f} "
              f"{float(m.get('open_interest_fp', 0)):>10,.0f}  "
              f"{m.get('title', '')} ({m['ticker']})")
    print(f"\n{len(markets)} open markets scanned. Est $ = contracts x last price.")


def cmd_orderbook(args):
    j = http("GET", f"/markets/{urllib.parse.quote(args.ticker)}/orderbook", {})
    ob = j.get("orderbook_fp", {})
    for side in ("yes_dollars", "no_dollars"):
        print(f"\n{side} (ascending, best last):")
        for price, count in ob.get(side, []):
            print(f"  {float(price) * 100:>6.1f}c  {float(count):>12,.0f} contracts")


def cmd_trades(args):
    j = http("GET", "/markets/trades",
             {"ticker": args.ticker, "limit": args.limit})
    print(f"{'time':<20} {'count':>8} {'yes':>6} {'no':>6}  taker  block")
    for t in j.get("trades", []):
        print(f"{t.get('created_time', ''):<20} {float(t['count_fp']):>8,.0f} "
              f"{float(t['yes_price_dollars']) * 100:>5.1f}c "
              f"{float(t['no_price_dollars']) * 100:>5.1f}c  "
              f"{t.get('taker_outcome_side', '')}  {t.get('is_block_trade')}")


def cmd_candles(args):
    end = int(time.time())
    start = end - args.minutes * 60
    j = http("GET", f"/series/{urllib.parse.quote(args.series)}/markets/"
             f"{urllib.parse.quote(args.ticker)}/candlesticks",
             {"start_ts": start, "end_ts": end, "period_interval": 1})
    print(f"{'end (UTC)':<20} {'open':>6} {'high':>6} {'low':>6} {'close':>6} "
          f"{'vol':>8}")
    for c in j.get("candlesticks", []):
        p = c.get("price", {})
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(c["end_period_ts"]))
        print(f"{ts:<20} {float(p.get('open_dollars', 0)) * 100:>5.1f}c "
              f"{float(p.get('high_dollars', 0)) * 100:>5.1f}c "
              f"{float(p.get('low_dollars', 0)) * 100:>5.1f}c "
              f"{float(p.get('close_dollars', 0)) * 100:>5.1f}c "
              f"{float(c.get('volume_fp', 0)):>8,.0f}")


# --- authenticated helpers ---
def auth_headers(method, path):
    key_id = os.environ.get("KALSHI_DEMO_KEY_ID")
    key_path = os.environ.get("KALSHI_DEMO_PRIVATE_KEY")
    if not key_id or not key_path:
        raise SystemExit("Set KALSHI_DEMO_KEY_ID and KALSHI_DEMO_PRIVATE_KEY "
                         "(path to demo private key PEM).")
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    with open(key_path, "rb") as f:
        priv = serialization.load_pem_private_key(f.read(), password=None)
    ts = str(int(time.time() * 1000))
    msg = f"{ts}{method}{path}".encode()
    if isinstance(priv, Ed25519PrivateKey):
        sig = priv.sign(msg)
    else:
        sig = priv.sign(msg, padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                                         salt_length=padding.PSS.DIGEST_LENGTH),
                        hashes.SHA256())
    return {"KALSHI-ACCESS-KEY": key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
            "Content-Type": "application/json"}


def auth(method, path, params=None, body=None):
    return http(method, path, params, body, auth_headers(method, path))


def cmd_balance(_):
    print(json.dumps(auth("GET", "/portfolio/balance"), indent=2))


def cmd_positions(_):
    print(json.dumps(auth("GET", "/portfolio/positions",
                          {"settlement_status": "all", "limit": 200}), indent=2))


def cmd_fills(args):
    print(json.dumps(auth("GET", "/portfolio/fills", {"limit": args.limit}), indent=2))


def cmd_place_order(args):
    body = {"ticker": args.ticker, "side": args.side, "count": args.count,
            "price": args.price, "time_in_force": args.tif,
            "self_trade_prevention_type": "taker_at_cross",
            "post_only": args.post_only}
    print(json.dumps(auth("POST", "/portfolio/events/orders", {}, body), indent=2))


def cmd_cancel_order(args):
    print(json.dumps(auth("DELETE", f"/portfolio/events/orders/{args.order_id}",
                          {"market_ticker": args.ticker}), indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("discover").set_defaults(fn=cmd_discover)
    p = sub.add_parser("scan")
    p.add_argument("--topic", choices=list(TOPICS), default=None)
    p.set_defaults(fn=cmd_scan)
    p = sub.add_parser("orderbook"); p.add_argument("ticker"); p.set_defaults(fn=cmd_orderbook)
    p = sub.add_parser("trades"); p.add_argument("ticker")
    p.add_argument("--limit", type=int, default=50); p.set_defaults(fn=cmd_trades)
    p = sub.add_parser("candles"); p.add_argument("series"); p.add_argument("ticker")
    p.add_argument("--minutes", type=int, default=60); p.set_defaults(fn=cmd_candles)
    sub.add_parser("balance").set_defaults(fn=cmd_balance)
    sub.add_parser("positions").set_defaults(fn=cmd_positions)
    p = sub.add_parser("fills"); p.add_argument("--limit", type=int, default=100)
    p.set_defaults(fn=cmd_fills)
    p = sub.add_parser("place-order"); p.add_argument("ticker")
    p.add_argument("--side", choices=["bid", "ask"], default="bid")
    p.add_argument("--count", default="10"); p.add_argument("--price", default="0.50")
    p.add_argument("--tif", default="good_till_canceled")
    p.add_argument("--post-only", action="store_true"); p.set_defaults(fn=cmd_place_order)
    p = sub.add_parser("cancel-order"); p.add_argument("order_id")
    p.add_argument("--ticker", required=True); p.set_defaults(fn=cmd_cancel_order)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
