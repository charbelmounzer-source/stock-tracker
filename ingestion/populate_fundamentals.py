import sys
import os
from datetime import datetime, timezone
from google.cloud import bigquery  # <-- add this back

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from bq_client import bq_client, project_id
from edgar_data import get_fundamentals_all_periods

ticker_to_cik = {
    'NVDA': '0001045810', 'AAPL': '0000320193', 'GOOGL': '0001652044',
    'MSFT': '0000789019', 'AMZN': '0001018724', 'META': '0001326801',
    'TSLA': '0001318605', 'JPM': '0000019617', 'V': '0001403161',
    'NFLX': '0001065280'
}

table_id = f"{project_id}.stock_data.fundamentals"


def get_existing_periods(ticker):
    """Returns the set of period_end dates already stored for this ticker."""
    query = f"""
        SELECT period_end
        FROM `{table_id}`
        WHERE ticker = @ticker
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("ticker", "STRING", ticker)]
    )
    result = bq_client.query(query, job_config=job_config).result()
    return {row.period_end.isoformat() for row in result}


rows_to_insert = []

for ticker, cik in ticker_to_cik.items():
    existing_periods = get_existing_periods(ticker)
    all_periods = get_fundamentals_all_periods(ticker, cik)

    new_periods = {p: m for p, m in all_periods.items() if p not in existing_periods}

    if not new_periods:
        print(f"{ticker}: no new fiscal years, skipping.")
        continue

    print(f"{ticker}: adding {len(new_periods)} new fiscal year(s): {list(new_periods.keys())}")

    for period_end, metrics in new_periods.items():
        rows_to_insert.append({
            "ticker": ticker,
            "period_end": period_end,
            "revenue": metrics["revenue"],
            "net_margin": metrics["net_margin"],
            "gross_margin": metrics["gross_margin"],
            "operating_cash_flow": metrics["operating_cash_flow"],
            "leverage": metrics["leverage"],
            "roe": metrics["roe"],
            "shares_outstanding": metrics["shares_outstanding"],
            "cash": metrics["cash"],
            "total_debt": metrics["total_debt"],
            "ebitda": metrics["ebitda"],
            "total_equity": metrics["total_equity"],
            "last_updated": datetime.now(timezone.utc).isoformat(),
        })

if rows_to_insert:
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
    load_job = bq_client.load_table_from_json(rows_to_insert, table_id, job_config=job_config)
    load_job.result()
    print(f"\nSuccessfully added {len(rows_to_insert)} new fundamentals rows.")
else:
    print("\nNo new rows to add -- everything already up to date.")