import json

import pandas as pd
import pytest

from pipeline.fundamentals import COLUMNS, build_fundamentals, combine_splits, detect_splits, latest_share_count
from tests.fakes import facts_frame, flow, instant, standard_company


def row(df, ptype, end):
    hit = df[(df["period_type"] == ptype) & (df["period_end"] == pd.Timestamp(end))]
    assert len(hit) == 1, f"expected one {ptype} row at {end}, got {len(hit)}"
    return hit.iloc[0]


@pytest.fixture(scope="module")
def company():
    return build_fundamentals("TEST", facts_frame(standard_company()))


def test_columns_and_period_counts(company):
    assert list(company.columns) == COLUMNS
    counts = company["period_type"].value_counts()
    assert counts["FY"] == 3 and counts["Q"] == 12
    assert not company.duplicated(["period_type", "period_end"]).any()


def test_direct_quarter_is_used_as_reported(company):
    assert row(company, "Q", "2023-06-30")["revenue"] == pytest.approx(121.0)


def test_q4_is_full_year_minus_nine_months(company):
    q4 = row(company, "Q", "2023-12-31")
    assert q4["revenue"] == pytest.approx(143.0)
    assert json.loads(q4["tag_sources"])["revenue"] == "Revenues*"  # * = derived
    assert json.loads(row(company, "TTM", "2023-12-31")["tag_sources"])["revenue"] == "Revenues"


def test_cash_flow_reported_year_to_date_is_split_into_quarters(company):
    # operating cash flow is 30% of revenue and only ever filed cumulatively
    for end, revenue in [("2023-03-31", 110), ("2023-06-30", 121), ("2023-09-30", 132), ("2023-12-31", 143)]:
        assert row(company, "Q", end)["operating_cash_flow"] == pytest.approx(revenue * 0.3)


def test_fiscal_year_and_ttm_agree_at_year_end(company):
    fy, ttm = row(company, "FY", "2023-12-31"), row(company, "TTM", "2023-12-31")
    assert fy["revenue"] == pytest.approx(506.0)
    assert ttm["revenue"] == pytest.approx(506.0)


def test_ttm_rolls_forward_mid_year(company):
    # Q2-Q4 2023 + Q1 2024 = 121 + 132 + 143 + 121
    assert row(company, "TTM", "2024-03-31")["revenue"] == pytest.approx(517.0)


def test_no_ttm_until_four_quarters_exist(company):
    early = company[(company["period_type"] == "TTM") & (company["period_end"] < "2022-12-31")]
    assert early.empty


def test_fiscal_labels(company):
    q2 = row(company, "Q", "2024-06-30")
    assert (q2["fiscal_year"], q2["fiscal_quarter"]) == (2024, 2)
    assert row(company, "Q", "2024-12-31")["fiscal_quarter"] == 4
    assert pd.isna(row(company, "FY", "2024-12-31")["fiscal_quarter"])


def test_reported_date_is_first_filing(company):
    assert row(company, "Q", "2023-06-30")["reported_date"] == pd.Timestamp("2023-08-05")
    assert row(company, "Q", "2023-12-31")["reported_date"] == pd.Timestamp("2024-02-10")


def test_metrics(company):
    ttm = row(company, "TTM", "2023-12-31")
    assert ttm["gross_profit"] == pytest.approx(506 * 0.4)        # computed: revenue - cost
    assert ttm["gross_margin"] == pytest.approx(0.4)
    assert ttm["net_margin"] == pytest.approx(0.2)
    assert ttm["free_cash_flow"] == pytest.approx(506 * 0.25)     # 30% - 5% capex
    assert ttm["ebitda"] == pytest.approx(506 * 0.29)
    assert ttm["total_debt"] == pytest.approx(220 * 1.1)
    assert ttm["net_debt"] == pytest.approx((220 - 50) * 1.1)
    assert ttm["roe"] == pytest.approx(506 * 0.2 / 440)
    assert ttm["current_ratio"] == pytest.approx(2.0)
    assert pd.isna(row(company, "Q", "2023-06-30")["roe"])        # needs a full year of profit


def test_growth(company):
    assert row(company, "FY", "2023-12-31")["revenue_yoy"] == pytest.approx(0.10)
    assert row(company, "Q", "2024-03-31")["revenue_yoy"] == pytest.approx(0.10)
    assert row(company, "TTM", "2024-03-31")["revenue_yoy"] == pytest.approx(517 / 470 - 1)
    assert pd.isna(row(company, "FY", "2022-12-31")["revenue_yoy"])  # nothing to compare with


def test_restatement_wins_but_reported_date_stays():
    rows = flow("Revenues", 2023, [100, 110, 120, 130])
    rows.append(("Revenues", "USD", "2023-01-01", "2023-12-31", 450, "10-K", "2025-02-10"))  # restated
    fy = row(build_fundamentals("TEST", facts_frame(rows)), "FY", "2023-12-31")
    assert fy["revenue"] == 450
    assert fy["reported_date"] == pd.Timestamp("2024-02-10")


def test_tag_switch_between_years_leaves_no_gap():
    rows = flow("SalesRevenueNet", 2022, [100, 100, 100, 100]) + flow("Revenues", 2023, [110, 110, 110, 110])
    df = build_fundamentals("TEST", facts_frame(rows))
    assert row(df, "FY", "2022-12-31")["revenue"] == 400
    assert row(df, "FY", "2023-12-31")["revenue"] == 440
    assert row(df, "FY", "2023-12-31")["revenue_yoy"] == pytest.approx(0.10)


def test_preferred_tag_wins_when_two_are_reported():
    rows = (flow("Revenues", 2023, [100, 100, 100, 100])
            + flow("RevenueFromContractWithCustomerExcludingAssessedTax", 2023, [90, 90, 90, 90]))
    assert row(build_fundamentals("TEST", facts_frame(rows)), "FY", "2023-12-31")["revenue"] == 400


def test_q4_fallback_without_nine_month_figure():
    rows = [("Revenues", "USD", "2023-01-01", "2023-03-31", 100, "10-Q", "2023-05-05"),
            ("Revenues", "USD", "2023-04-01", "2023-06-30", 110, "10-Q", "2023-08-05"),
            ("Revenues", "USD", "2023-07-01", "2023-09-30", 120, "10-Q", "2023-11-05"),
            ("Revenues", "USD", "2023-01-01", "2023-12-31", 460, "10-K", "2024-02-10")]
    assert row(build_fundamentals("TEST", facts_frame(rows)), "Q", "2023-12-31")["revenue"] == 130


def test_per_share_data_filed_before_a_split_is_rescaled():
    rows = standard_company(years=(2023, 2024))
    splits = pd.DataFrame({"ex_date": ["2024-06-10"], "split_ratio": [10.0]})
    plain = build_fundamentals("TEST", facts_frame(rows))
    adjusted = build_fundamentals("TEST", facts_frame(rows), splits)

    before = row(adjusted, "Q", "2023-06-30")          # filed 2023-08-05, before the split
    assert before["eps_diluted"] == pytest.approx(row(plain, "Q", "2023-06-30")["eps_diluted"] / 10)
    assert before["shares_diluted"] == 10_000
    after = row(adjusted, "Q", "2024-06-30")           # filed 2024-08-05: already on the new basis
    assert after["eps_diluted"] == pytest.approx(row(plain, "Q", "2024-06-30")["eps_diluted"])
    assert after["shares_diluted"] == 1000
    assert before["revenue"] == row(plain, "Q", "2023-06-30")["revenue"]  # dollars are untouched


def test_non_calendar_fiscal_year():
    rows = [("Revenues", "USD", "2022-10-01", "2022-12-31", 100, "10-Q", "2023-02-01"),
            ("Revenues", "USD", "2022-10-01", "2023-03-31", 210, "10-Q", "2023-05-01"),
            ("Revenues", "USD", "2022-10-01", "2023-06-30", 330, "10-Q", "2023-08-01"),
            ("Revenues", "USD", "2022-10-01", "2023-09-30", 460, "10-K", "2023-11-01"),
            ("Revenues", "USD", "2023-10-01", "2023-12-31", 140, "10-Q", "2024-02-01")]
    df = build_fundamentals("TEST", facts_frame(rows))
    q1 = row(df, "Q", "2022-12-31")
    assert (q1["fiscal_year"], q1["fiscal_quarter"]) == (2023, 1)
    assert row(df, "Q", "2023-09-30")["revenue"] == 130
    next_q1 = row(df, "Q", "2023-12-31")               # fiscal 2024 has no 10-K yet
    assert (next_q1["fiscal_year"], next_q1["fiscal_quarter"]) == (2024, 1)
    assert row(df, "TTM", "2023-12-31")["revenue"] == 110 + 120 + 130 + 140


def test_negative_equity_blanks_equity_ratios():
    rows = (flow("Revenues", 2023, [100] * 4) + flow("NetIncomeLoss", 2023, [20] * 4)
            + instant("StockholdersEquity", 2023, [-50] * 4) + instant("LongTermDebt", 2023, [300] * 4))
    fy = row(build_fundamentals("TEST", facts_frame(rows)), "FY", "2023-12-31")
    assert pd.isna(fy["roe"]) and pd.isna(fy["debt_to_equity"])
    assert fy["total_debt"] == 300  # falls back to the all-in long-term debt tag


def test_total_liabilities_derived_when_not_reported():
    rows = (flow("Revenues", 2023, [100] * 4) + instant("LiabilitiesAndStockholdersEquity", 2023, [1000] * 4)
            + instant("StockholdersEquity", 2023, [400] * 4))
    assert row(build_fundamentals("TEST", facts_frame(rows)), "FY", "2023-12-31")["total_liabilities"] == 600


def test_only_annual_and_quarterly_reports_are_used():
    rows = flow("Revenues", 2023, [100] * 4)
    rows.append(("Revenues", "USD", "2023-01-01", "2023-12-31", 999, "8-K", "2025-01-01"))
    assert row(build_fundamentals("TEST", facts_frame(rows)), "FY", "2023-12-31")["revenue"] == 400


def test_latest_share_count(company):
    shares, as_of = latest_share_count(company)
    assert shares == 1000 and as_of == pd.Timestamp("2024-12-31")


def test_share_count_prefers_the_balance_sheet_figure_when_it_is_plausible(company):
    with_point = company.assign(shares_outstanding=980.0)       # slightly below the average: buybacks
    assert latest_share_count(with_point) == (980.0, pd.Timestamp("2024-12-31"))
    one_class_only = company.assign(shares_outstanding=300.0)   # a single share class: not the whole company
    assert latest_share_count(one_class_only)[0] == 1000


def split_history():
    """A 7-for-1 split in June 2014: reports from July 2014 on restate earlier share counts."""
    tag, eps = "WeightedAverageNumberOfDilutedSharesOutstanding", "EarningsPerShareDiluted"
    rows = flow("Revenues", 2012, [100] * 4) + flow("Revenues", 2013, [100] * 4) + flow("Revenues", 2014, [100] * 4)
    for year, filed in ((2012, "2013-02-10"), (2013, "2014-02-10")):       # original, old basis
        rows.append((tag, "shares", f"{year}-01-01", f"{year}-12-31", 1000, "10-K", filed))
        rows.append((eps, "USD/shares", f"{year}-01-01", f"{year}-12-31", 7.0, "10-K", filed))
    rows.append((tag, "shares", "2013-04-01", "2013-06-30", 1000, "10-Q", "2013-08-05"))
    rows.append((tag, "shares", "2014-04-01", "2014-06-30", 6900, "10-Q", "2014-07-23"))   # first on new basis
    rows.append((tag, "shares", "2013-04-01", "2013-06-30", 7000, "10-Q", "2014-07-23"))   # restated comparative
    rows.append((tag, "shares", "2013-01-01", "2013-12-31", 7000, "10-K", "2015-02-10"))   # restated comparative
    rows.append((eps, "USD/shares", "2013-01-01", "2013-12-31", 1.0, "10-K", "2015-02-10"))
    rows.append((tag, "shares", "2014-01-01", "2014-12-31", 6800, "10-K", "2015-02-10"))
    rows.append((eps, "USD/shares", "2014-01-01", "2014-12-31", 1.1, "10-K", "2015-02-10"))
    return rows


def test_split_is_detected_from_restated_share_counts():
    found = detect_splits(facts_frame(split_history()))
    assert found.values.tolist() == [[pd.Timestamp("2014-07-23"), 7.0]]


def test_detected_split_rescales_periods_never_restated():
    df = build_fundamentals("TEST", facts_frame(split_history()))
    never_restated = row(df, "FY", "2012-12-31")                 # only ever filed on the old basis
    assert never_restated["eps_diluted"] == pytest.approx(1.0)
    assert never_restated["shares_diluted"] == 7000
    assert row(df, "FY", "2013-12-31")["eps_diluted"] == pytest.approx(1.0)   # restated by the company
    assert row(df, "FY", "2014-12-31")["shares_diluted"] == 6800              # filed after the split


def test_buybacks_and_single_odd_restatements_are_not_splits():
    tag = "WeightedAverageNumberOfDilutedSharesOutstanding"
    rows = [(tag, "shares", "2013-01-01", "2013-12-31", 1000, "10-K", "2014-02-10"),
            (tag, "shares", "2013-01-01", "2013-12-31", 985, "10-K", "2015-02-10"),    # small correction
            (tag, "shares", "2012-01-01", "2012-12-31", 1000, "10-K", "2013-02-10"),
            (tag, "shares", "2012-01-01", "2012-12-31", 2000, "10-K", "2014-02-10")]   # only one period doubled
    assert detect_splits(facts_frame(rows)).empty


def test_provider_split_is_not_applied_twice():
    detected = pd.DataFrame({"ex_date": pd.to_datetime(["2020-10-30"]), "split_ratio": [4.0]})
    provider = pd.DataFrame({"ex_date": ["2020-08-31", "2026-10-01"], "split_ratio": [4.0, 2.0]})
    combined = combine_splits(detected, provider)
    assert combined.values.tolist() == [[pd.Timestamp("2020-10-30"), 4.0], [pd.Timestamp("2026-10-01"), 2.0]]


def test_reported_date_survives_a_later_change_of_tag():
    rows = flow("SalesRevenueNet", 2016, [100] * 4)   # filed under the old tag at the time...
    rows.append(("Revenues", "USD", "2016-01-01", "2016-12-31", 400, "10-K", "2019-02-10"))  # ...re-filed later
    fy = row(build_fundamentals("TEST", facts_frame(rows)), "FY", "2016-12-31")
    assert fy["reported_date"] == pd.Timestamp("2017-02-10")
    assert json.loads(fy["tag_sources"])["revenue"] == "Revenues"


def test_ttm_at_year_end_is_the_reported_year_not_a_sum_of_rounded_quarters():
    eps = [("EarningsPerShareDiluted", "USD/shares", s, e, v, form, filed) for s, e, v, form, filed in [
        ("2023-01-01", "2023-03-31", 1.11, "10-Q", "2023-05-05"), ("2023-04-01", "2023-06-30", 1.11, "10-Q", "2023-08-05"),
        ("2023-01-01", "2023-06-30", 2.23, "10-Q", "2023-08-05"), ("2023-07-01", "2023-09-30", 1.11, "10-Q", "2023-11-05"),
        ("2023-01-01", "2023-09-30", 3.35, "10-Q", "2023-11-05"), ("2023-01-01", "2023-12-31", 4.47, "10-K", "2024-02-10")]]
    df = build_fundamentals("TEST", facts_frame(flow("Revenues", 2023, [100] * 4) + eps))
    assert row(df, "TTM", "2023-12-31")["eps_diluted"] == 4.47   # 1.11 * 3 + 1.12 would give 4.45


def test_company_without_usable_facts_gives_empty_frame():
    df = build_fundamentals("TEST", facts_frame([("Assets", "USD", None, "2023-12-31", 5, "10-K", "2024-02-10")]))
    assert df.empty and list(df.columns) == COLUMNS
