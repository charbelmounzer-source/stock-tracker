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
