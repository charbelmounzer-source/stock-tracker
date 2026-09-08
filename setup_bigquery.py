import os
from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()

project_id = os.environ["GCP_PROJECT_ID"]
client = bigquery.Client(project=project_id)

dataset_id = f"{project_id}.stock_data"

# Step 1: Create the dataset (like a "schema" or "folder" that holds tables)
dataset = bigquery.Dataset(dataset_id)
dataset.location = "US"  # matches Alpaca's US-listed stocks
client.create_dataset(dataset, exists_ok=True)
print(f"Dataset ready: {dataset_id}")

# Step 2: Define and create the "companies" table
companies_schema = [
    bigquery.SchemaField("ticker", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("company_name", "STRING"),
    bigquery.SchemaField("cik", "STRING"),
    bigquery.SchemaField("sic_code", "STRING"),
    bigquery.SchemaField("sic_description", "STRING"),
    bigquery.SchemaField("state_of_incorporation", "STRING"),
    bigquery.SchemaField("earliest_filing_date", "DATE"),
    bigquery.SchemaField("last_updated", "TIMESTAMP"),
]
companies_table = bigquery.Table(f"{dataset_id}.companies", schema=companies_schema)
client.create_table(companies_table, exists_ok=True)
print("Table ready: companies")

# Step 3: Define and create the "daily_prices" table
prices_schema = [
    bigquery.SchemaField("ticker", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("price_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("close", "FLOAT"),
    bigquery.SchemaField("last_updated", "TIMESTAMP"),
]
prices_table = bigquery.Table(f"{dataset_id}.daily_prices", schema=prices_schema)
client.create_table(prices_table, exists_ok=True)
print("Table ready: daily_prices")

# Step 4: Define and create the "fundamentals" table
fundamentals_schema = [
    bigquery.SchemaField("ticker", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("period_end", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("revenue", "FLOAT"),
    bigquery.SchemaField("net_margin", "FLOAT"),
    bigquery.SchemaField("gross_margin", "FLOAT"),
    bigquery.SchemaField("operating_cash_flow", "FLOAT"),
    bigquery.SchemaField("leverage", "FLOAT"),
    bigquery.SchemaField("roe", "FLOAT"),
    bigquery.SchemaField("last_updated", "TIMESTAMP"),
]
fundamentals_table = bigquery.Table(f"{dataset_id}.fundamentals", schema=fundamentals_schema)
client.create_table(fundamentals_table, exists_ok=True)
print("Table ready: fundamentals")

print("\nAll tables set up successfully.")