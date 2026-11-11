"""Raw XBRL facts -> one clean row per company per period (quarter, fiscal year, trailing 12 months).

Why this is not trivial, and what the code does about it:

1. Companies use different tags for the same idea, and switch tags over time.
   -> each concept has an ordered list of candidate tags; per period, the first tag with a value wins.
2. A period is restated in later filings.
   -> per (tag, start, end) the most recently filed value wins.
3. 10-Qs report many items year-to-date only, and nobody files a 10-Q for Q4.
   -> a quarter is derived by subtracting two cumulative facts that share a start date
      (9 months - 6 months = Q3, full year - 9 months = Q4).
4. EDGAR's `fy` / `fp` fields describe the filing, not the fact.
   -> periods are identified by their start/end dates only.
5. Share counts and per-share amounts filed before a stock split are on the old share basis.
   -> they are rescaled using the split calendar.
"""
import json
from collections import defaultdict
from dataclasses import dataclass

import numpy as np
import pandas as pd

ANNUAL_DAYS = (340, 380)    # 52/53-week fiscal years
QUARTER_DAYS = (75, 125)    # 12- to 17-week fiscal quarters
TTM_SPAN_DAYS = (250, 300)  # distance between the 1st and 4th quarter-end of a trailing year


@dataclass(frozen=True)
class Concept:
    kind: str                # "flow" (adds up over time), "instant" (balance at a date), "average"
    tags: tuple              # candidate us-gaap tags, most trusted first
    unit: str = "USD"
    split: str | None = None  # "divide" for per-share amounts, "multiply" for share counts


def _c(kind, *tags, unit="USD", split=None):
    return Concept(kind, tags, unit, split)


CONCEPTS = {
    # --- income statement
    "revenue": _c("flow", "RevenuesNetOfInterestExpense", "Revenues",
                  "RevenueFromContractWithCustomerExcludingAssessedTax",
                  "RevenueFromContractWithCustomerIncludingAssessedTax",
                  "SalesRevenueNet", "SalesRevenueGoodsNet", "RegulatedAndUnregulatedOperatingRevenue"),
    "cost_of_revenue": _c("flow", "CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"),
    "gross_profit": _c("flow", "GrossProfit"),
    "rd_expense": _c("flow", "ResearchAndDevelopmentExpense"),
    "sga_expense": _c("flow", "SellingGeneralAndAdministrativeExpense"),
    "operating_income": _c("flow", "OperatingIncomeLoss"),
    "interest_expense": _c("flow", "InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"),
    "pretax_income": _c(
        "flow",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"),
    "income_tax": _c("flow", "IncomeTaxExpenseBenefit"),
    "net_income": _c("flow", "NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"),
    # --- per share
    "eps_basic": _c("flow", "EarningsPerShareBasic", unit="USD/shares", split="divide"),
    "eps_diluted": _c("flow", "EarningsPerShareDiluted", unit="USD/shares", split="divide"),
    "dividends_per_share": _c("flow", "CommonStockDividendsPerShareDeclared",
                              "CommonStockDividendsPerShareCashPaid", unit="USD/shares", split="divide"),
    "shares_basic": _c("average", "WeightedAverageNumberOfSharesOutstandingBasic",
                       unit="shares", split="multiply"),
    "shares_diluted": _c("average", "WeightedAverageNumberOfDilutedSharesOutstanding",
                         unit="shares", split="multiply"),
    "shares_outstanding": _c("instant", "CommonStockSharesOutstanding", unit="shares", split="multiply"),
    # --- cash flow
    "operating_cash_flow": _c("flow", "NetCashProvidedByUsedInOperatingActivities",
                              "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
    "capex": _c("flow", "PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"),
    "depreciation_amortization": _c("flow", "DepreciationDepletionAndAmortization",
                                    "DepreciationAmortizationAndAccretionNet", "DepreciationAndAmortization",
                                    "DepreciationAmortizationAndOther"),
    "depreciation": _c("flow", "Depreciation"),
    "amortization_of_intangibles": _c("flow", "AmortizationOfIntangibleAssets"),
    "stock_compensation": _c("flow", "ShareBasedCompensation"),
    "dividends_paid": _c("flow", "PaymentsOfDividendsCommonStock", "PaymentsOfDividends"),
    "buybacks": _c("flow", "PaymentsForRepurchaseOfCommonStock"),
    # --- balance sheet
    "cash": _c("instant", "CashAndCashEquivalentsAtCarryingValue",
               "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
    "short_term_investments": _c("instant", "MarketableSecuritiesCurrent", "ShortTermInvestments",
                                 "AvailableForSaleSecuritiesDebtSecuritiesCurrent"),
    "current_assets": _c("instant", "AssetsCurrent"),
    "total_assets": _c("instant", "Assets"),
    "current_liabilities": _c("instant", "LiabilitiesCurrent"),
    "total_liabilities": _c("instant", "Liabilities"),
    "equity": _c("instant", "StockholdersEquity"),
    "equity_incl_minorities": _c("instant", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
    "liabilities_and_equity": _c("instant", "LiabilitiesAndStockholdersEquity"),
    "long_term_debt_noncurrent": _c("instant", "LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"),
    "long_term_debt_current": _c("instant", "LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"),
    "long_term_debt_total": _c("instant", "LongTermDebt"),
    "short_term_borrowings": _c("instant", "ShortTermBorrowings", "CommercialPaper", "OtherShortTermBorrowings"),
    "debt_current": _c("instant", "DebtCurrent"),
}

# A period exists in the output only if one of these was reported for it.
ANCHORS = ("revenue", "net_income", "operating_cash_flow")

METRICS = ["free_cash_flow", "ebitda", "total_debt", "net_debt", "gross_margin", "operating_margin",
           "net_margin", "fcf_margin", "roe", "roa", "debt_to_equity", "current_ratio",
           "revenue_yoy", "net_income_yoy", "eps_diluted_yoy"]

COLUMNS = (["ticker", "period_type", "period_end", "fiscal_year", "fiscal_quarter", "reported_date"]
           + list(CONCEPTS) + METRICS + ["tag_sources"])


def latest_facts(facts: pd.DataFrame) -> pd.DataFrame:
    """One row per (tag, unit, start, end): the value from the most recent 10-K/10-Q,
    plus `first_filed`, the day the number first became public."""
    f = facts[(facts["taxonomy"] == "us-gaap") & facts["form"].astype(str).str.startswith(("10-K", "10-Q"))].copy()
    for col in ("start_date", "end_date", "filed_date"):
        f[col] = pd.to_datetime(f[col])
    f = f.sort_values("filed_date")
    grouped = f.groupby(["tag", "unit", "start_date", "end_date"], dropna=False, sort=False)
    return grouped.agg(value=("value", "last"), filed_date=("filed_date", "last"),
                       first_filed=("filed_date", "first")).reset_index()


def adjust_for_splits(sub: pd.DataFrame, splits: pd.DataFrame | None, mode: str) -> pd.DataFrame:
    """Put share counts / per-share amounts on today's share basis.
    A fact filed before a split's ex-date is on the old basis; later filings already restate."""
    if splits is None or splits.empty or sub.empty:
        return sub
    factor = pd.Series(1.0, index=sub.index)
    for ex_date, ratio in zip(pd.to_datetime(splits["ex_date"]), splits["split_ratio"]):
        factor = factor.where(sub["filed_date"] >= ex_date, factor * ratio)
    sub = sub.copy()
    sub["value"] = sub["value"] * factor if mode == "multiply" else sub["value"] / factor
    return sub


SHARE_COUNT_TAGS = ("WeightedAverageNumberOfDilutedSharesOutstanding",
                    "WeightedAverageNumberOfSharesOutstandingBasic")
SPLIT_RATIOS = (1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 10, 15, 20, 25, 50, 100)


def _clean_ratio(ratio: float) -> float | None:
    """The split ratio a restatement corresponds to (7.0, 0.125...), or None if it is not one."""
    for clean in SPLIT_RATIOS:
        if abs(ratio / clean - 1) < 0.02:
            return float(clean)
        if abs(ratio * clean - 1) < 0.02:
            return 1 / clean
    return None


def detect_splits(facts: pd.DataFrame) -> pd.DataFrame:
    """Find stock splits from the filings themselves.

    After a split, the next filings restate earlier periods' share counts by a clean
    multiple (x7, x4, x0.125...). The date of the first filing on the new basis is exactly
    the cut-off needed here: everything filed before it is on the old basis. This covers
    splits older than the price provider's history. A split counts only if at least two
    periods were restated by the same ratio."""
    f = facts[(facts["taxonomy"] == "us-gaap") & facts["tag"].isin(SHARE_COUNT_TAGS)
              & (facts["unit"] == "shares")
              & facts["form"].astype(str).str.startswith(("10-K", "10-Q"))].copy()
    f["filed_date"] = pd.to_datetime(f["filed_date"])
    f = f.sort_values("filed_date").drop_duplicates(["tag", "start_date", "end_date", "filed_date"], keep="last")
    seen = defaultdict(list)  # ratio -> filing dates on which a period first appeared restated by it
    for _, period in f.groupby(["tag", "start_date", "end_date"], dropna=False):
        values, filed = period["value"].tolist(), period["filed_date"].tolist()
        for i in range(1, len(values)):
            if values[i - 1] > 0 and values[i] > 0:
                ratio = _clean_ratio(values[i] / values[i - 1])
                if ratio:
                    seen[ratio].append(filed[i])
    events = []
    for ratio, dates in seen.items():
        cluster = []
        for day in sorted(dates) + [pd.Timestamp.max]:
            if cluster and (day - cluster[-1]).days > 300:  # restatements of one split arrive quarterly
                if len(cluster) >= 2:
                    events.append((cluster[0], ratio))
                cluster = []
            cluster.append(day)
    found = pd.DataFrame(events, columns=["ex_date", "split_ratio"]).astype({"split_ratio": float})
    found["ex_date"] = pd.to_datetime(found["ex_date"])
    return found.sort_values("ex_date").reset_index(drop=True)


def combine_splits(detected: pd.DataFrame, provider: pd.DataFrame | None) -> pd.DataFrame:
    """Splits seen in the filings, plus provider splits the filings do not show yet
    (a split so recent that no report has restated anything)."""
    if provider is None or provider.empty:
        return detected
    extra = []
    for ex_date, ratio in zip(pd.to_datetime(provider["ex_date"]), provider["split_ratio"]):
        if _clean_ratio(ratio) is None:  # e.g. 1.011: a spin-off price adjustment, not a share split
            continue
        same = detected[(detected["split_ratio"] / ratio - 1).abs() < 0.02]
        days = (same["ex_date"] - ex_date).dt.days
        if not ((days >= -120) & (days <= 250)).any():
            extra.append((ex_date, ratio))
    if not extra:
        return detected
    return pd.concat([detected, pd.DataFrame(extra, columns=["ex_date", "split_ratio"])],
                     ignore_index=True).sort_values("ex_date").reset_index(drop=True)


def _flow_periods(sub: pd.DataFrame, additive: bool) -> dict:
    """{(period_type, end): (value, reported_date, derived)} for one tag."""
    d = sub.dropna(subset=["start_date"])
    records = sorted(zip(d["start_date"], d["end_date"], d["value"], d["first_filed"]))
    out = {}
    for start, end, value, reported in records:
        days = (end - start).days
        if ANNUAL_DAYS[0] <= days <= ANNUAL_DAYS[1]:
            out[("FY", end)] = (value, reported, False)
        elif QUARTER_DAYS[0] <= days <= QUARTER_DAYS[1]:
            out[("Q", end)] = (value, reported, False)

    if not additive:  # averages (weighted share counts) cannot be subtracted or summed
        for (ptype, end), hit in list(out.items()):
            if ptype == "FY" or ("TTM", end) not in out:
                out[("TTM", end)] = hit
        return out

    by_start = defaultdict(list)
    for start, end, value, reported in records:
        by_start[start].append((end, value, reported))
    for items in by_start.values():
        for (end0, v0, r0), (end1, v1, r1) in zip(items, items[1:]):
            if QUARTER_DAYS[0] <= (end1 - end0).days <= QUARTER_DAYS[1] and ("Q", end1) not in out:
                out[("Q", end1)] = (v1 - v0, max(r0, r1), True)

    # Fallback for Q4 when no 9-month figure exists: full year minus the three reported quarters.
    for start, end, value, reported in records:
        if ANNUAL_DAYS[0] <= (end - start).days <= ANNUAL_DAYS[1] and ("Q", end) not in out:
            inside = [hit[0] for (ptype, e), hit in out.items()
                      if ptype == "Q" and start < e < end - pd.Timedelta(days=60)]
            if len(inside) == 3:
                out[("Q", end)] = (value - sum(inside), reported, True)

    quarters = sorted((end, hit) for (ptype, end), hit in out.items() if ptype == "Q")
    for i in range(3, len(quarters)):
        end = quarters[i][0]
        if TTM_SPAN_DAYS[0] <= (end - quarters[i - 3][0]).days <= TTM_SPAN_DAYS[1]:
            out[("TTM", end)] = (sum(hit[0] for _, hit in quarters[i - 3:i + 1]), quarters[i][1][1], True)
    for (ptype, end), hit in list(out.items()):
        if ptype == "FY":  # at a fiscal year end the trailing year is the reported year
            out[("TTM", end)] = hit
    return out


def _instant_periods(sub: pd.DataFrame) -> dict:
    d = sub[sub["start_date"].isna()]
    return {("I", end): (value, reported, False)
            for end, value, reported in zip(d["end_date"], d["value"], d["first_filed"])}


def concept_values(by_tag: dict, concept: Concept, splits=None) -> tuple[dict, dict]:
    """Resolve one concept across its candidate tags. Returns (values, which tag supplied each).

    The value comes from the preferred tag, but the reported date is the earliest filing
    under any candidate tag: when a company adopts a new tag it re-files old periods under
    it, and that later filing date must not replace the original one."""
    values, sources, first_seen = {}, {}, {}
    for tag in concept.tags:
        sub = by_tag.get(tag)
        if sub is None:
            continue
        sub = sub[sub["unit"] == concept.unit]
        if concept.split:
            sub = adjust_for_splits(sub, splits, concept.split)
        found = _instant_periods(sub) if concept.kind == "instant" else _flow_periods(sub, concept.kind == "flow")
        for key, hit in found.items():
            first_seen[key] = min(first_seen.get(key, hit[1]), hit[1])
            if key not in values:
                values[key], sources[key] = hit, tag
    values = {key: (value, first_seen[key], derived) for key, (value, _, derived) in values.items()}
    return values, sources


def _fiscal_labels(df: pd.DataFrame) -> pd.DataFrame:
    """fiscal_year = calendar year in which the fiscal year ends; fiscal_quarter = 1..4."""
    fy_ends = sorted(pd.Timestamp(e) for e in df.loc[df["period_type"] == "FY", "period_end"].unique())
    years, quarters = [], []
    for ptype, end in zip(df["period_type"], df["period_end"]):
        fy_end = next((e for e in fy_ends if e >= end - pd.Timedelta(days=10)), None)
        if fy_end is None and fy_ends:  # fiscal year still in progress: project the last one forward
            fy_end = fy_ends[-1]
            while fy_end < end - pd.Timedelta(days=10):
                fy_end = fy_end + pd.DateOffset(years=1)
        if fy_end is None:
            years.append(pd.NA)
            quarters.append(pd.NA)
            continue
        years.append(fy_end.year)
        quarter = 4 - round((fy_end - end).days / 91.25)
        quarters.append(pd.NA if ptype == "FY" else min(4, max(1, quarter)))
    df["fiscal_year"] = pd.array(years, dtype="Int64")
    df["fiscal_quarter"] = pd.array(quarters, dtype="Int64")
    return df


def _ratio(numerator, denominator, only_if=None):
    ok = denominator.notna() & (denominator != 0)
    if only_if is not None:
        ok &= only_if
    return (numerator / denominator.where(ok)).astype(float)


def add_metrics(df: pd.DataFrame) -> pd.DataFrame:
    d = df
    # Some companies (McDonald's) file share counts in thousands or millions. Profit / EPS
    # gives the true order of magnitude, so rescale when a count is off by exactly that much.
    implied = (d["net_income"] / d["eps_diluted"].where(d["eps_diluted"] != 0)).abs()
    for column in ("shares_basic", "shares_diluted", "shares_outstanding"):
        for scale in (1e3, 1e6):
            off = (d[column] * scale / implied).between(0.5, 2)
            d[column] = d[column].where(~off, d[column] * scale)

    # Fallbacks for items some companies do not report as a line of their own.
    d["gross_profit"] = d["gross_profit"].fillna(d["revenue"] - d["cost_of_revenue"])
    d["equity"] = d["equity"].fillna(d["equity_incl_minorities"])
    d["equity"] = d["equity"].fillna(d["total_assets"] - d["total_liabilities"])
    d["total_liabilities"] = d["total_liabilities"].fillna(
        d["liabilities_and_equity"] - d["equity_incl_minorities"].fillna(d["equity"]))
    d["operating_income"] = d["operating_income"].fillna(d["pretax_income"] + d["interest_expense"])
    separate = d[["depreciation", "amortization_of_intangibles"]]
    d["depreciation_amortization"] = d["depreciation_amortization"].fillna(
        separate.sum(axis=1).where(separate.notna().any(axis=1)))
    d["free_cash_flow"] = d["operating_cash_flow"] - d["capex"]
    d["ebitda"] = d["operating_income"] + d["depreciation_amortization"]

    # Debt tagging is inconsistent across companies; this covers the common layouts.
    due_within_a_year = d["debt_current"].fillna(
        d["long_term_debt_current"].fillna(0) + d["short_term_borrowings"].fillna(0))
    d["total_debt"] = (d["long_term_debt_noncurrent"] + due_within_a_year).fillna(
        d["long_term_debt_total"] + d["short_term_borrowings"].fillna(0))
    d["net_debt"] = d["total_debt"] - d["cash"] - d["short_term_investments"].fillna(0)

    d["gross_margin"] = _ratio(d["gross_profit"], d["revenue"])
    d["operating_margin"] = _ratio(d["operating_income"], d["revenue"])
    d["net_margin"] = _ratio(d["net_income"], d["revenue"])
    d["fcf_margin"] = _ratio(d["free_cash_flow"], d["revenue"])

    # Returns need a full year of profit, and are meaningless on negative equity.
    full_year = d["period_type"].isin(["FY", "TTM"])
    positive_equity = d["equity"] > 0
    d["roe"] = _ratio(d["net_income"], d["equity"], full_year & positive_equity)
    d["roa"] = _ratio(d["net_income"], d["total_assets"], full_year)
    d["debt_to_equity"] = _ratio(d["total_debt"], d["equity"], positive_equity)
    d["current_ratio"] = _ratio(d["current_assets"], d["current_liabilities"])
    return d


def add_growth(df: pd.DataFrame) -> pd.DataFrame:
    """Year-over-year growth versus the same period type about 365 days earlier.
    Left empty when the base is zero or negative (a % change would mislead)."""
    df = df.sort_values("period_end").reset_index(drop=True)
    fields = ["revenue", "net_income", "eps_diluted"]
    previous = df[["period_type", "period_end"] + fields].rename(columns={f: f"{f}_prev" for f in fields})
    left = df[["period_type", "period_end"]].copy()
    left["target"] = left["period_end"] - pd.Timedelta(days=365)
    left = left.reset_index().sort_values("target")
    matched = pd.merge_asof(left, previous.rename(columns={"period_end": "target"}).sort_values("target"),
                            on="target", by="period_type", direction="nearest",
                            tolerance=pd.Timedelta(days=20)).set_index("index").sort_index()
    for f in fields:
        base = matched[f"{f}_prev"]
        df[f"{f}_yoy"] = (df[f] / base.where(base > 0) - 1).astype(float)
    return df


def build_fundamentals(ticker: str, facts: pd.DataFrame, splits: pd.DataFrame | None = None) -> pd.DataFrame:
    """All periods for one company. `splits` (columns ex_date, split_ratio) are the price
    provider's; splits visible in the filings are detected and merged in."""
    splits = combine_splits(detect_splits(facts), splits)
    latest = latest_facts(facts)
    by_tag = {tag: sub for tag, sub in latest.groupby("tag")}
    values, sources = {}, {}
    for name, concept in CONCEPTS.items():
        values[name], sources[name] = concept_values(by_tag, concept, splits)

    keys = {key for anchor in ANCHORS for key in values[anchor]}
    rows = []
    for ptype, end in sorted(keys, key=lambda k: (k[1], k[0])):
        row = {"ticker": ticker, "period_type": ptype, "period_end": end}
        tags = {}
        for name, concept in CONCEPTS.items():
            key = ("I", end) if concept.kind == "instant" else (ptype, end)
            hit = values[name].get(key)
            row[name] = hit[0] if hit else np.nan
            if hit:
                # * = a quarter obtained by subtraction rather than reported as such
                tags[name] = sources[name][key] + ("*" if hit[2] and ptype == "Q" else "")
        row["reported_date"] = min(values[a][(ptype, end)][1] for a in ANCHORS if (ptype, end) in values[a])
        row["tag_sources"] = json.dumps(tags)
        rows.append(row)

    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.DataFrame(rows)
    df = add_growth(add_metrics(_fiscal_labels(df)))
    return df[COLUMNS].sort_values(["period_end", "period_type"]).reset_index(drop=True)


STALE_SHARES_DAYS = 200


def latest_share_count(fundamentals: pd.DataFrame):
    """(shares, as_of_date, basis) used for market cap. (None, None, None) if nothing usable.

    Preferred: shares outstanding at the latest balance-sheet date. EDGAR's API omits that
    figure, or gives only one class, for multi-class companies, so it is used only when it
    agrees (within -15% / +5%) with the weighted-average count, which always covers every
    class. Otherwise the weighted-average count itself is used. A count more than 200 days
    older than the latest results is ignored: a stale count gives a confidently wrong
    market cap, which is worse than none."""
    reported = fundamentals[fundamentals["period_type"].isin(["Q", "FY"])].sort_values("period_end")
    if reported.empty:
        return None, None, None
    fresh = reported[reported["period_end"] >= reported["period_end"].max() - pd.Timedelta(days=STALE_SHARES_DAYS)]
    weighted = None
    for column in ("shares_diluted", "shares_basic"):
        known = fresh.dropna(subset=[column])
        if not known.empty:
            weighted = (float(known[column].iloc[-1]), known["period_end"].iloc[-1], "weighted average")
            break
    point = fresh.dropna(subset=["shares_outstanding"])
    if not point.empty:
        shares, as_of = float(point["shares_outstanding"].iloc[-1]), point["period_end"].iloc[-1]
        if weighted is None or (as_of >= weighted[1] and 0.85 <= shares / weighted[0] <= 1.05):
            return shares, as_of, "balance sheet"
    return weighted or (None, None, None)
