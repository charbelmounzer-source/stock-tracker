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


def get_annual_metric(facts, tag_candidates):
    """
    Merges data across ALL candidate tags (not just the first that works),
    since companies sometimes switch tags between periods, or use different
    tags for the same underlying concept.
    Returns a dict of {period_end_date: value}, deduped to the latest filing.
    """
    latest_per_period = {}

    for tag in tag_candidates:
        if tag in facts["us-gaap"]:
            usd_values = facts["us-gaap"][tag]["units"]["USD"]
            annual_values = [e for e in usd_values if e["fp"] == "FY"]

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
    net_income = get_annual_metric(facts, ["NetIncomeLoss"])
    gross_profit = get_annual_metric(facts, ["GrossProfit"])
    cost_of_revenue = get_annual_metric(facts, ["CostOfRevenue", "CostOfGoodsAndServicesSold"])
    operating_cash_flow = get_annual_metric(facts, ["NetCashProvidedByUsedInOperatingActivities"])
    total_liabilities = get_annual_metric(facts, ["Liabilities"])
    total_equity = get_annual_metric(
        facts,
        ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]
    )

    all_periods = sorted(revenue.keys())  # every fiscal year we have revenue for

    results_by_period = {}

    for period in all_periods:
        net_margin = None
        gross_margin = None
        leverage = None
        roe = None  # add this line

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

        results_by_period[period] = {
            "revenue": revenue.get(period),
            "net_margin": net_margin,
            "gross_margin": gross_margin,
            "operating_cash_flow": operating_cash_flow.get(period),
            "leverage": leverage,
            "roe": roe,  # add this line
        }

    return results_by_period