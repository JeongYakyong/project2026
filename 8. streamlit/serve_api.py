# -*- coding: utf-8 -*-
"""Gascast — 가스 수급 예측 + AI 브리핑 제공 API (FastAPI).

계산은 전부 기존 모듈(common·brief_ai·brief_store) 재사용 — 새 로직 없음.

엔드포인트:
  GET /forecast?start=YYYY-MM-DD&days=N      예측 시계열(수요·신재생·가스발전·송출 TON)
  GET /chart?start=&days=                    예측을 대화형 차트(HTML)로 제공
  GET /brief?start=&days=&kind=&generate=    저장된 AI 브리핑(없으면 generate=true로 생성·저장)
  GET /bundle?start=&days=&kind=&generate=   시계열 + 브리핑 텍스트를 한 번에 제공
  GET /briefings                             저장된 브리핑 목록

실행:  uvicorn serve_api:app --port 8800   (cwd = 8. streamlit)
문서:  http://localhost:8800/docs           (Swagger UI)

주의: API는 use_live=False — DB만 읽고 KPX/KMA 수집은 절대 트리거하지 않는다(한도 보호).
"""
import os
import sys
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brief_ai
import brief_store as store

KINDS = ("overview", "sendout", "weather")

# Caddy 등 리버스 프록시가 /api 경로 아래 둘 때 Swagger·openapi 가 깨지지 않게 root_path 설정.
# 프록시 없이 직접 띄울 땐 빈 값 → 동작 변화 없음.  배포 시 = SERVE_API_ROOT_PATH=/api
ROOT_PATH = os.environ.get("SERVE_API_ROOT_PATH", "")
app = FastAPI(title="Gascast — 국가 가스수급 예측 API", version="0.1",
              root_path=ROOT_PATH,
              description="가스 수급 예측(수요→신재생→가스 송출)과 AI 브리핑을 외부 시스템에 제공합니다.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])   # 다양한 환경에서 호출 가능하게


def _resolve(start: str | None) -> pd.Timestamp:
    return pd.Timestamp(start).normalize() if start else pd.Timestamp.now().normalize()


def _series_records(sd: pd.Timestamp, days: int) -> list[dict]:
    """예측 시계열 → JSON 직렬화(결측은 null)."""
    ser = brief_ai.forecast_series(sd, days, use_live=False)
    ser = ser.assign(timestamp=ser["timestamp"].astype(str))
    ser = ser.where(pd.notna(ser), None)
    return ser.to_dict("records")


@app.get("/")
def root():
    return {"service": "Gascast forecast + ai-brief",
            "endpoints": ["/forecast", "/chart", "/brief", "/bundle", "/briefings", "/docs"],
            "kinds": list(KINDS)}


@app.get("/forecast")
def forecast(start: str | None = Query(None, description="시작일 YYYY-MM-DD(기본 오늘)"),
             days: int = Query(1, ge=1, le=15, description="시작일부터 N일")):
    """예측 시계열 — 수요(MW)·신재생(MW)·가스발전(MW)·송출(TON/h)."""
    sd = _resolve(start)
    recs = _series_records(sd, days)
    return {"region": "land", "start": sd.strftime("%Y-%m-%d"), "days": days,
            "fields": ["timestamp", "horizon_d", "demand_mw", "renew_mw",
                       "gas_gen_mw", "sendout_ton"],
            "n_rows": len(recs), "series": recs}


@app.get("/chart", response_class=HTMLResponse)
def chart(start: str | None = Query(None, description="시작일 YYYY-MM-DD(기본 오늘)"),
          days: int = Query(1, ge=1, le=15, description="시작일부터 N일")):
    """예측 시계열을 인터랙티브 차트(HTML)로 바로 제공 — 링크만 열면 그림이 뜬다.

    데이터(/forecast)와 같은 값을 plotly 로 그린다. 브라우저가 렌더하므로 한글 폰트 문제 없음.
    """
    import plotly.graph_objects as go   # lazy — 다른 엔드포인트는 plotly 없이도 동작
    sd = _resolve(start)
    ser = brief_ai.forecast_series(sd, days, use_live=False)
    if ser.empty or ser["sendout_ton"].dropna().empty:   # 행은 있어도 값이 전부 비면 404
        raise HTTPException(404, f"{sd:%Y-%m-%d} 예측이 적재 범위에 없습니다.")

    fig = go.Figure()
    fig.add_scatter(x=ser["timestamp"], y=ser["sendout_ton"], name="가스 송출 (TON/h)",
                    line=dict(color="#c2410c", width=2.4))
    fig.add_scatter(x=ser["timestamp"], y=ser["demand_mw"], name="전력수요 (MW)",
                    line=dict(color="#1d4ed8", width=1.6, dash="dot"), yaxis="y2")
    fig.add_scatter(x=ser["timestamp"], y=ser["renew_mw"], name="신재생 (MW)",
                    line=dict(color="#059669", width=1.6, dash="dot"), yaxis="y2")
    fig.update_layout(
        title=f"Gascast 가스 송출량 예측 · {sd:%Y-%m-%d} 부터 {days}일",
        xaxis=dict(title="시각"),
        yaxis=dict(title="가스 송출 (TON/h)"),
        yaxis2=dict(title="전력수요·신재생 (MW)", overlaying="y", side="right", showgrid=False),
        legend=dict(orientation="h", y=1.1, x=0),
        template="plotly_white", height=560, margin=dict(t=80, r=70, l=70, b=50),
        hovermode="x unified")
    return fig.to_html(include_plotlyjs="cdn", full_html=True)


def _make_brief(sd: pd.Timestamp, start: str, days: int, kind: str) -> dict:
    """없는 브리핑을 생성·저장하고 레코드 반환(Gemini 호출 — generate=true일 때만)."""
    _end, _df, facts = brief_ai.assemble_facts(sd, days, kind, use_live=False)
    text = brief_ai.generate_brief(kind, facts)
    ca = store.save(start, days, kind, text, fact_text=facts, model=brief_ai.GEMINI_MODEL)
    return {"region": "land", "start_date": start, "days": days, "kind": kind,
            "brief_text": text, "fact_text": facts, "model": brief_ai.GEMINI_MODEL,
            "created_at": ca}


@app.get("/brief")
def brief(start: str = Query(..., description="시작일 YYYY-MM-DD"),
          days: int = Query(1, ge=1, le=15),
          kind: str = Query("overview"),
          generate: bool = Query(False, description="저장본이 없으면 새로 생성(Gemini 호출)")):
    """저장된 AI 브리핑 조회 — (시작일·지평·종류) 키. 없으면 generate=true로 생성."""
    if kind not in KINDS:
        raise HTTPException(400, f"kind는 {KINDS} 중 하나")
    sd = _resolve(start)
    rec = store.load(start, days, kind)
    if rec is None:
        if not generate:
            raise HTTPException(404, "저장된 브리핑 없음 — generate=true로 생성하세요.")
        rec = _make_brief(sd, start, days, kind)
    return rec


@app.get("/bundle")
def bundle(start: str = Query(..., description="시작일 YYYY-MM-DD"),
           days: int = Query(1, ge=1, le=15),
           kind: str = Query("overview"),
           generate: bool = Query(False)):
    """예측 시계열 + AI 브리핑 텍스트를 한 번에 제공(다른 시스템 연동용)."""
    if kind not in KINDS:
        raise HTTPException(400, f"kind는 {KINDS} 중 하나")
    sd = _resolve(start)
    recs = _series_records(sd, days)
    rec = store.load(start, days, kind)
    if rec is None and generate:
        rec = _make_brief(sd, start, days, kind)
    return {"region": "land", "start": sd.strftime("%Y-%m-%d"), "days": days, "kind": kind,
            "forecast": {"fields": ["timestamp", "horizon_d", "demand_mw", "renew_mw",
                                    "gas_gen_mw", "sendout_ton"],
                         "n_rows": len(recs), "series": recs},
            "brief": rec}   # 저장본 없고 generate=false면 null


@app.get("/briefings")
def briefings(limit: int = Query(50, ge=1, le=500)):
    """저장된 브리핑 목록(최근 순) — 카테고리 메타 + 미리보기."""
    return {"items": store.list_all(region="land", limit=limit)}
