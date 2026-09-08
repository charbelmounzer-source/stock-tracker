symbols = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "JPM", "V", "NFLX",
    "JNJ", "PFE", "UNH", "ABBV", "MRK",
    "XOM", "CVX", "COP",
    "BA", "CAT", "GE", "HON",
    "KO", "PEP", "PG", "WMT", "COST",
    "HD", "MCD", "NKE", "SBUX", "DIS",
    "GS", "MS", "BRK.B",
    "VZ", "T",
    "NEE", "DUK",
    "LIN",
    "PLD",
    "AVGO", "AMD", "INTC",
    "ORCL", "CRM", "ADBE", "IBM", "CSCO",
]

ticker_to_cik = {
    'NVDA': '0001045810', 'AAPL': '0000320193', 'GOOGL': '0001652044',
    'MSFT': '0000789019', 'AMZN': '0001018724', 'META': '0001326801',
    'TSLA': '0001318605', 'JPM': '0000019617', 'V': '0001403161',
    'NFLX': '0001065280',
    'AVGO': '0001730168', 'WMT': '0000104169', 'AMD': '0000002488', 'JNJ': '0000200406',
    'XOM': '0000034088', 'INTC': '0000050863', 'ABBV': '0001551152', 'ORCL': '0001341439',
    'CSCO': '0000858877', 'CVX': '0000093410', 'COST': '0000909832', 'KO': '0000021344',
    'MRK': '0000310158', 'CAT': '0000018230', 'UNH': '0000731766', 'GE': '0000040545',
    'PG': '0000080424', 'MS': '0000895421', 'HD': '0000354950', 'GS': '0000886982',
    'LIN': '0001707925', 'IBM': '0000051143', 'CRM': '0001108524', 'VZ': '0000732712',
    'PEP': '0000077476', 'DIS': '0001744489', 'MCD': '0000063908', 'T': '0000732717',
    'NEE': '0000753308', 'BA': '0000012927', 'PFE': '0000078003', 'COP': '0001163165',
    'PLD': '0001045609', 'SBUX': '0000829224', 'ADBE': '0000796343', 'DUK': '0001326160',
    'HON': '0000773840', 'NKE': '0000320187', 'BRK.B': '0001067983',
}

sector_macro_mapping = [
    {
        "sic_range": (6000, 6999),
        "series": [
            ("FEDFUNDS", "Fed Funds Rate", "Higher rates squeeze bank lending margins and loan demand — rising rates are mixed, falling rates generally ease pressure."),
            ("DGS10", "10-Year Treasury Yield", "Banks borrow short and lend long — a steeper yield curve (higher long rates) tends to help profitability."),
        ],
    },
    {
        "sic_range": (1300, 1399),
        "series": [
            ("DCOILWTICO", "WTI Oil Price", "Direct revenue driver — higher oil prices are generally good for this sector's earnings."),
        ],
    },
    {
        "sic_range": (4500, 4599),
        "series": [
            ("DCOILWTICO", "WTI Oil Price", "Jet fuel is a major cost — higher oil prices hurt margins."),
            ("UNRATE", "Unemployment Rate", "Air travel is discretionary — rising unemployment tends to reduce demand."),
        ],
    },
    {
        "sic_range": (5200, 5999),
        "series": [
            ("UNRATE", "Unemployment Rate", "Consumer spending power — rising unemployment tends to reduce retail demand."),
            ("CPIAUCSL", "CPI (Inflation)", "High inflation can squeeze consumer budgets and raise input costs."),
        ],
    },
    {
        "sic_range": (2800, 2899),
        "series": [
            ("DCOILWTICO", "WTI Oil Price", "Oil is a key input cost — higher prices tend to raise production costs."),
        ],
    },
    {
        "sic_range": (3570, 3579),
        "series": [
            ("DGS10", "10-Year Treasury Yield", "Growth/tech valuations are sensitive to rates — higher yields tend to pressure high-multiple stocks."),
        ],
    },
    {
        "sic_range": (3674, 3674),
        "series": [
            ("DGS10", "10-Year Treasury Yield", "Growth valuations are rate-sensitive — higher yields tend to pressure high-multiple stocks."),
            ("FEDFUNDS", "Fed Funds Rate", "Affects the broader cost of capital for capital-intensive chip manufacturing."),
        ],
    },
    {
        "sic_range": (7370, 7379),
        "series": [
            ("DGS10", "10-Year Treasury Yield", "Growth/tech valuations are sensitive to rates — higher yields tend to pressure high-multiple stocks."),
        ],
    },
    {
        "sic_range": (3711, 3711),
        "series": [
            ("FEDFUNDS", "Fed Funds Rate", "Auto purchases are often financed — higher rates raise loan costs and can reduce demand."),
            ("UNRATE", "Unemployment Rate", "Vehicles are a big-ticket purchase — rising unemployment tends to reduce demand."),
        ],
    },
    {
        "sic_range": (7812, 7841),
        "series": [
            ("UNRATE", "Unemployment Rate", "Subscription spending is discretionary — rising unemployment can pressure demand."),
            ("CPIAUCSL", "CPI (Inflation)", "High inflation can squeeze household discretionary budgets."),
        ],
    },
]

DEFAULT_MACRO_SERIES = [
    ("FEDFUNDS", "Fed Funds Rate", "General cost-of-capital indicator, relevant to almost any company."),
    ("CPIAUCSL", "CPI (Inflation)", "Broad inflation gauge, affects costs and consumer spending economy-wide."),
]


def get_macro_series_for_sic(sic_code):
    try:
        sic_int = int(sic_code)
    except (TypeError, ValueError):
        return DEFAULT_MACRO_SERIES, False

    for entry in sector_macro_mapping:
        low, high = entry["sic_range"]
        if low <= sic_int <= high:
            return entry["series"], True

    return DEFAULT_MACRO_SERIES, False