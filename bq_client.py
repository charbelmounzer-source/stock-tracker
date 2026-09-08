import os
from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()

project_id = os.environ["GCP_PROJECT_ID"]
bq_client = bigquery.Client(project=project_id)