# -*- coding: utf-8 -*-
"""전국 가스 송출량 AI 브리핑.

설계 원칙: 코드가 사실을 확정하고, LLM은 그 위에서 서술만 한다.
원시 시계열은 LLM에 넣지 않는다 — 코드가 통계로 압축한 '사실표(fact sheet)'만 넘겨
없는 수치를 지어낼 여지를 없앤다.
"""
from html import escape
from pathlib import Path
import json
import os
import re

import pandas as pd
import streamlit as st

import common as C
import brief_store as store

try:
    from dotenv import load_dotenv
    load_dotenv(C.DATA_DIR / ".env")          # GEMINI_API_KEY (수집기와 같은 .env)
except Exception:
    pass

# 모델 — 저비용·저지연, 버튼식 소량 호출에 충분. 더 풍부한 서술이 필요하면 상위 모델로 한 줄 변경.
GEMINI_MODEL = "gemini-3.1-flash-lite"

# 발전용 가스 단가 환산은 common(gas_cost_won)을 그대로 쓴다.
# 송출량(TON) = 발전량(MWh) × 0.1521. 여기선 est_gas_sendout_ton_land 저장값을 직접 읽는다.


# ============================================================ 시계열 요약 통계 (ground truth)
# 하루를 4구간으로 — 흐름(블록 평균)을 한 줄로 압축할 때 쓴다.
BLOCKS = [("심야(00-06)", 0, 5), ("오전(06-12)", 6, 11),
          ("오후(12-18)", 12, 17), ("저녁(18-24)", 18, 23)]
SOLAR_PEAK = (10, 15)   # 한낮 태양광 피크대 — '덕커브' 송출 저점을 여기서 찾는다
EVE_PEAK = (18, 21)     # 저녁 수요 피크대 — 송출 고점


def _flow(ts: pd.Series, s: pd.Series, fmt: str = "{:.1f}") -> str:
    """시간대 블록 평균 흐름 — '심야 12 → 오전 18 → 오후 9 → 저녁 22' 식."""
    h = ts.dt.hour
    parts = []
    for lab, a, b in BLOCKS:
        m = s[(h >= a) & (h <= b)]
        if m.notna().any():
            parts.append(f"{lab} {fmt.format(m.mean())}")
    return " → ".join(parts) if parts else "데이터 없음"


def _argext(ts: pd.Series, s: pd.Series, kind: str = "max"):
    """결측 무시 최대/최소와 그 발생 시각 → (값, Timestamp) 또는 None."""
    v = s.dropna()
    if v.empty:
        return None
    idx = v.idxmax() if kind == "max" else v.idxmin()
    return float(v.loc[idx]), pd.Timestamp(ts.loc[idx])


def _window_min(ts: pd.Series, s: pd.Series, lo: int, hi: int):
    """특정 시간대(lo~hi시) 안의 최소값·시각 — 한낮 덕커브 저점 탐지용."""
    h = ts.dt.hour
    sub = s[(h >= lo) & (h <= hi)]
    return _argext(ts, sub, "min")


def _window_max(ts: pd.Series, s: pd.Series, lo: int, hi: int):
    h = ts.dt.hour
    sub = s[(h >= lo) & (h <= hi)]
    return _argext(ts, sub, "max")


def _daily_sums(ts: pd.Series, s: pd.Series) -> pd.Series:
    """일별 합계(index=date). 다일 구간의 추세·변동성 계산 기반."""
    return s.groupby(ts.dt.date).sum(min_count=1).dropna()


def _stats(s: pd.Series) -> dict:
    """기초 통계 — 평균·표준편차·변동계수·분위수. 변동성=조달 불확실성의 핵심 지표."""
    v = s.dropna()
    if v.empty:
        return {}
    mean = float(v.mean())
    std = float(v.std(ddof=0))
    return {"mean": mean, "std": std,
            "cv": (std / abs(mean) * 100) if abs(mean) > 1e-9 else float("nan"),
            "p10": float(v.quantile(0.10)), "p50": float(v.quantile(0.50)),
            "p90": float(v.quantile(0.90))}


def _hhmm(t) -> str:
    return f"{pd.Timestamp(t):%m-%d %H시}" if t is not None else "—"


# ============================================================ 기상 추출 (forecast_horizon, tall)
WX_FIELDS = ["radiation", "total_cloud", "wind_spd_10m", "wind_spd_80m", "rainfall", "temp"]


def _fc_horizon(cols: list[str], start: str, end: str,
                mode: str = "latest", value=None) -> pd.DataFrame:
    """forecast_horizon(base×지평)에서 시계열 추출 — land_est_horizon과 같은 세 정리축."""
    cl = ", ".join(cols)
    if mode == "asof":
        base = pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")
        return C.query("land", f"SELECT timestamp, horizon_d, {cl} FROM forecast_horizon "
                       "WHERE base=? AND timestamp BETWEEN ? AND ? ORDER BY timestamp",
                       (base, start, end))
    if mode == "fixed":
        return C.query("land", f"SELECT timestamp, horizon_d, {cl} FROM forecast_horizon "
                       "WHERE horizon_d=? AND timestamp BETWEEN ? AND ? ORDER BY timestamp",
                       (int(value), start, end))
    ec = ", ".join(f"e.{c}" for c in cols)
    return C.query("land", f"SELECT e.timestamp, e.horizon_d, {ec} FROM forecast_horizon e "
                   "JOIN (SELECT timestamp, MIN(horizon_d) h FROM forecast_horizon "
                   "WHERE timestamp BETWEEN ? AND ? GROUP BY timestamp) m "
                   "ON e.timestamp=m.timestamp AND e.horizon_d=m.h ORDER BY e.timestamp",
                   (start, end))


def weather_national(start: str, end: str, mode: str = "latest", value=None) -> pd.DataFrame:
    """5개 대표 지점 평균 = 전국 기상 시계열(일사·운량·풍속·강수·기온)."""
    stns = C.STATIONS_LAND
    cols = [f"{f}_{s}" for f in WX_FIELDS for s in stns]
    raw = _fc_horizon(cols, start, end, mode, value)
    out = pd.DataFrame({"timestamp": raw.get("timestamp", pd.Series(dtype="datetime64[ns]"))})
    for f in WX_FIELDS:
        present = [f"{f}_{s}" for s in stns if f"{f}_{s}" in raw.columns]
        out[f] = raw[present].mean(axis=1) if present else float("nan")
    return out


# ============================================================ 사실표 구성 (kind별)
# 태양광 한낮 피크 이용률(0~1) → 크기 3단계 임계. 맑은 날 피크 ~0.8 가 거의 최대(사용자 기준).
# 조정 가능: 활발 ≥ HI / 낮다 [LO,HI) / 매우 낮다 < LO.
SOLAR_HI, SOLAR_LO = 0.55, 0.25
SOLAR_STATIONS = ["seosan", "pohang", "yeonggwang"]   # 태양광 3지점(서산·포항·영광)
RAIN_VAR_HOURS = 3                                    # 3지점 강수 시간 ≥ 이 값이면 '변동성 크다'


def _sendout_facts(start: pd.Timestamp, end: pd.Timestamp, df: pd.DataFrame,
                   prev_ton: float | None, citygas_total: float | None = None) -> list[str]:
    """가스 송출 사실 — 총량(발전용+도시가스)·시간당 피크/저점·덕커브·전일비·조달 변동폭."""
    ts = df["timestamp"]
    ton = df["est_gas_sendout_ton_land"]
    if ton.dropna().empty:
        return ["송출량 예측 없음(이 구간 예측 미보유)"]

    n_days = (end.normalize() - start.normalize()).days + 1
    gen_total = float(ton.sum())
    cost = float(C.gas_cost_won(ts, ton).sum())
    pk = _argext(ts, ton, "max")
    tr = _argext(ts, ton, "min")
    duck = _window_min(ts, ton, *SOLAR_PEAK)   # 한낮 저점
    eve = _window_max(ts, ton, *EVE_PEAK)      # 저녁 고점

    out = [f"구간: {start:%m-%d}~{end:%m-%d} ({n_days}일)"]
    if citygas_total and citygas_total > 0:
        out.append(f"총 천연가스 송출(예측): {gen_total + citygas_total:,.0f} TON "
                   f"= 발전용 {gen_total:,.0f} + 도시가스 {citygas_total:,.0f} "
                   "(도시가스=난방 기반 보조·참고, 발전용과 별개 동인)")
    else:
        out.append(f"발전용 가스 송출(예측): {gen_total:,.0f} TON")
    out.append(f"발전용 가스비 환산: {cost / 1e8:,.0f} 억원")
    out += [
        f"시간당 최대 송출: {pk[0]:,.0f} TON/h ({_hhmm(pk[1])})" if pk else "최대 송출 데이터 없음",
        f"시간당 최소 송출: {tr[0]:,.0f} TON/h ({_hhmm(tr[1])})" if tr else "최소 송출 데이터 없음",
    ]
    if duck:
        out.append(f"한낮 덕커브 저점(10~15시): {duck[0]:,.0f} TON/h ({_hhmm(duck[1])}) "
                   "— 태양광 피크로 가스 송출이 눌리는 구간")
    if eve:
        out.append(f"저녁 피크(18~21시): {eve[0]:,.0f} TON/h ({_hhmm(eve[1])})")

    # 전일 대비 — 첫날 합 기준
    day1 = float(ton[ts.dt.date == start.date()].sum())
    if prev_ton and prev_ton > 0:
        chg = (day1 - prev_ton) / prev_ton * 100
        arrow = "증가" if chg >= 0 else "감소"
        out.append(f"전일 대비(첫날): {day1:,.0f} vs {prev_ton:,.0f} TON → {chg:+.1f}% {arrow}")

    # 조달 시사 — 일 송출량 변동폭(σ). 안전재고는 Z·σ 정석(메모리 LNG procurement).
    if n_days >= 2:
        ds = _daily_sums(ts, ton)
        if len(ds) >= 2:
            sigma, mean = float(ds.std(ddof=0)), float(ds.mean())
            cv = sigma / mean * 100 if mean else float("nan")
            slope = (ds.iloc[-1] - ds.iloc[0]) / ds.iloc[0] * 100 if ds.iloc[0] else float("nan")
            out.append(f"일 송출량 평균 {mean:,.0f} TON · 변동폭 σ {sigma:,.0f} TON "
                       f"(변동계수 {cv:.0f}%) — 조달 안전재고는 σ에 비례")
            out.append(f"구간 추세: 첫날→끝날 {slope:+.0f}% "
                       f"({'증가 추세' if slope > 5 else '감소 추세' if slope < -5 else '대체로 평탄'})")
    return out


def _demand_fact(df: pd.DataFrame) -> list[str]:
    """전력수요는 가볍게 — 시간대 평균 패턴에서 '대체로 몇 시 최고/최저'만."""
    if "est_demand_land" not in df.columns:
        return []
    sub = df.dropna(subset=["est_demand_land"])
    if sub.empty:
        return []
    byhour = sub.groupby(sub["timestamp"].dt.hour)["est_demand_land"].mean()
    if byhour.empty:
        return []
    return [f"전력수요 예측: 대체로 {int(byhour.idxmax())}시 최고 · {int(byhour.idxmin())}시 최저 "
            f"(최고 약 {byhour.max():,.0f} MW)"]


def _solar_stations_rain(start: str, end: str) -> int:
    """태양광 3지점(서산·포항·영광) 강수(≥0.3mm/h) 시간 수 — 비구름=태양광 변동성 신호."""
    cols = [f"rainfall_{s}" for s in SOLAR_STATIONS]
    raw = _fc_horizon(cols, start, end)
    present = [c for c in cols if c in raw.columns]
    if raw.empty or not present:
        return 0
    return int((raw[present] >= 0.3).any(axis=1).sum())


def _solar_peak_label(df: pd.DataFrame, rain_hours: int):
    """태양광 한낮(10~15시) 피크 이용률 → (대표 피크 0~1, 라벨) 또는 None.

    크기 3단계(활발/낮다/매우 낮다) + 서산·포항·영광 강수면 '변동성이 크다'로 덮어씀.
    """
    if "est_solar_util_land" not in df.columns:
        return None
    ts = df["timestamp"]
    mid = df[(ts.dt.hour >= SOLAR_PEAK[0]) & (ts.dt.hour <= SOLAR_PEAK[1])]
    daily_peak = mid.groupby(mid["timestamp"].dt.date)["est_solar_util_land"].max().dropna()
    if daily_peak.empty:
        return None
    rep = float(daily_peak.mean())              # 일별 한낮 피크의 구간 평균
    if rain_hours >= RAIN_VAR_HOURS:
        lab = "변동성이 크다 (서산·포항·영광 비구름 예보로 태양광이 출렁임)"
    elif rep >= SOLAR_HI:
        lab = "활발하다"
    elif rep >= SOLAR_LO:
        lab = "낮다"
    else:
        lab = "매우 낮다"
    return rep, lab


def _solar_util_fact(start: pd.Timestamp, end: pd.Timestamp, df: pd.DataFrame,
                     rain_hours: int) -> list[str]:
    """태양광 한낮 피크 이용률 사실(% + 라벨) — 상세/표준 티어용."""
    r = _solar_peak_label(df, rain_hours)
    if r is None:
        return []
    rep, lab = r
    return [f"태양광 한낮 피크 이용률 예측: 약 {rep * 100:.0f}% — {lab}"]


def _weather_facts(start: pd.Timestamp, end: pd.Timestamp, df: pd.DataFrame,
                   wx: pd.DataFrame, rain_hours: int) -> list[str]:
    """기상 요약(weather kind 전용) — 전운량·일사·강수 + 태양광 이용률 + 순 부하 저점. 풍력은 다루지 않음."""
    out = []
    if not wx.empty:
        ts = wx["timestamp"]
        out.append(f"전운량 흐름(0~1): {_flow(ts, wx['total_cloud'], '{:.2f}')}")
        out.append(f"일사 흐름(MJ/m²·h): {_flow(ts, wx['radiation'], '{:.2f}')}")
        rh = int((wx["rainfall"] >= 0.3).sum())
        out.append(f"강수: {rh}시간 (태양광 변동성 ↑)" if rh else "강수: 없음(건조)")
    out += _solar_util_fact(start, end, df, rain_hours)
    nl = df["est_net_load_land"]
    if nl.dropna().any():
        nlpk = _argext(df["timestamp"], nl, "min")
        out.append(f"순 부하(Net Load) 저점 — 가스가 메울 잔여 수요 최저: {nlpk[0]:,.0f} MW ({_hhmm(nlpk[1])})")
    return out


def _confidence_facts(df: pd.DataFrame) -> list[str]:
    """예측 신뢰도 — 구간 지평(D+k)·지평별 어조 지침·그 지평의 최근 가스 MAPE."""
    out = []
    hz = df["horizon_d"].dropna()
    if hz.empty:
        return ["지평 정보 없음"]
    lo, hi = int(hz.min()), int(hz.max())
    out.append(f"이 구간 예측 지평: D+{lo} ~ D+{hi} (멀수록 불확실)")
    tone = ("근지평 — 운영에 바로 쓸 수 있게 수치까지 구체적으로 서술" if lo <= 3
            else "중지평 — 대체적 흐름 위주" if lo <= 10
            else "장지평 — 대략적 전망만, 수치는 최소로(수요가 많다/적다 수준)로 두루뭉술하게")
    out.append(f"서술 어조 지침: {tone}")
    today = pd.Timestamp.now().normalize()
    cutoff = (today - pd.Timedelta(days=92)).strftime("%Y-%m-%d")
    acc = C.land_horizon_accuracy(start=cutoff)   # 최근 3개월 발행본
    if not acc.empty and "가스 MAPE" in acc.columns:
        for k in sorted({lo, hi, 1}):
            row = acc.loc[f"D+{k}"] if f"D+{k}" in acc.index else None
            if row is not None and pd.notna(row.get("가스 MAPE")):
                out.append(f"최근 3개월 가스 MAPE D+{k}: {row['가스 MAPE']:.1f}% "
                           f"(bias {row.get('가스 bias', float('nan')):+.1f}%)")
    return out


def _coarse_facts(start: pd.Timestamp, df: pd.DataFrame,
                  citygas_total: float | None, rain_hours: int) -> list[str]:
    """장지평(먼 지평) 거친 사실 — 정확한 시각·σ 빼고 규모·수준만(두루뭉술 유도)."""
    out = [f"대상일: {start:%m-%d} (먼 지평 — 대략적 전망)"]
    ton = df["est_gas_sendout_ton_land"]
    if ton.dropna().any():
        tot = float(ton.sum()) + (citygas_total or 0)
        out.append(f"총 천연가스 송출(예측): 약 {round(tot, -3):,.0f} TON 규모(발전용+도시가스)")
    out += _demand_fact(df)                       # 수요는 시각만
    r = _solar_peak_label(df, rain_hours)
    if r is not None:
        out.append(f"태양광 한낮 수준: {r[1]}")    # 라벨만(% 생략)
    return out


def build_fact_sheet(kind: str, start: pd.Timestamp, end: pd.Timestamp,
                     df: pd.DataFrame, wx: pd.DataFrame, prev_ton: float | None,
                     citygas_total: float | None = None, rain_hours: int = 0,
                     tier: str = "standard") -> str:
    """kind별 사실표(텍스트) — 그대로 LLM 프롬프트에 들어가고, 화면에도 근거로 노출된다.

    tier='coarse'(장지평)면 overview 를 거친 사실(규모·수준·시각)만으로 줄여 두루뭉술을 유도한다.
    """
    if tier == "coarse" and kind == "overview":
        blocks = ["[대략 전망]\n" + "\n".join(f"- {x}" for x in
                  _coarse_facts(start, df, citygas_total, rain_hours))]
        blocks.append("[예측 신뢰도]\n" + "\n".join(f"- {x}" for x in _confidence_facts(df)))
        return "\n\n".join(blocks)
    blocks = []
    if kind in ("sendout", "overview"):
        blocks.append("[가스 송출]\n" + "\n".join(f"- {x}" for x in
                       _sendout_facts(start, end, df, prev_ton, citygas_total)))
    if kind == "overview":
        facts = _demand_fact(df) + _solar_util_fact(start, end, df, rain_hours)
        blocks.append("[전력수요·태양광]\n" + "\n".join(f"- {x}" for x in facts))
    if kind == "weather":
        blocks.append("[기상·태양광]\n" + "\n".join(f"- {x}" for x in
                       _weather_facts(start, end, df, wx, rain_hours)))
    # 신뢰도·어조는 모든 종류 말미에 근거로 붙인다.
    blocks.append("[예측 신뢰도]\n" + "\n".join(f"- {x}" for x in _confidence_facts(df)))
    return "\n\n".join(blocks)


# ============================================================ 데이터 조립 (패널·API 공용)
# 서빙체인 결과 컬럼 → 외부에 보낼 친화적 이름.
CHAIN_COLS = {"est_demand_land": "demand_mw", "est_market_renew_land": "renew_mw",
              "est_gas_gen_land": "gas_gen_mw", "est_gas_sendout_ton_land": "sendout_ton"}


def assemble_facts(start_day: pd.Timestamp, n: int, kind: str, use_live: bool = True,
                   tier: str = "standard"):
    """선택일부터 N일 구간의 (end, 체인 프레임 df, 사실표 텍스트)를 만든다.

    패널은 use_live=True(최근 실측 보강), API는 use_live=False(DB만, 수집 트리거 금지).
    tier='coarse'(장지평)면 거친 사실표로 줄인다(두루뭉술).
    """
    end = start_day + pd.Timedelta(days=n - 1)
    df = C.land_range_compare(start_day, end, use_live=use_live)
    s = start_day.strftime("%Y-%m-%d 00:00:00")
    e = end.strftime("%Y-%m-%d 23:00:00")
    wx = weather_national(s, e)
    prev = C.land_day_compare(start_day - pd.Timedelta(days=1), use_live=use_live)
    prev_ton = float(prev["est_gas_sendout_ton_land"].sum())
    # 도시가스 일합(보조·참고) — 발전용과 합쳐 '총 천연가스 송출'로 제시
    citygas_total = None
    try:
        daily = C.land_daily_sendout(start_day, end)
        if not daily.empty and "citygas_ton" in daily.columns:
            cg = float(daily["citygas_ton"].sum())
            citygas_total = cg if cg > 0 else None
    except Exception:  # noqa: BLE001 — 도시가스 미적재 시 발전용만
        citygas_total = None
    rain_hours = _solar_stations_rain(s, e)   # 태양광 3지점 강수 → 변동성 판정
    fact = build_fact_sheet(kind, start_day, end, df, wx, prev_ton,
                            citygas_total=citygas_total, rain_hours=rain_hours, tier=tier)
    return end, df, fact


def forecast_series(start_day: pd.Timestamp, n: int, use_live: bool = False) -> pd.DataFrame:
    """서빙체인 예측 시계열(수요·신재생·가스발전·송출 TON) — API 전송용 깔끔한 프레임."""
    end = start_day + pd.Timedelta(days=n - 1)
    df = C.land_range_compare(start_day, end, use_live=use_live)
    keep = ["timestamp", "horizon_d"] + list(CHAIN_COLS)
    out = df[[c for c in keep if c in df.columns]].rename(columns=CHAIN_COLS)
    return out


# ============================================================ LLM 호출
_PERSONA = ("당신은 전국 천연가스 수급·조달 담당자를 돕는 분석 보조입니다. "
            "[사실]의 모든 수치는 '앞으로의 예측값'입니다(이미 일어난 일이 아님) — 반드시 "
            "'예상됩니다·전망입니다·예측됩니다' 같은 미래·예측 표현으로 서술하고, "
            "'송출되었습니다·기록하였습니다·도달하였습니다' 같은 과거 단정은 절대 쓰지 마십시오. "
            "발전기 기동·정지 같은 급전 지시나 SMP·경제성 단정은 하지 않습니다. "
            "오직 [사실]에 제시된 수치만 사용하고, 거기 없는 값을 추론하거나 지어내지 마십시오.")

_RULES = ("\n[작성 규칙]\n"
          "1. 각 항목 '•' 기호 + 빈 줄(개조식), 최대 4줄, 경어체. 모든 서술은 예측(미래형).\n"
          "2. [사실]의 수치만 인용하고, 없는 리스크를 창작하지 마십시오. 대괄호 구획명([가스 송출]·"
          "[전력수요·태양광]·[예측 신뢰도])을 제목처럼 그대로 옮기지 말고 자연스러운 문장에 녹이십시오.\n"
          "3. 취소선(~~)·구분선(---, ***, ___)·표를 절대 쓰지 마십시오 — 오직 '•' 글머리만 씁니다.\n"
          "4. [예측 신뢰도]의 '서술 어조 지침'을 따르십시오 — 근지평이면 수치까지 구체적으로, "
          "장지평이면 수치를 최소로 줄여 '수요가 많다/적다' 수준의 대략적 전망으로 두루뭉술하게 씁니다.\n"
          "5. 마지막 한 줄은 예측 신뢰도(지평이 멀수록·강수 시 불확실)로 마무리.")

_SYS = {
    "sendout": _PERSONA + " 가스 송출 규모(발전용+도시가스)·피크/저점·덕커브 저점·전일 대비·조달 변동폭(σ)을 "
               "수급 담당 관점에서 예측·전망합니다." + _RULES,
    "weather": _PERSONA + " 기상(전운량·일사·강수)이 태양광 이용률을 통해 한낮 가스 송출을 어디서 누르는지 "
               "예측·설명합니다. 풍력은 다루지 않습니다. 강수가 있으면 태양광 변동성·신뢰도 저하를 짚습니다." + _RULES,
    "overview": _PERSONA + " 가스 송출 규모(발전용+도시가스)와 그 동인(태양광 이용률·전력수요)을 묶어 종합 전망합니다. "
                "첫 줄 총 송출 규모(발전용·도시가스 구분), 둘째 줄 태양광·수요 동인, 셋째 줄 조달 시사, "
                "마지막 줄 신뢰도 순." + _RULES,
}

# 배치(여러 날 한 콜) 시스템 지침 — 티어별 어조. 출력은 JSON(_gen_llm_json 에서 강제).
_BATCH_COMMON = (_PERSONA +
                 " 여러 날짜의 [사실]이 주어집니다. 각 날짜마다 독립된 종합 브리핑을 작성하되, 날마다 "
                 "내용이 다르게 쓰고 같은 문장·수치를 반복하지 마십시오. 각 브리핑은 '•' 글머리 개조식이며 "
                 "취소선·구분선·표는 절대 쓰지 않고, 모든 서술은 미래·예측형입니다.")
_SYS_BATCH = {
    "detail": _BATCH_COMMON + " [근지평] 운영에 바로 쓰도록 총 송출(발전용+도시가스)·시간당 피크/저점·"
              "덕커브·전일 대비·태양광 이용률·수요 시각까지 구체적으로(각 날 3~4줄).",
    "standard": _BATCH_COMMON + " [중지평] 총 송출 규모와 태양광·수요 동인 중심으로 대체적 흐름을(각 날 3줄 내외).",
    "coarse": _BATCH_COMMON + " [장지평] 대략적 전망만. 수치는 최소로 줄이고 '수요가 많다/적다', "
              "'태양광 활발/낮음' 수준으로 두루뭉술하게(각 날 2~3줄).",
}


_HR_LINE = re.compile(r"\s*([-*_])\1{2,}\s*")   # ---, ***, ___ 등 구분선만 있는 줄


def _sanitize(text: str) -> str:
    """LLM 출력 정리 — 구분선만 있는 줄·취소선 마커 제거(화면에 줄/취소선이 안 뜨게)."""
    if not text:
        return text
    kept = [ln for ln in text.splitlines() if not _HR_LINE.fullmatch(ln)]
    return "\n".join(kept).replace("~~", "").strip()


def _gen_llm(kind: str, fact_text: str, model: str = GEMINI_MODEL) -> str:
    """Gemini 호출 본체(캐시 없음) — 패널은 캐시 래퍼(generate_brief), cron/API 는 이 함수를 직접 쓴다."""
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        return "⚠ GEMINI_API_KEY가 없어 브리핑을 생성할 수 없습니다 (.env 확인)."
    try:
        from google import genai
        from google.genai import types
        client = genai.Client()
        resp = client.models.generate_content(
            model=model,
            contents=f"[사실]\n{fact_text}",
            config=types.GenerateContentConfig(
                system_instruction=_SYS.get(kind, _SYS["overview"]),
                temperature=0.2),
        )
        return _sanitize(resp.text) or "(빈 응답)"
    except Exception as e:  # noqa: BLE001
        return f"브리핑 생성 실패: {e}"


@st.cache_data(ttl=86400, show_spinner=False)
def generate_brief(kind: str, fact_text: str, model: str = GEMINI_MODEL) -> str:
    """Gemini 호출(패널용) — 사실표를 자연어로. 같은 (kind·사실) 24시간 캐시(재과금 방지). 본체=_gen_llm."""
    return _gen_llm(kind, fact_text, model)


def _gen_llm_json(prompt: str, sys: str, model: str = GEMINI_MODEL) -> dict:
    """여러 날을 한 콜로 — JSON 배열 [{horizon_d, brief}] 을 받아 {k: brief} 로. 실패 시 {}(상위에서 단건 폴백)."""
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        return {}
    try:
        from google import genai
        from google.genai import types
        client = genai.Client()
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=sys, temperature=0.2,
                response_mime_type="application/json"),   # JSON 강제(스키마는 프롬프트로)
        )
        data = json.loads(resp.text or "[]")
        out = {}
        for d in (data if isinstance(data, list) else []):
            try:
                out[int(d["horizon_d"])] = _sanitize(str(d["brief"]))
            except (KeyError, TypeError, ValueError):
                continue
        return out
    except Exception:  # noqa: BLE001 — 상위에서 그 날만 단건 폴백
        return {}


# ============================================================ 지평 티어(매일 자동 생성)
# 모든 브리핑은 '하루치(단일일)'. D+1~15 를 3티어로 묶어 티어별 1콜(JSON)로 받아 날짜별로 저장한다.
# 저장 키 = (그 날짜, days=1, 'overview'). 표시는 날짜 선택기 → 그 날짜 키를 그대로 읽는다(밴드 없음).
#   (티어명, 시작 D+, 끝 D+, 사실/어조 모드)
TIERS = [
    ("근지평", 1, 3, "detail"),
    ("중지평", 4, 10, "standard"),
    ("장지평", 11, 15, "coarse"),
]


def _tier_prompt(blocks: list) -> str:
    """여러 날 사실 블록 → 한 콜 프롬프트. blocks=[(k, day, fact), ...]."""
    parts = [f"### D+{k} ({day:%Y-%m-%d}) 사실\n{fact}" for k, day, fact in blocks]
    head = ("아래 여러 날짜의 [사실]을 바탕으로 각 날짜의 종합 브리핑을 작성하라. 반드시 다음 JSON 배열 "
            "형식으로만 답하라(다른 텍스트·코드펜스 없이): "
            '[{"horizon_d": 1, "brief": "..."}, {"horizon_d": 2, "brief": "..."}]. '
            "brief 는 '•' 글머리 개조식 문자열이며, 날짜마다 내용을 다르게 작성한다.\n\n")
    return head + "\n\n".join(parts)


def generate_tier(region: str, anchor: pd.Timestamp, tier,
                  use_live: bool = False, model: str = GEMINI_MODEL) -> list[dict]:
    """한 티어(예: D+4~10)의 날짜별 '종합' 브리핑을 1콜(JSON)로 생성·저장. 누락은 그 날만 단건 폴백."""
    _name, lo, hi, mode = tier
    blocks = []   # (k, day, fact|None)
    for k in range(lo, hi + 1):
        day = anchor.normalize() + pd.Timedelta(days=k)
        try:
            _e, _df, fact = assemble_facts(day, 1, "overview", use_live=use_live, tier=mode)
        except Exception:  # noqa: BLE001 — 그 날 사실표 실패
            fact = None
        blocks.append((k, day, fact))

    usable = [(k, d, f) for k, d, f in blocks if f]
    parsed = _gen_llm_json(_tier_prompt(usable),
                           _SYS_BATCH.get(mode, _SYS_BATCH["standard"]), model) if usable else {}

    out = []
    for k, day, fact in blocks:
        sd = day.strftime("%Y-%m-%d")
        if fact is None:
            out.append({"horizon": k, "start": sd, "ok": False, "msg": "사실표 구성 실패"})
            continue
        text = parsed.get(k)
        if not text:                            # 배치 누락 → 그 날만 단건 폴백
            text = _gen_llm("overview", fact, model)
        ok = bool(text) and not (text.startswith("브리핑 생성 실패") or text.startswith("⚠"))
        ca = store.save(sd, 1, "overview", text, fact_text=fact,
                        model=model, region=region) if ok else ""
        out.append({"horizon": k, "start": sd, "ok": ok, "created_at": ca,
                    "msg": "" if ok else str(text)[:80]})
    return out


def generate_all_days(region: str, anchor: pd.Timestamp, use_live: bool = False) -> list[dict]:
    """D+1~15 날짜별 '종합' 브리핑을 3티어(=3콜, 폴백 시 +α)로 생성·저장. anchor=생성 기준일(오늘)."""
    res = []
    for tier in TIERS:
        res += generate_tier(region, anchor, tier, use_live=use_live, model=GEMINI_MODEL)
    return res


# ============================================================ UI 패널
_KINDS = {"종합 요약": "overview", "송출량 요약": "sendout", "기상 요약": "weather"}


def _brief_html(text: str) -> str:
    """브리핑 본문 → 글머리(•)별 줄바꿈 카드 HTML(연한 톤). st.markdown(unsafe_allow_html=True)로 렌더.

    LLM 출력은 '• A\\n• B' 식이라 st.markdown 이 single newline 을 공백으로 합쳐 한 줄로 붙는다.
    • 로 쪼개 항목별 <div> 로 만들어 줄바꿈 + 카드 배경으로 구분한다.
    """
    items = [p.strip() for p in (text or "").replace("\n", " ").split("•") if p.strip()]
    if not items:
        return ""
    lis = "".join(f"<div class='bi'>{escape(it)}</div>" for it in items)
    return f"<div class='brief-card'>{lis}</div>"


def render_brief_display(prefix: str, target_day: pd.Timestamp | None = None):
    """상단 날짜 선택기가 고른 '그 날짜'의 하루치 종합 브리핑을 자동 표시(생성 버튼 없음).

    fresh 룰 — 날짜별 가장 최신 발행본을 과거·오늘·미래 가리지 않고 그대로 보여준다. 저장 키가
    (날짜, days=1, kind)뿐이라 upsert 로 마지막 생성본 하나만 남으므로, 날짜로 읽으면 곧 최신본.
    저장이 없으면 안내만. 두 탭이 동시 렌더되므로 숨은 prefix 마커로 ID 충돌 방지.
    """
    today = pd.Timestamp.now().normalize()
    target = (target_day or today).normalize()
    lead = (target - today).days
    mark = f"<span style='display:none'>·{prefix}</span>"

    sd = target.strftime("%Y-%m-%d")
    saved = store.load(sd, 1, "overview")   # 날짜 키 = 최신 발행본(upsert 라 마지막 생성분만 남음)
    if saved and saved.get("brief_text"):
        pub = (saved.get("created_at", "") or "")[:10]
        st.markdown(_brief_html(saved["brief_text"]) + mark, unsafe_allow_html=True)
        st.caption((f"💾 {sd} 종합브리핑 - {pub} 발행 (매일 자동 갱신){mark}" if pub
                    else f"💾 {sd} 종합브리핑 (매일 자동 갱신){mark}"),
                   unsafe_allow_html=True)
    elif lead > 15:
        st.caption(f"예측 브리핑은 **D+15까지** 제공합니다 (선택일 {sd}). "
                   f"날짜를 그 안으로 옮겨 주세요.{mark}", unsafe_allow_html=True)
    else:
        st.caption(f"{sd} 브리핑이 아직 없습니다 — 매일 새벽 자동 생성됩니다.{mark}",
                   unsafe_allow_html=True)


def render_brief_panel(prefix: str, start_day: pd.Timestamp, default_n: int = 1,
                       fixed_n: int | None = None):
    """예측 확인/장지평/메인 탭에 끼우는 브리핑 패널 — 요약 종류·N일 선택 + 생성 버튼.

    원시 시계열은 LLM에 가지 않는다: 코드가 사실표를 만들고, 버튼을 눌러야만 Gemini를 호출한다.
    fixed_n 을 주면 구간 슬라이더를 숨기고 그 지평(예: 메인=1일)으로 고정한다.
    """
    if fixed_n is not None:
        n = fixed_n
        c_kind, c_gen = st.columns([2.7, 1.1], vertical_alignment="bottom")
    else:
        # 컨트롤 한 줄 — 구간(N일) → 요약 종류 → 생성 버튼 순서로 흐르게 배치
        c_n, c_kind, c_gen = st.columns([1.7, 2.0, 1.1], vertical_alignment="bottom")
        n = c_n.slider("① 브리핑 구간 (선택일부터 N일)", 1, 15, default_n, key=f"{prefix}_bn",
                       help="미리 저장된 예측을 불러오므로 길게 잡아도 빠릅니다")
    klabel = c_kind.segmented_control("요약 종류" if fixed_n else "② 요약 종류", list(_KINDS),
                                      default="종합 요약", key=f"{prefix}_bk") or "종합 요약"
    kind = _KINDS[klabel]

    # 사실표 구성 — 코드가 확정(LLM 무관). 실패해도 패널은 살아 있게.
    try:
        _end, _df, fact_text = assemble_facts(start_day, n, kind, use_live=True)
    except Exception as ex:  # noqa: BLE001
        st.warning(f"사실표 구성 실패: {ex}")
        return

    sd = start_day.strftime("%Y-%m-%d")
    res_key = f"{prefix}_bres_{kind}_{start_day:%Y%m%d}_{n}"
    saved = store.load(sd, n, kind)           # (시작일·지평·종류)로 저장된 브리핑

    if c_gen.button("③ AI 브리핑 생성", key=f"{prefix}_bgen", type="primary", width="stretch"):
        with st.spinner("AI 브리핑 작성 중..."):
            text = generate_brief(kind, fact_text)
        # 생성 즉시 별도 저장소에 저장(upsert) — 같은 카테고리는 갱신
        ca = store.save(sd, n, kind, text, fact_text=fact_text, model=GEMINI_MODEL)
        st.session_state[res_key] = text
        saved = {"brief_text": text, "created_at": ca}
        st.rerun()
    if saved:
        st.caption(f"💾 저장됨 · {sd} · 지평 {n}일 · {klabel} · {saved.get('created_at', '')}")

    # 표시 우선순위: 이번 세션 생성분 → 저장소의 기존 브리핑
    show = st.session_state.get(res_key) or (saved or {}).get("brief_text")
    if show:
        st.markdown(_brief_html(show), unsafe_allow_html=True)
    else:
        st.caption(f"‘{klabel}’ · 선택일부터 {n}일 구간. 버튼을 누르면 아래 근거 위에서 해설하고 저장합니다.")

    with st.expander("브리핑 근거 — 코드가 확정한 수치"):
        st.code(fact_text)
    # '저장된 브리핑' 목록은 종합 화면 밖(관리자메뉴)으로 — render_saved_briefs() 참조.


def render_saved_briefs(region: str = "land", limit: int = 30):
    """저장된 브리핑 기록 표 — 종합 화면이 아닌 조용한 위치(관리자메뉴)에 둔다."""
    rows = store.list_all(region=region, limit=limit)
    if not rows:
        st.caption("저장된 브리핑이 아직 없습니다.")
        return
    tbl = pd.DataFrame(rows)[["start_date", "days", "kind", "created_at", "preview"]]
    tbl.columns = ["시작일", "지평(일)", "종류", "저장시각", "미리보기"]
    st.dataframe(tbl, width="stretch", hide_index=True, height=300)
