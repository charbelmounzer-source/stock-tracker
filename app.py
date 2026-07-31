import os
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed
from alpaca.trading.client import TradingClient
from datetime import datetime, date, timedelta
import altair as alt
from edgar_data import get_fundamentals_all_periods, get_earliest_filing_date
from edgar_data import get_fundamentals_all_periods, get_earliest_filing_date, get_company_info
from edgar_data import get_fundamentals_all_periods, get_earliest_filing_date, get_company_info, get_full_statement

load_dotenv()

api_key = os.environ["ALPACA_API_KEY"]
secret_key = os.environ["ALPACA_SECRET_KEY"]

client = StockHistoricalDataClient(api_key, secret_key)
trading_client = TradingClient(api_key, secret_key, paper=True)

symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "JPM", "V", "NFLX"]

ticker_to_cik = {
    'NVDA': '0001045810', 'AAPL': '0000320193', 'GOOGL': '0001652044',
    'MSFT': '0000789019', 'AMZN': '0001018724', 'META': '0001326801',
    'TSLA': '0001318605', 'JPM': '0000019617', 'V': '0001403161',
    'NFLX': '0001065280'
}

# Look up real company names dynamically from Alpaca
company_names = {}
for symbol in symbols:
    asset = trading_client.get_asset(symbol)
    company_names[symbol] = asset.name

request = StockBarsRequest(
    symbol_or_symbols=symbols,
    timeframe=TimeFrame.Day,
    start=datetime(2016, 1, 1),   # "all time" -- Alpaca's free tier goes back 7+ years
    end=datetime.now() - timedelta(minutes=20),
    feed=DataFeed.IEX,
)

bars = client.get_stock_bars(request)

# Build one table: rows = dates, columns = symbols, values = close price
data = {}
for symbol in symbols:
    dates = [bar.timestamp.date() for bar in bars[symbol]]
    closes = [bar.close for bar in bars[symbol]]
    data[symbol] = pd.Series(closes, index=dates)

df = pd.DataFrame(data)

# --- Streamlit UI ---
st.title("Stock Price Tracker")

chosen_stock = st.selectbox(
    "Choose a stock",
    symbols,
    format_func=lambda ticker: f"{company_names[ticker]} ({ticker})",
)

date_range = st.radio(
    "Date range",
    ["All time", "L3Y", "L1Y", "L30D"],
    horizontal=True,
)

st.write(f"Showing: **{company_names[chosen_stock]} ({chosen_stock})** — {date_range} (prices in USD)")

company_info = get_company_info(ticker_to_cik[chosen_stock])
st.caption(f"Industry: {company_info['sic_description']} (SIC {company_info['sic_code']}) · Incorporated in {company_info['state_of_incorporation']}")

# Filter the data based on the chosen range
today = date.today()
series = df[chosen_stock]

if date_range == "L30D":
    cutoff = today - timedelta(days=30)
    series = series[series.index >= cutoff]
elif date_range == "L1Y":
    cutoff = today - timedelta(days=365)
    series = series[series.index >= cutoff]
elif date_range == "L3Y":
    cutoff = today - timedelta(days=3 * 365)
    series = series[series.index >= cutoff]
# "All time" -> no filtering, keep series as is

chart_data = series.reset_index()
chart_data.columns = ["date", "price"]

chart = (
    alt.Chart(chart_data)
    .mark_line(point=True)
    .encode(
        x=alt.X("date:T", axis=alt.Axis(format="%b %Y", title="Date")),
        y=alt.Y("price:Q", title="Price (USD)"),
        tooltip=[
            alt.Tooltip("date:T", title="Date", format="%b %d, %Y"),
            alt.Tooltip("price:Q", title="Price", format="$.2f"),
        ],
    )
)

st.altair_chart(chart, use_container_width=True)

st.write("Key stats (for selected date range):")

col1, col2, col3 = st.columns(3)

with col1:
    st.metric("Max price", f"${series.max():,.2f}")

with col2:
    st.metric("Min price", f"${series.min():,.2f}")

with col3:
    st.metric("Average price", f"${series.mean():,.2f}")

st.divider()
st.subheader(f"Fundamentals — {company_names[chosen_stock]}")

all_periods_data = get_fundamentals_all_periods(chosen_stock, ticker_to_cik[chosen_stock])

# Sort periods newest-first so the dropdown defaults to the most recent
sorted_periods = sorted(all_periods_data.keys(), reverse=True)

chosen_period = st.selectbox("Fiscal year ending", sorted_periods)

fundamentals = all_periods_data[chosen_period]

col4, col5, col6 = st.columns(3)

with col4:
    st.metric("Revenue", f"${fundamentals['revenue']/1_000_000:,.1f}M" if fundamentals['revenue'] else "N/A")

with col5:
    st.metric("Net margin", f"{fundamentals['net_margin']:.1%}" if fundamentals['net_margin'] else "N/A")

with col6:
    st.metric("Gross margin", f"{fundamentals['gross_margin']:.1%}" if fundamentals['gross_margin'] else "N/A")

col7, col8, col9 = st.columns(3)

with col7:
    st.metric("Operating cash flow", f"${fundamentals['operating_cash_flow']/1_000_000:,.1f}M" if fundamentals['operating_cash_flow'] else "N/A")

with col8:
    st.metric("Leverage (Liabilities/Equity)", f"{fundamentals['leverage']:.2f}x" if fundamentals['leverage'] else "N/A")

with col9:
    st.metric("ROE", f"{fundamentals['roe']:.1%}" if fundamentals['roe'] else "N/A")

col10, col11, col12 = st.columns(3)

with col10:
    ipo_proxy_date = get_earliest_filing_date(ticker_to_cik[chosen_stock])
    st.metric("Earliest EDGAR filing", ipo_proxy_date)

with col11:
    st.empty()

with col12:
    st.empty()



with st.expander("View full financial statement (raw EDGAR data)"):
    full_statement = get_full_statement(ticker_to_cik[chosen_stock], chosen_period)

    # Format the Value column with commas for readability
    full_statement["Value"] = full_statement["Value"].apply(lambda x: f"{x:,.0f}")

    st.dataframe(full_statement, use_container_width=True, hide_index=True)

    st.markdown(
        f"[View this company's filings directly on SEC EDGAR ↗](https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ticker_to_cik[chosen_stock]}&type=10-K)"
    )