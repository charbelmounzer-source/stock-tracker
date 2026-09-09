import pandas as pd
import streamlit as st
from datetime import date, timedelta
import altair as alt
from bq_client import bq_client, project_id
from edgar_data import get_full_statement, compute_valuation_ratios
from indicators import compute_rsi, compute_std_dev
from config import symbols, ticker_to_cik
from queries import load_companies, load_prices, load_fundamentals
from fred_data import get_macro_snapshot
from config import get_macro_series_for_sic
from ai_analysis import build_stock_summary, get_ai_analysis, get_cached_ai_analysis


def get_latest_price(ticker, prices_df):
    ticker_prices = prices_df[prices_df["ticker"] == ticker]
    latest_row = ticker_prices.sort_values("price_date").iloc[-1]
    return latest_row["close"]


companies_df = load_companies()
prices_df = load_prices()
fundamentals_df = load_fundamentals()

company_names = dict(zip(companies_df["ticker"], companies_df["company_name"]))

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

company_row = companies_df[companies_df["ticker"] == chosen_stock].iloc[0]
st.write(f"Showing: **{company_row['company_name']} ({chosen_stock})** — {date_range} (prices in USD)")
st.caption(
    f"Industry: {company_row['sic_description']} (SIC {company_row['sic_code']}) "
    f"· Incorporated in {company_row['state_of_incorporation']}"
)

# Filter prices for the chosen stock
stock_prices = prices_df[prices_df["ticker"] == chosen_stock].copy()
stock_prices["price_date"] = pd.to_datetime(stock_prices["price_date"])
series = stock_prices.set_index("price_date")["close"]

# Compute RSI/volatility on the full price history (not the filtered range) for
# accuracy, then align to whatever date range is currently displayed
full_stock_prices = prices_df[prices_df["ticker"] == chosen_stock].copy()
full_stock_prices["price_date"] = pd.to_datetime(full_stock_prices["price_date"])
full_stock_prices = full_stock_prices.sort_values("price_date")
full_stock_prices["rsi"] = compute_rsi(full_stock_prices["close"])

latest_rsi = full_stock_prices["rsi"].iloc[-1]
volatility = compute_std_dev(full_stock_prices["close"])

today = date.today()
if date_range == "L30D":
    cutoff = today - timedelta(days=30)
    series = series[series.index >= pd.Timestamp(cutoff)]
elif date_range == "L1Y":
    cutoff = today - timedelta(days=365)
    series = series[series.index >= pd.Timestamp(cutoff)]
elif date_range == "L3Y":
    cutoff = today - timedelta(days=3 * 365)
    series = series[series.index >= pd.Timestamp(cutoff)]
# "All time" -> no filtering

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

# --- Price Stats ---
with st.container(border=True):
    st.markdown("##### 📈 Price Stats")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Max price", f"${series.max():,.2f}")
    with col2:
        st.metric("Min price", f"${series.min():,.2f}")
    with col3:
        st.metric("Average price", f"${series.mean():,.2f}")

# --- Technical & Risk ---
with st.container(border=True):
    st.markdown("##### 🎯 Technical & Risk")
    col_rsi, col_vol = st.columns(2)
    with col_rsi:
        rsi_label = "Neutral"
        if latest_rsi >= 70:
            rsi_label = "Overbought"
        elif latest_rsi <= 30:
            rsi_label = "Oversold"
        st.metric("RSI (14-day)", f"{latest_rsi:.1f}", rsi_label)
    with col_vol:
        st.metric("Annualized Volatility", f"{volatility:.1%}" if volatility else "N/A")

st.divider()
st.subheader(f"Fundamentals — {company_row['company_name']}")

stock_fundamentals = fundamentals_df[fundamentals_df["ticker"] == chosen_stock].copy()
stock_fundamentals["period_end"] = pd.to_datetime(stock_fundamentals["period_end"])
sorted_periods = sorted(stock_fundamentals["period_end"].dt.date.tolist(), reverse=True)

chosen_period = st.selectbox("Fiscal year ending", sorted_periods)

fundamentals = stock_fundamentals[
    stock_fundamentals["period_end"].dt.date == chosen_period
].iloc[0]

current_price = get_latest_price(chosen_stock, prices_df)
valuation = compute_valuation_ratios(fundamentals.to_dict(), current_price)

# --- Profitability ---
with st.container(border=True):
    st.markdown("##### 💰 Profitability")
    col4, col5, col6 = st.columns(3)
    with col4:
        st.metric(
            "Revenue",
            f"${fundamentals['revenue']/1_000_000:,.1f}M" if pd.notna(fundamentals['revenue']) else "N/A",
        )
    with col5:
        st.metric(
            "Net margin",
            f"{fundamentals['net_margin']:.1%}" if pd.notna(fundamentals['net_margin']) else "N/A",
        )
    with col6:
        st.metric(
            "Gross margin",
            f"{fundamentals['gross_margin']:.1%}" if pd.notna(fundamentals['gross_margin']) else "N/A",
        )

# --- Financial Health ---
with st.container(border=True):
    st.markdown("##### 🏦 Financial Health")
    col7, col8, col9 = st.columns(3)
    with col7:
        st.metric(
            "Operating cash flow",
            f"${fundamentals['operating_cash_flow']/1_000_000:,.1f}M"
            if pd.notna(fundamentals['operating_cash_flow']) else "N/A",
        )
    with col8:
        st.metric(
            "Leverage (Liab/Equity)",
            f"{fundamentals['leverage']:.2f}x" if pd.notna(fundamentals['leverage']) else "N/A",
        )
    with col9:
        st.metric(
            "ROE",
            f"{fundamentals['roe']:.1%}" if pd.notna(fundamentals['roe']) else "N/A",
        )

# --- Valuation ---
with st.container(border=True):
    st.markdown("##### 📊 Valuation")
    col13, col14, col15 = st.columns(3)
    with col13:
        st.metric("EV/Sales", f"{valuation['ev_to_sales']:.2f}x" if valuation['ev_to_sales'] else "N/A")
    with col14:
        st.metric("EV/EBITDA", f"{valuation['ev_to_ebitda']:.2f}x" if valuation['ev_to_ebitda'] else "N/A")
    with col15:
        st.metric("Price to Book", f"{valuation['price_to_book']:.2f}x" if valuation['price_to_book'] else "N/A")

    if valuation['ev_to_ebitda'] is None:
        st.caption("ℹ️ EV/EBITDA unavailable — this company doesn't report a standalone operating income figure in recent filings.")

    if chosen_period != sorted_periods[0]:
        st.caption(
            "⚠️ Valuation ratios use today's price against this year's fundamentals "
            "— not a true historical valuation."
        )

# --- Company Info ---
with st.container(border=True):
    st.markdown("##### 🏢 Company Info")
    st.metric("Earliest EDGAR filing", str(company_row['earliest_filing_date']))

with st.expander("View full financial statement (raw EDGAR data)"):
    full_statement = get_full_statement(ticker_to_cik[chosen_stock], chosen_period.isoformat())
    full_statement["Value"] = full_statement["Value"].apply(lambda x: f"{x:,.0f}")
    st.dataframe(full_statement, use_container_width=True, hide_index=True)
    st.markdown(
        f"[View this company's filings directly on SEC EDGAR ↗]"
        f"(https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ticker_to_cik[chosen_stock]}&type=10-K)"
    )

# --- Macro Exposure ---
with st.container(border=True):
    st.markdown("##### 🌍 Macro Exposure")

    macro_series, is_specific = get_macro_series_for_sic(company_row["sic_code"])
    if not is_specific:
        st.caption("No sector-specific mapping yet — showing general economic indicators.")

    snapshot = get_macro_snapshot(macro_series)

    cols = st.columns(len(snapshot))
    for col, (label, date, value, note) in zip(cols, snapshot):
        with col:
            display_value = f"{value:.2f}" if value is not None else "N/A"
            st.metric(label, display_value)
            if date:
                st.caption(f"as of {date}")
            st.caption(f"💡 {note}")


# --- AI Analysis ---
with st.container(border=True):
    st.markdown("##### 🤖 AI Analysis")
    st.caption("Informational only — not financial advice.")

    if st.button("Generate AI Analysis", key="ai_analysis_btn"):
        with st.spinner("Analyzing..."):
            summary = build_stock_summary(chosen_stock, companies_df, prices_df, fundamentals_df)
            summary_tuple = tuple(sorted(summary.items()))
            analysis = get_cached_ai_analysis(chosen_stock, summary_tuple)
            st.session_state["ai_analysis_result"] = analysis
            st.session_state["ai_analysis_ticker"] = chosen_stock

    if "ai_analysis_result" in st.session_state and st.session_state.get("ai_analysis_ticker") == chosen_stock:
        st.markdown(st.session_state["ai_analysis_result"])