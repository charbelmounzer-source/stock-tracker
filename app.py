"""Internal viewer for the data foundation. Not the product UI: its job is to make
the data easy to inspect and to show where it is incomplete."""
import streamlit as st

st.navigation([
    st.Page("pages/1_Explorer.py", title="Stock explorer", icon="📈"),
    st.Page("pages/2_Data_Quality.py", title="Data quality", icon="🔍"),
]).run()
