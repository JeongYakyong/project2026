"""
migrate_rt_smp_gugan.py -- (1회성, 2026-06-03) RT SMP 저장 스키마를 구간 원시값으로 재편.

배경:
  기존 historical 은 RT SMP 를 파생 2종(smp_jeju_rt=시간평균, smp_rt_neg_flag=any<0)
  으로만 저장했다.  이제 구간 원시값을 그대로 보관하고 파생은 함께(필요시 재)계산한다.

이 스크립트가 한 번에 수행 (drop -> CSV ingest):
  1) DROP COLUMN smp_rt_neg_flag           (구 boolean 파생 폐기)
  2) clean_rt_smp.csv (2024-03-01 ~ 2026-05-28 무결 구간) 적재
        smp_rt_g1..g4  = CSV g1..g4 원시값
        smp_jeju_rt    = mean(g1..g4)                  (시간평균, 모델 타깃)
        smp_rt_neg_num = count(g1..g4 < NEG_THRESHOLD)  (음수권 구간 개수 0..4)

CSV 가 못 덮는 최근 일자(2026-05-29~)의 g1..g4 는 채우지 않는다 -- 평상시
collect_data_jeju 파이프라인(fetch_kpx_jeju_rt_smp)이 이후 g 포함으로 채운다.
그때까진 해당 행의 smp_jeju_rt(구값)만 남고 g1..g4 / smp_rt_neg_num 은 NULL.

partial_upsert 사용 -- historical 의 다른 컬럼(관측 수급/기상/_da)은 보존(COALESCE).
NEG_THRESHOLD 는 api_fetchers_jeju._JEJU_RT_NEG_THRESHOLD 와 동일(=5.0).

사용:  python "temp(remove_after_use)/migrate_rt_smp_gugan.py"
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "core"))

from _common import partial_upsert  # noqa: E402
from api_fetchers_jeju import (  # noqa: E402
    _JEJU_RT_GUGAN as DB_GUGAN,
    _JEJU_RT_MEAN,
    _JEJU_RT_NEG_NUM,
    _JEJU_RT_NEG_THRESHOLD as NEG_THRESHOLD,
)

CSV_PATH = HERE / "clean_rt_smp.csv"
DB_PATH = REPO / "data" / "input_data_jeju.db"
TABLE = "historical"
CSV_GUGAN = ["g1", "g2", "g3", "g4"]
OLD_FLAG_COL = "smp_rt_neg_flag"


def drop_old_flag(db_path: Path) -> None:
    """구 boolean 파생 컬럼 smp_rt_neg_flag 를 제거 (존재할 때만)."""
    with sqlite3.connect(db_path) as c:
        cols = {r[1] for r in c.execute(f"PRAGMA table_info({TABLE})").fetchall()}
        if OLD_FLAG_COL in cols:
            c.execute(f'ALTER TABLE {TABLE} DROP COLUMN "{OLD_FLAG_COL}"')
            print(f"[drop] removed column {OLD_FLAG_COL}")
        else:
            print(f"[drop] {OLD_FLAG_COL} not present -- skip")


def ingest_csv(db_path: Path) -> int:
    """clean_rt_smp.csv -> smp_rt_g1..g4 + smp_jeju_rt + smp_rt_neg_num 적재."""
    df = pd.read_csv(CSV_PATH)
    # timestamp: "2024-03-01 0:00" (앞자리 0 없음, 초 없음) -> historical PK 포맷.
    ts = pd.to_datetime(df["timestamp"], format="%Y-%m-%d %H:%M")
    g = df[CSV_GUGAN].apply(pd.to_numeric, errors="coerce")

    out = pd.DataFrame(g.round(4).values, columns=DB_GUGAN)
    out.index = ts.dt.strftime("%Y-%m-%d %H:%M:%S")
    out.index.name = "timestamp"
    out[_JEJU_RT_MEAN] = g.mean(axis=1).round(4).values
    out[_JEJU_RT_NEG_NUM] = (g < NEG_THRESHOLD).sum(axis=1).astype(int).values

    out = out.dropna(subset=[_JEJU_RT_MEAN])  # 전구간 결측 행 제거.
    print(
        f"[csv] {len(out):,} rows ({out.index[0]} ~ {out.index[-1]}), "
        f"neg_num>0: {int((out[_JEJU_RT_NEG_NUM] > 0).sum()):,}"
    )
    n = partial_upsert(TABLE, out, db_path)
    print(f"[csv] UPSERT {TABLE}: {n:,} rows")
    return n


def verify(db_path: Path) -> None:
    cols_check = DB_GUGAN + [_JEJU_RT_MEAN, _JEJU_RT_NEG_NUM]
    with sqlite3.connect(db_path) as c:
        present = {r[1] for r in c.execute(f"PRAGMA table_info({TABLE})").fetchall()}
        print(f"[verify] {OLD_FLAG_COL} dropped: {OLD_FLAG_COL not in present}")
        for col in cols_check:
            row = c.execute(
                f'SELECT COUNT(*), MIN(timestamp), MAX(timestamp) '
                f'FROM {TABLE} WHERE "{col}" IS NOT NULL'
            ).fetchone()
            print(f"[verify] {col:16s} non-null={row[0]:,}  [{row[1]} ~ {row[2]}]")
        # 파생 정합: smp_jeju_rt == mean(g1..g4), neg_num == count(g<thr).
        df = pd.read_sql(
            f'SELECT {", ".join(chr(34)+c2+chr(34) for c2 in cols_check)} '
            f'FROM {TABLE} WHERE "{DB_GUGAN[0]}" IS NOT NULL', c,
        )
    g = df[DB_GUGAN]
    mean_ok = (g.mean(axis=1).round(2) == df[_JEJU_RT_MEAN].round(2)).mean()
    neg_ok = ((g < NEG_THRESHOLD).sum(axis=1) == df[_JEJU_RT_NEG_NUM]).mean()
    print(f"[verify] mean==mean(g) match: {mean_ok:.4%} of g-present rows")
    print(f"[verify] neg_num==count(g<{NEG_THRESHOLD}) match: {neg_ok:.4%}")


def main() -> None:
    if not DB_PATH.exists():
        sys.exit(f"DB not found: {DB_PATH}")
    print(f"[migrate] {DB_PATH}")
    drop_old_flag(DB_PATH)
    ingest_csv(DB_PATH)
    verify(DB_PATH)
    print("[migrate] done.")


if __name__ == "__main__":
    main()
