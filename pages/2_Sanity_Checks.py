import pandas as pd
import streamlit as st
from bq_client import bq_client, project_id
from config import symbols, ticker_to_cik, get_macro_series_for_sic
from queries import load_companies, load_prices, load_fundamentals

st.title("🔍 Sanity Checks")
st.caption("Data completeness and freshness across all tracked stocks.")

companies_df = load_companies()
prices_df = load_prices()
fundamentals_df = load_fundamentals()

# --- Data Freshness ---
with st.container(border=True):
    st.markdown("##### 🕐 Table Freshness (last_updated)")

    for table_name, df in [("companies", companies_df), ("daily_prices", prices_df), ("fundamentals", fundamentals_df)]:
        query = f"SELECT MAX(last_updated) AS last_refresh FROM `{project_id}.stock_data.{table_name}`"
        result = list(bq_client.query(query).result())
        last_refresh = result[0]["last_refresh"]
        st.write(f"**{table_name}**: last refreshed {last_refresh}")

# --- Overview ---
with st.container(border=True):
    st.markdown("##### 📋 Overview")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Stocks in config", len(symbols))
    with col2:
        st.metric("Companies in BigQuery", companies_df["ticker"].nunique())
    with col3:
        st.metric("Stocks with price data", prices_df["ticker"].nunique())
    with col4:
        st.metric("Stocks with fundamentals", fundamentals_df["ticker"].nunique())

    missing_companies = set(symbols) - set(companies_df["ticker"])
    missing_prices = set(symbols) - set(prices_df["ticker"])
    missing_fundamentals = set(symbols) - set(fundamentals_df["ticker"])

    if missing_companies:
        st.warning(f"Missing from companies table: {sorted(missing_companies)}")
    if missing_prices:
        st.warning(f"Missing from daily_prices table: {sorted(missing_prices)}")
    if missing_fundamentals:
        st.warning(f"Missing from fundamentals table: {sorted(missing_fundamentals)}")
    if not (missing_companies or missing_prices or missing_fundamentals):
        st.success("All configured stocks present in all 3 tables.")

# --- Price Freshness ---
with st.container(border=True):
    st.markdown("##### 📈 Price Data Freshness")

    latest_prices = prices_df.groupby("ticker")["price_date"].max().reset_index()
    latest_prices.columns = ["ticker", "latest_price_date"]
    latest_prices["latest_price_date"] = pd.to_datetime(latest_prices["latest_price_date"])

    most_recent_date = latest_prices["latest_price_date"].max()
    stale = latest_prices[latest_prices["latest_price_date"] < most_recent_date - pd.Timedelta(days=5)]

    st.write(f"Most recent price date across all stocks: **{most_recent_date.date()}**")
    if len(stale) > 0:
        st.warning(f"{len(stale)} stock(s) more than 5 days behind the most recent date:")
        st.dataframe(stale, hide_index=True, use_container_width=True)
    else:
        st.success("All stocks are up to date (within 5 days of the most recent date).")

# --- Fundamentals: Period Count Sanity ---
with st.container(border=True):
    st.markdown("##### 📅 Fundamentals — Fiscal Year Coverage")
    st.caption("Flags unusually high (possible data contamination) or low (possible gap) period counts.")

    period_counts = fundamentals_df.groupby("ticker")["period_end"].nunique().reset_index()
    period_counts.columns = ["ticker", "num_periods"]
    period_counts = period_counts.sort_values("num_periods", ascending=False)

    too_many = period_counts[period_counts["num_periods"] > 25]
    too_few = period_counts[period_counts["num_periods"] < 3]

    if len(too_many) > 0:
        st.warning("Unusually high period count (possible contamination):")
        st.dataframe(too_many, hide_index=True, use_container_width=True)
    if len(too_few) > 0:
        st.warning("Unusually low period count (possible data gap):")
        st.dataframe(too_few, hide_index=True, use_container_width=True)
    if len(too_many) == 0 and len(too_few) == 0:
        st.success("All stocks have a reasonable number of fiscal years (3-25).")

    with st.expander("View full period count table"):
        st.dataframe(period_counts, hide_index=True, use_container_width=True)

# --- Field Completion Rates (latest period per stock) ---
with st.container(border=True):
    st.markdown("##### ✅ Fundamentals Field Completion (latest fiscal year per stock)")

    latest_fundamentals = (
        fundamentals_df.sort_values("period_end")
        .groupby("ticker")
        .tail(1)
    )

    fields_to_check = [
        "revenue", "net_margin", "gross_margin", "operating_cash_flow",
        "leverage", "roe", "shares_outstanding", "cash", "total_debt",
        "ebitda", "total_equity",
    ]

    completion_data = []
    total = len(latest_fundamentals)
    for field in fields_to_check:
        non_null = latest_fundamentals[field].notna().sum()
        completion_data.append({
            "Field": field,
            "Complete": non_null,
            "Missing": total - non_null,
            "Completion %": round(100 * non_null / total, 1) if total > 0 else 0,
        })

    completion_df = pd.DataFrame(completion_data).sort_values("Completion %")
    st.dataframe(completion_df, hide_index=True, use_container_width=True)
    st.bar_chart(completion_df.set_index("Field")["Completion %"])

# --- Company Info Completion ---
with st.container(border=True):
    st.markdown("##### 🏢 Company Info Completion")

    company_fields = ["sic_code", "sic_description", "state_of_incorporation", "earliest_filing_date"]
    company_completion = []
    total_companies = len(companies_df)
    for field in company_fields:
        non_null = companies_df[field].notna().sum()
        company_completion.append({
            "Field": field,
            "Complete": non_null,
            "Missing": total_companies - non_null,
            "Completion %": round(100 * non_null / total_companies, 1) if total_companies > 0 else 0,
        })
    st.dataframe(pd.DataFrame(company_completion), hide_index=True, use_container_width=True)

# --- Macro Mapping Coverage ---
with st.container(border=True):
    st.markdown("##### 🌍 Macro Sector Mapping Coverage")

    mapping_results = []
    for _, row in companies_df.iterrows():
        _, is_specific = get_macro_series_for_sic(row["sic_code"])
        mapping_results.append({
            "ticker": row["ticker"],
            "sic_description": row["sic_description"],
            "mapped": "✅ Sector-specific" if is_specific else "⚠️ Default fallback",
        })
    mapping_df = pd.DataFrame(mapping_results)

    specific_count = (mapping_df["mapped"] == "✅ Sector-specific").sum()
    st.write(f"**{specific_count} / {len(mapping_df)}** stocks have a sector-specific macro mapping.")

    with st.expander("View mapping details"):
        st.dataframe(mapping_df, hide_index=True, use_container_width=True)

# --- Split-Adjustment Check ---
with st.container(border=True):
    st.markdown("##### ✂️ Potential Unadjusted Stock Splits")
    st.caption("Flags any single-day price move >40% — could be a real crash, but is more likely an unadjusted split.")

    prices_sorted = prices_df.sort_values(["ticker", "price_date"]).copy()
    prices_sorted["pct_change"] = prices_sorted.groupby("ticker")["close"].pct_change()

    suspicious_moves = prices_sorted[prices_sorted["pct_change"].abs() > 0.40][
        ["ticker", "price_date", "close", "pct_change"]
    ]

    if len(suspicious_moves) > 0:
        suspicious_moves["pct_change"] = (suspicious_moves["pct_change"] * 100).round(1).astype(str) + "%"
        st.warning(f"{len(suspicious_moves)} suspicious single-day move(s) found:")
        st.dataframe(suspicious_moves, hide_index=True, use_container_width=True)
    else:
        st.success("No single-day moves >40% detected.")


# --- Duplicate Row Detection ---
with st.container(border=True):
    st.markdown("##### 🔁 Duplicate Row Check")

    price_dupes = prices_df.duplicated(subset=["ticker", "price_date"]).sum()
    fundamentals_dupes = fundamentals_df.duplicated(subset=["ticker", "period_end"]).sum()
    company_dupes = companies_df.duplicated(subset=["ticker"]).sum()

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Duplicate price rows", price_dupes)
    with col2:
        st.metric("Duplicate fundamentals rows", fundamentals_dupes)
    with col3:
        st.metric("Duplicate company rows", company_dupes)

    if price_dupes == 0 and fundamentals_dupes == 0 and company_dupes == 0:
        st.success("No duplicate rows detected in any table.")
    else:
        st.warning("Duplicates found — ingestion logic may need review.")

# Compute valuation ratios for all stocks' latest period, for outlier scanning
from edgar_data import compute_valuation_ratios

latest_fundamentals_all = fundamentals_df.sort_values("period_end").groupby("ticker").tail(1)
latest_prices_all = prices_df.sort_values("price_date").groupby("ticker").tail(1).set_index("ticker")["close"]

valuation_rows = []
for _, row in latest_fundamentals_all.iterrows():
    ticker = row["ticker"]
    if ticker not in latest_prices_all.index:
        continue
    price = latest_prices_all[ticker]
    ratios = compute_valuation_ratios(row.to_dict(), price)
    valuation_rows.append({"ticker": ticker, **ratios})

valuation_df = pd.DataFrame(valuation_rows)

# --- Valuation Ratio Outliers ---
with st.container(border=True):
    st.markdown("##### 📊 Valuation Ratio Outliers")
    st.caption("Flags negative or implausibly extreme ratios that likely indicate a calculation error.")

    outliers = valuation_df[
        (valuation_df["ev_to_sales"] < 0) | (valuation_df["ev_to_sales"] > 100) |
        (valuation_df["ev_to_ebitda"] < 0) | (valuation_df["ev_to_ebitda"] > 200) |
        (valuation_df["price_to_book"] < 0) | (valuation_df["price_to_book"] > 200)
    ]

    if len(outliers) > 0:
        st.warning(f"{len(outliers)} stock(s) with outlier valuation ratios:")
        st.dataframe(outliers, hide_index=True, use_container_width=True)
    else:
        st.success("No outlier valuation ratios detected.")

# --- Macro Data Staleness ---
with st.container(border=True):
    st.markdown("##### 🌍 Macro Data Staleness")
    st.caption("Flags any FRED series older than 90 days.")

    from fred_data import get_latest_value

    all_series = set()
    for entry in __import__("config").sector_macro_mapping:
        for series_id, label, note in entry["series"]:
            all_series.add((series_id, label))
    for series_id, label, note in __import__("config").DEFAULT_MACRO_SERIES:
        all_series.add((series_id, label))

    stale_series = []
    for series_id, label in all_series:
        date, value = get_latest_value(series_id)
        if date:
            days_old = (pd.Timestamp.today() - pd.Timestamp(date)).days
            if days_old > 90:
                stale_series.append({"series": label, "last_date": date, "days_old": days_old})

    if stale_series:
        st.warning("Stale macro series found:")
        st.dataframe(pd.DataFrame(stale_series), hide_index=True, use_container_width=True)
    else:
        st.success("All macro series are up to date (within 90 days).")