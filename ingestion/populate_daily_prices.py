import sys
import os
from datetime import datetime, date, timedelta, timezone
from google.cloud import bigquery
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from bq_client import bq_client, project_id
from config import symbols

api_key = os.environ["ALPACA_API_KEY"]
secret_key = os.environ["ALPACA_SECRET_KEY"]
alpaca_client = StockHistoricalDataClient(api_key, secret_key)

table_id = f"{project_id}.stock_data.daily_prices"


def get_last_date_stored(ticker):
    """Check BigQuery for the most recent price_date we already have for this ticker."""
    query = f"""
        SELECT MAX(price_date) AS last_date
        FROM `{table_id}`
        WHERE ticker = @ticker
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("ticker", "STRING", ticker)]
    )
    result = bq_client.query(query, job_config=job_config).result()
    row = list(result)[0]
    return row.last_date  # None if no rows exist yet for this ticker


rows_to_insert = []

for ticker in symbols:
    last_date = get_last_date_stored(ticker)

    if last_date is None:
        # First time ever for this ticker -- pull full history
        start_date = datetime(2016, 1, 1)
        print(f"{ticker}: no existing data, pulling full history from 2016...")
    else:
        # Already have data -- only pull days after what we've got
        start_date = datetime.combine(last_date + timedelta(days=1), datetime.min.time())
        print(f"{ticker}: last stored date is {last_date}, pulling new data since then...")

    end_date = datetime.now() - timedelta(minutes=20)

    if start_date >= end_date:
        print(f"{ticker}: already up to date, skipping.")
        continue

    request = StockBarsRequest(
        symbol_or_symbols=ticker,
        timeframe=TimeFrame.Day,
        start=start_date,
        end=end_date,
        feed=DataFeed.IEX,
    )
    bars = alpaca_client.get_stock_bars(request)
    
    ticker_bars = bars.data.get(ticker, [])  # safely returns [] if no new bars exist

    if not ticker_bars:
        print(f"{ticker}: no new bars in this range, skipping.")
        continue

    for bar in ticker_bars:
        rows_to_insert.append({
            "ticker": ticker,
            "price_date": bar.timestamp.date().isoformat(),
            "close": float(bar.close),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        })

if rows_to_insert:
    job_config = bigquery.LoadJobConfig(
        write_disposition="WRITE_APPEND",  # ADD new rows, don't wipe existing history
    )
    load_job = bq_client.load_table_from_json(rows_to_insert, table_id, job_config=job_config)
    load_job.result()
    print(f"\nSuccessfully appended {len(rows_to_insert)} new rows to daily_prices.")
else:
    print("\nNo new rows to add -- everything already up to date.")