"""collect_forecast_v2.py -- 기상예보 수집기 v2: 신 KIM 소스 → forecast_horizon.

2026-07-01 KMA 개편 대응 (new_kma 연구 REPORT_01~03, PROJECT.md 2026-07-04 로그).
기존 collect_forecast_new.py(현행 cron)는 그대로 두고, 이 파일이 병행 수집한다.

무엇이 바뀌나 (컬럼명·수식·반올림은 현행과 완전 동일 -- 서빙체인 무영향)
- 육지 D+1~5: 지역모델 R030(3km) **1h** -- 기온·습도·바람·돌풍·강수·일사
  (07-01 이후 3h 로 떨어졌던 해상도 복원 + 소스는 NE57 전구 8km -> R030 3km).
  D+6~12 와 운량(전 지평)은 현행 NE57 경로(cdln.build_forecast_wide) 그대로.
- 제주(2026-07-05 최종): met = KIMR GRIB 시계열 1콜/지점(운영 X/Y 셀·cape/cinn/
  tcog/tcoh 연속성 유지, 서버 혼잡 면역 -- NC per-hf 통일안은 혼잡 밤 실측에서
  기각) / 일사 3지점 = R030 NC per-hf 2변수(GRIB 에 일사 없음) / 운량·D+6~7 =
  NE57.  구 운영과의 차이는 일사 소스 전환과 reh 반올림(r4->r2, 값 동일)뿐 --
  compat 검사로 met 전 컬럼 양자화 동일 확인.
- frcc(등압면 1h 운량 아카이브, 신규 컬럼 total/midlow_cloud_r030_*)는 GRIB
  지점당 2콜인데 **밤 혼잡 시 60~110s/콜 + 부분 응답** -- --skip-frcc 로 본 수집과
  분리 가능(부족분은 core/temp/backfill_frcc_cols.py 를 한가한 시간에, 컬럼 보존
  upsert 라 재실행=치유).
- 신규 컬럼(재훈련용 아카이브): 육지 cape/cinn/hpbl_<지점>, 양권역
  radiation_direct/diffuse_<지점> + 운량 r030 2종.  기존 컬럼은 불변.

안전장치
- 기본 출력 = 격리 DB(data/v2_land.db / v2_jeju.db).  본 DB(input_data_*.db)는
  --production 플래그가 있을 때만.
- upsert 는 **컬럼 보존 병합**(ON CONFLICT DO UPDATE + COALESCE) -- 지점 단위
  부분 백필(--points)이 다른 지점 데이터를 지우지 않고, --merge 가 본 DB 의
  1h 시절(~06-30) 운량 등 기존 값을 NULL 로 덮지 않는다.
  (cfr._upsert_df 의 INSERT OR REPLACE 는 배치에 없는 컬럼을 NULL 로 덮는다.)

사용 예
    python core/collect_forecast_v2.py                        # 최신 12z, 육지 -> v2_land.db
    python core/collect_forecast_v2.py --region both          # 육지 + 제주
    python core/collect_forecast_v2.py --backfill 10          # 과거 10일치 (resume-skip)
    python core/collect_forecast_v2.py --points seosan --backfill 30   # 신지점만 백필
    python core/collect_forecast_v2.py --verify               # 완전성 검사 (fetch 없음)
    python core/collect_forecast_v2.py --merge                # v2_*.db -> 본 DB 병합
    python core/collect_forecast_v2.py --production ...       # 본 DB 직적재 (컷오버 후 cron)
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

import collect_forecast_runs as cfr
import collect_forecast_new as cfn
import collect_data_land_new as cdln
import collect_data_jeju_new as cdjn
import collect_data_jeju as cj
import api_fetchers_kim2 as k2
import postprocess as pp

KST = cfr.KST
UTC = cfr.UTC
RUNS_TABLE = cfr.RUNS_TABLE

# land 16일 = D+15.5 까지 "요청은 전부"(사용자 지시).  실제 데이터는 288h(D+12)까지만
# 오지만, KMA 가 지평을 확장하는 날 자동 수용.  완결성 기대치는 NE57_AVAIL_HF(288)
# 기준이라 churn 없음.
REGIONS_V2 = {
    "land": {"days": 16, "points": k2.POINTS_LAND_V2},   # 16일=D+15.5 요청(확장 자동 수용)
    "jeju": {"days": 7,  "points": k2.POINTS_JEJU_V2},
}
DEFAULT_OUT = "v2"   # 격리 기본.  --production 이면 None(본 DB).


def _points_for(region: str, sfx_filter: list[str] | None) -> list[dict]:
    pts = REGIONS_V2[region]["points"]
    if not sfx_filter:
        return pts
    sel = [p for p in pts if p["sfx"] in sfx_filter]
    unknown = set(sfx_filter) - {p["sfx"] for p in sel}
    if unknown:
        raise SystemExit(f"--points 에 모르는 접미사: {sorted(unknown)} "
                         f"(가능: {[p['sfx'] for p in pts]})")
    return sel


# ── 컬럼 보존 upsert (v2 전용 -- cfr._upsert_df 의 NULL 덮어쓰기 문제 해결) ──
def upsert_wide_coalesce(df: pd.DataFrame, db_path: Path,
                         table: str = RUNS_TABLE) -> int:
    """(base,timestamp) 충돌 시 새 값이 NULL 이 아니면 갱신, NULL 이면 기존 유지.

    INSERT ... ON CONFLICT(base,timestamp) DO UPDATE SET col=COALESCE(excluded.col, col).
    스키마 자동 확장(ALTER)·유니크 인덱스 생성은 cfr._upsert_df 와 동일 패턴.
    """
    if df.empty:
        return 0
    drop = [c for c in df.columns if cfr.is_non_kma(c)]
    if drop:
        df = df.drop(columns=drop)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = f"_tmp_{table}"
    with sqlite3.connect(db_path) as c:
        df.to_sql(tmp, c, if_exists="replace", index=True)
        existing = {r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
        tmp_cols = [r[1] for r in c.execute(f"PRAGMA table_info({tmp})").fetchall()]
        if not existing:
            c.execute(f"CREATE TABLE {table} AS SELECT * FROM {tmp} WHERE 0")
            existing = set(tmp_cols)
        for col in tmp_cols:
            if col not in existing:
                c.execute(f'ALTER TABLE {table} ADD COLUMN "{col}"')
        c.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_base_ts "
            f"ON {table}(base, timestamp)"
        )
        col_list = ", ".join(f'"{col}"' for col in tmp_cols)
        updates = ", ".join(
            f'"{col}"=COALESCE(excluded."{col}", "{table}"."{col}")'
            for col in tmp_cols if col not in ("base", "timestamp")
        )
        c.execute(
            f"INSERT INTO {table} ({col_list}) SELECT {col_list} FROM {tmp} "
            f"WHERE true ON CONFLICT(base, timestamp) DO UPDATE SET {updates}"
        )
        n = c.execute("SELECT changes()").fetchone()[0]
        c.execute(f"DROP TABLE {tmp}")
    return n


def upsert_runs_v2(wide: pd.DataFrame, base_utc: datetime, db_path: Path,
                   table: str = RUNS_TABLE) -> int:
    """wide(단일 base)에 base/horizon_d 태그(cfr.upsert_runs 와 동일 산식)를 붙여
    컬럼 보존 UPSERT."""
    if wide.empty:
        return 0
    base_kst = base_utc.astimezone(KST)
    base_date = base_kst.date()
    df = wide.copy()
    ts_dates = pd.to_datetime(df.index, format="%Y-%m-%d %H:%M:%S").date
    df.insert(0, "horizon_d", [(d - base_date).days for d in ts_dates])
    df.insert(0, "base", base_kst.strftime("%Y-%m-%d %H:%M:%S"))
    df.index.name = "timestamp"
    return upsert_wide_coalesce(df, db_path, table)


def merge_v2(src_db: Path, dst_db: Path) -> int:
    """src 의 forecast_horizon 전체를 dst 에 컬럼 보존 병합.

    cfr.merge_runs(INSERT OR REPLACE)와 달리 dst 의 기존 값(예: ~06-30 의
    1h 시절 운량)을 v2 의 NULL 로 덮지 않는다."""
    if not src_db.exists():
        print(f"  [merge] {src_db.name} 없음 -- skip")
        return 0
    with sqlite3.connect(src_db) as c:
        try:
            df = pd.read_sql(f"SELECT * FROM {RUNS_TABLE}", c)
        except Exception as e:
            print(f"  [merge] {src_db.name} 읽기 실패: {e} -- skip")
            return 0
    if df.empty:
        print(f"  [merge] {src_db.name} 비어있음 -- skip")
        return 0
    df = df.set_index("timestamp")
    n = upsert_wide_coalesce(df, dst_db)
    print(f"  [merge] {src_db.name} -> {dst_db.name}::{RUNS_TABLE}  "
          f"{n:,} rows ({df['base'].nunique()} bases, 컬럼 보존)")
    return n


# ── wide 조립 ────────────────────────────────────────────────────────────────
def _window_strs(base_utc: datetime, days: int) -> tuple[str, str]:
    """day-aligned 윈도우 [D+1 00시, D+1+days 00시) 의 KST 문자열 경계."""
    base_kst = base_utc.astimezone(KST)
    start = (base_kst + timedelta(days=1)).replace(hour=0, minute=0, second=0,
                                                   microsecond=0)
    end = start + timedelta(days=days)
    return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")


def build_wide_v2(region: str, base_utc: datetime, days: int,
                  points: list[dict] | None = None,
                  with_frcc: bool = True) -> pd.DataFrame:
    """v2 wide 조립.  points 지정 시 그 지점만 (부분 백필용)."""
    pts = points if points is not None else REGIONS_V2[region]["points"]
    w_start, w_end = _window_strs(base_utc, days)

    if region == "land":
        suffix_map = {p["name"]: p["sfx"] for p in pts}
        # [1] R030 1h part -- per-hf std 멀티변수 (일사·MCAPE 가 시계열 grib 에
        #     없거나 다른 진단이라 per-hf 가 필수.  grib met 병행안은 검증에서
        #     기각: cape(7006)!=MCAPE·cinn 9999 센티넬·셀 불일치 — 2026-07-04).
        long = k2.fetch_model_long(
            pts, "KIMR", "R030", k2.R030_NAME_LAND, base_utc, days,
            k2.R030_MAX_HF, rain_anchor=True)
        # + 1h 결합 운량 아카이브 (frcc GRIB 시계열 2콜/지점, 신규 컬럼 전용 --
        #   기존 total/midlow_cloud 는 NE57 유지, 서빙 무영향)
        if with_frcc:
            frcc = k2.fetch_r030_frcc_long(pts, base_utc, days, k2.R030_MAX_HF)
            long = pd.concat([long, frcc], ignore_index=True)
        r030 = k2.long_to_wide_v2(long, suffix_map)
        if not r030.empty:
            r030 = pp.clip_ranges(r030)
            r030 = r030[(r030.index >= w_start) & (r030.index < w_end)]
        # [2] NE57 3h part -- pt_txt2_std per-hf (구 typ01 pt 와 값 동일, 4~5배
        #     빠름).  빈 응답이면 현행 빌더(cdln) 경로로 자동 폴백.
        ne57_long = k2.fetch_ne57_std_long(pts, base_utc, days)
        if not ne57_long.empty:
            ne57 = k2.long_to_wide_v2(ne57_long, suffix_map)
            ne57 = pp.clip_ranges(ne57)
            ne57 = ne57[(ne57.index >= w_start) & (ne57.index < w_end)]
        else:
            print("  [WARN] NE57-std 빈 응답 -- 현행 빌더(구 pt)로 폴백")
            with k2.ne57_3h_only(), k2.land_points_override(points):
                ne57 = cdln.build_forecast_wide(base=base_utc, forecast_days=days)
        # [3] combine: R030 우선, R030 에 없는 컬럼(운량)은 NE57 그대로
        if r030.empty:
            print("  [WARN] R030 part 비어있음 -- NE57 단독 wide (부분 적재)")
            return ne57
        if ne57.empty:
            print("  [WARN] NE57 part 비어있음 -- R030 단독 wide (부분 적재)")
            return r030
        return r030.combine_first(ne57)

    if region == "jeju":
        # 2026-07-05 최종: met = KIMR GRIB 시계열 1콜/지점(운영 X/Y·cape 연속성,
        # 서버 혼잡 면역) / 일사 = NC per-hf 2변수(GRIB 에 일사 없음) / frcc = GRIB /
        # 운량·D+6~7 = NE57.  met GRIB 실패 시 현행 빌더(cdjn) 폴백.
        suffix_map = {p["name"]: p["sfx"] for p in pts}
        met_long = k2.fetch_kimr_grib_long(pts, base_utc, days, k2.R030_MAX_HF)
        if met_long.empty:
            print("  [WARN] KIMR-grib met 비어있음 -- 현행 제주 빌더 전체 폴백")
            with k2.ne57_3h_only():
                return cdjn.build_forecast_wide(base=base_utc, forecast_days=days)
        sol_long = k2.fetch_model_long(
            pts, "KIMR", "R030", "SWDDIR2,SWDDIF2,ACSWDNB", base_utc, days,
            k2.R030_MAX_HF, rain_anchor=True, anchor_name="ACSWDNB")
        parts = [met_long, sol_long]
        if with_frcc:
            parts.append(k2.fetch_r030_frcc_long(pts, base_utc, days, k2.R030_MAX_HF))
        long = pd.concat(parts, ignore_index=True)
        r030 = k2.long_to_wide_v2(long, suffix_map, radiation_round=2)
        if not r030.empty:
            r030 = pp.clip_ranges(r030)
            r030 = r030[(r030.index >= w_start) & (r030.index < w_end)]
        ne57_long = k2.fetch_ne57_std_long(pts, base_utc, days)
        if not ne57_long.empty:
            ne57 = k2.long_to_wide_v2(ne57_long, suffix_map, radiation_round=2)
            ne57 = pp.clip_ranges(ne57)
            ne57 = ne57[(ne57.index >= w_start) & (ne57.index < w_end)]
        else:
            print("  [WARN] NE57-std 빈 응답 -- 현행 제주 빌더로 폴백")
            with k2.ne57_3h_only():
                ne57 = cdjn.build_forecast_wide(base=base_utc, forecast_days=days)
        if r030.empty:
            print("  [WARN] R030 part 비어있음 -- 현행 제주 빌더 전체 폴백")
            with k2.ne57_3h_only():
                return cdjn.build_forecast_wide(base=base_utc, forecast_days=days)
        if ne57.empty:
            print("  [WARN] NE57 part 비어있음 -- R030 단독 wide (부분 적재)")
            return r030
        return r030.combine_first(ne57)

    raise ValueError(region)


# ── 완결성 (v2 그리드 기준) ──────────────────────────────────────────────────
def expected_timestamps_v2(region: str, base_utc: datetime, days: int) -> set[str]:
    """v2 가 수집하는 timestamp 집합 = R030 1h 그리드 ∪ NE57 3h 그리드.

    NE57 쪽은 실수집과 같은 코드(collection_hf_range + ne57_3h_only)로 산출해
    기대와 실제가 어긋나는 무한 재수집(churn)을 원천 차단한다.
    12z 검산: land(12d) = 118 + 56 = 174 행 / jeju(7d) = 118 + 16 = 134 행.
    """
    base_kst = base_utc.astimezone(KST)
    hfs_1h = set(k2.hf_range_1h(base_utc, days, k2.R030_MAX_HF))
    # NE57 기대 그리드 = 가용 상한(288h) 기준 -- 요청은 372h 까지 하되(확장 자동
    # 수용) 기대치를 288 에 두어 "영원히 불완전" churn 을 막는다.
    hfs_3h = set(k2.hf_range_3h(base_utc, days, k2.NE57_AVAIL_HF))
    return {(base_kst + timedelta(hours=h)).strftime("%Y-%m-%d %H:%M:%S")
            for h in (hfs_1h | hfs_3h)}


def incomplete_points(region: str, db_path: Path, base_utc: datetime, days: int,
                      pts: list[dict]) -> list[dict] | None:
    """base 의 불완전 지점 목록.  None = base 자체가 미완(행 누락) -> 전 지점 재수집.
    빈 리스트 = 완전(skip 가능).

    판정:
    - 기대 timestamp 전부 존재해야 함 (아니면 None -- 행 누락은 지점 구분 불가)
    - 지점별 sentinel: temp_<sfx> NULL 셀 0 (전 행)
    - 제주 추가 sentinel: radiation_direct_<sfx> -- R030 1h 커버 행에서 NULL 0
      (일사는 met 과 별도 콜이라 temp 로는 실패를 못 잡는다)
    """
    if not db_path.exists() or db_path.stat().st_size == 0:
        return None
    base_str = base_utc.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")
    exp = expected_timestamps_v2(region, base_utc, days)
    base_kst = base_utc.astimezone(KST)
    ts_1h = {(base_kst + timedelta(hours=h)).strftime("%Y-%m-%d %H:%M:%S")
             for h in k2.hf_range_1h(base_utc, days, k2.R030_MAX_HF)}
    with sqlite3.connect(db_path) as c:
        try:
            cols = {r[1] for r in c.execute(f"PRAGMA table_info({RUNS_TABLE})")}
        except sqlite3.OperationalError:
            return None
        if "timestamp" not in cols:
            return None
        present = {r[0] for r in c.execute(
            f"SELECT timestamp FROM {RUNS_TABLE} WHERE base=?", (base_str,))}
        if not exp.issubset(present):
            return None
        bad: list[dict] = []
        for p in pts:
            sent = f"temp_{p['sfx']}"
            if sent not in cols:
                bad.append(p)
                continue
            n_null = c.execute(
                f'SELECT SUM("{sent}" IS NULL) FROM {RUNS_TABLE} WHERE base=?',
                (base_str,)).fetchone()[0] or 0
            if n_null > 0:
                bad.append(p)
                continue
            if region == "jeju":
                rsent = f"radiation_direct_{p['sfx']}"
                if rsent not in cols:
                    bad.append(p)
                    continue
                marks = ",".join("?" * len(ts_1h))
                n_null = c.execute(
                    f'SELECT SUM("{rsent}" IS NULL) FROM {RUNS_TABLE} '
                    f"WHERE base=? AND timestamp IN ({marks})",
                    (base_str, *sorted(ts_1h))).fetchone()[0] or 0
                if n_null > 0:
                    bad.append(p)
    return bad


def run_region_v2(region: str, bases: list[datetime], days: int, force: bool,
                  db_path: Path, sfx_filter: list[str] | None,
                  with_frcc: bool = True, max_bases: int | None = None) -> int:
    pts_all = _points_for(region, sfx_filter)
    total = 0
    collected = 0            # 실제 수집한(=콜을 쓴) base 수 -- --max-bases 상한 기준
    for i, b in enumerate(bases, 1):
        base_str = b.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")
        label = f"[v2:{region}] base {b.strftime('%Y%m%d %HZ')} ({base_str} KST)"
        pts = pts_all
        if not force:
            bad = incomplete_points(region, db_path, b, days, pts_all)
            if bad is not None and len(bad) == 0:
                print(f"{label} -- skip (완전; --force 로 재수집)")
                continue
            if bad:  # 행은 완전, 일부 지점 컬럼만 결손 -> 그 지점만
                pts = bad
                print(f"{label} -- 부분 재수집: {[p['sfx'] for p in pts]}")
        if max_bases is not None and collected >= max_bases:
            print(f"[v2:{region}] --max-bases {max_bases} 도달 -- 남은 미완 base 는 "
                  f"다음 실행에서 이어받음(resume-skip). 하루 콜 상한 보호.")
            break
        collected += 1
        print(f"\n{'='*70}\n{label}  ({i}/{len(bases)}, window={days}d, "
              f"points={[p['sfx'] for p in pts]})\n{'='*70}")
        try:
            wide = build_wide_v2(region, b, days, points=pts, with_frcc=with_frcc)
        except Exception as e:
            print(f"{label} -- [WARN] fetch failed: {e} (skip)")
            continue
        if wide.empty:
            print(f"{label} -- [WARN] empty wide, nothing to write")
            continue
        n = upsert_runs_v2(wide, b, db_path)
        total += n
        h = pd.Series([(d - b.astimezone(KST).date()).days
                       for d in pd.to_datetime(wide.index).date])
        print(f"{label} -- UPSERT {n:,} rows -> {db_path.name}::{RUNS_TABLE} "
              f"(horizon D+{h.min()}~D+{h.max()})")
    return total


def verify_v2(region: str, db_path: Path, days: int) -> list[str]:
    """base 별 완전성 검사 (fetch 없음).  기대 행수·sentinel 은 v2 그리드 기준."""
    if not db_path.exists() or db_path.stat().st_size == 0:
        print(f"[verify-v2:{region}] {db_path.name} 없음")
        return []
    with sqlite3.connect(db_path) as c:
        try:
            bases = [r[0] for r in c.execute(
                f"SELECT DISTINCT base FROM {RUNS_TABLE} ORDER BY base")]
        except sqlite3.OperationalError:
            print(f"[verify-v2:{region}] {RUNS_TABLE} 테이블 없음")
            return []
    bad: list[str] = []
    pts = REGIONS_V2[region]["points"]
    print(f"[verify-v2:{region}] {db_path.name}::{RUNS_TABLE} -- {len(bases)} bases")
    for base_str in bases:
        base_kst = datetime.strptime(base_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
        base_utc = base_kst.astimezone(UTC)
        res = incomplete_points(region, db_path, base_utc, days, pts)
        if res is None:
            n_exp = len(expected_timestamps_v2(region, base_utc, days))
            with sqlite3.connect(db_path) as c:
                n_have = c.execute(
                    f"SELECT COUNT(*) FROM {RUNS_TABLE} WHERE base=?",
                    (base_str,)).fetchone()[0]
            print(f"  {base_str[:10]}  INCOMPLETE: rows {n_have}/{n_exp}")
            bad.append(base_str[:10].replace("-", ""))
        elif res:
            print(f"  {base_str[:10]}  INCOMPLETE: 지점 {[p['sfx'] for p in res]}")
            bad.append(base_str[:10].replace("-", ""))
    if bad:
        print(f"[verify-v2:{region}] 불완전 base {len(bad)}개 -- "
              f"재실행만으로 부족분 auto-resume")
    else:
        print(f"[verify-v2:{region}] 모든 base 완전 (OK)")
    return bad


# ── CLI ──────────────────────────────────────────────────────────────────────
def main() -> None:
    p = argparse.ArgumentParser(
        description="기상예보 수집기 v2 (R030 1h + NE57 3h) -> forecast_horizon. "
                    "기본은 격리 DB(data/v2_*.db), --production 시 본 DB.")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--base", metavar="YYYYMMDD",
                      help="특정 날짜의 발표 (기본: 최신 가용, 시각은 --utc)")
    mode.add_argument("--backfill", type=int, metavar="N_DAYS",
                      help="과거 N 일치 발표 (resume-skip)")
    mode.add_argument("--merge", action="store_true",
                      help="격리 DB(data/<out>_<region>.db) -> 본 DB 컬럼 보존 병합")
    mode.add_argument("--verify", action="store_true",
                      help="base 별 완전성 검사 (fetch 없음)")
    p.add_argument("--utc", type=int, choices=[0, 6, 12, 18], default=12)
    p.add_argument("--region", choices=["jeju", "land", "both"], default="land")
    p.add_argument("--days", type=int, default=None,
                   help="윈도우 override (기본: 육지 12 / 제주 7)")
    p.add_argument("--points", default=None,
                   help="지점 접미사 콤마 목록 -- 부분 수집/신지점 백필용")
    p.add_argument("--out", default=DEFAULT_OUT,
                   help=f"격리 DB 이름 (기본 {DEFAULT_OUT} -> data/v2_<region>.db)")
    p.add_argument("--production", action="store_true",
                   help="본 DB(input_data_*.db)에 직접 적재 (컷오버 후 cron 용)")
    p.add_argument("--force", action="store_true",
                   help="완전한 base 도 다시 받기")
    p.add_argument("--frcc", action="store_true",
                   help="frcc 1h 운량 아카이브도 수집 (기본 꺼짐 -- 2026-07-05 사용자 "
                        "결정: 운량은 당분간 NE57 3h+서빙 보간 유지.  등압면 GRIB 은 "
                        "혼잡 시 느리고 부분 응답이 잦음.  필요 시 이 플래그 또는 "
                        "core/temp/backfill_frcc_cols.py)")
    p.add_argument("--max-bases", type=int, default=None, metavar="N",
                   dest="max_bases",
                   help="실행당 실제 수집할 base 최대 개수 (하루 콜 상한 보호). "
                        "resume-skip 과 함께 쓰면 같은 cron 을 매일 밤 돌려 N개씩 "
                        "이어받아 수렴(예: --backfill 146 --max-bases 28 ~= 5만콜/일).")
    args = p.parse_args()

    out = None if args.production else args.out
    regions = ["jeju", "land"] if args.region == "both" else [args.region]
    sfx_filter = args.points.split(",") if args.points else None

    if args.verify:
        for region in regions:
            days = args.days or REGIONS_V2[region]["days"]
            verify_v2(region, cfr.region_db(region, out), days)
            print()
        return

    if args.merge:
        for region in regions:
            merge_v2(cfr.region_db(region, args.out), cfr.REGIONS[region]["db"])
        return

    if args.base:
        bases = [datetime.strptime(args.base, "%Y%m%d").replace(hour=args.utc,
                                                                tzinfo=UTC)]
    elif args.backfill:
        bases = [cfn.latest_base(args.utc) - timedelta(days=k)
                 for k in range(args.backfill)][::-1]
    else:
        bases = [cfn.latest_base(args.utc)]

    print(f"[collect_forecast_v2] regions={regions}  bases={len(bases)} "
          f"({bases[0].strftime('%Y%m%d')}~{bases[-1].strftime('%Y%m%d')} "
          f"{args.utc:02d}Z)  out={'본 DB(production)' if out is None else out}  "
          f"points={sfx_filter or '전체'}")

    t0 = time.time()
    for region in regions:
        days = args.days or REGIONS_V2[region]["days"]
        db_path = cfr.region_db(region, out)
        n = run_region_v2(region, bases, days, args.force, db_path, sfx_filter,
                          with_frcc=args.frcc, max_bases=args.max_bases)
        print(f"\n[v2:{region}] total UPSERT {n:,} rows -> {db_path.name}")
    print(f"\n[collect_forecast_v2] done in {(time.time() - t0) / 60:.1f}m")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
