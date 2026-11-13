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
ALPACA_BATCH = 100              # symbols per Alpaca request
BENCHMARK = "SPY"                # priced like a stock, used for beta / relative return

# Tickers whose listed share is a fraction of the share class the filings report.
# Berkshire reports shares and EPS in Class A equivalents; 1 Class A = 1,500 Class B.
SHARE_CLASS_MULTIPLIER = {"BRK.B": 1500}

# Earlier SEC registrants of the same company, whose filing history must be merged in.
# Exxon moved to a new holding company (new CIK) on 1 July 2026.
PREDECESSOR_CIKS = {"XOM": ["0000034088"]}

# Companies that file one joint 10-Q/10-K with their subsidiaries. Since mid-2026, EDGAR's
# companyfacts API lists the parent's numbers from those joint reports under a subsidiary's
# CIK instead of the parent's. Only facts from the parent's own filings are taken from
# these CIKs: some also hold the subsidiary's own older reports, which must stay out.
CO_REGISTRANT_CIKS = {
    "NEE": ["0000037634"],  # Florida Power & Light
    "DUK": ["0000017797"],  # Duke Energy Progress
    "PLD": ["0001045610"],  # Prologis, L.P.
}

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

# Sector from the SEC industry code (SIC), only where the code clearly implies one sector.
# Codes that mix sectors are left out on purpose, so those companies get no sector rather
# than a wrong one: e.g. 3841 (3M files next to medical-device makers), 7370 (Alphabet and
# Meta next to software firms), 7389 (Visa, Uber, Accenture: "business services"), 3559
# (Lam Research as "special industry machinery"). The SEC's own industry description is
# always kept in `sic_description`. Ranges are inclusive.
SIC_SECTORS = [
    (1000, 1099, "Materials"),               # metal mining
    (1311, 1389, "Energy"),                  # oil & gas extraction and field services
    (1731, 1731, "Industrials"),             # electrical contractors
    (2000, 2099, "Consumer Staples"),        # food and beverages
    (2111, 2199, "Consumer Staples"),        # tobacco
    (2810, 2829, "Materials"),               # industrial chemicals, plastics
    (2833, 2836, "Health Care"),             # drugs and biologics
    (2844, 2844, "Consumer Staples"),        # cosmetics and toiletries
    (2900, 2999, "Energy"),                  # petroleum refining
    (3021, 3021, "Consumer Discretionary"),  # footwear
    (3490, 3499, "Industrials"),             # fabricated metal products
    (3510, 3549, "Industrials"),             # engines, farm, construction, metalworking machinery
    (3560, 3569, "Industrials"),             # general industrial machinery
    (3570, 3579, "Technology"),              # computers, storage, networking
    (3580, 3599, "Industrials"),             # HVAC, misc industrial machinery
    (3600, 3629, "Industrials"),             # electrical equipment
    (3661, 3669, "Technology"),              # communications equipment
    (3672, 3678, "Technology"),              # circuit boards, semiconductors, connectors
    (3711, 3716, "Consumer Discretionary"),  # motor vehicles
    (3720, 3769, "Industrials"),             # aerospace, ships, defense
    (3812, 3812, "Industrials"),             # defense electronics
    (3822, 3822, "Industrials"),             # building controls
    (3842, 3851, "Health Care"),             # medical appliances and devices
    (4011, 4013, "Industrials"),             # railroads
    (4210, 4215, "Industrials"),             # trucking and couriers
    (4512, 4581, "Industrials"),             # airlines, air courier
    (4610, 4619, "Energy"),                  # pipelines
    (4812, 4899, "Communication Services"),  # telecom, cable
    (4900, 4941, "Utilities"),               # electric, gas, water utilities
    (4950, 4959, "Industrials"),             # waste management
    (5122, 5122, "Health Care"),             # drug wholesale
    (5211, 5211, "Consumer Discretionary"),  # home improvement retail
    (5311, 5399, "Consumer Staples"),        # general merchandise and warehouse clubs
    (5500, 5599, "Consumer Discretionary"),  # auto dealers and parts
    (5600, 5699, "Consumer Discretionary"),  # apparel retail
    (5800, 5899, "Consumer Discretionary"),  # restaurants
    (5961, 5961, "Consumer Discretionary"),  # online and catalog retail
    (6000, 6323, "Financials"),              # banks, brokers, asset managers, life insurance
    (6324, 6324, "Health Care"),             # health insurers (UnitedHealth, Elevance, Cigna)
    (6325, 6411, "Financials"),              # property and casualty insurance, brokers
    (6798, 6798, "Real Estate"),             # REITs
    (7011, 7011, "Consumer Discretionary"),  # hotels
    (7320, 7320, "Financials"),              # credit rating agencies
    (7359, 7359, "Industrials"),             # equipment rental
    (7371, 7373, "Technology"),              # software
    (7812, 7841, "Communication Services"),  # film, TV, streaming
    (8060, 8069, "Health Care"),             # hospitals
]


def sector_for_sic(sic) -> str | None:
    if not (sic and str(sic).isdigit()):
        return None
    code = int(sic)
    return next((sector for low, high, sector in SIC_SECTORS if low <= code <= high), None)


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


def load_universe() -> list[str]:
    """Tickers from universe.csv. Add a line there (or run `python -m pipeline.universe`)."""
    with open(ROOT / "universe.csv", newline="") as f:
        return [row["ticker"].strip() for row in csv.DictReader(f)]


def env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing environment variable {name} (see .env.example)")
    return value
