from pipeline import universe
from tests import fakes


def test_universe_keeps_us_filers_in_order_and_existing_tickers():
    listing = {"data": [
        [1, "Big Co", "BIG", "Nasdaq"],
        [1, "Big Co class C", "BIGC", "Nasdaq"],   # second share class of the same company
        [2, "Foreign Co", "FRN", "NYSE"],          # files 20-F, not 10-K
        [3, "Otc Co", "OTCX", "OTC"],              # not on NYSE / Nasdaq
        [4, "Berkshire", "BRK-B", "NYSE"],
        [5, "Too Small", "SML", "NYSE"],
    ]}

    def handler(url, params):
        if url == universe.EXCHANGE_LIST_URL:
            return listing
        form = "20-F" if "CIK0000000002" in url else "10-K"
        return fakes.submissions(extra_filings=[("0001-26-000001", "2026-02-01", "2025-12-31", form, "", "a.htm", form)])

    client = fakes.FakeClient(handler)
    chosen = universe.build(client, size=3, keep=["KEEP"], since="2025-06-01")
    assert chosen == ["KEEP", "BIG", "BRK.B"]
