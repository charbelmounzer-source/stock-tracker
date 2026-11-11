"""FRED (St. Louis Fed): macro time series. Free API key."""
import pandas as pd

from . import config
from .net import Client

URL = "https://api.stlouisfed.org/fred/series/observations"


def client() -> Client:
    return Client(max_per_second=2)


def fetch_series(c: Client, api_key: str, series_id: str, name: str, start: str = "2000-01-01") -> pd.DataFrame:
    payload = c.get_json(URL, {"series_id": series_id, "api_key": api_key, "file_type": "json",
                               "observation_start": start})
    rows = [(series_id, name, o["date"], float(o["value"]))
            for o in payload.get("observations", []) if o["value"] != "."]  # "." = no data that day
    return pd.DataFrame(rows, columns=["series_id", "series_name", "obs_date", "value"])


def fetch_all(c: Client) -> pd.DataFrame:
    api_key = config.env("FRED_API_KEY")
    return pd.concat([fetch_series(c, api_key, sid, name) for sid, name in config.FRED_SERIES.items()],
                     ignore_index=True)
