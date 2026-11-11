"""Run the pipeline:  python -m pipeline [--local DIR] [--only step,step] [--tickers AAPL,MSFT]

Source steps fetch data; derived steps (fundamentals, snapshot) are computed from what
was fetched in the same run. A failing step never stops the others: its table simply
keeps yesterday's data, and the run exits with code 1 so the scheduler flags it.
"""
import argparse
import sys
import traceback
from datetime import datetime, timedelta, timezone

import pandas as pd

from . import alpaca, config, edgar, fred
from .bq import BigQuerySink, LocalSink
from .fundamentals import build_fundamentals
from .snapshot import build_snapshot


def days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%d")


class Run:
    def __init__(self, sink, universe: dict[str, str]):
        self.sink = sink
        self.universe = universe
        self.frames: dict[str, pd.DataFrame] = {}
        self._edgar = self._alpaca = self._ciks = None

    @property
    def edgar(self):
        self._edgar = self._edgar or edgar.client()
        return self._edgar

    @property
    def alpaca(self):
        self._alpaca = self._alpaca or alpaca.client()
        return self._alpaca

    def cik(self, ticker: str) -> str:
        self._ciks = self._ciks or edgar.fetch_cik_map(self.edgar)
        return self._ciks[edgar.sec_ticker(ticker)]

    def save(self, table: str, df: pd.DataFrame):
        if df is None or df.empty:
            raise RuntimeError(f"{table}: nothing fetched, keeping the existing table")
        self.frames[table] = df
        print(f"  {table}: {self.sink.write(table, df):,} rows")


# ---------------------------------------------------------------- source steps

def companies(run: Run):
    """EDGAR company info and recent filings (one payload gives both)."""
    cutoff = days_ago(config.FILINGS_LOOKBACK_DAYS)
    company_rows, filing_rows = [], []
    for ticker, sector in run.universe.items():
        cik = run.cik(ticker)
        submissions = edgar.fetch_submissions(run.edgar, cik)
        company_rows.append(edgar.parse_company(ticker, sector, cik, submissions))
        blocks = edgar.fetch_filing_blocks(run.edgar, submissions, cutoff)
        filing_rows += edgar.parse_filings(ticker, cik, blocks, cutoff)
    run.save("companies", pd.DataFrame(company_rows))
    run.save("filings", pd.DataFrame(filing_rows))


def facts(run: Run):
    """Every XBRL fact each company has ever reported."""
    fact_frames, tag_frames = [], []
    for ticker in run.universe:
        f, t = edgar.flatten_facts(ticker, edgar.fetch_company_facts(run.edgar, run.cik(ticker)))
        fact_frames.append(f)
        tag_frames.append(t)
    run.save("xbrl_facts", pd.concat(fact_frames, ignore_index=True))
    run.save("xbrl_tags", pd.concat(tag_frames, ignore_index=True).drop_duplicates(["taxonomy", "tag"]))


def insiders(run: Run):
    """Insider trades: one request per recent Form 4 (needs the `companies` step)."""
    filings = run.frames["filings"]
    recent = filings[filings["form"].isin(["4", "4/A"])
                     & (filings["filing_date"] >= days_ago(config.INSIDER_LOOKBACK_DAYS))
                     & filings["primary_document"].notna()]
    rows, failed = [], 0
    for f in recent.to_dict("records"):
        try:
            url = edgar.form4_url(run.cik(f["ticker"]), f["accession_number"], f["primary_document"])
            for trade in edgar.parse_form4(run.edgar.get(url).text):
                rows.append({"ticker": f["ticker"], "accession_number": f["accession_number"],
                             "filing_date": f["filing_date"], **trade})
        except Exception as error:  # one unreadable form must not lose the rest
            failed += 1
            print(f"  skipped {f['accession_number']}: {error}")
    if failed > 0.2 * max(len(recent), 1):
        raise RuntimeError(f"{failed} of {len(recent)} Form 4 filings failed")
    run.save("insider_trades", pd.DataFrame(rows))


def actions(run: Run):
    """Splits and dividends."""
    run.save("corporate_actions", alpaca.fetch_corporate_actions(
        run.alpaca, list(run.universe), config.ACTIONS_START, days_ago(0)))


def prices(run: Run):
    """Daily prices for every stock plus the benchmark."""
    run.save("prices", alpaca.fetch_prices(run.alpaca, list(run.universe) + [config.BENCHMARK],
                                           config.PRICE_START))


def news(run: Run):
    run.save("news", alpaca.fetch_news(run.alpaca, list(run.universe),
                                       days_ago(config.NEWS_LOOKBACK_DAYS), days_ago(-1)))


def macro(run: Run):
    run.save("macro", fred.fetch_all(fred.client()))


# --------------------------------------------------------------- derived steps

def fundamentals(run: Run):
    """Quarterly / annual / trailing-12-month statements from the raw facts."""
    all_facts = run.frames["xbrl_facts"]
    all_actions = run.frames.get("corporate_actions")
    if all_actions is None:
        print("  no corporate actions this run: per-share history is NOT split-adjusted")
    frames = []
    for ticker, company_facts in all_facts.groupby("ticker"):
        splits = None
        if all_actions is not None:
            splits = all_actions[(all_actions["ticker"] == ticker) & all_actions["split_ratio"].notna()]
        frames.append(build_fundamentals(ticker, company_facts, splits))
    run.save("fundamentals", pd.concat(frames, ignore_index=True))


def snapshot(run: Run):
    """One row per stock: latest price, performance, valuation, growth, health."""
    run.save("stock_snapshot", build_snapshot(run.frames["companies"], run.frames.get("prices"),
                                              run.frames.get("fundamentals"), run.frames.get("corporate_actions")))


# name -> (function, tables it needs from earlier steps)
STEPS = {
    "companies": (companies, []),
    "actions": (actions, []),
    "prices": (prices, []),
    "facts": (facts, []),
    "insiders": (insiders, ["filings"]),
    "news": (news, []),
    "macro": (macro, []),
    "fundamentals": (fundamentals, ["xbrl_facts"]),
    "snapshot": (snapshot, ["companies"]),
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--local", metavar="DIR", help="write CSV files to DIR instead of BigQuery")
    parser.add_argument("--only", help=f"comma-separated steps to run, from: {', '.join(STEPS)}")
    parser.add_argument("--tickers", help="comma-separated subset of universe.csv (for a quick trial)")
    args = parser.parse_args(argv)

    universe = config.load_universe()
    if args.tickers:
        wanted = [t.strip().upper() for t in args.tickers.split(",")]
        unknown = set(wanted) - set(universe)
        if unknown:
            parser.error(f"not in universe.csv: {sorted(unknown)}")
        universe = {t: universe[t] for t in wanted}
    selected = args.only.split(",") if args.only else list(STEPS)
    unknown = set(selected) - set(STEPS)
    if unknown:
        parser.error(f"unknown steps: {sorted(unknown)}")

    run = Run(LocalSink(args.local) if args.local else BigQuerySink(), universe)
    results = {}
    for name, (step, needs) in STEPS.items():
        if name not in selected:
            continue
        missing = [table for table in needs if table not in run.frames]
        if missing:
            results[name] = f"skipped (needs {', '.join(missing)} from an earlier step)"
            continue
        print(f"[{name}]")
        try:
            step(run)
            results[name] = "ok"
        except Exception as error:
            traceback.print_exc()
            results[name] = f"FAILED: {error}"

    print("\nSummary")
    for name, outcome in results.items():
        print(f"  {name:<13}{outcome}")
    return 0 if all(outcome == "ok" for outcome in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
