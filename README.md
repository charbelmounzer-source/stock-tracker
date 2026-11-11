# Stock tracker — data foundation

The data layer for a beginner-friendly stock app: for each US stock, the prices, financials,
company events, insider trades, news and macro context a "stock card" needs. Everything here
comes from **free** sources. The product UI is not built yet; the Streamlit app in this repo
is an internal viewer for checking the data.

> **Status: usable for 45 of 49 stocks, with four known gaps.** Two full runs on 11 Nov 2026.
> Apple and JPMorgan were checked against published figures; the others were checked for
> plausibility only, not against a second source. NEE, DUK and PLD show results that stop in
> March 2026, and BRK.B has no market cap. [Known problems](#known-problems) has the detail.

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
python -m pytest -q         # 73 tests, no network or credentials needed
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

What to check when running all 49 stocks:

- **The run log.** The `fundamentals` step prints the splits it found in each company's
  filings. Compare a few with the company's real split history.
- **The Data quality page.** Go through every warning, in particular "Implausible snapshot
  values" and "Annual EPS up more than 5x or down more than 80%".
- **Multi-class and unusual companies** (GOOGL, META, V, BRK.B): see the caveats below.
- **A few stocks by hand.** Compare revenue, EPS, market cap and P/E with any finance site.
- **Form 4 parsing.** It runs, but individual trades have not been compared with the filings.

On Windows, use `py -m pipeline ...` and `py -m streamlit run app.py`.

## Known problems

From the first 49-stock run. "Fixed" means fixed in code and unit-tested, not yet re-run on real data.

| Stock | Problem | State |
|---|---|---|
| NEE, DUK, PLD | Results stop at March 2026 | Open. Their later 10-Qs exist, but EDGAR's facts API returns nothing from them under the company's CIK. All three file jointly with subsidiaries, so the facts may sit under a subsidiary's CIK: check with `python -m pipeline.diagnose probe <CIK>`, then add it to `PREDECESSOR_CIKS` |
| BRK.B | No usable share count since 2015 | Market cap and P/E left empty. A real fix needs the cover-page count from the filing itself |
| V | No share count or EPS in EDGAR's API (multi-class) | Approximated: shares = dividends paid / dividend per share (`shares_basis` says so). Gave a market cap of $807B |
| MCD | Share count filed in millions | Fixed and confirmed on real data |
| XOM | New SEC registrant since July 2026 | Fixed and confirmed: the previous registrant's history is merged |
| HON | Price showed the 2026 spin-off as a 42% loss | Fixed and confirmed: prices adjust for spin-offs |
| ORCL, CAT, COP, NKE, GE, VZ, T | Some of debt, EBITDA, operating margin or free cash flow empty | Tags added after the second run; not yet re-run. COP, NEE and PLD use company-specific capex tags that the API does not expose |
| 13 stocks | Gross margin empty | Expected: these companies do not report a cost of revenue (telecoms, utilities, restaurants, Visa, Exxon...) |

To see what a company filed for each empty metric, and so which tags to add:

```bash
python -m pipeline.diagnose out      # writes out/diagnosis.txt
```

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
5. **Stock splits.** Share counts and per-share amounts filed before a split are rescaled;
   later filings already restate them. Splits are found in the filings themselves: after a
   split, companies restate earlier share counts by a clean multiple, and the first filing
   on the new basis gives the cut-off date. This matters because Alpaca's split history only
   starts in 2016 (Apple's 2014 seven-for-one split is not in it). Alpaca's splits are added
   only for a split so recent that no report has restated anything yet.

Trailing-12-month (TTM) values are the sum of the last four quarters, except at a fiscal
year end, where they are the reported annual figures. Market cap uses shares outstanding at
the latest balance-sheet date when that figure agrees with the weighted-average share count,
and the weighted-average count otherwise (EDGAR's API omits or truncates the balance-sheet
figure for multi-class companies). `reported_date` is the first filing of a period under any
candidate tag, so it survives a company re-filing old years under a new tag.

## Caveats

**Data**

- **Split detection is a heuristic.** It needs at least two periods restated by the same
  clean ratio. A missed split shows up as a jump in the EPS check on the Data quality page.
- **Dividend yield is trailing**: regular dividends over the 350 days up to the latest payment.
  Finance sites often show the forward figure (latest payment x 4), which is slightly higher
  for a company that just raised its dividend. Alpaca's dividend history also starts in 2016.
- **Prices start in 2016** (Alpaca's limit) and are end-of-day. `close` is split-adjusted;
  `close_total_return` also includes dividends.
- **Structured data only from 2009 onwards**, when XBRL reporting began.
- **Multi-class companies may come out incomplete.** EDGAR's facts API drops numbers reported
  per share class. If a company reports EPS or share counts only that way, EPS falls back to
  net income / shares, and if shares are missing too, market cap and every valuation ratio are
  empty. The Data quality page lists these.
- **BRK.B** has no market cap or P/E: Berkshire has not reported a usable share count through
  EDGAR's API since 2015. The 1,500 multiplier (`SHARE_CLASS_MULTIPLIER`, Class A to Class B)
  is kept for when a count is available.
- **Prices are adjusted for spin-offs as well as splits**, so past prices of GE or Honeywell
  are lower than what traded at the time.
- **Fallbacks are approximations**: operating income as pre-tax income plus interest, equity
  including minorities, share count implied from dividends.
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
  diagnose.py           explains gaps in a local run
app.py, app_data.py, pages/   the internal viewer
tests/                  synthetic-data tests, including a full end-to-end run
```
