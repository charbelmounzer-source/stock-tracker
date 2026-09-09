import os
from wsgiref import types
from dotenv import load_dotenv
from google import genai
import pandas as pd
from edgar_data import compute_valuation_ratios
import time
import streamlit as st
from google.genai import types as genai_types



load_dotenv()

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def build_stock_summary(ticker, companies_df, prices_df, fundamentals_df):
    """
    Gathers everything relevant about one stock into a structured dict,
    ready to be turned into a prompt for the AI.
    """
    company = companies_df[companies_df["ticker"] == ticker].iloc[0]

    stock_prices = prices_df[prices_df["ticker"] == ticker].copy()
    stock_prices["price_date"] = pd.to_datetime(stock_prices["price_date"])
    stock_prices = stock_prices.sort_values("price_date")

    current_price = stock_prices["close"].iloc[-1]
    price_30d_ago = stock_prices["close"].iloc[-22] if len(stock_prices) >= 22 else stock_prices["close"].iloc[0]
    price_1y_ago = stock_prices["close"].iloc[-252] if len(stock_prices) >= 252 else stock_prices["close"].iloc[0]

    change_30d_pct = ((current_price - price_30d_ago) / price_30d_ago) * 100
    change_1y_pct = ((current_price - price_1y_ago) / price_1y_ago) * 100

    stock_fundamentals = fundamentals_df[fundamentals_df["ticker"] == ticker].copy()
    stock_fundamentals["period_end"] = pd.to_datetime(stock_fundamentals["period_end"])
    latest_fundamentals = stock_fundamentals.sort_values("period_end").iloc[-1]

    valuation = compute_valuation_ratios(latest_fundamentals.to_dict(), current_price)

    return {
        "ticker": ticker,
        "company_name": company["company_name"],
        "sector": company["sic_description"],
        "current_price": round(current_price, 2),
        "price_change_30d_pct": round(change_30d_pct, 1),
        "price_change_1y_pct": round(change_1y_pct, 1),
        "fiscal_year_end": str(latest_fundamentals["period_end"].date()),
        "revenue": latest_fundamentals["revenue"],
        "net_margin": latest_fundamentals["net_margin"],
        "gross_margin": latest_fundamentals["gross_margin"],
        "roe": latest_fundamentals["roe"],
        "leverage": latest_fundamentals["leverage"],
        "operating_cash_flow": latest_fundamentals["operating_cash_flow"],
        "ebitda": latest_fundamentals["ebitda"],
        "ev_to_sales": valuation["ev_to_sales"],
        "ev_to_ebitda": valuation["ev_to_ebitda"],
        "price_to_book": valuation["price_to_book"],
    }


def format_summary_for_prompt(summary):
    """Turns the raw summary dict into clean, readable text for the prompt."""
    def fmt_pct(x):
        return f"{x*100:.1f}%" if x is not None else "N/A"

    def fmt_money(x):
        return f"${x/1e9:.2f}B" if x is not None else "N/A"

    def fmt_ratio(x):
        return f"{x:.2f}x" if x is not None else "N/A"

    return f"""
Company: {summary['company_name']} ({summary['ticker']})
Sector: {summary['sector']}
Current price: ${summary['current_price']}
Price change (30 days): {summary['price_change_30d_pct']}%
Price change (1 year): {summary['price_change_1y_pct']}%
Fiscal year ending: {summary['fiscal_year_end']}

Revenue: {fmt_money(summary['revenue'])}
Net margin: {fmt_pct(summary['net_margin'])}
Gross margin: {fmt_pct(summary['gross_margin'])}
ROE: {fmt_pct(summary['roe'])}
Leverage (Liabilities/Equity): {fmt_ratio(summary['leverage'])}
Operating cash flow: {fmt_money(summary['operating_cash_flow'])}
EBITDA: {fmt_money(summary['ebitda'])}

EV/Sales: {fmt_ratio(summary['ev_to_sales'])}
EV/EBITDA: {fmt_ratio(summary['ev_to_ebitda'])}
Price to Book: {fmt_ratio(summary['price_to_book'])}
""".strip()


def get_ai_analysis(summary):
    """
    Sends the stock summary to Gemini and returns its analysis:
    key highlights + a buy/sell/hold read, clearly framed as informational.
    """
    prompt_data = format_summary_for_prompt(summary)

    prompt = f"""You are a financial analysis assistant. Based ONLY on the data below, provide:

1. **Key Highlights** (3-4 bullet points on the most notable aspects of this stock's fundamentals, valuation, and recent price action)
2. **Outlook**: One of Buy / Sell / Hold, with a one-sentence rationale

Be specific and reference actual numbers from the data. This is informational analysis only, not financial advice -- state this clearly.

DATA:
{prompt_data}
"""

    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
    )

    return response.text


def get_ai_analysis(summary, max_retries=3):
    prompt_data = format_summary_for_prompt(summary)

    prompt = f"""You are a financial analysis assistant. Based ONLY on the data below, provide:

1. **Key Highlights** (3-4 bullet points on the most notable aspects of this stock's fundamentals, valuation, and recent price action)
2. **Outlook**: One of Buy / Sell / Hold, with a one-sentence rationale

Be specific and reference actual numbers from the data. This is informational analysis only, not financial advice -- state this clearly.

DATA:
{prompt_data}
"""

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    max_output_tokens=400,
                ),
)
            return response.text
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                return f"AI analysis temporarily unavailable ({str(e)}). Please try again shortly."


@st.cache_data(ttl=3600)  # 1 hour
def get_cached_ai_analysis(ticker, summary_tuple):
    summary = dict(summary_tuple)
    return get_ai_analysis(summary)