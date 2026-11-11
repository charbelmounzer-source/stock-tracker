"""Data access and formatting shared by the Streamlit pages.

Reads BigQuery by default. Set LOCAL_DATA_DIR to a folder produced by
`python -m pipeline --local DIR` to browse a trial run without BigQuery.
"""
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from pipeline import config  # noqa: F401  (loads .env before LOCAL_DATA_DIR is read)
from pipeline.schemas import TABLES

LOCAL_DIR = os.environ.get("LOCAL_DATA_DIR")


def _parse_dates(df: pd.DataFrame, table: str) -> pd.DataFrame:
    for name, kind, _ in TABLES[table]["columns"]:
        if kind == "DATE":
            df[name] = pd.to_datetime(df[name])
        elif kind == "TIMESTAMP":
            df[name] = pd.to_datetime(df[name], utc=True)
    return df


@st.cache_resource
def _client():
    from pipeline.bq import get_client
    return get_client()


@st.cache_data(ttl=3600)
def load(table: str, ticker: str | None = None) -> pd.DataFrame:
    """A whole table, or one ticker's rows."""
    if LOCAL_DIR:
        df = pd.read_csv(Path(LOCAL_DIR) / f"{table}.csv")
        df = df[df["ticker"] == ticker] if ticker else df
    else:
        from google.cloud import bigquery
        from pipeline.bq import table_id
        client = _client()
        sql, params = f"SELECT * FROM `{table_id(client, table)}`", []
        if ticker:
            sql += " WHERE ticker = @ticker"
            params = [bigquery.ScalarQueryParameter("ticker", "STRING", ticker)]
        df = client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).to_dataframe()
    return _parse_dates(df.reset_index(drop=True), table)


def doc(table: str, column: str) -> str:
    """The column's description from the data dictionary, used as a tooltip."""
    return next(d for name, _, d in TABLES[table]["columns"] if name == column)


def money(x) -> str:
    if pd.isna(x):
        return "n/a"
    for size, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(x) >= size:
            return f"${x / size:,.1f}{suffix}"
    return f"${x:,.2f}"


def pct(x) -> str:
    return "n/a" if pd.isna(x) else f"{x:+.1%}"


def share(x) -> str:
    return "n/a" if pd.isna(x) else f"{x:.1%}"


def times(x) -> str:
    return "n/a" if pd.isna(x) else f"{x:,.1f}x"


def number(x, digits: int = 1) -> str:
    return "n/a" if pd.isna(x) else f"{x:,.{digits}f}"
