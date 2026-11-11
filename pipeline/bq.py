"""Where tables are written: BigQuery, or a local folder of CSVs for a trial run.

Every table is fully replaced on every run (WRITE_TRUNCATE). No incremental logic, no
duplicates, restated numbers always land, and re-running after a failure is always safe.
Only load jobs are used (free, and allowed in the BigQuery sandbox, unlike DML).
"""
import io
from pathlib import Path

from . import config
from .schemas import TABLES, conform, to_ndjson

CHUNK_ROWS = 500_000  # keeps memory bounded for the large xbrl_facts table


def get_client():
    """BigQuery client from Streamlit secrets (deployed app) or the environment (local, CI)."""
    from google.cloud import bigquery
    try:
        import streamlit as st
        info = st.secrets["gcp_service_account"]
    except Exception:
        return bigquery.Client(project=config.env("GCP_PROJECT_ID"))
    from google.oauth2 import service_account
    return bigquery.Client(project=info["project_id"],
                           credentials=service_account.Credentials.from_service_account_info(dict(info)))


def table_id(client, table: str) -> str:
    return f"{client.project}.{config.BQ_DATASET}.{table}"


class BigQuerySink:
    def __init__(self):
        from google.cloud import bigquery
        self.bigquery = bigquery
        self.client = get_client()
        self.client.create_dataset(config.BQ_DATASET, exists_ok=True)

    def write(self, table: str, df) -> int:
        bq = self.bigquery
        df = conform(df, table)
        spec = TABLES[table]
        schema = [bq.SchemaField(name, kind, description=doc) for name, kind, doc in spec["columns"]]
        for start in range(0, len(df), CHUNK_ROWS):
            job_config = bq.LoadJobConfig(
                schema=schema,
                source_format=bq.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition="WRITE_TRUNCATE" if start == 0 else "WRITE_APPEND",
                clustering_fields=spec.get("cluster"),
            )
            payload = to_ndjson(df.iloc[start:start + CHUNK_ROWS], table).encode()
            self.client.load_table_from_file(io.BytesIO(payload), table_id(self.client, table),
                                             job_config=job_config).result()
        return len(df)


class LocalSink:
    """Writes <folder>/<table>.csv. For checking the output before touching BigQuery."""

    def __init__(self, folder: str):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)

    def write(self, table: str, df) -> int:
        conform(df, table).to_csv(self.folder / f"{table}.csv", index=False)
        return len(df)
