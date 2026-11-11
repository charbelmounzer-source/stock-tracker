"""Settings and static reference data. Everything tunable lives here."""
import csv
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent

# A new dataset name on purpose: the first runs never overwrite the old `stock_data` tables.
BQ_DATASET = os.environ.get("BQ_DATASET", "stock_data_v2")

PRICE_START = "2016-01-01"       # Alpaca history starts in 2016
ACTIONS_START = "2009-01-01"     # splits are needed back to the start of XBRL data
FILINGS_LOOKBACK_DAYS = 3 * 365
INSIDER_LOOKBACK_DAYS = 180      # one HTTP call per Form 4, so keep this bounded
NEWS_LOOKBACK_DAYS = 90
BENCHMARK = "SPY"                # priced like a stock, used for beta / relative return

# Tickers whose listed share is a fraction of the share class the filings report.
# Berkshire reports shares and EPS in Class A equivalents; 1 Class A = 1,500 Class B.
SHARE_CLASS_MULTIPLIER = {"BRK.B": 1500}

# SIC 6000-6499 = banks, brokers, insurers. Debt, EBITDA and cash-flow metrics do not
# mean the same thing for them, so the snapshot leaves those metrics empty.
FINANCIAL_SIC_RANGE = (6000, 6499)

FRED_SERIES = {
    "FEDFUNDS": "Fed funds rate (%)",
    "DGS2": "2-year Treasury yield (%)",
    "DGS10": "10-year Treasury yield (%)",
    "T10Y2Y": "10-year minus 2-year Treasury spread (%)",
    "MORTGAGE30US": "30-year mortgage rate (%)",
    "CPIAUCSL": "Consumer price index (index)",
    "UNRATE": "Unemployment rate (%)",
    "GDPC1": "Real GDP (billions of 2017 USD, annualised)",
    "UMCSENT": "Consumer sentiment (index)",
    "DCOILWTICO": "WTI crude oil price (USD/barrel)",
    "VIXCLS": "VIX volatility index",
    "DTWEXBGS": "US dollar index (broad)",
}

# Which macro series matter most per sector, with a one-line beginner explanation.
SECTOR_MACRO = {
    "Technology": [("DGS10", "Higher long-term rates tend to pressure highly valued growth stocks.")],
    "Communication Services": [("DGS10", "Higher long-term rates tend to pressure highly valued growth stocks."),
                               ("UMCSENT", "Ad and subscription spending follows consumer confidence.")],
    "Consumer Discretionary": [("UNRATE", "Rising unemployment cuts spending on non-essentials."),
                               ("UMCSENT", "Confident consumers spend more on non-essentials.")],
    "Consumer Staples": [("CPIAUCSL", "Inflation raises input costs and tests pricing power.")],
    "Health Care": [("DGS10", "Mostly defensive; rates matter through valuation.")],
    "Financials": [("FEDFUNDS", "Short-term rates drive what banks earn on loans and pay on deposits."),
                   ("T10Y2Y", "Banks borrow short and lend long: a steeper curve helps margins.")],
    "Energy": [("DCOILWTICO", "Oil price is the direct driver of revenue.")],
    "Industrials": [("GDPC1", "Demand for equipment follows the economic cycle."),
                    ("DCOILWTICO", "Fuel is a major cost for transport and aerospace customers.")],
    "Utilities": [("DGS10", "Utilities carry heavy debt and compete with bonds for income investors.")],
    "Materials": [("GDPC1", "Demand for materials follows the economic cycle.")],
    "Real Estate": [("MORTGAGE30US", "Borrowing costs drive property values and financing."),
                    ("DGS10", "Real estate competes with bonds for income investors.")],
}

# Filings worth keeping. Everything else (mostly banks' daily structured-note
# prospectuses) is noise for this product.
FILING_FORMS = {
    "10-K", "10-K/A", "10-Q", "10-Q/A", "8-K", "8-K/A", "20-F", "6-K",
    "3", "4", "4/A", "5", "144", "DEF 14A", "S-1", "S-3",
    "SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A",
    "SCHEDULE 13D", "SCHEDULE 13D/A", "SCHEDULE 13G", "SCHEDULE 13G/A",
}

# 8-K item numbers -> plain-English event labels.
EIGHT_K_ITEMS = {
    "1.01": "Signed a material agreement",
    "1.02": "Ended a material agreement",
    "1.03": "Bankruptcy or receivership",
    "1.05": "Material cybersecurity incident",
    "2.01": "Completed an acquisition or sale of assets",
    "2.02": "Earnings results released",
    "2.03": "Took on new debt or a financial obligation",
    "2.04": "Debt repayment accelerated",
    "2.05": "Restructuring or exit costs",
    "2.06": "Material impairment (write-down)",
    "3.01": "Delisting notice",
    "3.02": "Unregistered sale of shares",
    "3.03": "Change to shareholder rights",
    "4.01": "Changed auditor",
    "4.02": "Past financial statements can no longer be relied on",
    "5.01": "Change in control of the company",
    "5.02": "Executive or director departure / appointment",
    "5.03": "Bylaw or fiscal-year change",
    "5.07": "Shareholder vote results",
    "7.01": "Regulation FD disclosure",
    "8.01": "Other material event",
    "9.01": "Financial statements and exhibits",
}

# Form 4 transaction codes -> plain English.
INSIDER_CODES = {
    "P": "Open-market purchase",
    "S": "Open-market sale",
    "A": "Grant or award",
    "M": "Option exercise",
    "F": "Shares withheld for taxes",
    "G": "Gift",
    "D": "Sold back to the company",
    "C": "Conversion",
    "X": "Derivative exercise",
    "J": "Other",
}


def load_universe() -> dict[str, str]:
    """ticker -> sector, from universe.csv. Add a line there to track a new stock."""
    with open(ROOT / "universe.csv", newline="") as f:
        return {row["ticker"].strip(): row["sector"].strip() for row in csv.DictReader(f)}


def env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing environment variable {name} (see .env.example)")
    return value
