"""
ingest_rt_smp_csv.py -- (1회성) clean_rt_smp.csv -> input_data_jeju.db::historical.

제주 실시간 SMP 과거치(2024-03-01 ~ 2026-05-28, 무결 구간)를 historical 에 적재한다.
이후 구간(2026-05-29~)은 api_fetchers_jeju.fetch_kpx_jeju_rt_smp 가 API 로 채운다.
(CSV 는 2026-05-28 까지만 무결 -- 그 이후 결측 행은 CSV 에서 제거됨.)

저장 정책 (2026-06-03 변경): 구간 원시값을 그대로 보관하고 파생은 함께 계산해 넣는다.
  smp_rt_g1..g4  = 구간 원시 RT SMP (CSV 의 g1..g4 그대로)
  smp_jeju_rt    = mean(g1..g4)                  (시간평균 RT SMP, 모델 타깃)
  smp_rt_neg_num = count(g1..g4 < NEG_THRESHOLD)  (음수권 구간 개수 0..4)
api_fetchers_jeju._fetch_jeju_rt_smp_one_day 와 동일 정의(임계 포함).  구 boolean
smp_rt_neg_flag 는 폐기 (drop 은 별도 마이그레이션 스크립트가 수행).

partial_upsert 사용 -- historical 의 다른 컬럼(관측 수급/기상/_da)은 건드리지 않는다.

사용:  python "temp(remove_after_use)/ingest_rt_smp_csv.py"
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "core"))

from _common import partial_upsert  # noqa: E402

CSV_PATH = HERE / "clean_rt_smp.csv"
DB_PATH = REPO / "data" / "input_data_jeju.db"
CSV_GUGAN = ["g1", "g2", "g3", "g4"]
DB_GUGAN = ["smp_rt_g1", "smp_rt_g2", "smp_rt_g3", "smp_rt_g4"]
NEG_THRESHOLD = 5.0  # api_fetchers_jeju._JEJU_RT_NEG_THRESHOLD 와 일치.


def main() -> None:
    df = pd.read_csv(CSV_PATH)
    # timestamp: "2024-03-01 0:00" (앞자리 0 없음, 초 없음) -> historical PK 포맷.
    ts = pd.to_datetime(df["timestamp"], format="%Y-%m-%d %H:%M")
    g = df[CSV_GUGAN].apply(pd.to_numeric, errors="coerce")

    out = pd.DataFrame(g.values, columns=DB_GUGAN)
    out.index = ts.dt.strftime("%Y-%m-%d %H:%M:%S")
    out.index.name = "timestamp"
    out[DB_GUGAN] = out[DB_GUGAN].round(4)
    out["smp_jeju_rt"] = g.mean(axis=1).round(4).values
    out["smp_rt_neg_num"] = (g < NEG_THRESHOLD).sum(axis=1).astype(int).values

    # 전구간 결측 행 제거 (g 가 모두 NaN 인 행).
    out = out.dropna(subset=["smp_jeju_rt"])
    print(
        f"[ingest] {len(out):,} rows  "
        f"({out.index[0]} ~ {out.index[-1]}), "
        f"neg_num>0: {int((out['smp_rt_neg_num'] > 0).sum()):,}"
    )

    n = partial_upsert("historical", out, DB_PATH)
    print(f"[ingest] UPSERT historical: {n:,} rows -> {DB_PATH}")


if __name__ == "__main__":
    main()
