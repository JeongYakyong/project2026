# -*- coding: utf-8 -*-
"""
8단계 — Streamlit 데모 엔트리 (멀티 페이지: 전국 / 제주)

명제: 신재생이 만든 잔여부하(net_load)를 가스 발전이 메운다.
체인: 5(수요) → 6(신재생) → 7(가스)의 사전 적재된 예측을 읽기 전용으로 표시한다.

실행:  streamlit run "8. streamlit/app.py"
G-15(PROJECT.md §7): 자체 서버 호스팅 / DB 직접 읽기 / 사전 적재 기본 + 시연 버튼 /
제주 페이지에 SMP 메뉴 포함(2026-06-10 설계 개편으로 ⑤ 번복).
"""
import streamlit as st

st.set_page_config(page_title="신재생→잔여부하→가스 브리핑", layout="wide")

pg = st.navigation([
    st.Page("page_land.py", title="전국", icon=":material/public:", default=True),
    st.Page("page_jeju.py", title="제주", icon=":material/landscape:"),
])
pg.run()
