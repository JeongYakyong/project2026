# -*- coding: utf-8 -*-
"""
전국 일단위 도시가스 송출량(추정) 예측 — 가벼운 모델 빌드 스크립트
====================================================================
배경: 일단위 도시가스 송출량 '실측'은 없다. 우리가 가진 것은
  - 월별 도시가스 (시도별 판매 1989~2024 / 용도별 전국 공급 2016~2026)
  - 일별 전국 기온 (관측소 5곳 평균, 2020~2026)
  - 연도별 도시가스 '일일 최대' 송출량 + 그 날짜 (2009~2026)  ← 일단위 실측 앵커(연 1점)
  - 일별 발전용 LNG 공급량 (2021~2026)  ← 기온반응 참고용(도시가스 아님)

설계(사용자 확정): "월 수요모델(검증가능) → 일별 기온 프로파일로 분해 → 일단위 송출 추정 곡선",
전국 합계 기준. 일 곡선은 월합 일치 + 기온반응 + 연 1점 일최대 앵커로 간접/부분 검증.
"""
import os, json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ── 보고서 공통 스타일 (step7_gas_corr.py와 같은 계열) ───────────────────
#   ▼▼▼ 색·계절 팔레트는 여기 한곳에서만 고치면 모든 그림에 반영됩니다 ▼▼▼
INK, MUTED, SOFT, ACCENT = "#2d3142", "#141618", "#7a8399", "#eb6c36"
RULE = "#d9dce3"                                  # 옅은 축선·구분선
# 계절 색: 겨울=파랑, 봄=초록, 여름=주황, 가을=황토
SEA_COL = {"겨울": "#4a78b5", "봄": "#5aa469", "여름": "#eb6c36", "가을": "#b58a3c"}
SEA_OF = {12: "겨울", 1: "겨울", 2: "겨울", 3: "봄", 4: "봄", 5: "봄",
          6: "여름", 7: "여름", 8: "여름", 9: "가을", 10: "가을", 11: "가을"}
WEEKDAY_COL, WEEKEND_COL = "#9bb7d4", ACCENT      # Fig6 평일/주말 막대
# ▲▲▲ 보통은 여기까지만 고치면 됩니다 ▲▲▲

plt.rcParams.update({
    "font.family": "Malgun Gothic", "axes.unicode_minus": False,
    "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
    "axes.edgecolor": MUTED, "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "figure.dpi": 150,
})


def _style(ax):
    """step7 양식의 축: 위/오른쪽 선 제거 · 남은 선은 옅게 · 눈금선 가늘게 · 점선 그리드."""
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color(RULE)
    ax.tick_params(length=0)
    ax.grid(True, alpha=0.16)
    ax.set_axisbelow(True)


def _title(ax, s, loc="center"):
    """굵은 제목(step7 양식). loc로 정렬 바꿈 — "left"(기본)·"center"·"right"."""
    ax.set_title(s, fontsize=12.5, fontweight="bold", color=INK, loc=loc, pad=10)


def _season_legend(fig, y=-0.05):
    """하단 가운데 계절 범례(점 마커) — step7과 동일."""
    handles = [plt.Line2D([0], [0], marker="o", ls="", mfc=c, mec="none", ms=7, label=s)
               for s, c in SEA_COL.items()]
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, y),
               ncol=4, frameon=False, fontsize=9)


def _save(fig, path):
    """저장 도우미 — 저장 직전 모든 축의 눈금 글자(xtick·ytick)를 굵게 처리한다.
    (제목은 _title에서 이미 굵음.) 자동 눈금에도 확실히 반영되도록 tight_layout 다음에 부른다."""
    for ax in fig.axes:
        for lab in ax.get_xticklabels() + ax.get_yticklabels():
            lab.set_fontweight("bold")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)

ROOT = r"C:\Users\bjkim\Desktop\project2026"
DATA = os.path.join(ROOT, "1. data_fetcher_and_db", "second_dataset")
OUT  = os.path.join(ROOT, "10. citygas_forecaster")
FIG  = os.path.join(OUT, "fig")
os.makedirs(FIG, exist_ok=True)

BASE_TEMP = 18.0  # 난방도일(HDD) 기준온도 — 한국 도시가스 난방 임계 통상 18℃
SUMMER_MONTHS = [6, 7, 8, 9]  # 난방 거의 0 → 기저부하 추정 구간

REPORT = {}  # 보고서에 박을 숫자 모음


# ----------------------------------------------------------------------
# 1. 월별 전국 도시가스 시계열
# ----------------------------------------------------------------------
def load_monthly():
    # A: 시도별 판매현황 (긴 역사, 1989~2024) — 사용자가 지목한 파일
    A = pd.read_csv(os.path.join(DATA, "한국가스공사_월별 시도별 도시가스 판매현황_20241201.csv"),
                    encoding="euc-kr")
    regions = [c for c in A.columns if c != "연월"]
    A["nat"] = A[regions].sum(axis=1)
    A["ym"] = pd.PeriodIndex(A["연월"], freq="M")
    A = A.sort_values("ym").reset_index(drop=True)

    # B: 용도별 월 공급량 중 '도시가스' (전국 공급, 2016~2026) — 모델 타깃
    B0 = pd.read_csv(os.path.join(DATA, "한국가스공사_용도별 월 공급량_20260331.csv"), encoding="euc-kr")
    B = B0[B0["용도"] == "도시가스"].copy()
    B["ym"] = pd.PeriodIndex(pd.to_datetime(dict(year=B["연도"], month=B["월"], day=1)), freq="M")
    B = B[["ym", "공급량"]].rename(columns={"공급량": "citygas"}).sort_values("ym").reset_index(drop=True)
    return A, regions, B


# ----------------------------------------------------------------------
# 2. 일별 전국 기온 → 일/월 HDD
# ----------------------------------------------------------------------
def load_daily_temp():
    stations = ["temp_c_daegwallyeong", "temp_c_wonju", "temp_c_seosan",
                "temp_c_pohang", "temp_c_yeonggwang"]
    T = pd.read_parquet(os.path.join(DATA, "data", "land_full.parquet"),
                        columns=["timestamp"] + stations)
    T["tmean_pt"] = T[stations].mean(axis=1)           # 시간별 5지점 평균
    T["date"] = T["timestamp"].dt.normalize()
    daily = T.groupby("date")["tmean_pt"].mean().reset_index().rename(columns={"tmean_pt": "tmean"})
    daily["ym"] = daily["date"].dt.to_period("M")
    daily["hdd"] = (BASE_TEMP - daily["tmean"]).clip(lower=0)
    return daily


def monthly_temp(daily):
    mt = daily.groupby("ym").agg(tmean=("tmean", "mean"),
                                 hdd_sum=("hdd", "sum"),
                                 ndays=("hdd", "size")).reset_index()
    return mt


# ----------------------------------------------------------------------
# 2-b. 일별 유효일수(요일·공휴일 가중치) — KOGAS 공식자료
#      민수용=가정/상업(난방 주도), 산업용=공장(주말 낙폭 큼)
# ----------------------------------------------------------------------
def load_effdays():
    def rd(fn):
        d = pd.read_csv(os.path.join(DATA, fn), encoding="euc-kr")
        d["date"] = pd.to_datetime(d["연월일"])
        return d.set_index("date")["유효일수"]
    eff = pd.DataFrame({
        "eff_minsu":    rd("한국가스공사_도시가스 민수용 일별 유효일수_20210901.csv"),
        "eff_industry": rd("한국가스공사_도시가스 산업용 일별 유효일수_20210901.csv"),
    })
    return eff


def blended_effday(eff, w_minsu, dates):
    """국가 도시가스 일별 캘린더계수 = w·민수 + (1-w)·산업. 결측일은 1.0."""
    e = eff.reindex(pd.DatetimeIndex(dates))
    f = w_minsu * e["eff_minsu"] + (1 - w_minsu) * e["eff_industry"]
    return f.fillna(1.0).values


# ----------------------------------------------------------------------
# 3. 월 수요모델  citygas = c0 + c1*HDD_sum + c2*trend
# ----------------------------------------------------------------------
def fit_monthly_model(df):
    df = df.sort_values("ym").reset_index(drop=True)
    df["t"] = np.arange(len(df))
    feat = ["hdd_sum", "t"]
    X = np.column_stack([np.ones(len(df))] + [df[f].values for f in feat])
    y = df["citygas"].values

    # holdout: 마지막 12개월
    n_test = 12
    Xtr, ytr = X[:-n_test], y[:-n_test]
    Xte, yte = X[-n_test:], y[-n_test:]
    beta, *_ = np.linalg.lstsq(Xtr, ytr, rcond=None)

    def pred(Xm): return Xm @ beta
    yhat_tr, yhat_te = pred(Xtr), pred(Xte)
    yhat_all = pred(X)

    def mape(a, p): return float(np.mean(np.abs((a - p) / a)) * 100)
    def r2(a, p): return float(1 - np.sum((a - p) ** 2) / np.sum((a - np.mean(a)) ** 2))

    metrics = dict(
        coef=dict(const=float(beta[0]), hdd=float(beta[1]), trend=float(beta[2])),
        mape_train=mape(ytr, yhat_tr), mape_test=mape(yte, yhat_te),
        r2_train=r2(ytr, yhat_tr), r2_all=r2(y, yhat_all),
        n_train=len(ytr), n_test=len(yte),
        train_period=f"{df['ym'].iloc[0]}~{df['ym'].iloc[-n_test-1]}",
        test_period=f"{df['ym'].iloc[-n_test]}~{df['ym'].iloc[-1]}",
    )
    df["pred"] = yhat_all
    return beta, df, metrics


# ----------------------------------------------------------------------
# 4. 기온 일분해기
#    g_d = base_day(연) + c1_hdd * hdd_d   →  월합이 월모델과 맞게 재조정
# ----------------------------------------------------------------------
def estimate_base_by_year(df):
    """여름철(난방 0) 월 공급량 / 일수 = 일 기저부하. 연도별로."""
    s = df[df["ym"].dt.month.isin(SUMMER_MONTHS)].copy()
    s["base_day"] = s["citygas"] / s["ndays"]
    s["year"] = s["ym"].dt.year
    by = s.groupby("year")["base_day"].mean()
    return by  # 연도별 일 기저부하


def daily_profile(daily_temps, base_day, c1_hdd, monthly_total, effday=None, mode="base"):
    """일별 기온(+요일/공휴일 유효일수) → 재조정된 일 송출 곡선. 월합 = monthly_total.

    요일·공휴일 가중(effday) 적용 방식:
      mode="base" : 기저부하(상업·산업·취사)에만 적용 — 난방은 추운 평일에도 안 꺾이므로
                    피크를 부풀리지 않음(물리적으로 타당, 일최대 앵커로 확인).
      mode="all"  : 기저+난방 전체에 적용(비교용).
    """
    hdd = np.clip(BASE_TEMP - np.asarray(daily_temps, float), 0, None)
    heat = c1_hdd * hdd
    base = np.full_like(hdd, base_day, dtype=float)
    if effday is not None:
        e = np.asarray(effday, float)
        if mode == "base":
            base = base * e
        else:
            base, heat = base * e, heat * e
    raw = base + heat
    scale = monthly_total / raw.sum()
    return raw * scale, hdd


# ----------------------------------------------------------------------
# 5. 일일 최대 앵커(연 1점 실측)로 피크 검증
# ----------------------------------------------------------------------
def load_daily_max():
    m = pd.read_csv(os.path.join(DATA, "한국가스공사_연도별 일일 최대 공급량_20260130.csv"),
                    encoding="euc-kr")
    m = m[["날짜(도시가스)", "공급량(도시가스)"]].rename(
        columns={"날짜(도시가스)": "date", "공급량(도시가스)": "max_obs"})
    m["date"] = pd.to_datetime(m["date"])
    return m


def main():
    A, regions, B = load_monthly()
    daily = load_daily_temp()
    mt = monthly_temp(daily)

    # A vs B 정합(겹치는 기간)
    ab = A[["ym", "nat"]].merge(B, on="ym", how="inner")
    REPORT["ab_overlap"] = f"{ab['ym'].min()}~{ab['ym'].max()} ({len(ab)}개월)"
    REPORT["ab_corr"] = float(ab["nat"].corr(ab["citygas"]))
    REPORT["ab_ratio_mean"] = float((ab["nat"] / ab["citygas"]).mean())

    # 모델 학습 데이터: B(도시가스 공급) ∩ 기온
    df = B.merge(mt, on="ym", how="inner").dropna().reset_index(drop=True)
    REPORT["model_period"] = f"{df['ym'].min()}~{df['ym'].max()} ({len(df)}개월)"

    beta, dff, metrics = fit_monthly_model(df)
    REPORT["monthly_model"] = metrics
    c1_hdd = metrics["coef"]["hdd"]
    base_by_year = estimate_base_by_year(dff)
    REPORT["base_day_recent"] = {int(y): float(v) for y, v in base_by_year.tail(4).items()}

    # ---- 일별 유효일수(요일·공휴일) ----
    eff = load_effdays()

    # ---- 일일 최대 앵커로 검증 (캘린더계수 적용 전/후 비교) ----
    dmax = load_daily_max()
    tmap = daily.set_index("date")["tmean"]

    def eval_anchors(w_minsu, mode="base"):
        """w_minsu=None이면 캘린더계수 미적용(기준선)."""
        rows = []
        for _, r in dmax.iterrows():
            d = r["date"]; ym = d.to_period("M"); yr = ym.year
            mrow = dff[dff["ym"] == ym]
            if mrow.empty or d not in tmap.index or yr not in base_by_year.index:
                continue
            mdays = daily[daily["ym"] == ym].sort_values("date")
            effv = None if w_minsu is None else blended_effday(eff, w_minsu, mdays["date"])
            prof, _ = daily_profile(mdays["tmean"].values, base_by_year[yr], c1_hdd,
                                    float(mrow["citygas"].iloc[0]), effday=effv, mode=mode)
            on = float(prof[(mdays["date"] == d).values][0]) if (mdays["date"] == d).any() else np.nan
            rows.append(dict(date=str(d.date()), obs_max=float(r["max_obs"]),
                             pred_on_day=on, peak_pred_month=float(prof.max()),
                             tmean=float(tmap[d])))
        a = pd.DataFrame(rows)
        a["err_pct_on_day"] = (a["pred_on_day"] - a["obs_max"]) / a["obs_max"] * 100
        return a

    base_anchors = eval_anchors(None)  # 기온만
    # 적용 방식 비교: 기저에만(base) vs 전체(all), 민수↔산업 혼합비 격자
    grid = {f"{mode}|w{w}": float(eval_anchors(w, mode)["err_pct_on_day"].abs().mean())
            for mode in ["base", "all"] for w in [1.0, 0.7]}
    # 물리적 근거가 명확한 mode="base"를 채택, 그 안에서 앵커 최소 w 선택
    best_mode = "base"
    best_w = min([1.0, 0.7], key=lambda w: eval_anchors(w, best_mode)["err_pct_on_day"].abs().mean())
    anchors = eval_anchors(best_w, best_mode)
    REPORT["calendar_grid_mae"] = grid
    REPORT["best_mode"] = best_mode
    REPORT["best_w_minsu"] = best_w
    REPORT["anchor_mae_pct_base"] = float(base_anchors["err_pct_on_day"].abs().mean())
    REPORT["anchor_mae_pct"] = float(anchors["err_pct_on_day"].abs().mean())
    REPORT["anchors"] = anchors.to_dict("records")

    # ================== 그림 ==================
    _figs(A, regions, B, df, dff, daily, anchors, base_anchors, base_by_year, c1_hdd, eff, best_w)

    # ================== 산출물 저장 ==================
    params = dict(
        base_temp=BASE_TEMP, summer_months=SUMMER_MONTHS,
        monthly_coef=metrics["coef"],
        base_day_by_year={int(y): float(v) for y, v in base_by_year.items()},
        calendar_weight_minsu=best_w,
        calendar_mode=best_mode,
        note="g_d = (base_day(year)*effday_d + hdd_coef*HDD_d), 월합을 월모델 예측으로 재조정. "
             "요일·공휴일 가중(effday)은 기저부하에만 적용(난방은 추운 평일에도 유지). "
             "effday_d = best_w*민수용 + (1-best_w)*산업용 유효일수.",
        units="TON (2026-06-21 확인: 원천 CSV에 단위 표기는 없으나 '연도별 일일 최대 공급량' "
              "한 테이블에서 발전[7-C에서 TON 확정]과 도시가스 일최대가 동일 스케일이고 연 환산이 "
              "한국 LNG 도입량과 정합 → 발전용과 같은 TON). 월공급량=ton/month, 일송출=ton/day.",
    )
    with open(os.path.join(OUT, "model_params.json"), "w", encoding="utf-8") as f:
        json.dump(params, f, ensure_ascii=False, indent=2)

    # 예시 일예측 CSV: 가장 최근 완전한 겨울월 (요일·공휴일 반영)
    ex_ym = pd.Period("2025-01", "M")
    mdays = daily[daily["ym"] == ex_ym].sort_values("date")
    mrow = dff[dff["ym"] == ex_ym]
    if not mrow.empty and len(mdays):
        effv = blended_effday(eff, best_w, mdays["date"])
        prof, hdd = daily_profile(mdays["tmean"].values, base_by_year[2025], c1_hdd,
                                  float(mrow["citygas"].iloc[0]), effday=effv)
        ex = pd.DataFrame(dict(date=mdays["date"].dt.date.values, tmean=mdays["tmean"].round(1).values,
                               hdd=np.round(hdd, 1), effday=np.round(effv, 4),
                               citygas_daily_est=np.round(prof).astype(int)))
        ex.to_csv(os.path.join(OUT, "example_daily_forecast_2025-01.csv"), index=False, encoding="utf-8-sig")

    with open(os.path.join(OUT, "_report_numbers.json"), "w", encoding="utf-8") as f:
        json.dump(REPORT, f, ensure_ascii=False, indent=2, default=str)
    print(json.dumps(REPORT, ensure_ascii=False, indent=2, default=str))


def _figs(A, regions, B, df, dff, daily, anchors, base_anchors, base_by_year, c1_hdd, eff, best_w):
    # Fig1: 월별 추세 (이동평균=짙은 잉크색 강조, 원자료=옅게)
    fig, ax = plt.subplots(figsize=(6, 3.4))
    x = A["ym"].dt.to_timestamp()
    ax.set_xlim(pd.Timestamp("2015-01-01"), pd.Timestamp("2024-12-31"))
    ax.plot(x, A["nat"], lw=1.0, color=ACCENT, alpha=0.95, label="월별 전국 판매량")
    ax.plot(x, A["nat"].rolling(12, center=True).mean(), lw=1.2, alpha=0.55, color=SOFT, label="12개월 이동평균")
    _title(ax, "전국 도시가스 월별 판매량 (2015~2024)")
    ax.set_ylabel("월 판매량"); ax.legend(fontsize=9, frameon=False, loc="upper right")
    _style(ax)
    fig.tight_layout(); _save(fig, os.path.join(FIG, "01_trend.png"))

    # Fig2: 월별 계절성 — 박스를 계절 색으로
    A2 = A.copy(); A2["m"] = A2["ym"].dt.month
    fig, ax = plt.subplots(figsize=(6.6, 3.6))
    data = [A2[A2["m"] == m]["nat"].values for m in range(1, 13)]
    bp = ax.boxplot(data, patch_artist=True, widths=0.62,
                    medianprops=dict(color=INK, lw=1.3),
                    whiskerprops=dict(color=MUTED), capprops=dict(color=MUTED),
                    flierprops=dict(marker="o", ms=2.5, mfc=SOFT, mec="none", alpha=0.5))
    for m, b in zip(range(1, 13), bp["boxes"]):
        b.set(facecolor=SEA_COL[SEA_OF[m]], edgecolor="white", alpha=0.92)
    ax.set_xticklabels(range(1, 13)); ax.set_xlabel("월"); ax.set_ylabel("월 판매량")
    _title(ax, "월별 계절성 — 겨울 난방 집중 (1989~2024)")
    _style(ax); _season_legend(fig)
    fig.tight_layout(); _save(fig, os.path.join(FIG, "02_seasonality.png"))

    # Fig3: 시도별 최근 1년 비중 — 1위만 강조색
    last12 = A.tail(12)[regions].sum().sort_values(ascending=False)
    share = (last12 / last12.sum() * 100)
    fig, ax = plt.subplots(figsize=(7.4, 3.6))
    colors = [ACCENT if i == 0 else INK for i in range(len(share))]
    ax.bar(range(len(share)), share.values, color=colors, width=0.72)
    ax.set_xticks(range(len(share))); ax.set_xticklabels(share.index, fontsize=8)
    ax.set_ylabel("비중(%)"); _title(ax, "시도별 도시가스 비중 (최근 12개월)")
    _style(ax)
    fig.tight_layout(); _save(fig, os.path.join(FIG, "03_region_share.png"))

    # Fig4: 월 기온 ↔ 가스 — 계절 색 산점도(step7 양식의 대표 그림)
    fig, ax = plt.subplots(figsize=(6.2, 4.2))
    df2 = df.copy(); df2["season"] = df2["ym"].dt.month.map(SEA_OF)
    for s, c in SEA_COL.items():
        g = df2[df2["season"] == s]
        ax.scatter(g["tmean"], g["citygas"] / 1e6, s=34, c=c, alpha=0.8,
                   edgecolors="none", label=s)
    ax.axvline(BASE_TEMP, ls="--", lw=0.9, color=SOFT)
    ax.text(BASE_TEMP + 0.5, 0.96, "난방 임계 18℃", transform=ax.get_xaxis_transform(),
            fontsize=8.5, color=MUTED, va="top", ha="left")
    ax.set_xlabel("월평균 기온(℃)"); ax.set_ylabel("월 도시가스 공급량")
    _title(ax, "월 기온 ↔ 가스 — 난방 주도, 여름은 기저")
    _style(ax); _season_legend(fig)
    fig.tight_layout(); _save(fig, os.path.join(FIG, "04_temp_curve.png"))

    # Fig5: 월모델 실측 vs 예측 + 검증구간
    fig, ax = plt.subplots(figsize=(9, 3.4))
    xm = dff["ym"].dt.to_timestamp()
    ax.plot(xm, dff["citygas"] / 1e6, "o-", ms=3, lw=1, color=INK, label="실측")
    ax.plot(xm, dff["pred"] / 1e6, lw=2.0, color=ACCENT, label="모델")
    ax.axvspan(xm.iloc[-12], xm.iloc[-1], color=ACCENT, alpha=0.08, label="검증구간(최근 12개월)")
    _title(ax, "월 수요모델: 실측 vs 예측"); ax.set_ylabel("월 공급량 (백만 톤)")
    _style(ax)
    fig.legend(fontsize=9, frameon=False, ncol=3, loc="lower center", bbox_to_anchor=(0.5, -0.04))
    fig.tight_layout(); _save(fig, os.path.join(FIG, "05_monthly_fit.png"))

    # Fig6: 일분해 예시 — 겨울 평월(주말 보임) + 설 포함월(연휴 보임)
    fig, axes = plt.subplots(1, 2, figsize=(9.8, 3.6), sharey=True)
    for ax, ym, ttl in [(axes[0], pd.Period("2021-01", "M"), "2021년 1월 — 주말 약화"),
                        (axes[1], pd.Period("2021-02", "M"), "2021년 2월 — 설 연휴 급감")]:
        md = daily[daily["ym"] == ym].sort_values("date")
        mrow = dff[dff["ym"] == ym]
        if mrow.empty or md.empty:
            continue
        effv = blended_effday(eff, best_w, md["date"])
        prof, hdd = daily_profile(md["tmean"].values, base_by_year[ym.year], c1_hdd,
                                  float(mrow["citygas"].iloc[0]), effday=effv)
        dow = md["date"].dt.dayofweek.values
        colors = [WEEKEND_COL if w >= 5 else WEEKDAY_COL for w in dow]
        ax.bar(md["date"].dt.day, prof, color=colors)
        ax2 = ax.twinx()
        ax2.plot(md["date"].dt.day, md["tmean"], color=INK, lw=1.5)
        ax2.set_ylabel("기온(℃)", color=INK, fontsize=9)
        ax2.tick_params(length=0); ax2.spines[["top"]].set_visible(False)
        ax2.spines[["right"]].set_color(RULE)
        ax.set_title(ttl, fontsize=11, color=INK, loc="left"); ax.set_xlabel("일")
        _style(ax)
    axes[0].set_ylabel("일 송출량(추정)")
    fig.suptitle("월 총량을 일별 기온·요일·공휴일로 분해", fontsize=12.5, fontweight="bold",
                 color=INK, x=0.012, ha="left", y=1.02)
    handles = [plt.Line2D([0], [0], marker="s", ls="", mfc=WEEKDAY_COL, mec="none", ms=8, label="평일"),
               plt.Line2D([0], [0], marker="s", ls="", mfc=WEEKEND_COL, mec="none", ms=8, label="주말"),
               plt.Line2D([0], [0], color=INK, lw=1.6, label="기온")]
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, -0.04),
               ncol=3, frameon=False, fontsize=9)
    fig.tight_layout(); _save(fig, os.path.join(FIG, "06_daily_disagg.png"))

    # Fig7: 일최대 앵커 검증 — 캘린더계수 적용 전(옅은 외곽선)/후(짙은 점)
    if anchors is not None and not anchors.empty:
        fig, ax = plt.subplots(figsize=(5.6, 4.8))
        allv = pd.concat([anchors[["obs_max", "pred_on_day"]],
                          base_anchors[["obs_max", "pred_on_day"]]])
        lim = [allv.min().min() * 0.95, allv.max().max() * 1.05]
        ax.plot(lim, lim, ls="--", color=SOFT, lw=1, zorder=0)
        ax.scatter(base_anchors["obs_max"], base_anchors["pred_on_day"], s=42,
                   facecolors="none", edgecolors=SOFT, label="기온만 (적용 전)")
        ax.scatter(anchors["obs_max"], anchors["pred_on_day"], s=46, color=INK,
                   label="+요일·공휴일 (적용 후)", zorder=3)
        for _, r in anchors.iterrows():
            ax.annotate(r["date"][:7], (r["obs_max"], r["pred_on_day"]), fontsize=7,
                        color=MUTED, xytext=(3, 3), textcoords="offset points")
        ax.set_xlabel("실측 일일 최대 송출량"); ax.set_ylabel("모델 예측(해당일)")
        _title(ax, "연 1점 일최대 앵커 검증", loc="center")
        ax.legend(fontsize=9, frameon=False, loc="upper left")
        _style(ax)
        fig.tight_layout(); _save(fig, os.path.join(FIG, "07_anchor_check.png"))

    # Fig8: 특수일 효과 (서울 기준, 평일 대비 감소율)
    sp = pd.read_csv(os.path.join(DATA, "한국가스공사_지역별 도시가스 수요의 특수일 효과_20220810.csv"),
                     encoding="euc-kr")
    pick = ["토요일", "일요일", "1월 1일", "설 당일", "추석 당일", "광복절", "크리스마스", "석가탄신일"]
    sp2 = sp[sp["특수일"].isin(pick)].set_index("특수일").reindex(pick)
    fig, ax = plt.subplots(figsize=(7.6, 3.6))
    vals = sp2["서울"].values * 100
    ax.bar(range(len(pick)), vals, color=ACCENT, alpha=0.9, width=0.72)
    ax.set_xticks(range(len(pick))); ax.set_xticklabels(pick, fontsize=8, rotation=20)
    ax.set_ylabel("평일 대비 수요 변화(%)")
    _title(ax, "특수일 효과 — 연휴일수록 도시가스 수요 급감 (서울)")
    ax.axhline(0, color=MUTED, lw=0.8)
    _style(ax)
    fig.tight_layout(); _save(fig, os.path.join(FIG, "08_special_day.png"))


if __name__ == "__main__":
    main()
