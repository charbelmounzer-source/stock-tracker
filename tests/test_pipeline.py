"""End-to-end: the real pipeline code, with the three APIs replaced by fakes."""
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from pipeline import __main__ as runner
from pipeline import alpaca, edgar, fred
from pipeline.schemas import TABLES, columns
from tests import fakes

RECENT = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")


def edgar_handler(url, params):
    if url == edgar.TICKERS_URL:
        return {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple"},
                "1": {"cik_str": 1067983, "ticker": "BRK-B", "title": "Berkshire"}}
    if "/submissions/" in url:
        recent_form4 = ("0001-26-000009", RECENT, RECENT, "4", "", "xslF345X05/form4.xml", "FORM 4")
        return fakes.submissions(sic="6331" if "1067983" in url else "3571", extra_filings=[recent_form4])
    if "/companyfacts/" in url:
        return fakes.payload(fakes.standard_company())
    if url.endswith("form4.xml"):
        return fakes.FORM4_XML
    raise AssertionError(f"unexpected EDGAR call: {url}")


def alpaca_handler(url, params):
    symbols = params["symbols"].split(",")
    if url.endswith("/v2/stocks/bars"):
        return {"bars": fakes.bars(symbols), "next_page_token": None}
    if url.endswith("/v1/corporate-actions"):
        return {"corporate_actions": {"cash_dividends": [
            {"symbol": "AAPL", "rate": 0.25, "special": False, "ex_date": "2024-05-10"}]}}
    if url.endswith("/v1beta1/news"):
        return {"news": [{"id": 1, "headline": "Apple news", "summary": "s", "author": "a", "source": "benzinga",
                          "url": "https://example.com", "created_at": f"{RECENT}T10:00:00Z",
                          "updated_at": f"{RECENT}T10:00:00Z", "symbols": ["AAPL"]}], "next_page_token": None}
    raise AssertionError(f"unexpected Alpaca call: {url}")


def fred_handler(url, params):
    return {"observations": [{"date": "2024-06-01", "value": "5.33"}]}


@pytest.fixture
def fake_sources(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test")
    handlers = {"alpaca": alpaca_handler}
    monkeypatch.setattr(edgar, "client", lambda: fakes.FakeClient(edgar_handler))
    monkeypatch.setattr(alpaca, "client", lambda: fakes.FakeClient(lambda u, p: handlers["alpaca"](u, p)))
    monkeypatch.setattr(fred, "client", lambda: fakes.FakeClient(fred_handler))
    return handlers


def read(folder, table):
    return pd.read_csv(folder / f"{table}.csv")


def test_full_run_writes_every_table(fake_sources, tmp_path, capsys):
    assert runner.main(["--local", str(tmp_path), "--tickers", "AAPL,BRK.B"]) == 0
    for table in TABLES:
        df = read(tmp_path, table)
        assert len(df) > 0, table
        assert list(df.columns) == columns(table), table

    assert set(read(tmp_path, "prices")["ticker"]) == {"AAPL", "BRK.B", "SPY"}
    assert set(read(tmp_path, "filings")["form"]) == {"10-K", "10-Q", "8-K", "4"}
    trades = read(tmp_path, "insider_trades")
    assert len(trades) == 4 and set(trades["filing_date"]) == {RECENT}  # 2 trades x 2 companies

    snap = read(tmp_path, "stock_snapshot").set_index("ticker")
    apple, berkshire = snap.loc["AAPL"], snap.loc["BRK.B"]
    assert apple["market_cap"] == pytest.approx(apple["close"] * 1000)
    assert apple["pe_ttm"] > 0 and apple["ev_to_ebitda"] > 0
    assert apple["dividends_per_share_ttm"] == pytest.approx(0.25) and apple["dividend_yield"] > 0
    assert berkshire["shares"] == 1_500_000 and berkshire["dividend_yield"] == 0
    assert bool(berkshire["is_financial"]) and pd.isna(berkshire["ev_to_ebitda"])
    assert "FAILED" not in capsys.readouterr().out


def test_one_failing_source_does_not_stop_the_rest(fake_sources, tmp_path, capsys):
    def broken_news(url, params):
        if url.endswith("/news"):
            raise RuntimeError("news is down")
        return alpaca_handler(url, params)
    fake_sources["alpaca"] = broken_news

    assert runner.main(["--local", str(tmp_path), "--tickers", "AAPL"]) == 1
    assert not (tmp_path / "news.csv").exists()
    assert len(read(tmp_path, "stock_snapshot")) == 1
    out = capsys.readouterr().out
    assert "news         FAILED: news is down" in out and "snapshot     ok" in out


def test_predecessor_registrant_history_is_merged(fake_sources, tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.config.PREDECESSOR_CIKS", {"AAPL": ["0000000042"]})
    seen = []
    original = edgar.fetch_company_facts
    monkeypatch.setattr(edgar, "fetch_company_facts", lambda c, cik: seen.append(cik) or original(c, cik))
    assert runner.main(["--local", str(tmp_path), "--tickers", "AAPL", "--only", "facts,fundamentals"]) == 0
    assert seen == ["0000320193", "0000000042"]
    assert not read(tmp_path, "fundamentals").duplicated(["period_type", "period_end"]).any()


def test_only_runs_the_requested_steps(fake_sources, tmp_path):
    assert runner.main(["--local", str(tmp_path), "--tickers", "AAPL", "--only", "prices,macro"]) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["macro.csv", "prices.csv"]


def test_derived_step_without_its_input_is_reported(fake_sources, tmp_path, capsys):
    assert runner.main(["--local", str(tmp_path), "--tickers", "AAPL", "--only", "fundamentals"]) == 1
    assert "skipped (needs xbrl_facts" in capsys.readouterr().out


def test_unknown_ticker_or_step_is_rejected(fake_sources, tmp_path):
    for args in (["--tickers", "NOPE"], ["--only", "nope"]):
        with pytest.raises(SystemExit):
            runner.main(["--local", str(tmp_path), *args])
