"""Topic scope + classification rules for the five required topics.

Requirement: track only gas prices, elections, culture, crypto and golf. Kalshi's own
`category` values are not reliably one-per-topic (e.g. golf lives under "Sports",
gas-price markets under "Economics"/"Climate and Weather"), so classification is a
published, auditable pipeline, weakest-last:

  1. API `tags`               (e.g. KXUSOPEN is tagged ["Golf"] -- official evidence)
  2. series-ticker regex      (specific prefix evidence)
  3. API `category` overlay   (only where the category maps 1:1 to a topic)
  4. event/market title regex (keyword evidence)

Every classified row stores the rule that matched (`classification_rule`) and the
exact API URL it came from, so the site can show why a row is in a topic instead of
asking anyone to trust it.

Source for the API fields used here (series_ticker, category, title):
  https://docs.kalshi.com/api-reference/events/get-events
  https://docs.kalshi.com/api-reference/market/get-markets
"""

from __future__ import annotations

import re
from typing import Optional

TOPICS = {
    "gas": "Gas prices",
    "elections": "Elections",
    "culture": "Culture",
    "crypto": "Crypto",
    "golf": "Golf",
}

# Order matters: the first topic whose rule matches wins. Gas before crypto so that
# "gasoline" style tickers cannot be pulled in by a crypto keyword, etc.
RULES: list[tuple[str, re.Pattern, re.Pattern]] = [
    (
        "gas",
        re.compile(r"^(KXGAS|KXAAAGAS|KXAAA|KXNATGAS|KXHEATINGOIL|KXDIESEL|KXPROPANE)(?=[-_.]|$)",
                   re.I),
        re.compile(
            r"(gas price|gas prices|price of gas|regular gas|gasoline|aaa gas|"
            r"gallon of gas|avg gas|average gas)", re.I),
    ),
    (
        "golf",
        re.compile(r"^(KXGOLF|KXPGA|KXLPGA|KXPGATOUR|KXPGARYDER|KXPGASOLHEIM|KXRYDER|"
                   r"KXMASTERS|KXOPEN|KXUSOPEN|KXDPWORLD|KXLIVGOLF|KXTHRC)(?=[-_.]|$)",
                   re.I),
        re.compile(
            r"(\bgolf\b|\bpga\b|ryder cup|solheim|\bmasters\b|fedex cup|\blpga\b|"
            r"open championship|us open golf|liv golf|rsm classic|tour championship)",
            re.I),
    ),
    (
        "crypto",
        # Trailing boundary is required: without it KXSOLE (solar energy production)
        # matched the KXSOL (Solana) prefix. Regression-tested in tests/test_pipeline.py.
        re.compile(r"^(KXBTC|KXETH|KXSOL|KXXRP|KXDOGE|KXCRYPTO|KXADA|KXAVAX|KXBNB|"
                   r"KXLTC|KXSHIB|KXUSDC|KXUSDT|KXSTABLECOIN)(?=[-_.]|$)", re.I),
        re.compile(
            r"(\bbitcoin\b|\bbtc\b|\bethereum\b|\beth\b|\bsolana\b|\bsol\b|\bxrp\b|"
            r"\bdogecoin\b|\bdoge\b|\bcrypto\b|stablecoin|\btether\b|\busdc\b|"
            r"\bblockchain\b|\bcardano\b|\bavalanche\b|\bbinance\b)", re.I),
    ),
    (
        "elections",
        re.compile(r"^(KXPRES|KXSENATE|KXHOUSE|KXGOV|KXMAYOR|KXPRIMARY|KXELECTION|"
                   r"KXNEXT[A-Z]*PRES|KXNOM|KXPRESNOM|KXPRESPERSON|KXPOLIT|KXPARTISAN|"
                   r"KXKNESS|KXPARL|KXNATOSECGEN|KXECCOMPACT|KXEUEXIT)(?=[-_.]|$)", re.I),
        re.compile(
            r"(\belection\b|\belectoral\b|presidential nominee|senate seat|house seat|"
            r"governorship|\bgovernor\b|mayoral|\bmayor of\b|referendum|primary election|"
            r"parliamentary|popular vote|control of (the )?(house|senate))", re.I),
    ),
    (
        "culture",
        re.compile(r"^(KXOSCAR|KXEMMY|KXGRAMMY|KXGOLDENGLOBE|KXBAFTA|KXFEATURE|"
                   r"KXBILLBOARD|KXBESTPICTURE|KXMOVIE|KXFILM|KXALBUM|KXSONG|KXCELEB|"
                   r"KXROYAL|KXMETGALA|KXCOACHELLA|KXRT|KXBOXOFFICE|KXSHOW|KXTV|KXSPOTIFY|"
                   r"KXBEYONCE|KXARTIST)(?=[-_.]|$)", re.I),
        re.compile(
            r"(\boscar|\bemmy\b|grammy|golden globe|\bbafta\b|best picture|box office|"
            r"rotten tomatoes|billboard|met gala|eurovision|miss universe|nobel prize|"
            r"person of the year|\balbum\b|\bcelebrity\b|\bfilm\b|\bmovie\b|"
            r"\btv show\b|\bseries finale\b)", re.I),
    ),
]

# Only tags that map 1:1 to exactly one of the five topics are used. Tags come from
# GET /series/{ticker} (docs.kalshi.com/api-reference/market/get-series) and are the
# strongest official evidence available about what a series is about.
TAG_MAP = {
    "golf": "golf",
    "crypto": "crypto",
    "elections": "elections",
    "entertainment": "culture",
}

# Only categories that map 1:1 to exactly one of the five topics are used.
CATEGORY_MAP = {
    "crypto": "crypto",
    "elections": "elections",
    "entertainment": "culture",
    "culture": "culture",
}


def classify(series_ticker: str = "", title: str = "", category: str = "",
             tags: list | None = None) -> tuple[Optional[str], str]:
    """Return (topic, rule) or (None, reason). Rule strings are shown on the site."""
    series_ticker = series_ticker or ""
    title = title or ""
    for tag in tags or []:
        t = TAG_MAP.get(str(tag).strip().lower())
        if t:
            return t, f"api_tag={tag}"
    for topic, sre, tre in RULES:
        if series_ticker and sre.search(series_ticker):
            return topic, f"series_ticker={series_ticker} matched {sre.pattern}"
    cat = (category or "").strip().lower()
    if cat in CATEGORY_MAP:
        return CATEGORY_MAP[cat], f"api_category={category}"
    for topic, _sre, tre in RULES:
        if title and tre.search(title):
            return topic, f"title matched /{tre.pattern}/"
    return None, "no topic rule matched"


def classify_market(market: dict, event: dict | None = None) -> tuple[Optional[str], str]:
    """Classify a market, preferring market-level evidence, then its event's."""
    ev = event or {}
    for ticker in (market.get("ticker", ""), market.get("series_ticker", ""),
                   ev.get("series_ticker", ""), market.get("event_ticker", "")):
        topic, rule = classify(ticker, "", "")
        if topic:
            return topic, rule
    title = market.get("title") or ev.get("title") or market.get("yes_sub_title") or ""
    topic, rule = classify(ev.get("series_ticker", ""), title, ev.get("category", ""))
    return topic, rule
