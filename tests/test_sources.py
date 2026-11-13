from datetime import datetime, timezone

import pytest
import requests

from pipeline import alpaca, edgar, fred
from pipeline.net import Client
from tests import fakes


# ------------------------------------------------------------------- EDGAR

def test_flatten_facts_keeps_every_fact_and_tag_label():
    facts, tags = edgar.flatten_facts("TEST", fakes.payload(fakes.flow("Revenues", 2023, [1, 2, 3, 4])))
    assert len(facts) == 6  # Q1, 6M, Q2, 9M, Q3, FY
    fy = facts[facts["form"] == "10-K"].iloc[0]
    assert (fy["start_date"], fy["end_date"], fy["value"], fy["filed_date"]) == \
        ("2023-01-01", "2023-12-31", 10, "2024-02-10")
    assert tags.iloc[0].to_dict() == {"taxonomy": "us-gaap", "tag": "Revenues", "label": "Revenues",
                                      "description": "About Revenues"}


def test_parse_company():
    company = edgar.parse_company("TEST", "0000000001", fakes.submissions())
    assert company["company_name"] == "Test Co" and company["sector"] == "Technology"
    assert company["is_financial"] is False
    assert company["earliest_filing_date"] == "2024-02-10"
    assert edgar.parse_company("BANK", "2", fakes.submissions(sic="6021"))["is_financial"] is True


def test_sector_only_where_the_sic_code_implies_one():
    from pipeline import config
    assert config.sector_for_sic("3674") == "Technology"
    assert config.sector_for_sic("6324") == "Health Care"   # health insurers, inside the finance range
    assert config.sector_for_sic("6021") == "Financials"
    for mixed in ("7389", "3841", "7370", None, ""):        # codes that mix sectors: empty, not a guess
        assert config.sector_for_sic(mixed) is None


def test_parse_filings_filters_labels_and_links():
    sub = fakes.submissions()
    rows = edgar.parse_filings("TEST", "0000000001", [sub["filings"]["recent"]], cutoff="2024-03-01")
    forms = {r["form"] for r in rows}
    assert forms == {"10-Q", "8-K", "4"}  # 424B2 is noise, the 10-K is before the cutoff
    eight_k = next(r for r in rows if r["form"] == "8-K")
    assert eight_k["event_labels"] == "Earnings results released; Financial statements and exhibits"
    assert eight_k["url"] == "https://www.sec.gov/Archives/edgar/data/1/000124000003/tc-8k.htm"
    assert eight_k["accepted_at"] == "2024-05-02T16:30:00.000Z"


def test_parse_filings_ignores_duplicates_across_pages():
    block = fakes.submissions()["filings"]["recent"]
    assert len(edgar.parse_filings("TEST", "1", [block, block], cutoff="2000-01-01")) == 4


def test_older_filing_pages_fetched_only_inside_the_window():
    sub = fakes.submissions()
    sub["filings"]["files"] = [{"name": "old.json", "filingFrom": "2010-01-01", "filingTo": "2015-01-01"},
                               {"name": "mid.json", "filingFrom": "2021-01-01", "filingTo": "2023-06-01"}]
    client = fakes.FakeClient(lambda url, params: {"accessionNumber": []})
    blocks = edgar.fetch_filing_blocks(client, sub, cutoff="2022-01-01")
    assert len(blocks) == 2
    assert [url for url, _ in client.calls] == ["https://data.sec.gov/submissions/mid.json"]


def test_cik_map_and_ticker_format():
    client = fakes.FakeClient(lambda url, params: {"0": {"cik_str": 1067983, "ticker": "BRK-B", "title": "x"}})
    assert edgar.fetch_cik_map(client) == {"BRK-B": "0001067983"}
    assert edgar.sec_ticker("BRK.B") == "BRK-B"


def test_parse_form4():
    sale, award = edgar.parse_form4(fakes.FORM4_XML)
    assert sale["owner_name"] == "DOE JANE" and sale["officer_title"] == "Chief Financial Officer"
    assert (sale["is_officer"], sale["is_director"], sale["is_ten_percent_owner"]) == (True, False, False)
    assert (sale["transaction_code"], sale["transaction_label"]) == ("S", "Open-market sale")
    assert (sale["shares"], sale["price_per_share"], sale["value"]) == (1000, 190.5, 190500)
    assert sale["shares_owned_after"] == 25000 and sale["ownership"] == "D"
    assert award["transaction_label"] == "Grant or award"
    assert award["price_per_share"] is None and award["value"] is None  # price given only as a footnote


def test_form4_url_points_at_raw_xml():
    assert edgar.form4_url("0000000001", "0001-24-000004", "xslF345X05/form4.xml") == \
        "https://www.sec.gov/Archives/edgar/data/1/000124000004/form4.xml"


# ------------------------------------------------------------------ Alpaca

NOW = datetime(2024, 7, 1, 21, 0, tzinfo=timezone.utc)  # 17:00 in New York


def bars_handler(url, params):
    all_bars = fakes.bars(["AAA", "BBB"], days=3, end="2024-07-01")
    if params["adjustment"] == "all":
        all_bars = {s: [{**b, "c": b["c"] * 0.9} for b in rows] for s, rows in all_bars.items()}
    if "page_token" not in params:  # two pages, to exercise pagination
        return {"bars": {"AAA": all_bars["AAA"]}, "next_page_token": "next"}
    return {"bars": {"BBB": all_bars["BBB"]}, "next_page_token": None}


def test_fetch_prices_paginates_merges_and_drops_today():
    client = fakes.FakeClient(bars_handler)
    prices = alpaca.fetch_prices(client, ["AAA", "BBB"], "2016-01-01", now=NOW)
    assert set(prices["ticker"]) == {"AAA", "BBB"}
    assert sorted(prices["price_date"].unique()) == ["2024-06-27", "2024-06-28"]  # 07-01 is "today"
    assert (prices["close_total_return"] / prices["close"]).round(6).eq(0.9).all()
    first = client.calls[0][1]
    assert first["feed"] == "sip" and first["adjustment"] == "split,spin-off" and first["symbols"] == "AAA,BBB"
    assert first["end"] == "2024-07-01T20:40:00Z"  # 20 minutes back: the free plan's SIP limit
    assert len(client.calls) == 4


def test_fetch_corporate_actions():
    client = fakes.FakeClient(lambda url, params: {"corporate_actions": {
        "forward_splits": [{"symbol": "AAA", "new_rate": 4, "old_rate": 1, "ex_date": "2020-08-31"}],
        "reverse_splits": [{"symbol": "BBB", "new_rate": 1, "old_rate": 8, "ex_date": "2021-01-04"}],
        "cash_dividends": [{"symbol": "AAA", "rate": 0.24, "special": False, "ex_date": "2024-05-10",
                            "record_date": "2024-05-13", "payable_date": "2024-05-16"}]}})
    actions = alpaca.fetch_corporate_actions(client, ["AAA", "BBB"], "2009-01-01", "2024-07-01")
    by_type = actions.set_index("action_type")
    assert by_type.loc["forward_split", "split_ratio"] == 4
    assert by_type.loc["reverse_split", "split_ratio"] == 0.125
    assert by_type.loc["cash_dividend", "cash_amount"] == 0.24
    assert by_type.loc["cash_dividend", "is_special"] == False  # noqa: E712
    assert client.calls[0][0].endswith("/v1/corporate-actions")


def test_fetch_news_one_row_per_tracked_ticker():
    article = {"id": 7, "headline": "AAA beats", "summary": "", "author": "Jo", "source": "benzinga",
               "url": "https://example.com/a", "created_at": "2024-06-28T12:00:00Z",
               "updated_at": "2024-06-28T12:05:00Z", "symbols": ["AAA", "BBB", "ZZZ"]}
    client = fakes.FakeClient(lambda url, params: {"news": [article], "next_page_token": None})
    news = alpaca.fetch_news(client, ["AAA", "BBB"], "2024-06-01", "2024-07-01")
    assert sorted(news["ticker"]) == ["AAA", "BBB"]  # ZZZ is not tracked
    assert news["n_symbols"].eq(3).all() and news["all_symbols"].eq("AAA,BBB,ZZZ").all()
    assert news["summary"].isna().all()


def test_alpaca_requests_are_batched_without_duplicates(monkeypatch):
    monkeypatch.setattr("pipeline.config.ALPACA_BATCH", 2)
    symbols = ["AAA", "BBB", "CCC", "DDD", "EEE"]
    article = {"id": 7, "headline": "h", "summary": "", "author": "Jo", "source": "benzinga",
               "url": "https://example.com/a", "created_at": "2024-06-28T12:00:00Z",
               "updated_at": "2024-06-28T12:05:00Z", "symbols": ["BBB", "CCC"]}

    def handler(url, params):
        if url.endswith("/news"):
            return {"news": [article], "next_page_token": None}
        if url.endswith("/corporate-actions"):
            return {"corporate_actions": {"cash_dividends": [
                {"symbol": s, "rate": 1.0, "special": False, "ex_date": "2024-05-10"}
                for s in params["symbols"].split(",")]}}
        return {"bars": fakes.bars(params["symbols"].split(","), days=3, end="2024-07-01"), "next_page_token": None}
    client = fakes.FakeClient(handler)
    prices = alpaca.fetch_prices(client, symbols, "2024-06-01", now=NOW)
    actions = alpaca.fetch_corporate_actions(client, symbols, "2009-01-01", "2024-07-01")
    news = alpaca.fetch_news(client, symbols, "2024-06-01", "2024-07-01")
    assert all(len(params["symbols"].split(",")) <= 2 for _, params in client.calls)
    assert sorted(prices["ticker"].unique()) == symbols and sorted(actions["ticker"]) == symbols
    assert sorted(news["ticker"]) == ["BBB", "CCC"]  # one row each, though they sit in different batches


# -------------------------------------------------------------------- FRED

def test_fred_skips_missing_observations():
    client = fakes.FakeClient(lambda url, params: {"observations": [
        {"date": "2024-05-01", "value": "5.33"}, {"date": "2024-05-02", "value": "."}]})
    series = fred.fetch_series(client, "key", "FEDFUNDS", "Fed funds rate (%)")
    assert series[["obs_date", "value"]].values.tolist() == [["2024-05-01", 5.33]]


# ------------------------------------------------------------- HTTP client

class FakeSession:
    def __init__(self, statuses):
        self.statuses, self.headers, self.calls = list(statuses), {}, 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        status = self.statuses.pop(0)
        if status == "boom":
            raise requests.ConnectionError("network down")
        response = requests.Response()
        response.status_code, response._content = status, b'{"ok": true}'
        return response


def make_client(statuses, **kwargs):
    sleeps = []
    session = FakeSession(statuses)
    return Client(session=session, sleep=sleeps.append, **kwargs), session, sleeps


def test_client_retries_then_succeeds():
    client, session, sleeps = make_client([503, "boom", 200])
    assert client.get_json("https://x") == {"ok": True}
    assert session.calls == 3 and len([s for s in sleeps if s >= 1]) == 2


def test_client_gives_up_after_retries():
    client, session, _ = make_client([500] * 3, retries=2)
    with pytest.raises(requests.HTTPError, match="500"):
        client.get("https://x")
    assert session.calls == 3


def test_client_does_not_retry_a_plain_error():
    client, session, _ = make_client([404, 200])
    with pytest.raises(requests.HTTPError, match="404"):
        client.get("https://x")
    assert session.calls == 1


def test_client_spaces_out_requests():
    ticks = iter([0.0, 0.05, 0.05, 1.0])
    sleeps = []
    client = Client(session=FakeSession([200, 200]), max_per_second=5, sleep=sleeps.append,
                    clock=lambda: next(ticks))
    client.get("https://x")
    client.get("https://x")
    assert sleeps == [pytest.approx(0.15)]
