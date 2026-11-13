"""Build universe.csv from the SEC's own ticker list:  python -m pipeline.universe 200

The SEC's company_tickers_exchange.json lists companies roughly from largest to smallest
(it is not documented as a ranking, so treat the order as approximate). Going down that
list, a company is kept if it trades on NYSE or Nasdaq and filed a 10-K in the last 15
months: that is, a US filer reporting in US GAAP, which is what the pipeline reads.
Foreign companies (20-F / 40-F filers such as ASML or Toyota) are skipped.

Tickers already in universe.csv are always kept, so adding stocks never drops one.
"""
import csv
import sys
from datetime import datetime, timedelta, timezone

from . import config, edgar

EXCHANGE_LIST_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
EXCHANGES = {"NYSE", "Nasdaq"}
RECENT_10K_DAYS = 455


def has_recent_10k(submissions: dict, since: str) -> bool:
    recent = submissions["filings"]["recent"]
    return any(form == "10-K" and date >= since for form, date in zip(recent["form"], recent["filingDate"]))


def build(c, size: int, keep: list[str], since: str) -> list[str]:
    """`keep` first, then companies down the SEC's list until there are `size` tickers."""
    chosen, seen = list(keep), set()
    for cik, name, ticker, exchange in c.get_json(EXCHANGE_LIST_URL)["data"]:
        if len(chosen) >= size:
            break
        if cik in seen:  # a company's first listed ticker is its main share class
            continue
        seen.add(cik)
        ticker = ticker.replace("-", ".")  # Alpaca and universe.csv use BRK.B, the SEC BRK-B
        if exchange not in EXCHANGES or ticker in chosen:
            continue
        if has_recent_10k(edgar.fetch_submissions(c, str(cik).zfill(10)), since):
            chosen.append(ticker)
            print(f"  {len(chosen):3}  {ticker:6} {name}")
    return chosen


def main(argv: list[str]) -> int:
    size = int(argv[0]) if argv else 200
    keep = list(config.load_universe())
    since = (datetime.now(timezone.utc) - timedelta(days=RECENT_10K_DAYS)).strftime("%Y-%m-%d")
    tickers = build(edgar.client(), size, keep, since)
    with open(config.ROOT / "universe.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ticker"])
        writer.writerows([t] for t in tickers)
    print(f"universe.csv: {len(tickers)} tickers ({len(tickers) - len(keep)} added)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
