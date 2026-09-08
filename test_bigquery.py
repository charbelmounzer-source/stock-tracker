import os
from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()

project_id = os.environ["GCP_PROJECT_ID"]

client = bigquery.Client(project=project_id)

# Simple test query -- doesn't touch any of our data, just confirms the connection works
query = "SELECT 1 AS test_value"
results = client.query(query).result()

for row in results:
    print("Connection successful! Test value:", row.test_value)