import streamlit as st

home_page = st.Page("pages/1_Home.py", title="Home", icon="🏠")
sanity_page = st.Page("pages/2_Sanity_Checks.py", title="Sanity Checks", icon="🔍")

pg = st.navigation([home_page, sanity_page])
pg.run()