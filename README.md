# Stock Price Tracker

A Streamlit app for exploring historical stock prices and company fundamentals
for a curated list of large-cap tickers. Price data comes from
[Alpaca](https://alpaca.markets/) and fundamentals come from the
[SEC EDGAR](https://www.sec.gov/edgar) XBRL API.

-----------------------------------------------------------------------
-----------------------------------------------------------------------

## Features

- **Price chart** — interactive daily close-price chart (via Altair) for a
  chosen stock, filterable to All time / L3Y / L1Y / L30D.
- **Key stats** — max, min, and average price over the selected date range.
- **Company info** — industry (SIC code/description) and state of
  incorporation, pulled from EDGAR.
- **Fundamentals by fiscal year** — revenue, net margin, gross margin,
  operating cash flow, leverage (liabilities/equity), and ROE, selectable by
  fiscal year end.
- **Raw financial statement** — every reported `us-gaap` line item for the
  selected fiscal year, plus a link to the company's filings on SEC EDGAR.

Tracked tickers: `AAPL`, `MSFT`, `GOOGL`, `AMZN`, `META`, `NVDA`, `TSLA`,
`JPM`, `V`, `NFLX`.

-----------------------------------------------------------------------
-----------------------------------------------------------------------

## Setup

1. **Clone the repo and install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

2. **Get Alpaca API credentials**

   Sign up for a free [Alpaca](https://alpaca.markets/) account and generate
   an API key/secret (paper trading credentials work fine — this app only
   reads market data and asset info).

3. **Configure environment variables**

   Create a `.env` file in the project root:

   ```
   ALPACA_API_KEY=your_api_key_here
   ALPACA_SECRET_KEY=your_secret_key_here
   ```
-----------------------------------------------------------------------
-----------------------------------------------------------------------

## Usage

```bash
streamlit run app.py
```

This opens the app in your browser (default: http://localhost:8501).

-----------------------------------------------------------------------
-----------------------------------------------------------------------

## Project structure

| File               | Purpose                                                              |
|--------------------|-----------------------------------------------------------------------|
| `app.py`           | Streamlit UI — fetches price bars from Alpaca and renders the app.   |
| `edgar_data.py`    | Helpers for pulling fundamentals, company info, and raw statements from SEC EDGAR's XBRL API. |
| `requirements.txt` | Python dependencies.                                                 |

-----------------------------------------------------------------------
-----------------------------------------------------------------------

## Notes

- Alpaca's free/IEX data feed generally provides ~7+ years of daily history,
  so "All time" is bounded by that rather than a company's full trading
  history.
- EDGAR requests require a descriptive `User-Agent` header (already set in
  `edgar_data.py`) per SEC's API usage guidelines.
- Ticker → CIK mappings are hardcoded in `app.py` for the tracked list above;
  add new tickers by extending `symbols` and `ticker_to_cik`.

-----------------------------------------------------------------------
-----------------------------------------------------------------------
## Data Sources

### US — currently implemented, €0/month

- **Prices (OHLCV):** [Alpaca](https://alpaca.markets/) free tier (IEX feed). Commercial use OK for compute/derived output — confirm in writing before charging users.
- **Fundamentals** (margins, ROE, cash flow, leverage): [SEC EDGAR](https://www.sec.gov/edgar) `companyfacts` API. Public domain.
- **Sector/industry:** EDGAR SIC codes. Public domain.
- **IPO age:** EDGAR earliest filing date (proxy — not exact for pre-EDGAR-era companies like AAPL/MSFT).
- **Company names:** Alpaca `/assets` endpoint.

Showing only computed scores (not raw price redistribution) keeps this in the cheapest license tier.

### EU — not yet built, here's the plan

- **Prices:** no free option is commercially licensed. Cheapest paid route: **Marketstack** (~$10/mo). Alternatives: Twelve Data business (~$29–99/mo), EODHD (pricier).
- **Fundamentals:** free via **filings.xbrl.org** (interim ESEF aggregator) — but annual-only and patchy coverage. **ESAP**, the EU's EDGAR equivalent, launches ~2027 and will close this gap for free.
- **Sector/industry:** free via NACE codes (national registries, e.g. France's INSEE) — more manual work than EDGAR's single API.
- **IPO age:** free via Wikidata, large/mid caps only.
- **Insider activity:** no free unified source exists (per-country regulators only) — deferred.
- **Macro:** already solved — ECB + Eurostat, free, no gap.

**Bottom line:** EU needs one paid line item (prices, ~$10–30/mo) plus weaker fundamentals until ESAP arrives. Planned for a funded v2.

-----------------------------------------------------------------------
-----------------------------------------------------------------------