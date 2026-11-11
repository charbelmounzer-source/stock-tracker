import pandas as pd
import streamlit as st

from app_data import card, doc, load, money, number, pct, share, times
from pipeline import config

SNAP = "stock_snapshot"

snapshot = load(SNAP).sort_values("market_cap", ascending=False)
names = dict(zip(snapshot["ticker"], snapshot["company_name"]))
ticker = st.selectbox("Stock", list(snapshot["ticker"]), format_func=lambda t: f"{names[t]} ({t})")
s = snapshot.set_index("ticker").loc[ticker]


def metrics(title: str, items: list[tuple[str, str, str]]):
    """items = (label, formatter, snapshot column). The tooltip is the column's description."""
    card(title, [(label, fmt(s[column]), doc(SNAP, column)) for label, fmt, column in items])


st.title(f"{s['company_name']} ({ticker})")
st.caption(f"{s['sector']} · {s['sic_description']} · price as of {s['price_date']:%d %b %Y} · "
           "for information only, not investment advice")

metrics("Today", [("Price", money, "close"), ("Today's change", pct, "ret_1d"),
                  ("Market cap", money, "market_cap"), ("1-year change", pct, "ret_1y"),
                  ("vs S&P 500, 1 year", pct, "ret_1y_vs_benchmark")])

# ---------------------------------------------------------------- price chart
prices = load("prices", ticker).sort_values("price_date")
ranges = {"1M": 30, "6M": 182, "1Y": 365, "3Y": 3 * 365, "All": None}
chosen = st.radio("Range", list(ranges), index=2, horizontal=True)
if ranges[chosen]:
    prices = prices[prices["price_date"] >= prices["price_date"].max() - pd.Timedelta(days=ranges[chosen])]
st.line_chart(prices, x="price_date", y="close", x_label="", y_label="Price (USD, split-adjusted)")

metrics("Performance", [
    ("1 month", pct, "ret_1m"), ("Year to date", pct, "ret_ytd"), ("3 years", pct, "ret_3y"),
    ("5 years", pct, "ret_5y"), ("From 52-week high", pct, "pct_from_high_52w"),
    ("Volatility", share, "volatility_1y"), ("Beta", lambda x: number(x, 2), "beta_1y")])
metrics("Valuation — is it expensive?", [
    ("Price / earnings", times, "pe_ttm"), ("Price / sales", times, "ps_ttm"), ("Price / book", times, "pb"),
    ("EV / EBITDA", times, "ev_to_ebitda"), ("Free cash flow yield", share, "fcf_yield"),
    ("Dividend yield", share, "dividend_yield")])
metrics("Growth — is it getting bigger?", [
    ("Revenue, last 12 months", money, "revenue_ttm"), ("Revenue growth", pct, "revenue_yoy"),
    ("Latest quarter growth", pct, "revenue_yoy_quarter"), ("Profit growth", pct, "net_income_yoy"),
    ("EPS growth", pct, "eps_diluted_yoy")])
metrics("Profitability — does it make money?", [
    ("Net income, last 12 months", money, "net_income_ttm"), ("Gross margin", share, "gross_margin"),
    ("Operating margin", share, "operating_margin"), ("Net margin", share, "net_margin"),
    ("Return on equity", share, "roe")])
metrics("Financial health — can it pay its bills?", [
    ("Cash", money, "cash"), ("Total debt", money, "total_debt"), ("Debt / equity", times, "debt_to_equity"),
    ("Current ratio", times, "current_ratio"), ("Free cash flow, last 12 months", money, "free_cash_flow_ttm")])
if s["is_financial"]:
    st.caption("Bank, broker or insurer: debt, EBITDA and cash-flow metrics are not comparable, so they are not shown.")
if pd.notna(s["fundamentals_period_end"]):
    st.caption(f"Financials: 12 months to {s['fundamentals_period_end']:%d %b %Y}, "
               f"filed {s['reported_date']:%d %b %Y}. Source: SEC EDGAR.")

# ------------------------------------------------------------ history tables
st.subheader("Financial history")
fundamentals = load("fundamentals", ticker)
view = st.radio("Period", ["Fiscal years", "Quarters"], horizontal=True)
history = fundamentals[fundamentals["period_type"] == ("FY" if view == "Fiscal years" else "Q")]
history = history.sort_values("period_end").tail(10 if view == "Fiscal years" else 12)
st.bar_chart(history, x="period_end", y=["revenue", "net_income"], stack=False, x_label="", y_label="USD")
st.dataframe(history[["period_end", "fiscal_year", "fiscal_quarter", "revenue", "revenue_yoy", "gross_margin",
                      "operating_income", "net_income", "eps_diluted", "operating_cash_flow", "free_cash_flow",
                      "cash", "total_debt", "equity"]].sort_values("period_end", ascending=False),
             hide_index=True)

# --------------------------------------------------------------------- events
st.subheader("Company events")
filings = load("filings", ticker).sort_values("filing_date", ascending=False)
events = filings[filings["form"].isin(["8-K", "10-K", "10-Q"])].head(25)
st.dataframe(events[["filing_date", "form", "event_labels", "url"]], hide_index=True,
             column_config={"url": st.column_config.LinkColumn("Document", display_text="open")})

st.subheader("Insider trades")
trades = load("insider_trades", ticker)
market_trades = trades[trades["transaction_code"].isin(["P", "S"])].sort_values("transaction_date", ascending=False)
if market_trades.empty:
    st.caption(f"No open-market insider purchases or sales in the last {config.INSIDER_LOOKBACK_DAYS} days.")
else:
    st.dataframe(market_trades[["transaction_date", "owner_name", "officer_title", "transaction_label",
                                "shares", "price_per_share", "value"]], hide_index=True)

st.subheader("News")
news = load("news", ticker)
focused = news[news["n_symbols"] <= 3].sort_values("published_at", ascending=False)  # skip market round-ups
for article in focused.head(10).to_dict("records"):
    st.markdown(f"**[{article['headline']}]({article['url']})**  \n{article['published_at']:%d %b %Y} · {article['source']}")

# ---------------------------------------------------------------------- macro
relevant = config.SECTOR_MACRO.get(s["sector"], [])
if relevant:
    st.subheader(f"What moves {s['sector']} stocks")
    macro = load("macro")
    for column, (series_id, why) in zip(st.columns(len(relevant)), relevant):
        series = macro[macro["series_id"] == series_id].sort_values("obs_date")
        if series.empty:
            continue
        latest = series.iloc[-1]
        column.metric(config.FRED_SERIES[series_id], number(latest["value"], 2))
        column.caption(f"{why} (as of {latest['obs_date']:%d %b %Y})")
