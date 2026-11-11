"""Alpaca market data (free Basic plan): daily prices, corporate actions, news.

Plain REST calls instead of the alpaca-py SDK: three endpoints do not justify a dependency.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from . import config
from .net import Client

BASE = "https://data.alpaca.markets"
NEW_YORK = ZoneInfo("America/New_York")


def client() -> Client:
    return Client(
        headers={"APCA-API-KEY-ID": config.env("ALPACA_API_KEY"),
                 "APCA-API-SECRET-KEY": config.env("ALPACA_SECRET_KEY")},
        max_per_second=3,  # free plan allows 200 calls/minute
    )


def _pages(c: Client, url: str, params: dict):
    """Yield every page of a paginated Alpaca endpoint."""
    params = dict(params)
    while True:
        page = c.get_json(url, params)
        yield page
        token = page.get("next_page_token")
        if not token:
            return
        params["page_token"] = token


def _bars(c: Client, symbols: list[str], start: str, end: str, adjustment: str) -> pd.DataFrame:
    params = {"symbols": ",".join(symbols), "timeframe": "1Day", "start": start, "end": end,
              "adjustment": adjustment, "feed": "sip", "limit": 10000, "sort": "asc"}
    rows = []
    for page in _pages(c, f"{BASE}/v2/stocks/bars", params):
        for symbol, bars in (page.get("bars") or {}).items():
            for b in bars:
                rows.append((symbol, b["t"][:10], b["o"], b["h"], b["l"], b["c"],
                             b["v"], b.get("vw"), b.get("n")))
    return pd.DataFrame(rows, columns=["ticker", "price_date", "open", "high", "low", "close",
                                       "volume", "vwap", "trade_count"])


def fetch_prices(c: Client, symbols: list[str], start: str, now: datetime | None = None) -> pd.DataFrame:
    """Daily OHLCV for the full market (SIP feed), adjusted for splits and spin-offs.
    (Without the spin-off adjustment, a company that hands shareholders a new company,
    as Honeywell did in 2026, shows a crash that no shareholder experienced.)

    - The free plan refuses the latest 15 minutes of SIP data, so `end` is 20 minutes ago.
    - Today's bar (New York date) is dropped: it may be incomplete.
    - `close_total_return` is also adjusted for dividends; use it for
      long-run performance, and `close` for anything shown as a price.
    """
    now = now or datetime.now(timezone.utc)
    end = (now - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    prices = _bars(c, symbols, start, end, "split,spin-off")
    total = _bars(c, symbols, start, end, "all")[["ticker", "price_date", "close"]]
    prices = prices.merge(total.rename(columns={"close": "close_total_return"}),
                          on=["ticker", "price_date"], how="left")
    today = now.astimezone(NEW_YORK).strftime("%Y-%m-%d")
    return prices[prices["price_date"] < today].reset_index(drop=True)


def fetch_corporate_actions(c: Client, symbols: list[str], start: str, end: str) -> pd.DataFrame:
    """Splits and cash dividends. `split_ratio` = new shares per old share (4.0 for a 4-for-1)."""
    params = {"symbols": ",".join(symbols), "types": "forward_split,reverse_split,cash_dividend",
              "start": start, "end": end, "limit": 1000, "sort": "asc"}
    rows = []
    for page in _pages(c, f"{BASE}/v1/corporate-actions", params):
        actions = page.get("corporate_actions") or {}
        for kind in ("forward_splits", "reverse_splits"):
            for a in actions.get(kind) or []:
                rows.append((a["symbol"], kind[:-1], a.get("ex_date"), a.get("record_date"),
                             a.get("payable_date"), a["new_rate"] / a["old_rate"], None, None))
        for a in actions.get("cash_dividends") or []:
            rows.append((a["symbol"], "cash_dividend", a.get("ex_date"), a.get("record_date"),
                         a.get("payable_date"), None, a.get("rate"), bool(a.get("special"))))
    return pd.DataFrame(rows, columns=["ticker", "action_type", "ex_date", "record_date",
                                       "payable_date", "split_ratio", "cash_amount", "is_special"])


def fetch_news(c: Client, symbols: list[str], start: str, end: str) -> pd.DataFrame:
    """Headlines and summaries (Benzinga, via Alpaca). One row per article per tracked ticker.
    `n_symbols` is how many tickers the article is tagged with: 1 means it is about that
    company, 20 means a market round-up."""
    tracked = set(symbols)
    params = {"symbols": ",".join(symbols), "start": start, "end": end, "limit": 50,
              "include_content": "false", "sort": "desc"}
    rows = []
    for page in _pages(c, f"{BASE}/v1beta1/news", params):
        for a in page.get("news") or []:
            tagged = a.get("symbols") or []
            for ticker in tracked.intersection(tagged):
                rows.append((ticker, a["id"], a.get("created_at"), a.get("updated_at"),
                             a.get("headline"), a.get("summary") or None, a.get("author") or None,
                             a.get("source"), a.get("url"), ",".join(tagged), len(tagged)))
    return pd.DataFrame(rows, columns=["ticker", "news_id", "published_at", "updated_at_source", "headline",
                                       "summary", "author", "source", "url", "all_symbols", "n_symbols"])
