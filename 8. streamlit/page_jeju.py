# -*- coding: utf-8 -*-
"""제주 페이지 — 골격(8-B에서 구현). 데이터 현황만 동작."""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C

C.page_header(
    "JEJU · DAILY BRIEFING", "제주 발전 브리핑",
    "신재생이 만든 잔여부하가 SMP를 흔든다 — 2→3→4 서빙 체인의 사전 적재 예측",
    [("수요", C.COLOR["demand"]), ("신재생", C.COLOR["renew"]),
     ("net_load", C.COLOR["net_load"]), ("SMP", "#d62728")])
menu = st.sidebar.radio("메뉴", ["종합", "수요 예측", "데이터 현황", "SMP 예측"])

if menu == "데이터 현황":
    st.subheader("데이터 적재 현황 (제주 DB)")
    st.dataframe(C.coverage_table("jeju"), width="stretch", hide_index=True)
    st.caption("수집은 crontab 백그라운드에서만 갱신됩니다(API 한도 보호 — 사용자 트리거 없음).")
elif menu == "SMP 예측":
    st.info("SMP 예측(D+1/D+2 + 음수가격 경보, 4단계)은 8-B에서 구현 예정입니다. "
            "백필은 2025-12-13~ 보유 중입니다.")
else:
    st.info("제주 종합·수요 예측은 8-B에서 구현 예정입니다. "
            "선행 작업: 2-B 수요 서빙(`jeju_est_demand_lh`)·하이브리드 신재생 서빙 백필.")
