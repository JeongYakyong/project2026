# -*- coding: utf-8 -*-
"""serve_citygas_daily.py -- 전국 일단위 도시가스 송출량(추정) 서빙 (예보지평 반영)

역할: 기상예보지평(forecast_horizon, 5지점 기온) → 일단위 도시가스 송출 추정 → est_horizon_citygas.
모델(2단, 월→일)의 '일 분해식'을 지평별로 그대로 적용한다.
  g_d = base_day(연)*effday_d + c1_hdd*HDD_d
  - HDD_d   : max(0, 18 - 그날 5지점 평균기온)   ← forecast_horizon에서 일평균
  - effday_d: 요일·공휴일 가중(민수:산업=7:3), 기저부하에만 적용  ← KOGAS 유효일수표(날짜조회)
  - base_day: 그해 여름 일평균(없으면 최근 연도)  ← model_params.json
계수·base_day는 학습(build_citygas_daily.py)에서 확정된 값을 그대로 읽어 쓴다.

입력 forecast_horizon : (timestamp 타깃시각, base 발행시각, horizon_d, temp_<5지점>) tall·시간별
출력 est_horizon_citygas : (timestamp 날짜, base, horizon_d, est_citygas_sendout, tmean, hdd, effday, n_hours)

사용
    python "10. citygas_forecaster/serve_citygas_daily.py"                 # 최신 base 1건
    python "10. citygas_forecaster/serve_citygas_daily.py" --base 2026-06-18
    python "10. citygas_forecaster/serve_citygas_daily.py" --backfill 5    # 최근 5 base
    python "10. citygas_forecaster/serve_citygas_daily.py" --days 10       # 지평 D+10까지만
    python "10. citygas_forecaster/serve_citygas_daily.py" --no-write      # 적재 없이 출력만
"""
from __future__ import annotations
import os, sys, json, sqlite3, argparse
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
DB = os.path.join(ROOT, "1. data_fetcher_and_db", "data", "input_data_land.db")
SECOND = os.path.join(ROOT, "1. data_fetcher_and_db", "second_dataset")
PARAMS = os.path.join(HERE, "model_params.json")

STATIONS = ["daegwallyeong", "wonju", "seosan", "pohang", "yeonggwang"]
TEMP_COLS = [f"temp_{s}" for s in STATIONS]
# 일평균 기온을 신뢰할 조건: 하루를 충분히 덮어야 함.
# KMA 예보는 D+5까지 1시간, 이후 3시간 간격 → 시간수 대신 '시각 범위'로 판정.
MIN_HOUR_SPAN = 18   # (그날 max시각 - min시각) ≥ 18h  (3시간격 풀데이=0..21=21h도 통과)
MIN_POINTS = 6       # 최소 관측점수(부분일 방지)


# ---------------------------------------------------------------- 유효일수
def load_effday_map(w_minsu):
    def rd(fn):
        d = pd.read_csv(os.path.join(SECOND, fn), encoding="euc-kr")
        d["date"] = pd.to_datetime(d["연월일"]).dt.normalize()
        return d.set_index("date")["유효일수"]
    minsu = rd("한국가스공사_도시가스 민수용 일별 유효일수_20210901.csv")
    indus = rd("한국가스공사_도시가스 산업용 일별 유효일수_20210901.csv")
    eff = (w_minsu * minsu + (1 - w_minsu) * indus)
    return eff  # Series: date -> effday


# ---------------------------------------------------------------- 모델
def load_model():
    p = json.load(open(PARAMS, encoding="utf-8"))
    coef = p["monthly_coef"]
    base_by_year = {int(k): float(v) for k, v in p["base_day_by_year"].items()}
    return dict(c1_hdd=coef["hdd"], base_temp=p["base_temp"],
                base_by_year=base_by_year, w_minsu=p["calendar_weight_minsu"])


def base_day_for(year, base_by_year):
    if year in base_by_year:
        return base_by_year[year]
    return base_by_year[max(base_by_year)]   # 미래연도 폴백: 최근 연도


# ---------------------------------------------------------------- 서빙 핵심
def serve_bases(con, bases, model, effmap, max_days=None):
    q = ("select timestamp, base, horizon_d, " + ", ".join(TEMP_COLS) +
         " from forecast_horizon where base in (%s)" % ",".join("?" * len(bases)))
    fh = pd.read_sql(q, con, params=list(bases))
    if fh.empty:
        return pd.DataFrame()
    fh["timestamp"] = pd.to_datetime(fh["timestamp"])
    fh["date"] = fh["timestamp"].dt.normalize()
    fh["hr"] = fh["timestamp"].dt.hour
    fh["tmean_pt"] = fh[TEMP_COLS].mean(axis=1)          # 시간별 5지점 평균

    g = (fh.groupby(["base", "date"])
            .agg(tmean=("tmean_pt", "mean"),
                 horizon_d=("horizon_d", "min"),
                 n_hours=("tmean_pt", "size"),
                 hmin=("hr", "min"), hmax=("hr", "max")).reset_index())
    g = g[(g["hmax"] - g["hmin"] >= MIN_HOUR_SPAN) & (g["n_hours"] >= MIN_POINTS)].copy()
    if max_days is not None:
        g = g[g["horizon_d"] <= max_days]

    bt = model["base_temp"]
    g["hdd"] = (bt - g["tmean"]).clip(lower=0)
    g["effday"] = g["date"].map(effmap).fillna(1.0).values
    g["year"] = g["date"].dt.year
    g["base_day"] = g["year"].map(lambda y: base_day_for(y, model["base_by_year"]))
    g["est_citygas_sendout"] = (g["base_day"] * g["effday"] + model["c1_hdd"] * g["hdd"]).round()

    g["timestamp"] = g["date"].dt.strftime("%Y-%m-%d %H:%M:%S")
    out = g[["timestamp", "base", "horizon_d", "est_citygas_sendout",
             "tmean", "hdd", "effday", "n_hours"]].copy()
    out[["tmean", "hdd", "effday"]] = out[["tmean", "hdd", "effday"]].round(3)
    return out.sort_values(["base", "horizon_d"]).reset_index(drop=True)


def write_est(con, out):
    con.execute("""create table if not exists est_horizon_citygas(
        timestamp text, base text, horizon_d integer,
        est_citygas_sendout real, tmean real, hdd real, effday real, n_hours integer,
        primary key(timestamp, base, horizon_d))""")
    con.executemany("""insert into est_horizon_citygas
        (timestamp, base, horizon_d, est_citygas_sendout, tmean, hdd, effday, n_hours)
        values(?,?,?,?,?,?,?,?)
        on conflict(timestamp, base, horizon_d) do update set
          est_citygas_sendout=excluded.est_citygas_sendout, tmean=excluded.tmean,
          hdd=excluded.hdd, effday=excluded.effday, n_hours=excluded.n_hours""",
        out.itertuples(index=False, name=None))
    con.commit()


def make_demo_fig(con, demo_base="2026-01-07", anchor_date="2026-01-22", anchor_obs=117836.0):
    """서빙 산출 예시 그림: (좌) 한 base의 D+1~15 일 예측, (우) 일최대 앵커의 지평별 예측."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = "Malgun Gothic"; plt.rcParams["axes.unicode_minus"] = False
    figdir = os.path.join(HERE, "fig"); os.makedirs(figdir, exist_ok=True)

    base = next((b for b in [r[0] for r in con.execute(
        "select distinct base from est_horizon_citygas").fetchall()] if str(b).startswith(demo_base)), None)
    L = pd.read_sql("select timestamp,horizon_d,est_citygas_sendout,tmean from "
                    "est_horizon_citygas where base=? order by horizon_d", con, params=[base])
    R = pd.read_sql("select horizon_d,est_citygas_sendout,tmean from est_horizon_citygas "
                    "where timestamp=? order by horizon_d", con, params=[anchor_date + " 00:00:00"])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 3.6))
    days = pd.to_datetime(L["timestamp"]).dt.strftime("%m-%d")
    ax1.bar(L["horizon_d"], L["est_citygas_sendout"], color="#1f4e79", alpha=0.85)
    a1 = ax1.twinx(); a1.plot(L["horizon_d"], L["tmean"], color="#c0392b", lw=1.4, marker="o", ms=3)
    a1.set_ylabel("예보 기온(℃)", color="#c0392b", fontsize=8)
    ax1.set_xlabel("예보지평 D+n"); ax1.set_ylabel("일 송출(추정)")
    ax1.set_title(f"발행 {str(base)[:10]} — 지평별 일 송출 예측", fontsize=10)
    ax1.spines[["top"]].set_visible(False)

    ax2.axhline(anchor_obs, ls="--", color="grey", lw=1.2, label=f"실측 일최대 {anchor_obs:,.0f}")
    ax2.plot(R["horizon_d"], R["est_citygas_sendout"], color="#1f4e79", lw=1.6, marker="o", ms=4,
             label="서빙 예측")
    ax2.set_xlabel("예보지평 D+n (멀수록 기온예보 불확실)"); ax2.set_ylabel("예측 송출")
    ax2.set_title(f"{anchor_date} 앵커 — 지평이 멀수록 오차↑", fontsize=10)
    ax2.legend(fontsize=8, frameon=False); ax2.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fp = os.path.join(figdir, "09_serving_horizon.png")
    fig.savefig(fp, dpi=120); plt.close(fig)
    print(f"[citygas] 그림 저장: {fp}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", help="발행시각 prefix (예: 2026-06-18). 생략 시 최신 1건")
    ap.add_argument("--backfill", type=int, default=0, help="최근 N개 base")
    ap.add_argument("--days", type=int, default=None, help="지평 상한 D+N (생략 시 전체)")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--fig", action="store_true", help="서빙 예시 그림 생성(est 적재 후)")
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    allbases = [r[0] for r in con.execute(
        "select distinct base from forecast_horizon order by base").fetchall()]
    if args.base:
        bases = [b for b in allbases if str(b).startswith(args.base)]
        if not bases:
            print(f"[citygas] base '{args.base}' 매칭 없음. 최신={allbases[-1]}"); return
    elif args.backfill > 0:
        bases = allbases[-args.backfill:]
    else:
        bases = allbases[-1:]

    model = load_model()
    effmap = load_effday_map(model["w_minsu"])
    out = serve_bases(con, bases, model, effmap, max_days=args.days)
    if out.empty:
        print("[citygas] 산출 없음(예보지평 데이터 확인)"); return

    print(f"[citygas] base {len(bases)}건, 산출 {len(out)}행 "
          f"(지평 D+{int(out.horizon_d.min())}~D+{int(out.horizon_d.max())})")
    show = out[out["base"] == bases[-1]]
    print(show.to_string(index=False))

    if not args.no_write:
        write_est(con, out)
        print(f"[citygas] est_horizon_citygas UPSERT {len(out)}행 완료")
    else:
        print("[citygas] --no-write: 적재 생략")

    if args.fig:
        make_demo_fig(con)
    con.close()


if __name__ == "__main__":
    main()
