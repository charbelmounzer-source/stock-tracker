import requests
import pandas as pd

headers = {
    "User-Agent": "Charbel Personal Project charbel@example.com"
}


def get_full_statement(cik, period_end):
    """
    Returns a DataFrame with every us-gaap line item reported for a given
    fiscal period end date -- a full raw look at everything EDGAR has for
    that company/year, not just our curated 6-7 metrics.
    """
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    response = requests.get(url, headers=headers)
    facts = response.json()["facts"]["us-gaap"]

    rows = []
    for tag, tag_data in facts.items():
        if "USD" not in tag_data.get("units", {}):
            continue  # skip non-dollar tags (shares, ratios, etc.) for now

        entries = [e for e in tag_data["units"]["USD"] if e["fp"] == "FY" and e["end"] == period_end]
        if not entries:
            continue

        # If multiple filings reported this same period, take the latest one
        latest_entry = max(entries, key=lambda e: e["filed"])

        rows.append({
            "Line item": tag_data.get("label", tag),
            "Value": latest_entry["val"],
        })

    df = pd.DataFrame(rows)
    df = df.sort_values("Line item").reset_index(drop=True)
    return df


def get_annual_metric(facts, tag_candidates, unit="USD", category="us-gaap"):
    """
    Merges data across ALL candidate tags (not just the first that works),
    since companies sometimes switch tags between periods, or use different
    tags for the same underlying concept.
    `unit` defaults to "USD" for dollar amounts, but should be "shares" for
    share-count metrics like shares outstanding.
    `category` defaults to "us-gaap", but some companies report certain
    facts (like shares outstanding) under "dei" instead.
    Returns a dict of {period_end_date: value}, deduped to the latest filing.
    """
    latest_per_period = {}

    if category not in facts:
        return {}

    for tag in tag_candidates:
        if tag in facts[category]:
            tag_units = facts[category][tag].get("units", {})
            if unit not in tag_units:
                continue

            values = tag_units[unit]
            annual_values = [e for e in values if e["fp"] == "FY"]

            for entry in annual_values:
                period_end = entry["end"]
                if period_end not in latest_per_period or entry["filed"] > latest_per_period[period_end]["filed"]:
                    latest_per_period[period_end] = entry

    return {period_end: entry["val"] for period_end, entry in latest_per_period.items()}


def get_earliest_filing_date(cik):
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    response = requests.get(url, headers=headers)
    submissions = response.json()

    dates = list(submissions["filings"]["recent"]["filingDate"])
    for file_info in submissions["filings"].get("files", []):
        dates.append(file_info["filingFrom"])

    return min(dates) if dates else None

def get_company_info(cik):
    """
    Returns basic company classification info: SIC code (industry),
    SIC description, and state of incorporation -- all from EDGAR's
    submissions endpoint (level 1: business model / sector).
    """
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    response = requests.get(url, headers=headers)
    submissions = response.json()

    return {
        "sic_code": submissions.get("sic"),
        "sic_description": submissions.get("sicDescription"),
        "state_of_incorporation": submissions.get("stateOfIncorporation"),
    }


def get_fundamentals_all_periods(ticker, cik):
    """
    Returns a dict of {period_end_date: {revenue, net_margin, gross_margin,
    operating_cash_flow, leverage}} -- one entry per fiscal year, instead
    of just the latest.
    """
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    response = requests.get(url, headers=headers)
    facts = response.json()["facts"]

    revenue = get_annual_metric(facts, ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"])
    shares_outstanding_gaap = get_annual_metric(facts, ["CommonStockSharesOutstanding"], unit="shares", category="us-gaap")
    shares_outstanding_dei = get_annual_metric(facts, ["EntityCommonStockSharesOutstanding"], unit="shares", category="dei")
    shares_outstanding_fallback = get_annual_metric(
        facts,
        ["WeightedAverageNumberOfDilutedSharesOutstanding", "WeightedAverageNumberOfSharesOutstandingBasic"],
        unit="shares",
        category="us-gaap"
    )
    # Priority: exact point-in-time count first, then dei, then weighted-average as last resort
    shares_outstanding = {**shares_outstanding_fallback, **shares_outstanding_dei, **shares_outstanding_gaap}
    cash = get_annual_metric(facts, ["CashAndCashEquivalentsAtCarryingValue"])
    long_term_debt = get_annual_metric(facts, ["LongTermDebtNoncurrent", "LongTermDebt"])
    short_term_debt = get_annual_metric(facts, ["DebtCurrent", "ShortTermBorrowings"])
    operating_income = get_annual_metric(facts, ["OperatingIncomeLoss"])
    depreciation_amortization = get_annual_metric(
        facts, ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet"]
    )

    # Fallback: some companies (e.g. Microsoft) split D&A into separate tags -- sum them
    depreciation_only = get_annual_metric(facts, ["Depreciation"])
    amortization_only = get_annual_metric(facts, ["AmortizationOfIntangibleAssets"])

    all_periods_for_da = set(depreciation_only.keys()) | set(amortization_only.keys())
    for period in all_periods_for_da:
        if period not in depreciation_amortization:
            dep = depreciation_only.get(period, 0) or 0
            amort = amortization_only.get(period, 0) or 0
            if period in depreciation_only or period in amortization_only:
                depreciation_amortization[period] = dep + amort
    net_income = get_annual_metric(facts, ["NetIncomeLoss"])
    gross_profit = get_annual_metric(facts, ["GrossProfit"])
    cost_of_revenue = get_annual_metric(facts, ["CostOfRevenue", "CostOfGoodsAndServicesSold"])
    operating_cash_flow = get_annual_metric(facts, ["NetCashProvidedByUsedInOperatingActivities"])
    
    total_equity = get_annual_metric(
        facts,
        ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]
    )

    total_liabilities = get_annual_metric(facts, ["Liabilities"])

    # Fallback: some companies (e.g. Amazon) don't tag Liabilities directly --
    # derive it as (Liabilities + Equity) - Equity
    total_liabilities_and_equity = get_annual_metric(facts, ["LiabilitiesAndStockholdersEquity"])
    for period, combined_value in total_liabilities_and_equity.items():
        if period not in total_liabilities and period in total_equity:
            total_liabilities[period] = combined_value - total_equity[period]

    all_periods = sorted(revenue.keys())  # every fiscal year we have revenue for

    results_by_period = {}

    for period in all_periods:
        net_margin = None
        gross_margin = None
        leverage = None
        roe = None  # add this line
        total_debt = None
        ebitda = None

        if period in net_income and revenue.get(period):
            net_margin = net_income[period] / revenue[period]

        if period in gross_profit and revenue.get(period):
            gross_margin = gross_profit[period] / revenue[period]
        elif period in cost_of_revenue and revenue.get(period):
            computed_gross_profit = revenue[period] - cost_of_revenue[period]
            gross_margin = computed_gross_profit / revenue[period]

        if period in total_liabilities and period in total_equity and total_equity.get(period):
            leverage = total_liabilities[period] / total_equity[period]

        # ROE = Net Income / Total Equity
        if period in net_income and period in total_equity and total_equity.get(period):
            roe = net_income[period] / total_equity[period]

        lt_debt = long_term_debt.get(period, 0) or 0
        st_debt = short_term_debt.get(period, 0) or 0
        if period in long_term_debt or period in short_term_debt:
            total_debt = lt_debt + st_debt

        op_income = operating_income.get(period)
        d_and_a = depreciation_amortization.get(period)
        if op_income is not None and d_and_a is not None:
            ebitda = op_income + d_and_a

        results_by_period[period] = {
            "revenue": revenue.get(period),
            "net_margin": net_margin,
            "gross_margin": gross_margin,
            "operating_cash_flow": operating_cash_flow.get(period),
            "leverage": leverage,
            "roe": roe,
            "shares_outstanding": shares_outstanding.get(period),
            "cash": cash.get(period),
            "total_debt": total_debt,
            "ebitda": ebitda,
            "total_equity": total_equity.get(period),
        }

    return results_by_period

def compute_valuation_ratios(fundamentals, current_price):
    """
    Computes EV/EBITDA, EV/Sales, and Price-to-Book using fundamentals
    (from EDGAR) combined with a current price (from Alpaca/BigQuery).
    Returns None for any ratio where required inputs are missing.
    """
    shares = fundamentals.get("shares_outstanding")
    revenue = fundamentals.get("revenue")
    ebitda = fundamentals.get("ebitda")
    cash = fundamentals.get("cash")
    total_debt = fundamentals.get("total_debt")

    market_cap = None
    if shares and current_price:
        market_cap = shares * current_price

    enterprise_value = None
    if market_cap is not None and total_debt is not None and cash is not None:
        enterprise_value = market_cap + total_debt - cash

    ev_to_sales = None
    if enterprise_value is not None and revenue:
        ev_to_sales = enterprise_value / revenue

    ev_to_ebitda = None
    if enterprise_value is not None and ebitda:
        ev_to_ebitda = enterprise_value / ebitda

    price_to_book = None
    total_equity_needed_for_pb = fundamentals.get("total_equity")  # note: not currently returned, see below
    if market_cap is not None and total_equity_needed_for_pb:
        price_to_book = market_cap / total_equity_needed_for_pb

    return {
        "market_cap": market_cap,
        "enterprise_value": enterprise_value,
        "ev_to_sales": ev_to_sales,
        "ev_to_ebitda": ev_to_ebitda,
        "price_to_book": price_to_book,
    }