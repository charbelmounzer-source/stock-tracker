# Stock tracker — data foundation

The data layer for a beginner-friendly stock app: for each US stock, the prices, financials,
company events, insider trades, news and macro context a "stock card" needs. Everything here
comes from **free** sources. The product UI is not built yet; the Streamlit app in this repo
is an internal viewer for checking the data.

> **Status: the code has never run against the live APIs.** It was written and tested (57
> tests) against synthetic data shaped like the real payloads, because the build environment
> had no credentials and no access to the SEC or Alpaca. Expect the first real run to surface
> things to fix. [First real run](#first-real-run) lists what to check.

## How it works

```
SEC EDGAR ─┐                      ┌─ companies, filings, insider_trades
Alpaca ────┼─ python -m pipeline ─┼─ prices, corporate_actions, news        ─ BigQuery ─ Streamlit viewer
FRED ──────┘                      ├─ xbrl_facts, xbrl_tags, macro
                                  └─ fundamentals, stock_snapshot (derived)
```

One command rebuilds every table from scratch. There is no incremental logic.

| Table | One row per | Source |
|---|---|---|
| `companies` | stock | EDGAR + `universe.csv` |
| `prices` | stock per trading day (since 2016) | Alpaca |
| `corporate_actions` | split or dividend | Alpaca |
| `xbrl_facts` | number a company ever reported in a 10-K/10-Q | EDGAR |
| `xbrl_tags` | accounting tag, with its official definition | EDGAR |
| `fundamentals` | stock per period (quarter, fiscal year, trailing 12 months) | derived from `xbrl_facts` |
| `filings` | filing in the last 3 years (8-K events in plain English) | EDGAR |
| `insider_trades` | insider transaction in the last 180 days | EDGAR Form 4 |
| `news` | article per stock, last 90 days | Alpaca (Benzinga) |
| `macro` | macro series per date (rates, inflation, oil, ...) | FRED |
| `stock_snapshot` | stock: price, performance, valuation, growth, health | derived |

`stock_snapshot` is the table the future app reads for a card. Every column of every table is
described in [`pipeline/schemas.py`](pipeline/schemas.py); those descriptions are also written
to BigQuery as column descriptions and shown as tooltips in the viewer.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env        # then fill it in
python -m pytest -q         # 57 tests, no network or credentials needed
```

Keys needed (all free): an [Alpaca](https://alpaca.markets/) account (paper keys are enough), a
[FRED API key](https://fred.stlouisfed.org/docs/api/api_key.html), and for the SEC just your
name and email in `SEC_USER_AGENT` (the SEC blocks anonymous clients).

## First real run

Do this in order; each step is cheap to repeat.

```bash
# 1. Two stocks, written to CSV files. Touches nothing in BigQuery.
python -m pipeline --local out --tickers AAPL,JPM

# 2. Look at it in the viewer, without BigQuery.
LOCAL_DATA_DIR=out streamlit run app.py

# 3. Everything, still local. My estimate is 10-20 minutes, mostly news and Form 4s.
python -m pipeline --local out

# 4. Load BigQuery. Writes to the dataset `stock_data_v2`; the old `stock_data` is untouched.
python -m pipeline
streamlit run app.py
```

Other options: `--only prices,macro` runs selected steps (`companies`, `actions`, `prices`,
`facts`, `insiders`, `news`, `macro`, `fundamentals`, `snapshot`). A failed step is reported in
the summary, leaves its table as it was, and makes the command exit with code 1; the other
steps still run.

What to check on the first run, because it could not be tested here:

- **Alpaca corporate actions from 2009.** The request asks for splits back to 2009. If Alpaca
  rejects or truncates that range, old per-share history will not be split-adjusted (the
  viewer's "EPS up more than 5x" check will show it).
- **Alpaca news on the free plan.** Believed to be included; if the step fails with 403 it is
  not, and the rest still works.
- **Form 4 parsing.** Written from the form's published structure, not checked against live
  filings.
- **AAPL sanity check.** Compare revenue, net income, EPS and market cap in the viewer with
  any finance site. Then open the Data quality page and go through every warning.
- **Multi-class and unusual companies** (GOOGL, META, V, BRK.B): see the caveats below.

## Scheduled refresh

`.github/workflows/nightly.yml` runs the pipeline at 07:17 UTC, Tuesday to Saturday, once the
repository secrets listed in that file are set. Scheduled workflows only run from the default
branch. `.github/workflows/tests.yml` runs the tests on every push.

## Adding a stock

Add a line to `universe.csv` (`ticker,sector`) and run the pipeline. The CIK, name and
industry are looked up from the SEC. Sectors are our own labels, chosen to be readable; SEC
industry codes are kept alongside but are too dated to show a beginner (Apple is "Electronic
Computers").

## Design choices

**Full rebuild instead of incremental loads.** Every run replaces every table. That removes
the "what do we already have" queries, makes re-running after a failure always safe, cannot
create duplicates, and picks up restated numbers automatically. It also fits split-adjusted
prices, whose whole history changes after each split. At 49 stocks the cost is a few minutes;
it stays reasonable into the hundreds of stocks. Only load jobs are used, which are free and
work in the BigQuery sandbox.

**Raw facts first, clean numbers derived.** `xbrl_facts` stores everything companies reported,
untouched. `fundamentals` is computed from it. A wrong tag mapping is then a code fix and a
re-run, never a data-recovery problem, and any number can be traced back: `tag_sources` on each
`fundamentals` row says which tag fed each column (`*` marks a value obtained by subtraction).

**Derived tables are computed in Python, not SQL views.** The quarter and trailing-12-month
logic is the riskiest code here, and Python is what could be covered by tests without a
BigQuery project. Porting the ratio layer to views later is straightforward.

**No SDKs.** Three REST endpoints at Alpaca and one at FRED did not justify the dependencies.
One small HTTP client handles rate limiting, retries and timeouts for all three sources.

**Schema in code.** `pipeline/schemas.py` is the single definition of every table. A DataFrame
with an unexpected column is rejected before loading rather than silently altered.

**A separate dataset.** The pipeline writes to `stock_data_v2` so the previous tables and the
deployed app keep working until this is validated.

## How `fundamentals` is built

Reported financial data has five traps. Each is handled explicitly and covered by tests in
`tests/test_fundamentals.py`:

1. **Same idea, different tags.** Each concept has an ordered list of candidate tags
   (`CONCEPTS` in `pipeline/fundamentals.py`); per period, the first tag with a value wins.
2. **Restatements.** For one tag and period, the most recently filed value wins.
   `reported_date` keeps the date the period was first filed.
3. **Year-to-date reporting and the missing Q4.** 10-Qs report many items cumulatively and no
   10-Q exists for the fourth quarter. A quarter is obtained by subtracting two cumulative
   figures with the same start date (full year minus nine months gives Q4).
4. **EDGAR's `fy`/`fp` fields describe the filing, not the number.** A 10-K repeats prior
   years under the new filing's label. Periods are identified by their dates only.
5. **Stock splits.** Share counts and per-share amounts filed before a split are rescaled
   using the split calendar; later filings already restate them.

Trailing-12-month (TTM) values are the sum of the last four quarters. Market cap uses the
latest diluted weighted-average share count: it covers every share class and matches the EPS
denominator, at the cost of being an average over a quarter rather than today's exact count.

## Caveats

**Data**

- **Prices start in 2016** (Alpaca's limit) and are end-of-day. `close` is split-adjusted;
  `close_total_return` also includes dividends.
- **Structured data only from 2009 onwards**, when XBRL reporting began.
- **Multi-class companies may come out incomplete.** EDGAR's facts API drops numbers reported
  per share class. If a company reports EPS or share counts only that way, EPS falls back to
  net income / shares, and if shares are missing too, market cap and every valuation ratio are
  empty. The Data quality page lists these.
- **BRK.B** is handled with a hard-coded 1,500 multiplier (`SHARE_CLASS_MULTIPLIER`), because
  Berkshire reports in Class A equivalents. The `fundamentals` table keeps the as-reported
  figures; only `stock_snapshot` applies the multiplier.
- **Banks, brokers and insurers** (SIC 6000-6499) have gross margin, EBITDA, debt, enterprise
  value and cash-flow metrics left empty in `stock_snapshot`: they do not mean the same thing
  there. Visa is not in that range and is treated as a normal company.
- **`total_debt` is best effort.** Debt tagging varies a lot between companies. A company with
  no long-term debt tags gets an empty `total_debt`, and so an empty enterprise value.
- **Q4 EPS is full-year EPS minus nine-month EPS**, the usual approximation; it is not exact
  when the share count moved during the year.
- **Ratios are left empty rather than misleading**: P/E on negative earnings, price-to-book
  and ROE on negative equity, growth rates from a zero or negative base.
- **Tag mapping is a judgement call.** `revenue` prefers `RevenuesNetOfInterestExpense`, then
  `Revenues`, then the contract-revenue tags. This has not been checked company by company.
- **8-K event labels** come from item numbers. Item 8.01 ("Other material event") says little.
- **Insider trades** cover common-stock transactions only, not option grants.
- **News is a 90-day window, filings 3 years, insider trades 180 days.** Older rows drop out on
  each rebuild. Change the windows in `pipeline/config.py`.
- **Today's price bar is never loaded** (it may be incomplete); a run after midnight New York
  time picks it up.

**Licensing (not legal advice; check before charging users)**

- **SEC EDGAR**: public domain.
- **Alpaca prices and news**: free to use for yourself. Showing them to other people in a
  product is a different question; get Alpaca's answer in writing. The news is Benzinga's.
- **FRED**: free; check its API terms for the attribution notice, and a few series (VIX, for
  example) belong to third parties.

## Not covered yet

Free, not built:

- Institutional holdings (13F filings) and short interest (FINRA).
- The text of filings and earnings releases (risk factors, guidance), useful for summaries.
- Sentiment: no free source worth relying on. The plan is to score the `news` headlines with a
  language model.
- More stocks. The pipeline is not tied to these 49.

Needs a paid source:

- Analyst estimates, price targets and upcoming earnings dates.
- Real-time or intraday prices for all exchanges, and price history before 2016.
- Clean sector and industry classification (GICS).
- Social sentiment (Reddit, X, StockTwits) at any useful scale.
- EU stocks: no free, commercially usable price source. Fundamentals are partly free through
  filings.xbrl.org (annual only).

## Removed from the previous version

- `ai_analysis.py`. It asked a model for a Buy / Sell / Hold call on thin data, which is risky
  to show beginners, and it crashed the app when its key was missing. It should come back as
  an explanation of the numbers, built on `stock_snapshot`.
- The append-only ingestion scripts, the hard-coded ticker-to-CIK table, the `alpaca-py`
  dependency, and the live EDGAR call inside the app.
- The IEX price feed, replaced by the full-market feed, which the free plan also provides for
  anything older than 15 minutes.

## Repository layout

```
universe.csv            the stocks tracked, with our sector labels
pipeline/
  __main__.py           the runner: steps, order, failure handling
  config.py             every setting and lookup table
  schemas.py            data dictionary + validation
  net.py                HTTP client (rate limit, retries)
  edgar.py              SEC: companies, filings, raw facts, Form 4
  alpaca.py             prices, splits/dividends, news
  fred.py               macro series
  fundamentals.py       raw facts -> quarters / years / TTM
  snapshot.py           price statistics and the one-row-per-stock table
  bq.py                 BigQuery and local-CSV writers
app.py, app_data.py, pages/   the internal viewer
tests/                  synthetic-data tests, including a full end-to-end run
```
