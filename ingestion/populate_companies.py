import sys
import os
from datetime import datetime, timezone
from alpaca.trading.client import TradingClient

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from bq_client import bq_client, project_id
from edgar_data import get_company_info, get_earliest_filing_date
from config import  ticker_to_cik

api_key = os.environ["ALPACA_API_KEY"]
secret_key = os.environ["ALPACA_SECRET_KEY"]
trading_client = TradingClient(api_key, secret_key, paper=True)


table_id = f"{project_id}.stock_data.companies"


def get_existing_tickers():
    query = f"SELECT DISTINCT ticker FROM `{table_id}`"
    result = bq_client.query(query).result()
    return {row.ticker for row in result}


existing_tickers = get_existing_tickers()
print(f"Already in BigQuery: {existing_tickers}")

tickers_to_fetch = [t for t in ticker_to_cik if t not in existing_tickers]

if not tickers_to_fetch:
    print("No new companies to add -- all tickers already in BigQuery.")
else:
    print(f"New tickers to fetch: {tickers_to_fetch}")

    rows_to_insert = []
    for ticker in tickers_to_fetch:
        cik = ticker_to_cik[ticker]
        print(f"Fetching {ticker}...")

        asset = trading_client.get_asset(ticker)
        company_info = get_company_info(cik)
        earliest_filing = get_earliest_filing_date(cik)

        rows_to_insert.append({
            "ticker": ticker,
            "company_name": asset.name,
            "cik": cik,
            "sic_code": company_info["sic_code"],
            "sic_description": company_info["sic_description"],
            "state_of_incorporation": company_info["state_of_incorporation"],
            "earliest_filing_date": earliest_filing,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        })

    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
    load_job = bq_client.load_table_from_json(rows_to_insert, table_id, job_config=job_config)
    load_job.result()
    print(f"\nSuccessfully added {len(rows_to_insert)} new companies.")