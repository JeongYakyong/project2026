"""
rebuild_main_fh_from_bf.py -- (일회성) 제주 forecast_horizon 을 bf 백필 자료로 통째 재구성.

목적 (2026-06-16, 사용자 결정)
input_data_jeju.db 의 forecast_horizon 에는 west 일사 없던 옛 자료가 섞여 있다.
새 백필(bf_jeju.db, radiation_west/east 포함, 180 base)로 **본 DB 테이블을 완전히
교체**한다.  bf 의 불완전 base(완결성 미달 -- 현재 2025-12-18 하나, KMA apihub
보관기간 초과로 재취득 불가)는 옮기기 전에 제거한다.

동작
  1) bf_jeju.db: kimr/kimg 완결성 미달 base 를 forecast_horizon 에서 DELETE.
  2) input_data_jeju.db: forecast_horizon 을 DROP (통째 비우기).
  3) bf_jeju.db 의 forecast_horizon 을 input_data_jeju.db 로 복사(merge_runs).
  4) 검증: 행수·base수·컬럼·radiation_west non-null 출력.

실행
    python core/rebuild_main_fh_from_bf.py            # 실제 수행
    python core/rebuild_main_fh_from_bf.py --dry-run  # 무엇을 지울지만 출력

파괴적 작업(본 DB forecast_horizon DROP)이라 --dry-run 으로 먼저 확인 권장.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parent
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import collect_data_jeju as cj
import collect_forecast_runs as cfr
import backfill_jeju_forecast as bf

T = cfr.RUNS_TABLE  # forecast_horizon


def main() -> None:
    ap = argparse.ArgumentParser(description="제주 forecast_horizon 을 bf 백필로 통째 재구성")
    ap.add_argument("--out", default="bf", help="소스 staging 이름 (기본 bf -> data/bf_jeju.db)")
    ap.add_argument("--dry-run", action="store_true", help="삭제 대상만 출력, 변경 없음")
    args = ap.parse_args()

    bf_db = cfr.region_db("jeju", args.out)
    main_db = cj.DEFAULT_DB
    if not bf_db.exists():
        sys.exit(f"{bf_db} 없음")

    # 1) bf 의 불완전 base 식별 (kimr/kimg 완결성).
    bases = bf._bases_in_db(bf_db)
    incomplete = [
        b for b in bases
        if not (bf.kimr_complete(bf_db, b) and bf.kimg_complete(bf_db, b))
    ]
    print(f"[bf] {bf_db.name}: {len(bases)} bases, 불완전 {len(incomplete)}개")
    for b in incomplete:
        print(f"     - {b.strftime('%Y-%m-%d')} (제거 대상)")

    with sqlite3.connect(main_db) as c:
        try:
            o = c.execute(f"SELECT COUNT(*) FROM {T}").fetchone()[0]
            ob = c.execute(f"SELECT COUNT(DISTINCT base) FROM {T}").fetchone()[0]
            oc = len(c.execute(f"PRAGMA table_info({T})").fetchall())
        except sqlite3.OperationalError:
            o = ob = oc = 0
    print(f"[main] {main_db.name}: 현재 {T} = {o} rows / {ob} bases / {oc} cols (DROP 예정)")

    if args.dry_run:
        print("\n[dry-run] 변경 없음.  실제 수행하려면 --dry-run 빼고 다시 실행.")
        return

    # 1) bf 에서 불완전 base 삭제.
    if incomplete:
        with sqlite3.connect(bf_db) as c:
            for b in incomplete:
                base_str = b.astimezone(cfr.KST).strftime("%Y-%m-%d")
                c.execute(f"DELETE FROM {T} WHERE base LIKE ?", (base_str + "%",))
            c.commit()
        print(f"[1] bf: 불완전 {len(incomplete)} base 삭제 완료")

    # 2) main forecast_horizon DROP.
    with sqlite3.connect(main_db) as c:
        c.execute(f"DROP TABLE IF EXISTS {T}")
        c.commit()
    print(f"[2] main: {T} DROP 완료")

    # 3) bf -> main 복사.
    print("[3] bf -> main 복사:")
    cfr.merge_runs(bf_db, main_db)

    # 4) 검증.
    with sqlite3.connect(main_db) as c:
        n = c.execute(f"SELECT COUNT(*) FROM {T}").fetchone()[0]
        nb = c.execute(f"SELECT COUNT(DISTINCT base) FROM {T}").fetchone()[0]
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({T})").fetchall()]
        chk = {
            col: c.execute(f'SELECT COUNT(*) FROM {T} WHERE "{col}" IS NOT NULL').fetchone()[0]
            for col in ("radiation_west", "radiation_east", "radiation_south")
            if col in cols
        }
    print(f"[4] main 새 {T} = {n} rows / {nb} bases / {len(cols)} cols")
    print(f"    radiation_west/east 존재: "
          f"{'radiation_west' in cols} / {'radiation_east' in cols}")
    print(f"    일사 non-null: {chk}")
    print("\n완료.")


if __name__ == "__main__":
    main()
