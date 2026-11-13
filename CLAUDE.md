# Stock tracker: context for Claude

Read `README.md` first: it has the architecture, design choices, caveats and the
"Known problems" table. This file adds what the README does not say.

## The product

A scrollable, beginner-friendly stock app (not for seasoned investors): per stock, the main
KPIs, news, sentiment, what could move the price, and a plain-language summary. The owner is
building the data foundation first and the UI later. US stocks first; EU later (not free).
Only free data sources for now; paid ones are to be evaluated later.

## State (11 Nov 2026)

- `python -m pipeline` works end to end on the real APIs for the 49 original stocks.
  13 Nov 2026: `universe.csv` grew to 200 (`python -m pipeline.universe`). The SEC steps were
  run for all 200 from Claude's sandbox (31 min, 5.3M facts, no failures); the first full run
  with Alpaca and BigQuery is the owner's next nightly run.
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
2. **Tag re-check: done 13 Nov 2026** (see README Known problems). ORCL debt and AT&T free
   cash flow fixed; CAT debt and COP/NEE/PLD capex are not in the free API; GE has no
   operating income line. A full 49-stock comparison showed no previously filled value changed.
3. **BRK.B and V: left empty on purpose** (no share count in the API; no patches).
4. **200 stocks: done 13 Nov 2026** (batched Alpaca, sectors from SIC, SEC-built universe).
   Confirm the first nightly run. Then, general fixes only: detect co-registrants
   automatically (stale C, SO, AEP, DLR, URI; replaces `CO_REGISTRANT_CIKS`).
5. **Incremental loads** before going much past 200: xbrl_facts is 5.3M rows (~680 MB as
   CSV) and fully reloaded nightly. Fetch companyfacts only for companies with a new
   10-K/10-Q since the last run; append new insider trades and news. Needs billing enabled.
6. Later: sentiment from news headlines, an explanation layer on `stock_snapshot` (no
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
  No estimates or approximations presented as data.
- No per-company patches: use what the standard SEC data gives, through rules that apply to
  every company. If a stock needs special handling, leave it empty and list it in the README's
  Known problems as "left empty on purpose". (Existing per-company lists: `PREDECESSOR_CIKS`,
  `CO_REGISTRANT_CIKS`, `SHARE_CLASS_MULTIPLIER`; replace them with general rules when scaling.)
- Claude's cloud environment `stock-tracker` can reach the SEC (data.sec.gov, www.sec.gov;
  needs `SEC_USER_AGENT`) but not Alpaca, BigQuery or FRED. Logic needing those is tested on
  synthetic data (`tests/fakes.py`) and then validated by the owner's real run. Say so plainly.
- Run `python -m pytest -q` before every push.
