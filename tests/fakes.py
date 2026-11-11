"""Synthetic stand-ins for the three data sources, shaped like the real API payloads."""
import pandas as pd

from pipeline import edgar

QUARTER_ENDS = ["03-31", "06-30", "09-30", "12-31"]
TENQ_FILED = ["05-05", "08-05", "11-05"]


def payload(rows, taxonomy="us-gaap"):
    """rows of (tag, unit, start, end, value, form, filed) -> EDGAR companyfacts JSON."""
    facts = {}
    for tag, unit, start, end, value, form, filed in rows:
        entry = {"end": end, "val": value, "form": form, "filed": filed, "accn": f"0000-{filed}",
                 "fy": int(filed[:4]), "fp": "FY" if form == "10-K" else "Q1"}
        if start:
            entry["start"] = start
        facts.setdefault(tag, {"label": tag, "description": f"About {tag}", "units": {}})
        facts[tag]["units"].setdefault(unit, []).append(entry)
    return {"cik": 1, "entityName": "Test Co", "facts": {taxonomy: facts}}


def facts_frame(rows, ticker="TEST"):
    return edgar.flatten_facts(ticker, payload(rows))[0]


def flow(tag, year, quarterly, unit="USD", direct_quarters=True):
    """A flow item for one calendar fiscal year, filed the way companies really file:
    10-Qs carry year-to-date figures (and, for income-statement items, the single quarter);
    the 10-K carries the full year only. There is never a standalone Q4."""
    rows, running = [], 0
    for i, value in enumerate(quarterly):
        running += value
        end = f"{year}-{QUARTER_ENDS[i]}"
        if i == 3:
            rows.append((tag, unit, f"{year}-01-01", end, running, "10-K", f"{year + 1}-02-10"))
            continue
        filed = f"{year}-{TENQ_FILED[i]}"
        rows.append((tag, unit, f"{year}-01-01", end, running, "10-Q", filed))
        if direct_quarters and i > 0:
            start = f"{year}-{['01-01', '04-01', '07-01'][i]}"
            rows.append((tag, unit, start, end, value, "10-Q", filed))
    return rows


def instant(tag, year, values, unit="USD"):
    rows = []
    for i, value in enumerate(values):
        form, filed = ("10-K", f"{year + 1}-02-10") if i == 3 else ("10-Q", f"{year}-{TENQ_FILED[i]}")
        rows.append((tag, unit, None, f"{year}-{QUARTER_ENDS[i]}", value, form, filed))
    return rows


def standard_company(years=(2022, 2023, 2024), scale=1.0):
    """A tidy company: revenue grows 10% a year, 20% net margin, 1,000 shares."""
    rows = []
    for n, year in enumerate(years):
        k = scale * 1.1 ** n
        revenue = [100 * k, 110 * k, 120 * k, 130 * k]
        rows += flow("Revenues", year, revenue)
        rows += flow("CostOfRevenue", year, [v * 0.6 for v in revenue])
        rows += flow("OperatingIncomeLoss", year, [v * 0.25 for v in revenue])
        rows += flow("NetIncomeLoss", year, [v * 0.2 for v in revenue])
        rows += flow("EarningsPerShareDiluted", year, [v * 0.2 / 1000 for v in revenue], unit="USD/shares")
        rows += flow("NetCashProvidedByUsedInOperatingActivities", year, [v * 0.3 for v in revenue],
                     direct_quarters=False)
        rows += flow("PaymentsToAcquirePropertyPlantAndEquipment", year, [v * 0.05 for v in revenue],
                     direct_quarters=False)
        rows += flow("DepreciationDepletionAndAmortization", year, [v * 0.04 for v in revenue],
                     direct_quarters=False)
        for i in range(3):  # weighted share counts: reported per quarter, and for the year
            start = f"{year}-{['01-01', '04-01', '07-01'][i]}"
            rows.append(("WeightedAverageNumberOfDilutedSharesOutstanding", "shares", start,
                         f"{year}-{QUARTER_ENDS[i]}", 1000, "10-Q", f"{year}-{TENQ_FILED[i]}"))
        rows.append(("WeightedAverageNumberOfDilutedSharesOutstanding", "shares", f"{year}-01-01",
                     f"{year}-12-31", 1000, "10-K", f"{year + 1}-02-10"))
        rows += instant("CashAndCashEquivalentsAtCarryingValue", year, [50 * k] * 4)
        rows += instant("Assets", year, [1000 * k] * 4)
        rows += instant("AssetsCurrent", year, [300 * k] * 4)
        rows += instant("LiabilitiesCurrent", year, [150 * k] * 4)
        rows += instant("Liabilities", year, [600 * k] * 4)
        rows += instant("StockholdersEquity", year, [400 * k] * 4)
        rows += instant("LongTermDebtNoncurrent", year, [200 * k] * 4)
        rows += instant("LongTermDebtCurrent", year, [20 * k] * 4)
    return rows


def submissions(name="Test Co", sic="3571", extra_filings=()):
    filings = [("0001-24-000001", "2024-02-10", "2023-12-31", "10-K", "", "tc-10k.htm", "10-K"),
               ("0001-24-000002", "2024-05-05", "2024-03-31", "10-Q", "", "tc-10q.htm", "10-Q"),
               ("0001-24-000003", "2024-05-02", "2024-05-02", "8-K", "2.02,9.01", "tc-8k.htm", "8-K"),
               ("0001-24-000004", "2024-06-01", "2024-05-30", "4", "", "xslF345X05/form4.xml", "FORM 4"),
               ("0001-24-000005", "2024-06-02", "", "424B2", "", "prospectus.htm", "424B2"),
               *extra_filings]
    keys = ["accessionNumber", "filingDate", "reportDate", "form", "items",
            "primaryDocument", "primaryDocDescription"]
    recent = {k: [f[i] for f in filings] for i, k in enumerate(keys)}
    recent["acceptanceDateTime"] = [f"{f[1]}T16:30:00.000Z" for f in filings]
    return {"name": name, "sic": sic, "sicDescription": "Electronic Computers",
            "stateOfIncorporation": "CA", "fiscalYearEnd": "1231", "exchanges": ["Nasdaq"],
            "filings": {"recent": recent, "files": []}}


FORM4_XML = """<?xml version="1.0"?>
<ownershipDocument>
  <documentType>4</documentType>
  <issuer><issuerCik>0000000001</issuerCik><issuerTradingSymbol>TEST</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerCik>0000000009</rptOwnerCik><rptOwnerName>DOE JANE</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>0</isDirector><isOfficer>1</isOfficer><isTenPercentOwner>false</isTenPercentOwner>
      <officerTitle>Chief Financial Officer</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2024-05-30</value></transactionDate>
      <transactionCoding><transactionFormType>4</transactionFormType><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>190.5</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts><sharesOwnedFollowingTransaction><value>25000</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
      <ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2024-05-30</value></transactionDate>
      <transactionCoding><transactionCode>A</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>500</value></transactionShares>
        <transactionPricePerShare><footnoteId id="F1"/></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts><sharesOwnedFollowingTransaction><value>25500</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
      <ownershipNature><directOrIndirectOwnership><value>I</value></directOrIndirectOwnership></ownershipNature>
    </nonDerivativeTransaction>
    <nonDerivativeHolding><securityTitle><value>Common Stock</value></securityTitle></nonDerivativeHolding>
  </nonDerivativeTable>
  <derivativeTable>
    <derivativeTransaction><securityTitle><value>Stock Option</value></securityTitle></derivativeTransaction>
  </derivativeTable>
</ownershipDocument>"""


def bars(symbols, days=600, end="2024-06-28", start_price=100.0, daily_growth=0.001):
    """Alpaca bars payload: steady growth, with a zig-zag so RSI and volatility are defined."""
    dates = pd.bdate_range(end=end, periods=days)
    out = {}
    for n, symbol in enumerate(symbols):
        price, rows = start_price * (1 + n), []
        for i, day in enumerate(dates):
            price *= 1 + daily_growth + (0.01 if i % 2 else -0.008) * (1 + 0.5 * n)
            rows.append({"t": f"{day:%Y-%m-%d}T04:00:00Z", "o": price, "h": price * 1.01, "l": price * 0.99,
                         "c": price, "v": 1_000_000 + i, "vw": price, "n": 5000})
        out[symbol] = rows
    return out


class FakeClient:
    """Answers get_json / get from a function of (url, params), and records the calls."""

    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def get_json(self, url, params=None):
        self.calls.append((url, dict(params or {})))
        return self.handler(url, params or {})

    def get(self, url, params=None):
        class Response:
            text = self.get_json(url, params)
        return Response()
