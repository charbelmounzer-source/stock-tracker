"""Explain the gaps in a local run:  python -m pipeline.diagnose out

For every stock with an empty key metric or stale results, list what the company actually
filed that could fill it: candidate XBRL tags with their latest values, and recent filings.
Writes <folder>/diagnosis.txt. Use it to decide which tags to add to CONCEPTS.
"""
import sys
from pathlib import Path

import pandas as pd

# snapshot column -> pattern of XBRL tag names that could supply it
CANDIDATES = {
    "revenue_ttm": "Revenue",
    "market_cap": "SharesOutstanding|WeightedAverageNumber|SharesIssued",
    "pe_ttm": "EarningsPerShare",
    "equity": "StockholdersEquity|^Equity|MembersEquity|PartnersCapital",
    "total_debt": "Debt|Borrowings|NotesPayable|CommercialPaper",
    "free_cash_flow_ttm": "PaymentsToAcquire|CapitalExpenditure|PaymentsFor.*Property",
    "ebitda_ttm": "Depreciation|Amortization|OperatingIncome",
    "operating_margin": "OperatingIncome|IncomeLossFromContinuingOperationsBefore|InterestExpense",
    "gross_margin": "CostOf|GrossProfit",
}
NOT_EXPECTED_FOR_FINANCIALS = {"total_debt", "free_cash_flow_ttm", "ebitda_ttm", "operating_margin", "gross_margin"}
ANCHOR_TAGS = "^(Revenues|RevenueFromContractWithCustomerExcludingAssessedTax|NetIncomeLoss|ProfitLoss|" \
              "NetCashProvidedByUsedInOperatingActivities|RegulatedAndUnregulatedOperatingRevenue)$"


def latest_per_tag(facts: pd.DataFrame, pattern: str, limit: int = 8) -> pd.DataFrame:
    """The most recent fact of each matching tag, newest tags first."""
    hits = facts[facts["tag"].str.contains(pattern, regex=True)].sort_values(["end_date", "filed_date"])
    latest = hits.groupby(["tag", "unit"]).tail(1).sort_values("end_date", ascending=False).head(limit)
    return latest[["tag", "unit", "start_date", "end_date", "value", "form", "filed_date"]]


def main(folder: str) -> int:
    out = Path(folder)
    snapshot = pd.read_csv(out / "stock_snapshot.csv", parse_dates=["price_date", "fundamentals_period_end"])
    facts = pd.read_csv(out / "xbrl_facts.csv", dtype={"fiscal_period": str})
    filings = pd.read_csv(out / "filings.csv")
    lines = []

    for s in snapshot.to_dict("records"):
        missing = [c for c in CANDIDATES if pd.isna(s[c])
                   and not (s["is_financial"] and c in NOT_EXPECTED_FOR_FINANCIALS)
                   and not (c == "pe_ttm" and s["eps_diluted_ttm"] <= 0)]  # no P/E on a loss: expected
        age = (s["price_date"] - s["fundamentals_period_end"]).days if pd.notna(s["fundamentals_period_end"]) else None
        stale = age is None or age > 150
        if not missing and not stale:
            continue
        mine = facts[(facts["ticker"] == s["ticker"]) & (facts["taxonomy"] == "us-gaap")]
        lines.append(f"\n{'=' * 100}\n{s['ticker']}  {s['company_name']}  |  empty: {', '.join(missing) or '-'}"
                     f"  |  latest results: {s['fundamentals_period_end']} ({age} days old)")
        if stale:
            recent = filings[(filings["ticker"] == s["ticker"]) & (filings["filing_date"] >= "2025-10-01")]
            forms = recent.groupby("form")["filing_date"].agg(["count", "max"])
            lines.append("\nSTALE. Filings since Oct 2025 (form: count, latest):\n" + forms.to_string())
            anchors = mine[mine["tag"].str.match(ANCHOR_TAGS) & (mine["end_date"] >= "2025-06-01")]
            anchors = anchors.sort_values(["tag", "end_date", "start_date"])
            lines.append("\nRevenue / profit / cash-flow facts ending since Jun 2025:\n"
                         + anchors[["tag", "start_date", "end_date", "value", "form", "filed_date"]].to_string(index=False))
        for column in missing:
            found = latest_per_tag(mine, CANDIDATES[column])
            lines.append(f"\n-- {column}: tags matching /{CANDIDATES[column]}/\n"
                         + (found.to_string(index=False) if len(found) else "   nothing filed"))

    text = "\n".join(lines) or "No gaps found."
    (out / "diagnosis.txt").write_text(text, encoding="utf-8")
    print(f"{text.count('=' * 100)} stocks with gaps -> {out / 'diagnosis.txt'}")
    return 0


def probe(ciks: list[str]) -> int:
    """python -m pipeline.diagnose probe CIK [CIK ...]: the latest profit facts EDGAR holds
    under each CIK. Used to find where a company's recent results went when its own CIK has
    none (filings shared with subsidiaries, a new holding company...)."""
    from . import edgar
    client = edgar.client()
    for cik in ciks:
        payload = edgar.fetch_company_facts(client, cik.zfill(10))
        facts, _ = edgar.flatten_facts("?", payload)
        latest = facts[facts["tag"].isin(["NetIncomeLoss", "ProfitLoss"])].sort_values(["end_date", "filed_date"])
        print(f"\nCIK {cik}  {payload.get('entityName')}\n"
              + latest[["tag", "start_date", "end_date", "value", "form", "filed_date"]].tail(6).to_string(index=False))
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "probe":
        sys.exit(probe(sys.argv[2:]))
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "out"))
