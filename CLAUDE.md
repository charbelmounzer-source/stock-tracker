# Stock tracker: context for Claude

Read `README.md` first: it has the architecture, design choices, caveats and the
"Known problems" table. This file adds what the README does not say.

## The product

A scrollable, beginner-friendly stock app (not for seasoned investors): per stock, the main
KPIs, news, sentiment, what could move the price, and a plain-language summary. The owner is
building the data foundation first and the UI later. US stocks first; EU later (not free).
Only free data sources for now; paid ones are to be evaluated later.

## State (11 Nov 2026)

- `python -m pipeline` works end to end on the real APIs for the 49 stocks in `universe.csv`.
- BigQuery dataset `stock_data_v2` is loaded. The GitHub workflow "Nightly data refresh"
  rebuilds it Tue-Sat at 07:17 UTC. The Streamlit Cloud app (internal viewer) reads it.
- The BigQuery project is still a sandbox (tables expire after 60 days). The owner was
  advised to add billing and remove the dataset's default table expiration.
- Checked against published figures: AAPL and JPM only. The other stocks were checked for
  plausibility, not against a second source.

## Next steps, in order

1. **NEE, DUK, PLD: fixed 13 Nov 2026** via `CO_REGISTRANT_CIKS` (see README). Confirm on
   the next nightly run; NEE's Q3 2026 net income ($4.8B, about twice last year's) is worth a
   look against NextEra's press release.
2. **Re-run and re-check** the tag additions made after the second run (ORCL, CAT, COP, NKE,
   GE, VZ, T debt / EBITDA / free cash flow). AT&T's empty free cash flow is unexplained.
3. **BRK.B** has no market cap: needs the cover-page share count from the filing itself.
4. **Scale to 150-200 stocks**: batch Alpaca requests (about 100 tickers per call) and derive
   sectors instead of hand-labelling. 1,000 stocks needs incremental loads for xbrl_facts,
   insider_trades and news, and billing enabled.
5. Later: sentiment from news headlines, an explanation layer on `stock_snapshot` (no
   Buy/Sell/Hold calls), then the real UI.

## Working with the owner

- Windows, Git Bash in VS Code. Python is `py` (`py -m pipeline ...`, `py -m streamlit run app.py`).
- His local `.env` has the keys; `LOCAL_DATA_DIR=out` makes the app read a local run.
- He cannot easily share large files. Ask for `out/stock_snapshot.csv` and the output of
  `py -m pipeline.diagnose out` (`out/diagnosis.txt`); `fundamentals.csv` is too big for all 49.
- He prefers step-by-step work, honest feedback, and code that stays simple.
- Work on a branch and open a pull request; he merges on GitHub.

## Rules of the codebase

- Every table is fully rebuilt on each run (load jobs, WRITE_TRUNCATE). No incremental logic yet.
- `pipeline/schemas.py` is the data dictionary; a new column must be added there first.
- A missing number is better than a wrong one: leave metrics empty when the inputs are doubtful.
- Claude's cloud environment `stock-tracker` can reach the SEC (data.sec.gov, www.sec.gov;
  needs `SEC_USER_AGENT`) but not Alpaca, BigQuery or FRED. Logic needing those is tested on
  synthetic data (`tests/fakes.py`) and then validated by the owner's real run. Say so plainly.
- Run `python -m pytest -q` before every push.
