import pandas as pd
import streamlit as st

from app_data import doc, load, money, number, pct, share, times
from pipeline import config

SNAP = "stock_snapshot"


def cards(title: str, items: list[tuple[str, str, str]]):
    """A bordered row of metrics. items = (label, formatted value, snapshot column for the tooltip)."""
    with st.container(border=True):
        st.markdown(f"##### {title}")
        for column, (label, value, source) in zip(st.columns(len(items)), items):
            column.metric(label, value, help=doc(SNAP, source))


snapshot = load(SNAP).sort_values("market_cap", ascending=False)
names = dict(zip(snapshot["ticker"], snapshot["company_name"]))
ticker = st.selectbox("Stock", list(snapshot["ticker"]), format_func=lambda t: f"{names[t]} ({t})")
s = snapshot.set_index("ticker").loc[ticker]

st.title(f"{s['company_name']} ({ticker})")
st.caption(f"{s['sector']} · {s['sic_description']} · price as of {s['price_date']:%d %b %Y} · "
           "for information only, not investment advice")

top = st.columns(4)
top[0].metric("Price", money(s["close"]), pct(s["ret_1d"]))
top[1].metric("Market cap", money(s["market_cap"]), help=doc(SNAP, "market_cap"))
top[2].metric("1-year change", pct(s["ret_1y"]), help=doc(SNAP, "ret_1y"))
top[3].metric("vs S&P 500 (1y)", pct(s["ret_1y_vs_benchmark"]), help=doc(SNAP, "ret_1y_vs_benchmark"))

# ---------------------------------------------------------------- price chart
prices = load("prices", ticker).sort_values("price_date")
ranges = {"1M": 30, "6M": 182, "1Y": 365, "3Y": 3 * 365, "All": None}
chosen = st.radio("Range", list(ranges), index=2, horizontal=True)
if ranges[chosen]:
    prices = prices[prices["price_date"] >= prices["price_date"].max() - pd.Timedelta(days=ranges[chosen])]
st.line_chart(prices, x="price_date", y="close", x_label="", y_label="Price (USD, split-adjusted)")

cards("Performance", [
    ("1 month", pct(s["ret_1m"]), "ret_1m"), ("Year to date", pct(s["ret_ytd"]), "ret_ytd"),
    ("5 years", pct(s["ret_5y"]), "ret_5y"), ("From 52-week high", pct(s["pct_from_high_52w"]), "pct_from_high_52w"),
    ("Volatility", share(s["volatility_1y"]), "volatility_1y"), ("Beta", number(s["beta_1y"], 2), "beta_1y"),
])
cards("Valuation — is it expensive?", [
    ("P/E", times(s["pe_ttm"]), "pe_ttm"), ("Price / sales", times(s["ps_ttm"]), "ps_ttm"),
    ("Price / book", times(s["pb"]), "pb"), ("EV / EBITDA", times(s["ev_to_ebitda"]), "ev_to_ebitda"),
    ("FCF yield", share(s["fcf_yield"]), "fcf_yield"), ("Dividend yield", share(s["dividend_yield"]), "dividend_yield"),
])
cards("Growth — is it getting bigger?", [
    ("Revenue (12m)", money(s["revenue_ttm"]), "revenue_ttm"), ("Revenue growth", pct(s["revenue_yoy"]), "revenue_yoy"),
    ("Latest quarter", pct(s["revenue_yoy_quarter"]), "revenue_yoy_quarter"),
    ("Profit growth", pct(s["net_income_yoy"]), "net_income_yoy"), ("EPS growth", pct(s["eps_diluted_yoy"]), "eps_diluted_yoy"),
])
cards("Profitability — does it make money?", [
    ("Net income (12m)", money(s["net_income_ttm"]), "net_income_ttm"), ("Gross margin", share(s["gross_margin"]), "gross_margin"),
    ("Operating margin", share(s["operating_margin"]), "operating_margin"), ("Net margin", share(s["net_margin"]), "net_margin"),
    ("Return on equity", share(s["roe"]), "roe"),
])
cards("Financial health — can it pay its bills?", [
    ("Cash", money(s["cash"]), "cash"), ("Total debt", money(s["total_debt"]), "total_debt"),
    ("Debt / equity", times(s["debt_to_equity"]), "debt_to_equity"), ("Current ratio", times(s["current_ratio"]), "current_ratio"),
    ("Free cash flow (12m)", money(s["free_cash_flow_ttm"]), "free_cash_flow_ttm"),
])
if s["is_financial"]:
    st.caption("Bank, broker or insurer: debt, EBITDA and cash-flow metrics are not comparable and are left empty.")
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
