"""Where the data is incomplete or suspicious. Read this before trusting a number."""
import pandas as pd
import streamlit as st

from app_data import load
from pipeline import config

st.title("Data quality")
universe = set(config.load_universe())
snapshot = load("stock_snapshot")
prices = load("prices")
fundamentals = load("fundamentals")
today = pd.Timestamp.now().normalize()


def report(title: str, problems: pd.DataFrame, ok: str, help_text: str = ""):
    with st.container(border=True):
        st.markdown(f"##### {title}")
        if help_text:
            st.caption(help_text)
        if problems.empty:
            st.success(ok)
        else:
            st.warning(f"{len(problems)} to check")
            st.dataframe(problems, hide_index=True)


# ------------------------------------------------------- freshness and coverage
DATE_COLUMN = {"companies": None, "prices": "price_date", "corporate_actions": "ex_date",
               "fundamentals": "period_end", "filings": "filing_date", "insider_trades": "filing_date",
               "news": "published_at", "macro": "obs_date", "stock_snapshot": "price_date"}
rows = []
for table, date_column in DATE_COLUMN.items():
    try:
        df = load(table)
    except Exception as error:  # a table that never loaded should show up here, not crash the page
        rows.append({"table": table, "rows": 0, "problem": str(error)[:80]})
        continue
    covered = set(df["ticker"]) if "ticker" in df.columns else None
    rows.append({
        "table": table, "rows": len(df),
        "tickers": len(covered & universe) if covered is not None else None,
        "missing tickers": ", ".join(sorted(universe - covered)) if covered is not None else "",
        "latest data": df[date_column].max() if date_column else None,
        "loaded at": df["updated_at"].max() if "updated_at" in df.columns else None,
    })
with st.container(border=True):
    st.markdown(f"##### Tables — {len(universe)} stocks tracked")
    st.caption("xbrl_facts and xbrl_tags are not listed: they are large and only feed `fundamentals`. "
               "Some stocks legitimately have no insider trades or dividends.")
    st.dataframe(pd.DataFrame(rows), hide_index=True)

# ------------------------------------------------------------------ staleness
latest_price = prices.groupby("ticker")["price_date"].max().reset_index()
report("Stale prices", latest_price[latest_price["price_date"] < latest_price["price_date"].max()],
       "Every stock has the latest trading day.")

latest_quarter = (fundamentals[fundamentals["period_type"] == "Q"].groupby("ticker")["period_end"].max()
                  .reset_index().assign(days_old=lambda d: (today - d["period_end"]).dt.days))
report("Stale fundamentals", latest_quarter[latest_quarter["days_old"] > 150],
       "Every stock has a quarter that ended within 150 days.",
       "A quarter is normally filed 4-6 weeks after it ends, and annual results up to 9 weeks after.")

# ------------------------------------------------------- suspicious numbers
moves = prices.sort_values(["ticker", "price_date"]).assign(
    change=lambda d: d.groupby("ticker")["close"].pct_change())
report("Price jumps over 40% in a day", moves.loc[moves["change"].abs() > 0.4, ["ticker", "price_date", "close", "change"]],
       "None: prices look correctly split-adjusted.", "Usually a split that was not adjusted.")

eps = fundamentals[(fundamentals["period_type"] == "FY") & fundamentals["eps_diluted_yoy"].notna()]
report("Annual EPS up more than 5x or down more than 80%",
       eps.loc[(eps["eps_diluted_yoy"] > 4) | (eps["eps_diluted_yoy"] < -0.8),
               ["ticker", "period_end", "eps_diluted", "eps_diluted_yoy"]],
       "No extreme EPS changes.",
       "Can be real (a recovery, a one-off charge) but also the signature of a split missing from the split calendar.")

checks = {
    "Market cap missing or under $5B (share count missing or wrong)": ~(snapshot["market_cap"] >= 5e9),
    "P/E above 300": snapshot["pe_ttm"] > 300,
    "Gross margin outside 0-100%": (snapshot["gross_margin"] < 0) | (snapshot["gross_margin"] > 1),
    "Revenue missing or not positive": ~(snapshot["revenue_ttm"] > 0),
    "No trailing-12-month figures": snapshot["fundamentals_period_end"].isna(),
}
flagged = pd.concat([snapshot.loc[mask, ["ticker", "company_name"]].assign(problem=name)
                     for name, mask in checks.items()])
report("Implausible snapshot values", flagged, "Nothing implausible in the snapshot.")

duplicates = pd.DataFrame([
    {"table": "prices", "duplicate rows": int(prices.duplicated(["ticker", "price_date"]).sum())},
    {"table": "fundamentals", "duplicate rows": int(fundamentals.duplicated(["ticker", "period_type", "period_end"]).sum())},
    {"table": "stock_snapshot", "duplicate rows": int(snapshot.duplicated(["ticker"]).sum())}])
report("Duplicate rows", duplicates[duplicates["duplicate rows"] > 0], "No duplicates.")

# --------------------------------------------------------------- completeness
with st.container(border=True):
    st.markdown("##### Snapshot completeness")
    st.caption("Share of non-financial stocks with a value. Financials are excluded because several "
               "metrics are left empty for them on purpose.")
    regular = snapshot[snapshot["is_financial"] != True]  # noqa: E712
    filled = regular.notna().mean().rename("filled").reset_index().rename(columns={"index": "column"})
    filled["missing for"] = [", ".join(regular.loc[regular[c].isna(), "ticker"]) for c in filled["column"]]
    st.dataframe(filled[filled["filled"] < 1].sort_values("filled"), hide_index=True,
                 column_config={"filled": st.column_config.ProgressColumn("filled", min_value=0, max_value=1)})

with st.container(border=True):
    st.markdown("##### Fundamentals depth per stock")
    depth = fundamentals.pivot_table(index="ticker", columns="period_type", values="period_end", aggfunc="count")
    depth["first period"] = fundamentals.groupby("ticker")["period_end"].min()
    depth["latest period"] = fundamentals.groupby("ticker")["period_end"].max()
    st.dataframe(depth.reset_index(), hide_index=True)
