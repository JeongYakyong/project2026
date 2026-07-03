# -*- coding: utf-8 -*-
"""Gascast — 국가 가스수급 예측 플랫폼 (Streamlit 엔트리: 전국 / 제주).

실행:  streamlit run "8. streamlit/app.py"
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C

st.set_page_config(page_title="Gascast — 국가 가스수급 예측 플랫폼", page_icon="⚡", layout="wide")
C.inject_style()

pg = st.navigation([
    st.Page("page_land.py", title="전국", icon=":material/public:", default=True),
    st.Page("page_jeju.py", title="제주", icon=":material/landscape:"),
])
pg.run()
