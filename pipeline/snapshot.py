"""`stock_snapshot`: one row per stock with everything a stock card needs today.

Built from the other tables, so it can always be rebuilt. Any input may be missing
(a source failed tonight): the matching columns are simply left empty.
"""
import numpy as np
import pandas as pd

from . import config
from .fundamentals import latest_share_count

RETURN_WINDOWS = {"ret_1w": pd.DateOffset(weeks=1), "ret_1m": pd.DateOffset(months=1),
                  "ret_3m": pd.DateOffset(months=3), "ret_6m": pd.DateOffset(months=6),
                  "ret_1y": pd.DateOffset(years=1), "ret_3y": pd.DateOffset(years=3),
                  "ret_5y": pd.DateOffset(years=5)}

# Not meaningful for banks, brokers and insurers (see config.FINANCIAL_SIC_RANGE).
NOT_FOR_FINANCIALS = ["gross_margin", "operating_margin", "free_cash_flow_ttm", "fcf_margin", "fcf_yield",
                      "ebitda_ttm", "total_debt", "net_debt", "debt_to_equity", "current_ratio",
                      "enterprise_value", "ev_to_ebitda", "ev_to_sales"]


def rsi(closes: pd.Series, period: int = 14) -> float:
    """Wilder's RSI, last value. 70+ is commonly read as overbought, 30- as oversold."""
    delta = closes.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    if len(closes) <= period:
        return np.nan
    if loss.iloc[-1] == 0:
        return 100.0
    return float(100 - 100 / (1 + gain.iloc[-1] / loss.iloc[-1]))


def _return(series: pd.Series, since) -> float:
    """Change from the last close on or before `since` to the latest close."""
    base = series.asof(since)
    return float(series.iloc[-1] / base - 1) if pd.notna(base) and base > 0 else np.nan


def price_stats(prices: pd.DataFrame, benchmark: str = config.BENCHMARK) -> pd.DataFrame:
    """Per-ticker price statistics from daily bars (one row per ticker)."""
    p = prices.copy()
    p["price_date"] = pd.to_datetime(p["price_date"])
    p = p.sort_values("price_date")
    by_ticker = {t: g.set_index("price_date") for t, g in p.groupby("ticker")}
    bench = by_ticker.get(benchmark)
    bench_returns = bench["close"].pct_change() if bench is not None else None

    rows = []
    for ticker, g in by_ticker.items():
        close, last = g["close"], g.index[-1]
        year = close[close.index > last - pd.DateOffset(years=1)]
        daily = close.pct_change().dropna().tail(252)
        row = {
            "ticker": ticker,
            "price_date": last,
            "close": float(close.iloc[-1]),
            "ret_1d": float(close.iloc[-1] / close.iloc[-2] - 1) if len(close) > 1 else np.nan,
            "ret_ytd": _return(close, pd.Timestamp(last.year - 1, 12, 31)),
            "total_return_1y": _return(g["close_total_return"].dropna(), last - pd.DateOffset(years=1))
            if g["close_total_return"].notna().any() else np.nan,
            "high_52w": float(year.max()),
            "low_52w": float(year.min()),
            "pct_from_high_52w": float(close.iloc[-1] / year.max() - 1),
            "volatility_1y": float(daily.std() * np.sqrt(252)) if len(daily) >= 60 else np.nan,
            "rsi_14": rsi(close),
            "sma_50": float(close.tail(50).mean()) if len(close) >= 50 else np.nan,
            "sma_200": float(close.tail(200).mean()) if len(close) >= 200 else np.nan,
            "avg_volume_30d": float(g["volume"].tail(30).mean()),
            "beta_1y": np.nan,
            "ret_1y_vs_benchmark": np.nan,
        }
        for name, window in RETURN_WINDOWS.items():
            row[name] = _return(close, last - window)
        if bench_returns is not None and len(daily) >= 60:
            both = pd.concat([daily, bench_returns], axis=1, join="inner").dropna()
            if len(both) >= 60 and both.iloc[:, 1].var() > 0:
                row["beta_1y"] = float(both.iloc[:, 0].cov(both.iloc[:, 1]) / both.iloc[:, 1].var())
            row["ret_1y_vs_benchmark"] = row["ret_1y"] - _return(bench["close"], last - pd.DateOffset(years=1))
        rows.append(row)
    return pd.DataFrame(rows)


def trailing_dividends(actions: pd.DataFrame, ticker: str, as_of) -> float:
    """Regular cash dividends per share over the last 12 months, on today's share basis."""
    mine = actions[actions["ticker"] == ticker].copy()
    mine["ex_date"] = pd.to_datetime(mine["ex_date"])
    splits = mine[mine["action_type"].str.endswith("split")]
    paid = mine[(mine["action_type"] == "cash_dividend") & (mine["is_special"] != True)  # noqa: E712
                & (mine["ex_date"] > as_of - pd.DateOffset(years=1)) & (mine["ex_date"] <= as_of)]
    total = 0.0
    for ex_date, amount in zip(paid["ex_date"], paid["cash_amount"]):
        later_splits = splits.loc[splits["ex_date"] > ex_date, "split_ratio"].prod()
        total += amount / later_splits
    return total


def _div(a, b):
    return a / b if a is not None and b is not None and pd.notna(a) and pd.notna(b) and b > 0 else np.nan


def build_snapshot(companies: pd.DataFrame, prices: pd.DataFrame | None = None,
                   fundamentals: pd.DataFrame | None = None,
                   actions: pd.DataFrame | None = None) -> pd.DataFrame:
    stats = price_stats(prices).set_index("ticker") if prices is not None and len(prices) else None
    rows = []
    for company in companies.to_dict("records"):
        ticker = company["ticker"]
        row = {k: company.get(k) for k in ("ticker", "company_name", "sector", "sic_description", "is_financial")}
        if stats is not None and ticker in stats.index:
            row.update(stats.loc[ticker].to_dict())
        close = row.get("close")
        multiplier = config.SHARE_CLASS_MULTIPLIER.get(ticker, 1)

        mine = fundamentals[fundamentals["ticker"] == ticker] if fundamentals is not None else None
        if mine is not None and len(mine):
            ttm = mine[mine["period_type"] == "TTM"].sort_values("period_end")
            quarters = mine[mine["period_type"] == "Q"].sort_values("period_end")
            shares, shares_as_of = latest_share_count(mine)
            row["shares"] = shares * multiplier if shares else np.nan
            row["shares_as_of"] = shares_as_of
            if len(quarters):
                row["revenue_yoy_quarter"] = quarters["revenue_yoy"].iloc[-1]
            if len(ttm):
                t = ttm.iloc[-1]
                # Diluted EPS as reported; else basic; else profit / shares (multi-class companies
                # often report EPS per share class, which EDGAR's API leaves out).
                eps = next((v for v in (t["eps_diluted"], t["eps_basic"], _div(t["net_income"], shares))
                            if pd.notna(v)), np.nan)
                row.update({
                    "fundamentals_period_end": t["period_end"], "fiscal_year": t["fiscal_year"],
                    "fiscal_quarter": t["fiscal_quarter"], "reported_date": t["reported_date"],
                    "revenue_ttm": t["revenue"], "net_income_ttm": t["net_income"],
                    "eps_diluted_ttm": eps / multiplier,
                    "free_cash_flow_ttm": t["free_cash_flow"], "ebitda_ttm": t["ebitda"],
                    "dividends_per_share_ttm": t["dividends_per_share"] / multiplier,
                    **{k: t[k] for k in ("gross_margin", "operating_margin", "net_margin", "fcf_margin",
                                         "roe", "roa", "revenue_yoy", "net_income_yoy", "eps_diluted_yoy",
                                         "cash", "total_debt", "net_debt", "equity", "debt_to_equity",
                                         "current_ratio")},
                })

        if actions is not None and len(actions) and pd.notna(row.get("price_date")):
            row["dividends_per_share_ttm"] = trailing_dividends(actions, ticker, row["price_date"])

        if pd.notna(close):
            market_cap = close * row["shares"] if pd.notna(row.get("shares")) else np.nan
            enterprise_value = market_cap + row.get("net_debt", np.nan)
            equity = row.get("equity", np.nan)
            row.update({
                "market_cap": market_cap,
                "enterprise_value": enterprise_value,
                "pe_ttm": _div(close, row.get("eps_diluted_ttm")),   # empty when earnings are negative
                "ps_ttm": _div(market_cap, row.get("revenue_ttm")),
                "pb": _div(market_cap, equity),                      # empty on negative equity
                "ev_to_ebitda": _div(enterprise_value, row.get("ebitda_ttm")),
                "ev_to_sales": _div(enterprise_value, row.get("revenue_ttm")),
                "fcf_yield": _div(row.get("free_cash_flow_ttm"), market_cap),
                "dividend_yield": _div(row.get("dividends_per_share_ttm"), close),
            })

        if row.get("is_financial"):
            for column in NOT_FOR_FINANCIALS:
                row[column] = np.nan
        rows.append(row)
    return pd.DataFrame(rows)
