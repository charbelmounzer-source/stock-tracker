# Stock Price Tracker

A Streamlit app for exploring historical stock prices and company fundamentals
for a curated list of large-cap tickers. Data is sourced from
[Alpaca](https://alpaca.markets/) (prices, company names) and
[SEC EDGAR](https://www.sec.gov/edgar) (fundamentals, company info), ingested
into **Google BigQuery**, and served to the app from there.

## Architecture

```
Alpaca / SEC EDGAR  --(ingestion/*.py)-->  BigQuery  --(bq_client.py)-->  app.py (Streamlit)
```

- The **ingestion scripts** (`ingestion/`) pull data from Alpaca and EDGAR and
  load it into BigQuery tables, incrementally (only new dates/tickers/fiscal
  years each run).
- **`app.py`** never calls Alpaca or EDGAR directly for prices/fundamentals —
  it queries BigQuery (with `st.cache_data` caching) and renders the UI.
- **`edgar_data.py`** is shared: the ingestion scripts use it to fetch
  fundamentals/company info, and `app.py` still uses it directly for the raw
  "full financial statement" expander.

## Features

- **Price chart** — interactive daily close-price chart (via Altair) for a
  chosen stock, filterable to All time / L3Y / L1Y / L30D.
- **Key stats** — max, min, and average price over the selected date range.
- **Company info** — industry (SIC code/description) and state of
  incorporation.
- **Fundamentals by fiscal year** — revenue, net margin, gross margin,
  operating cash flow, leverage (liabilities/equity), and ROE, selectable by
  fiscal year end.
- **Raw financial statement** — every reported `us-gaap` line item for the
  selected fiscal year (fetched live from EDGAR), plus a link to the
  company's filings on SEC EDGAR.

Tracked tickers: `AAPL`, `MSFT`, `GOOGL`, `AMZN`, `META`, `NVDA`, `TSLA`,
`JPM`, `V`, `NFLX`.

## Setup

1. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

2. **Get Alpaca API credentials**

   Sign up for a free [Alpaca](https://alpaca.markets/) account and generate
   an API key/secret (paper trading credentials work fine — this app only
   reads market data and asset info).

3. **Set up a Google Cloud project + credentials**

   - Create (or reuse) a GCP project with the BigQuery API enabled.
   - Create a service account with BigQuery read/write access and download
     its JSON key.

4. **Configure environment variables**

   Create a `.env` file in the project root:

   ```
   ALPACA_API_KEY=your_api_key_here
   ALPACA_SECRET_KEY=your_secret_key_here
   GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json
   GCP_PROJECT_ID=your_gcp_project_id
   ```

5. **Create the BigQuery dataset and tables**

   ```bash
   python setup_bigquery.py
   ```

   This creates the `stock_data` dataset and its `companies`,
   `daily_prices`, and `fundamentals` tables (safe to re-run — uses
   `exists_ok=True`).

6. **Populate the tables**

   Run the ingestion scripts (each is incremental, so re-running is safe and
   only fetches what's missing):

   ```bash
   python ingestion/populate_companies.py
   python ingestion/populate_daily_prices.py
   python ingestion/populate_fundamentals.py
   ```

## Usage

```bash
streamlit run app.py
```

This opens the app in your browser (default: http://localhost:8501).

To refresh the data (e.g. pick up new trading days or a new fiscal year
filing), re-run the ingestion scripts from step 6 above — the app's
`st.cache_data(ttl=3600)` caches will pick up changes within an hour, or
immediately on app restart.

## Project structure

| File / folder                          | Purpose                                                                 |
|-----------------------------------------|--------------------------------------------------------------------------|
| `app.py`                                | Streamlit UI — queries BigQuery for prices/fundamentals/company info and renders the app. |
| `bq_client.py`                          | Shared BigQuery client + project ID, built from env vars.               |
| `setup_bigquery.py`                     | One-time (idempotent) creation of the `stock_data` dataset and tables.  |
| `edgar_data.py`                         | Helpers for pulling fundamentals, company info, and raw statements from SEC EDGAR's XBRL API. |
| `ingestion/populate_companies.py`       | Loads company name/CIK/industry/incorporation data into BigQuery.       |
| `ingestion/populate_daily_prices.py`    | Loads daily close prices from Alpaca into BigQuery, incrementally.      |
| `ingestion/populate_fundamentals.py`    | Loads per-fiscal-year fundamentals from EDGAR into BigQuery, incrementally. |
| `requirements.txt`                      | Python dependencies.                                                    |

## Code walkthrough & design decisions

### `bq_client.py`

```python
project_id = os.environ["GCP_PROJECT_ID"]
bq_client = bigquery.Client(project=project_id)
```

A tiny module whose only job is to build one `bigquery.Client` and expose it
alongside `project_id`, so every other file (`app.py`, the three `ingestion/`
scripts) imports the same client instead of constructing its own. This keeps
credential/project wiring in one place — `bigquery.Client()` picks up
`GOOGLE_APPLICATION_CREDENTIALS` automatically, so nothing else needs to
touch auth.

### `setup_bigquery.py`

Creates the `stock_data` dataset and its three tables (`companies`,
`daily_prices`, `fundamentals`) with explicit schemas. Every
`create_dataset`/`create_table` call passes **`exists_ok=True`**, which is
the key choice here: it means the script is idempotent — you can run it
once during setup, or accidentally run it again later, without it erroring
out on "already exists" or wiping data. It's a setup script, not something
the app or ingestion scripts depend on at runtime.

### `edgar_data.py`

The original data-access layer for SEC EDGAR, still used two ways: directly
by `app.py` (for the raw "full financial statement" expander, which is
fetched live rather than cached in BigQuery), and by the `ingestion/`
scripts (to populate BigQuery).

- **`headers = {"User-Agent": "..."}`** — SEC EDGAR rejects/blocks requests
  without a descriptive `User-Agent`; this is a hard requirement of their
  API, not a style choice.
- **`get_annual_metric(facts, tag_candidates)`** — the trickiest bit.
  Companies don't consistently use the same XBRL tag for the same concept
  across years (e.g. revenue might be reported as
  `RevenueFromContractWithCustomerExcludingAssessedTax` in recent filings
  but `Revenues` in older ones). Instead of taking "the first tag that
  works," it **merges every candidate tag** and, for periods reported under
  more than one tag, keeps whichever entry has the latest `filed` date. This
  avoids silently dropping years just because a company switched tags.
- Similarly, **`get_full_statement`** and `get_annual_metric` both dedupe by
  taking `max(entries, key=lambda e: e["filed"])` — a company can restate a
  prior fiscal year in a later filing (e.g. a 10-K/A amendment), and EDGAR's
  API returns all of them. Taking the latest-filed value ensures the app
  shows restated/corrected figures rather than the original ones.
- **Gross margin fallback**: if a company doesn't report `GrossProfit`
  directly, it's computed as `revenue - cost_of_revenue` instead of showing
  "N/A" — trades a small amount of derived-data risk for fewer blank
  fields.

### `ingestion/populate_companies.py`, `populate_daily_prices.py`, `populate_fundamentals.py`

All three follow the same pattern, which is the main architectural decision
in this project: **query BigQuery first for what's already stored, then
only fetch/insert what's missing**, rather than re-fetching everything on
every run. Specifically:

- `populate_companies.py` checks `SELECT DISTINCT ticker` and skips tickers
  already present.
- `populate_daily_prices.py` checks `MAX(price_date)` per ticker and only
  requests bars after that date (or the full 2016+ history for a brand-new
  ticker).
- `populate_fundamentals.py` checks which `period_end` values already exist
  per ticker and only inserts new fiscal years.

Why: both Alpaca and EDGAR are rate-limited, and re-pulling years of daily
bars or full XBRL fact sets on every run would be slow and wasteful. This
also makes the scripts **safe to schedule** (e.g. a daily cron job) — each
run is cheap and a no-op once caught up, so there's no need for separate
"initial backfill" vs. "incremental update" scripts.

All three use `write_disposition="WRITE_APPEND"` — BigQuery tables here are
treated as append-only logs guarded by the existence checks above, rather
than using `MERGE`/upsert, since the checks already prevent duplicate rows
and append jobs are simpler and cheaper than merge queries.

### `app.py`

The Streamlit UI. The key change from the original (pre-BigQuery) version:
`app.py` used to call Alpaca and EDGAR **directly on every page load** —
meaning every user interaction (or Streamlit re-run) re-triggered live API
calls for 10 tickers' worth of price history and financial statements. Two
issues with that: it was slow (EDGAR in particular is not fast for full
`companyfacts` payloads), and it risked hitting rate limits with more than
one user.

The fix was to move the actual API calls into the `ingestion/` scripts
(run separately, on a schedule) and have `app.py` only read pre-loaded data
back out of BigQuery:

```python
@st.cache_data(ttl=3600)
def load_prices():
    ...
```

- **`st.cache_data(ttl=3600)`** on each `load_*()` function caches the
  BigQuery query result for an hour, so multiple users / re-runs within
  that window don't re-issue the same query. This is a second layer of
  caching on top of the ingestion scripts' incremental writes — one
  controls *how often data is fetched from the source*, the other controls
  *how often the app re-queries the warehouse*.
- Filtering by date range (`L30D`/`L1Y`/`L3Y`/`All time`) happens **in
  pandas after loading**, not as separate SQL queries — since `load_prices()`
  pulls the full history for all tickers in one cached query, slicing a
  `pd.Series` by index is cheap and avoids re-querying BigQuery every time
  the user changes the radio button.
- The raw "full financial statement" expander (`get_full_statement`) is the
  one place `app.py` still calls EDGAR directly instead of BigQuery — it
  returns every reported `us-gaap` line item (not just the curated 6-7
  metrics), which wasn't worth modeling as a BigQuery table since it's only
  viewed on demand, per company, per year.

## Notes

- Alpaca's free/IEX data feed generally provides ~7+ years of daily history,
  so "All time" is bounded by that rather than a company's full trading
  history.
- EDGAR requests require a descriptive `User-Agent` header (already set in
  `edgar_data.py`) per SEC's API usage guidelines.
- Ticker → CIK mappings are hardcoded (duplicated across `app.py` and the
  `ingestion/` scripts) for the tracked list above; add new tickers by
  extending `symbols`/`ticker_to_cik` in each file and re-running the
  ingestion scripts.
- BigQuery tables are append-only from the ingestion scripts' perspective —
  they check for existing tickers/dates/periods before inserting, so
  duplicate runs are safe.

## Data sources

### US — currently implemented, €0/month

- **Prices (OHLCV):** [Alpaca](https://alpaca.markets/) free tier (IEX feed).
  Commercial use OK for compute/derived output — confirm in writing before
  charging users.
- **Fundamentals** (margins, ROE, cash flow, leverage): [SEC EDGAR](https://www.sec.gov/edgar)
  `companyfacts` API. Public domain.
- **Sector/industry:** EDGAR SIC codes. Public domain.
- **IPO age:** EDGAR earliest filing date (proxy — not exact for
  pre-EDGAR-era companies like AAPL/MSFT).
- **Company names:** Alpaca `/assets` endpoint.

Showing only computed scores (not raw price redistribution) keeps this in
the cheapest license tier.

### EU — not yet built, here's the plan

- **Prices:** no free option is commercially licensed. Cheapest paid route:
  **Marketstack** (~$10/mo). Alternatives: Twelve Data business
  (~$29–99/mo), EODHD (pricier).
- **Fundamentals:** free via **filings.xbrl.org** (interim ESEF aggregator)
  — but annual-only and patchy coverage. **ESAP**, the EU's EDGAR
  equivalent, launches ~2027 and will close this gap for free.
- **Sector/industry:** free via NACE codes (national registries, e.g.
  France's INSEE) — more manual work than EDGAR's single API.
- **IPO age:** free via Wikidata, large/mid caps only.
- **Insider activity:** no free unified source exists (per-country
  regulators only) — deferred.
- **Macro:** already solved — ECB + Eurostat, free, no gap.

**Bottom line:** EU needs one paid line item (prices, ~$10–30/mo) plus
weaker fundamentals until ESAP arrives. Planned for a funded v2.
