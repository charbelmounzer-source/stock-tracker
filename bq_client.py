import os
import streamlit as st
from dotenv import load_dotenv
from google.cloud import bigquery
from google.oauth2 import service_account

load_dotenv()

if "gcp_service_account" in st.secrets:
    # Running on Streamlit Cloud -- use secrets
    credentials = service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"]
    )
    project_id = st.secrets["gcp_service_account"]["project_id"]
    bq_client = bigquery.Client(project=project_id, credentials=credentials)
else:
    # Running locally -- use the .env file path
    project_id = os.environ["GCP_PROJECT_ID"]
    bq_client = bigquery.Client(project=project_id)