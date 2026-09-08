import os
from dotenv import load_dotenv
import requests
import streamlit as st

load_dotenv()

FRED_API_KEY = os.environ.get("FRED_API_KEY")

BASE_URL = "https://api.stlouisfed.org/fred/series/observations"


@st.cache_data(ttl=21600)  # 6 hours -- macro data moves slowly
def get_latest_value(series_id):
    """
    Returns the most recent (date, value) for a FRED series.
    Returns (None, None) if the series has no data or the request fails.
    """
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 1,
    }
    response = requests.get(BASE_URL, params=params)
    data = response.json()

    observations = data.get("observations", [])
    if not observations:
        return None, None

    latest = observations[0]
    value = latest["value"]

    if value == ".":
        return latest["date"], None

    return latest["date"], float(value)


@st.cache_data(ttl=21600)
def get_recent_history(series_id, limit=12):
    """
    Returns a list of (date, value) tuples, most recent first.
    """
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
    }
    response = requests.get(BASE_URL, params=params)
    data = response.json()

    results = []
    for obs in data.get("observations", []):
        value = None if obs["value"] == "." else float(obs["value"])
        results.append((obs["date"], value))

    return results


def get_macro_snapshot(series_list):
    """
    Given a list of (series_id, label, note) tuples, returns a list of
    (label, date, value, note) for each -- the current snapshot to display.
    """
    results = []
    for series_id, label, note in series_list:
        date, value = get_latest_value(series_id)
        results.append((label, date, value, note))
    return results