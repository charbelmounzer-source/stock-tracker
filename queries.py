import streamlit as st
from bq_client import bq_client, project_id


@st.cache_data(ttl=3600)
def load_companies():
    query = f"""
        SELECT ticker, company_name, sic_code, sic_description,
               state_of_incorporation, earliest_filing_date
        FROM `{project_id}.stock_data.companies`
    """
    return bq_client.query(query).to_dataframe()


@st.cache_data(ttl=3600)
def load_prices():
    query = f"""
        SELECT ticker, price_date, close
        FROM `{project_id}.stock_data.daily_prices`
        ORDER BY price_date
    """
    return bq_client.query(query).to_dataframe()


@st.cache_data(ttl=3600)
def load_fundamentals():
    query = f"""
        SELECT ticker, period_end, revenue, net_margin, gross_margin,
               operating_cash_flow, leverage, roe,
               shares_outstanding, cash, total_debt, ebitda, total_equity
        FROM `{project_id}.stock_data.fundamentals`
        ORDER BY period_end
    """
    return bq_client.query(query).to_dataframe()