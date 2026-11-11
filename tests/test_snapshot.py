import json

import numpy as np
import pandas as pd
import pytest

from pipeline.fundamentals import build_fundamentals
from pipeline.schemas import TABLES, columns, conform, to_ndjson
from pipeline.snapshot import build_snapshot, price_stats, rsi, trailing_dividends
from tests.fakes import facts_frame, standard_company


def price_frame(ticker, closes, end="2024-12-31"):
    dates = pd.bdate_range(end=end, periods=len(closes))
    return pd.DataFrame({"ticker": ticker, "price_date": dates.strftime("%Y-%m-%d"), "close": closes,
                         "close_total_return": [c * 0.98 for c in closes[:-1]] + [closes[-1]],
                         "volume": 1000.0})


def test_price_stats_returns():
    closes = list(np.linspace(50, 100, 600))
    stats = price_stats(price_frame("AAA", closes)).iloc[0]
    assert stats["close"] == 100 and stats["price_date"] == pd.Timestamp("2024-12-31")
    assert stats["ret_1d"] == pytest.approx(100 / closes[-2] - 1)
    base = dict(zip(pd.bdate_range(end="2024-12-31", periods=600), closes))
    assert stats["ret_1y"] == pytest.approx(100 / base[pd.Timestamp("2023-12-29")] - 1)  # 12-31 was a Sunday
    assert stats["ret_ytd"] == pytest.approx(stats["ret_1y"])
    assert stats["total_return_1y"] > stats["ret_1y"]
    assert stats["high_52w"] == 100 and stats["pct_from_high_52w"] == 0
    assert stats["sma_50"] == pytest.approx(np.mean(closes[-50:]))
    assert pd.isna(stats["ret_3y"])  # only ~2.4 years of history


def test_rsi_extremes_and_short_history():
    assert rsi(pd.Series(np.linspace(1, 2, 50))) == 100
    assert rsi(pd.Series(np.linspace(2, 1, 50))) == pytest.approx(0, abs=1e-9)
    assert pd.isna(rsi(pd.Series([1.0, 2.0, 3.0])))


def test_beta_against_benchmark():
    rng = np.random.default_rng(0)
    market = rng.normal(0.0005, 0.01, 400)
    spy = 100 * np.cumprod(1 + market)
    double = 100 * np.cumprod(1 + 2 * market)
    stats = price_stats(pd.concat([price_frame("SPY", list(spy)), price_frame("AAA", list(double))]))
    stats = stats.set_index("ticker")
    assert stats.loc["SPY", "beta_1y"] == pytest.approx(1.0)
    assert stats.loc["AAA", "beta_1y"] == pytest.approx(2.0)
    assert stats.loc["SPY", "ret_1y_vs_benchmark"] == pytest.approx(0.0)


ACTION_COLUMNS = ["ticker", "action_type", "ex_date", "split_ratio", "cash_amount", "is_special"]


def test_trailing_dividends_are_put_on_todays_share_basis():
    actions = pd.DataFrame([
        ("AAA", "cash_dividend", "2024-02-01", None, 1.00, False),   # before the split: 1.00 / 4
        ("AAA", "forward_split", "2024-06-01", 4.0, None, None),
        ("AAA", "cash_dividend", "2024-08-01", None, 0.25, False),
        ("AAA", "cash_dividend", "2024-09-01", None, 5.00, True),    # special: excluded
        ("AAA", "cash_dividend", "2023-06-01", None, 9.00, False),   # more than a year before the latest
        ("BBB", "cash_dividend", "2024-08-01", None, 7.00, False),
    ], columns=ACTION_COLUMNS)
    assert trailing_dividends(actions, "AAA", pd.Timestamp("2024-12-31")) == pytest.approx(0.50)
    assert trailing_dividends(actions, "CCC", pd.Timestamp("2024-12-31")) == 0


def test_trailing_dividends_count_four_quarterly_payments_despite_date_drift():
    # Apple's real ex-dates: a 365-day window ending 2026-11-10 would catch only three of these
    dates = ["2025-08-11", "2025-11-10", "2026-02-09", "2026-05-11", "2026-08-10"]
    amounts = [0.26, 0.26, 0.26, 0.27, 0.27]
    actions = pd.DataFrame([("AAA", "cash_dividend", d, None, a, False) for d, a in zip(dates, amounts)],
                           columns=ACTION_COLUMNS)
    assert trailing_dividends(actions, "AAA", pd.Timestamp("2026-11-10")) == pytest.approx(1.06)
    assert trailing_dividends(actions, "AAA", pd.Timestamp("2028-01-01")) == 0   # stopped paying


@pytest.fixture(scope="module")
def inputs():
    companies = pd.DataFrame([
        {"ticker": "TEST", "company_name": "Test Co", "sector": "Technology",
         "sic_description": "Computers", "is_financial": False},
        {"ticker": "BANK", "company_name": "Bank Co", "sector": "Financials",
         "sic_description": "Banks", "is_financial": True}])
    fundamentals = pd.concat([build_fundamentals(t, facts_frame(standard_company())) for t in ("TEST", "BANK")])
    prices = pd.concat([price_frame(t, list(np.linspace(40, 50, 300))) for t in ("TEST", "BANK", "SPY")])
    return companies, prices, fundamentals


def test_snapshot_valuation(inputs):
    snap = build_snapshot(*inputs).set_index("ticker").loc["TEST"]
    revenue, net_income = 100 * 1.21 * 4.6, 100 * 1.21 * 4.6 * 0.2   # fiscal 2024
    assert snap["revenue_ttm"] == pytest.approx(revenue)
    assert snap["fundamentals_period_end"] == pd.Timestamp("2024-12-31")
    assert snap["shares"] == 1000 and snap["market_cap"] == pytest.approx(50_000)
    assert snap["pe_ttm"] == pytest.approx(50 / (net_income / 1000))
    assert snap["ps_ttm"] == pytest.approx(50_000 / revenue)
    assert snap["pb"] == pytest.approx(50_000 / (400 * 1.21))
    assert snap["enterprise_value"] == pytest.approx(50_000 + 170 * 1.21)
    assert snap["ev_to_ebitda"] == pytest.approx((50_000 + 170 * 1.21) / (revenue * 0.29))
    assert snap["fcf_yield"] == pytest.approx(revenue * 0.25 / 50_000)
    assert snap["revenue_yoy"] == pytest.approx(0.10) and snap["revenue_yoy_quarter"] == pytest.approx(0.10)


def test_snapshot_blanks_metrics_that_mislead_for_financials(inputs):
    bank = build_snapshot(*inputs).set_index("ticker").loc["BANK"]
    assert pd.isna(bank["ev_to_ebitda"]) and pd.isna(bank["debt_to_equity"]) and pd.isna(bank["gross_margin"])
    assert bank["pe_ttm"] > 0 and bank["roe"] > 0 and bank["net_margin"] == pytest.approx(0.2)


def test_snapshot_share_class_multiplier(inputs, monkeypatch):
    monkeypatch.setattr("pipeline.config.SHARE_CLASS_MULTIPLIER", {"TEST": 1500})
    plain = build_snapshot(*inputs).set_index("ticker").loc["BANK"]
    scaled = build_snapshot(*inputs).set_index("ticker").loc["TEST"]
    assert scaled["shares"] == 1_500_000
    assert scaled["eps_diluted_ttm"] == pytest.approx(plain["eps_diluted_ttm"] / 1500)
    assert scaled["pe_ttm"] == pytest.approx(plain["pe_ttm"] * 1500)


def test_snapshot_survives_missing_inputs(inputs):
    companies, prices, fundamentals = inputs
    only_companies = conform(build_snapshot(companies), "stock_snapshot")
    assert len(only_companies) == 2 and only_companies["close"].isna().all()
    no_fundamentals = conform(build_snapshot(companies, prices), "stock_snapshot")
    assert no_fundamentals["close"].notna().all() and no_fundamentals["market_cap"].isna().all()


def test_negative_earnings_give_no_pe(inputs):
    companies, prices, fundamentals = inputs
    losing = fundamentals.copy()
    losing["eps_diluted"] = -1.0
    assert build_snapshot(companies, prices, losing)["pe_ttm"].isna().all()


def test_eps_falls_back_to_profit_per_share(inputs):
    companies, prices, fundamentals = inputs
    no_eps = fundamentals.assign(eps_diluted=np.nan)
    snap = build_snapshot(companies, prices, no_eps).set_index("ticker").loc["TEST"]
    assert snap["eps_diluted_ttm"] == pytest.approx(snap["net_income_ttm"] / 1000)
    assert snap["pe_ttm"] == pytest.approx(snap["market_cap"] / snap["net_income_ttm"])


def test_share_count_implied_from_dividends_when_none_is_reported(inputs):
    companies, prices, fundamentals = inputs
    no_shares = fundamentals.assign(shares_diluted=np.nan, shares_basic=np.nan, shares_outstanding=np.nan,
                                    eps_diluted=np.nan, eps_basic=np.nan, dividends_paid=2000.0)
    actions = pd.DataFrame([(t, "cash_dividend", "2024-11-01", None, 2.0, False) for t in ("TEST", "BANK")],
                           columns=ACTION_COLUMNS)
    snap = build_snapshot(companies, prices, no_shares, actions).set_index("ticker").loc["TEST"]
    assert snap["shares"] == 1000 and snap["shares_basis"] == "implied from dividends"
    assert snap["market_cap"] == pytest.approx(50_000)
    assert snap["eps_diluted_ttm"] == pytest.approx(snap["net_income_ttm"] / 1000)
    without_dividends = build_snapshot(companies, prices, no_shares).set_index("ticker").loc["TEST"]
    assert pd.isna(without_dividends["market_cap"]) and pd.isna(without_dividends["pe_ttm"])  # empty, not wrong


# ----------------------------------------------------------------- schemas

def test_conform_types_order_and_load_timestamp(inputs):
    out = conform(build_snapshot(*inputs), "stock_snapshot")
    assert list(out.columns) == columns("stock_snapshot")
    assert str(out["price_date"].dtype).startswith("datetime64") and out["fiscal_year"].dtype == "Int64"
    assert out["is_financial"].dtype == "boolean" and out["updated_at"].notna().all()


def test_conform_rejects_unknown_columns():
    with pytest.raises(ValueError, match="typo_column"):
        conform(pd.DataFrame({"series_id": ["X"], "typo_column": [1]}), "macro")


def test_ndjson_is_what_bigquery_expects():
    df = pd.DataFrame({"ticker": ["AAA", "AAA"], "price_date": ["2024-06-28", "2024-07-01"],
                       "close": [10.5, None], "trade_count": [12, None]})
    lines = to_ndjson(conform(df, "prices", loaded_at=pd.Timestamp("2024-07-02 06:00", tz="UTC")), "prices")
    first, second = [json.loads(line) for line in lines.strip().split("\n")]
    assert first["price_date"] == "2024-06-28" and first["close"] == 10.5 and first["trade_count"] == 12
    assert first["updated_at"] == "2024-07-02T06:00:00Z"
    assert second["close"] is None and second["trade_count"] is None and second["open"] is None


def test_every_table_has_documented_unique_columns():
    for name, spec in TABLES.items():
        names = [c[0] for c in spec["columns"]]
        assert len(names) == len(set(names)), name
        assert all(doc for _, _, doc in spec["columns"]), name
        assert set(spec.get("cluster", [])) <= set(names), name
