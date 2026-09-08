import os
from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()

def _try_get_streamlit_secrets():
    try:
        import streamlit as st
        if "gcp_service_account" in st.secrets:
            return st.secrets["gcp_service_account"]
    except Exception:
        pass
    return None

gcp_secrets = _try_get_streamlit_secrets()

if gcp_secrets:
    # Running on Streamlit Cloud -- use secrets
    from google.oauth2 import service_account
    credentials = service_account.Credentials.from_service_account_info(gcp_secrets)
    project_id = gcp_secrets["project_id"]
    bq_client = bigquery.Client(project=project_id, credentials=credentials)
else:
    # Running locally -- use the .env file path
    project_id = os.environ["GCP_PROJECT_ID"]
    bq_client = bigquery.Client(project=project_id)