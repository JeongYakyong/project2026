# -*- coding: utf-8 -*-
"""8-D · 전국 가스 송출량 예측 브리핑봇 (Gemini).

설계 원칙:
  ── 코드가 사실을 확정하고, LLM은 그 위에서 서술만 한다. ──
원시 시계열은 LLM에 절대 넣지 않는다. 코드가 통계로 압축한 '사실표(fact sheet)'만
넘기므로 (1) LLM 컨텍스트가 병목이 되지 않고 (2) 없는 수치를 지어낼 여지가 없다.

목적: 5→6→7 체인이 산출한 선택일~장지평 송출량 예측(TON)을, 가스 수급·조달 담당이
읽기 쉬운 자연어로 해설. 발전기 급전 지시·SMP 단정은 범위 밖(그건 제주 영역).

객관식 2축:
  - 지평/구간 : 선택일부터 N일(슬라이더). 코드가 그 구간만 DB에서 읽어 요약.
  - 요약 종류 : 종합 요약 / 송출량 요약 / 기상 요약. 종류마다 담는 사실·시스템 지침이 다름.
"""
from pathlib import Path
import os

import pandas as pd
import streamlit as st

import common as C
import brief_store as store

try:
    from dotenv import load_dotenv
    load_dotenv(C.DATA_DIR / ".env")          # GEMINI_API_KEY (수집기와 같은 .env)
except Exception:
    pass

# 모델 — gemini-3.1-flash-lite(stable, 2026-05). 저비용·저지연, 버튼식 소량 호출에 충분.
# 더 풍부한 서술이 필요하면 gemini-3.1-flash 로 올리면 됨(한 줄 변경).
GEMINI_MODEL = "gemini-3.1-flash-lite"

# 발전용 가스 단가 환산은 common(gas_cost_won)을 그대로 쓴다.
# 송출량(TON) = 발전량(MWh) × 0.1521 (7-C). 여기선 est_gas_sendout_ton_land 적재값을 직접 읽는다.


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
def _sendout_facts(start: pd.Timestamp, end: pd.Timestamp, df: pd.DataFrame,
                   prev_ton: float | None) -> list[str]:
    """송출량 관련 사실 — 규모·피크/저점·덕커브·전일비·조달 변동폭."""
    ts = df["timestamp"]
    ton = df["est_gas_sendout_ton_land"]
    gen = df["est_gas_gen_land"]
    if ton.dropna().empty:
        return ["송출량 예측 없음(구간 미적재)"]

    n_days = (end.normalize() - start.normalize()).days + 1
    total = float(ton.sum())
    cost = float(C.gas_cost_won(ts, ton).sum())
    pk = _argext(ts, ton, "max")
    tr = _argext(ts, ton, "min")
    duck = _window_min(ts, ton, *SOLAR_PEAK)   # 한낮 저점
    eve = _window_max(ts, ton, *EVE_PEAK)      # 저녁 고점

    out = [
        f"구간: {start:%m-%d}~{end:%m-%d} ({n_days}일)",
        f"송출량 합계: {total:,.0f} TON / 가스비 환산 {cost / 1e8:,.0f} 억원",
        f"가스발전 합계: {gen.sum() / 1000:,.1f} GWh",
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


def _weather_facts(start: pd.Timestamp, end: pd.Timestamp,
                   df: pd.DataFrame, wx: pd.DataFrame) -> list[str]:
    """기상 → 신재생 → net_load → 송출 영향 사실."""
    out = []
    if not wx.empty:
        ts = wx["timestamp"]
        out.append(f"전운량 흐름(0~1): {_flow(ts, wx['total_cloud'], '{:.2f}')}")
        out.append(f"일사 흐름(MJ/m²·h): {_flow(ts, wx['radiation'], '{:.2f}')}")
        out.append(f"풍속 흐름(10m, m/s): {_flow(ts, wx['wind_spd_10m'], '{:.1f}')}")
        rain = wx["rainfall"]
        rain_hrs = int((rain >= 0.3).sum())
        if rain_hrs > 0:
            rw = _window_max(ts, rain, 0, 23)
            out.append(f"강수: {rain_hrs}시간 (피크 {rw[0]:.1f}mm/h @{_hhmm(rw[1])}) "
                       "— 일사·태양광 예측 신뢰도 저하 구간")
        else:
            out.append("강수: 없음(건조)")

    # 신재생 예측 — net_load를 어디서 눌렀나 (체인 프레임에서)
    rts = df["timestamp"]
    renew = df["est_market_renew_land"]
    if renew.dropna().any():
        rpk = _argext(rts, renew, "max")
        out.append(f"시장 신재생 예측 최대: {rpk[0]:,.0f} MW ({_hhmm(rpk[1])}) "
                   "— 이 시각 net_load·가스 송출이 가장 낮아짐")
    nl = df["est_net_load_land"]
    if nl.dropna().any():
        out.append(f"net_load 흐름(MW): {_flow(rts, nl, '{:.0f}')}")
    return out


def _confidence_facts(df: pd.DataFrame) -> list[str]:
    """예측 신뢰도 — 구간 지평(D+k)과 그 지평의 최근 가스 MAPE."""
    out = []
    hz = df["horizon_d"].dropna()
    if hz.empty:
        return ["지평 정보 없음"]
    lo, hi = int(hz.min()), int(hz.max())
    out.append(f"이 구간 예측 지평: D+{lo} ~ D+{hi} (멀수록 불확실)")
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


def build_fact_sheet(kind: str, start: pd.Timestamp, end: pd.Timestamp,
                     df: pd.DataFrame, wx: pd.DataFrame, prev_ton: float | None) -> str:
    """kind별 사실표(텍스트) — 그대로 LLM 프롬프트에 들어가고, 화면에도 근거로 노출된다."""
    blocks = []
    if kind in ("sendout", "overview"):
        blocks.append("[송출량]\n" + "\n".join(f"- {x}" for x in
                       _sendout_facts(start, end, df, prev_ton)))
    if kind in ("weather", "overview"):
        blocks.append("[기상·신재생]\n" + "\n".join(f"- {x}" for x in
                       _weather_facts(start, end, df, wx)))
    # 신뢰도는 모든 종류 말미에 한 줄 근거로 붙인다.
    blocks.append("[예측 신뢰도]\n" + "\n".join(f"- {x}" for x in _confidence_facts(df)))
    return "\n\n".join(blocks)


# ============================================================ 데이터 조립 (패널·API 공용)
# 서빙체인 결과 컬럼 → 외부에 보낼 친화적 이름.
CHAIN_COLS = {"est_demand_land": "demand_mw", "est_market_renew_land": "renew_mw",
              "est_gas_gen_land": "gas_gen_mw", "est_gas_sendout_ton_land": "sendout_ton"}


def assemble_facts(start_day: pd.Timestamp, n: int, kind: str, use_live: bool = True):
    """선택일부터 N일 구간의 (end, 체인 프레임 df, 사실표 텍스트)를 만든다.

    패널은 use_live=True(최근 실측 보강), API는 use_live=False(DB만, 수집 트리거 금지).
    """
    end = start_day + pd.Timedelta(days=n - 1)
    df = C.land_range_compare(start_day, end, use_live=use_live)
    s = start_day.strftime("%Y-%m-%d 00:00:00")
    e = end.strftime("%Y-%m-%d 23:00:00")
    wx = weather_national(s, e)
    prev = C.land_day_compare(start_day - pd.Timedelta(days=1), use_live=use_live)
    prev_ton = float(prev["est_gas_sendout_ton_land"].sum())
    return end, df, build_fact_sheet(kind, start_day, end, df, wx, prev_ton)


def forecast_series(start_day: pd.Timestamp, n: int, use_live: bool = False) -> pd.DataFrame:
    """서빙체인 예측 시계열(수요·신재생·가스발전·송출 TON) — API 전송용 깔끔한 프레임."""
    end = start_day + pd.Timedelta(days=n - 1)
    df = C.land_range_compare(start_day, end, use_live=use_live)
    keep = ["timestamp", "horizon_d"] + list(CHAIN_COLS)
    out = df[[c for c in keep if c in df.columns]].rename(columns=CHAIN_COLS)
    return out


# ============================================================ LLM 호출
_PERSONA = ("당신은 전국 천연가스 수급·조달 담당자를 돕는 분석 보조입니다. "
            "발전기 기동·정지 같은 급전 지시나 SMP·경제성 단정은 하지 않습니다. "
            "오직 [사실]에 제시된 수치만 사용하고, 거기 없는 값을 추론하거나 지어내지 마십시오.")

_RULES = ("\n[작성 규칙]\n"
          "1. 각 항목 '•' 기호 + 빈 줄(개조식), 최대 5줄, '~입니다/습니다' 경어체.\n"
          "2. [사실]에 있는 수치만 인용하고, 없는 리스크를 평균·추세로 창작하지 마십시오.\n"
          "3. 마지막 한 줄은 [예측 신뢰도]에 근거한 주의(지평이 멀거나 강수가 있으면 불확실)로 마무리.")

_SYS = {
    "sendout": _PERSONA + " 송출량 규모·피크/저점·덕커브 저점·전일 대비·조달 변동폭(σ)을 "
               "수급 담당 관점에서 요약합니다." + _RULES,
    "weather": _PERSONA + " 기상 흐름이 신재생을 통해 net_load와 가스 송출을 어디서 끌어올리고 "
               "한낮에 어디서 눌렀는지 인과로 설명합니다. 강수가 있으면 예측 신뢰도 저하를 짚습니다." + _RULES,
    "overview": _PERSONA + " 송출량 규모와 그 동인(기상·신재생·net_load)을 묶어 종합 브리핑합니다. "
                "첫 줄 송출 규모, 둘째 줄 동인, 셋째 줄 조달 시사, 마지막 줄 신뢰도 순." + _RULES,
}


@st.cache_data(ttl=86400, show_spinner=False)
def generate_brief(kind: str, fact_text: str, model: str = GEMINI_MODEL) -> str:
    """Gemini 호출 — 사실표를 자연어 브리핑으로. 같은 (kind·사실) 24시간 캐시(재과금 방지)."""
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
        return resp.text or "(빈 응답)"
    except Exception as e:  # noqa: BLE001
        return f"브리핑 생성 실패: {e}"


# ============================================================ UI 패널
_KINDS = {"종합 요약": "overview", "송출량 요약": "sendout", "기상 요약": "weather"}
_KIND_REV = {v: k for k, v in _KINDS.items()}


def render_brief_display(prefix: str, start_day: pd.Timestamp, days: int = 1):
    """생성된 브리핑을 가져와 표시만 한다(생성 버튼 없음) — 메인·예측확인 탭 공용.

    생성은 '운영 실행' 메뉴에서 한다. 같은 브리핑을 두 탭에서 동시에 렌더하므로,
    보이지 않는 prefix 마커(display:none)로 Streamlit 요소 ID 충돌을 막는다.
    """
    sd = start_day.strftime("%Y-%m-%d")
    saved = store.latest_for(sd, days=days)
    mark = f"<span style='display:none'>·{prefix}</span>"
    if saved and saved.get("brief_text"):
        st.markdown(saved["brief_text"] + mark, unsafe_allow_html=True)
        st.caption(f"💾 {sd} · {_KIND_REV.get(saved['kind'], saved['kind'])} · "
                   f"{saved.get('created_at', '')} — ‘운영 실행’ 메뉴에서 생성·갱신합니다.{mark}",
                   unsafe_allow_html=True)
    else:
        st.caption(f"아직 생성된 브리핑이 없습니다 — **운영 실행** 메뉴에서 생성하세요.{mark}",
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
                       help="사전 적재 예측을 읽기만 하므로 길게 잡아도 지연 없음")
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
        with st.spinner("Gemini가 통계 요약을 해설하는 중..."):
            text = generate_brief(kind, fact_text)
        # 생성 즉시 별도 저장소에 적재(upsert) — 같은 카테고리는 갱신
        ca = store.save(sd, n, kind, text, fact_text=fact_text, model=GEMINI_MODEL)
        st.session_state[res_key] = text
        saved = {"brief_text": text, "created_at": ca}
        st.rerun()
    if saved:
        st.caption(f"💾 저장됨 · {sd} · 지평 {n}일 · {klabel} · {saved.get('created_at', '')}")

    # 표시 우선순위: 이번 세션 생성분 → 저장소의 기존 브리핑
    show = st.session_state.get(res_key) or (saved or {}).get("brief_text")
    if show:
        st.markdown(show)
    else:
        st.caption(f"‘{klabel}’ · 선택일부터 {n}일 구간. 버튼을 누르면 아래 근거 위에서 해설하고 저장합니다.")

    with st.expander("브리핑 근거 — 코드가 확정한 사실(이 수치 밖은 창작 금지)"):
        st.code(fact_text)
    # '저장된 브리핑' 목록은 종합 화면 밖(운영 실행)으로 — render_saved_briefs() 참조.


def render_saved_briefs(region: str = "land", limit: int = 30):
    """저장된 브리핑 기록 표 — 종합 화면이 아닌 조용한 위치(운영 실행)에 둔다."""
    rows = store.list_all(region=region, limit=limit)
    if not rows:
        st.caption("저장된 브리핑이 아직 없습니다.")
        return
    tbl = pd.DataFrame(rows)[["start_date", "days", "kind", "created_at", "preview"]]
    tbl.columns = ["시작일", "지평(일)", "종류", "저장시각", "미리보기"]
    st.dataframe(tbl, width="stretch", hide_index=True, height=300)
