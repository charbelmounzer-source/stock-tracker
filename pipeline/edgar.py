"""SEC EDGAR: company info, filings, raw XBRL facts and insider trades (Form 4).

Public domain, no key. The SEC requires a User-Agent with real contact details and
at most 10 requests/second; we stay at 5.
"""
import xml.etree.ElementTree as ET

import pandas as pd

from . import config
from .net import RETRY_STATUSES, Client

DATA = "https://data.sec.gov"
ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

FILING_COLUMNS = ["accessionNumber", "filingDate", "reportDate", "acceptanceDateTime",
                  "form", "items", "primaryDocument", "primaryDocDescription"]
FACT_TAXONOMIES = ("us-gaap", "dei")


def client() -> Client:
    return Client(
        headers={"User-Agent": config.env("SEC_USER_AGENT"), "Accept-Encoding": "gzip, deflate"},
        max_per_second=5,
        retry_statuses=RETRY_STATUSES + (403,),  # the SEC answers 403 when it throttles
    )


def fetch_cik_map(c: Client) -> dict[str, str]:
    """SEC ticker -> zero-padded 10-digit CIK. SEC tickers use '-' where exchanges use '.'."""
    rows = c.get_json(TICKERS_URL).values()
    return {r["ticker"].upper(): str(r["cik_str"]).zfill(10) for r in rows}


def sec_ticker(ticker: str) -> str:
    return ticker.upper().replace(".", "-")


def fetch_submissions(c: Client, cik: str) -> dict:
    return c.get_json(f"{DATA}/submissions/CIK{cik}.json")


def fetch_filing_blocks(c: Client, submissions: dict, cutoff: str) -> list[dict]:
    """The 'recent' block holds the last ~1,000 filings. Heavy filers (banks) need the
    older pages too, so fetch every page that still overlaps the lookback window."""
    blocks = [submissions["filings"]["recent"]]
    for page in submissions["filings"].get("files", []):
        if page.get("filingTo", "") >= cutoff:
            blocks.append(c.get_json(f"{DATA}/submissions/{page['name']}"))
    return blocks


def parse_company(ticker: str, cik: str, sub: dict) -> dict:
    filing_dates = list(sub["filings"]["recent"].get("filingDate", []))
    filing_dates += [p["filingFrom"] for p in sub["filings"].get("files", []) if p.get("filingFrom")]
    sic = sub.get("sic") or None
    low, high = config.FINANCIAL_SIC_RANGE
    return {
        "ticker": ticker,
        "cik": cik,
        "company_name": sub.get("name"),
        "sector": config.sector_for_sic(sic),
        "sic_code": sic,
        "sic_description": sub.get("sicDescription") or None,
        "is_financial": bool(sic and str(sic).isdigit() and low <= int(sic) <= high),
        "exchange": ", ".join(e for e in sub.get("exchanges") or [] if e) or None,
        "state_of_incorporation": sub.get("stateOfIncorporation") or None,
        "fiscal_year_end": sub.get("fiscalYearEnd") or None,
        "earliest_filing_date": min(filing_dates) if filing_dates else None,
    }


def parse_filings(ticker: str, cik: str, blocks: list[dict], cutoff: str) -> list[dict]:
    """Flatten EDGAR's column-oriented filing lists into rows, keeping useful forms only."""
    rows, seen = [], set()
    for block in blocks:
        n = len(block.get("accessionNumber", []))
        cols = {k: block.get(k) or [None] * n for k in FILING_COLUMNS}
        for i in range(n):
            accession, form, filed = cols["accessionNumber"][i], cols["form"][i], cols["filingDate"][i]
            if form not in config.FILING_FORMS or filed < cutoff or accession in seen:
                continue
            seen.add(accession)
            items = cols["items"][i] or None
            labels = [config.EIGHT_K_ITEMS[x.strip()] for x in (items or "").split(",")
                      if x.strip() in config.EIGHT_K_ITEMS]
            doc = cols["primaryDocument"][i] or None
            folder = f"{ARCHIVES}/{int(cik)}/{accession.replace('-', '')}"
            rows.append({
                "ticker": ticker,
                "accession_number": accession,
                "form": form,
                "filing_date": filed,
                "report_date": cols["reportDate"][i] or None,
                "accepted_at": cols["acceptanceDateTime"][i] or None,
                "items": items,
                "event_labels": "; ".join(labels) or None,
                "description": cols["primaryDocDescription"][i] or None,
                "primary_document": doc,
                "url": f"{folder}/{doc}" if doc else folder,
            })
    return rows


def fetch_company_facts(c: Client, cik: str) -> dict:
    return c.get_json(f"{DATA}/api/xbrl/companyfacts/CIK{cik}.json")


def flatten_facts(ticker: str, payload: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """companyfacts JSON -> (one row per reported fact, one row per tag with its label).

    Note: `fiscal_year` / `fiscal_period` describe the FILING a fact appeared in, not the
    period the fact covers (a 10-K repeats prior years). Always use start/end dates.
    """
    facts, tags = [], []
    for taxonomy in FACT_TAXONOMIES:
        for tag, body in payload.get("facts", {}).get(taxonomy, {}).items():
            tags.append((taxonomy, tag, body.get("label"), body.get("description")))
            for unit, entries in body.get("units", {}).items():
                for e in entries:
                    facts.append((ticker, taxonomy, tag, unit, e.get("start"), e["end"], e["val"],
                                  e.get("form"), e.get("filed"), e.get("accn"), e.get("fy"), e.get("fp")))
    facts_df = pd.DataFrame(facts, columns=[
        "ticker", "taxonomy", "tag", "unit", "start_date", "end_date", "value",
        "form", "filed_date", "accession_number", "fiscal_year", "fiscal_period"])
    tags_df = pd.DataFrame(tags, columns=["taxonomy", "tag", "label", "description"])
    return facts_df, tags_df


def form4_url(cik: str, accession: str, primary_document: str) -> str:
    """primaryDocument points at the styled view (xslF345X05/doc.xml); the raw XML sits
    one level up under the same file name."""
    return f"{ARCHIVES}/{int(cik)}/{accession.replace('-', '')}/{primary_document.split('/')[-1]}"


def _text(node, path):
    found = node.find(path) if node is not None else None
    return found.text.strip() if found is not None and found.text else None


def _number(node, path):
    try:
        return float(_text(node, path))
    except (TypeError, ValueError):
        return None


def _flag(node, path):
    return (_text(node, path) or "").lower() in ("1", "true")


def parse_form4(xml_text: str) -> list[dict]:
    """One row per common-stock (non-derivative) transaction in a Form 4.
    Option grants and other derivative rows are skipped on purpose."""
    root = ET.fromstring(xml_text)
    owners = root.findall("reportingOwner")
    relation = owners[0].find("reportingOwnerRelationship") if owners else None
    names = [_text(o, "reportingOwnerId/rptOwnerName") for o in owners]
    rows = []
    for t in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = _text(t, "transactionCoding/transactionCode")
        shares = _number(t, "transactionAmounts/transactionShares/value")
        price = _number(t, "transactionAmounts/transactionPricePerShare/value")
        rows.append({
            "owner_name": "; ".join(n for n in names if n) or None,
            "is_director": _flag(relation, "isDirector"),
            "is_officer": _flag(relation, "isOfficer"),
            "is_ten_percent_owner": _flag(relation, "isTenPercentOwner"),
            "officer_title": _text(relation, "officerTitle"),
            "security_title": _text(t, "securityTitle/value"),
            "transaction_date": _text(t, "transactionDate/value"),
            "transaction_code": code,
            "transaction_label": config.INSIDER_CODES.get(code, "Other"),
            "acquired_or_disposed": _text(t, "transactionAmounts/transactionAcquiredDisposedCode/value"),
            "shares": shares,
            "price_per_share": price,
            "value": shares * price if shares is not None and price is not None else None,
            "shares_owned_after": _number(t, "postTransactionAmounts/sharesOwnedFollowingTransaction/value"),
            "ownership": _text(t, "ownershipNature/directOrIndirectOwnership/value"),
        })
    return rows
