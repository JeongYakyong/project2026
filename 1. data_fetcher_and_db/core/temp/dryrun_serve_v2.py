"""dryrun_serve_v2.py -- 검증(iii): v2 데이터가 들어간 DB 사본으로 서빙 체인 실행.

본 DB 는 절대 건드리지 않는다:
  1. input_data_<region>.db -> data/dryrun_<region>.db 사본
  2. v2_<region>.db 의 forecast_horizon 을 사본에 컬럼 보존 병합
  3. 서빙 체인(serve_chain_*_new.py)을 importlib 로 로드, 모듈 전역 DB 경로를
     사본으로 패치(체인 본체 + build_horizon_backtest 류가 각자 DB 상수를 가짐
     -- sys.modules 전수 패치로 누락 방지) 후 main() 실행
  4. 사본의 est_horizon_* 산출을 점검: 행수/NaN/물리범위

사용:
    python core/temp/dryrun_serve_v2.py --region land --base 2026-07-03
    python core/temp/dryrun_serve_v2.py --region jeju --base 2026-07-03
    python core/temp/dryrun_serve_v2.py --region land --base 2026-06-25 --compare
      (--compare: v2 병합 전 사본으로도 같은 base 를 돌려 산출 차이 분포 보고)
"""
from __future__ import annotations

import argparse
import importlib.util
import shutil
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

CORE = Path(__file__).resolve().parent.parent
ROOT = CORE.parent.parent
DATA = CORE.parent / "data"
sys.path.insert(0, str(CORE))

CHAIN = {
    "land": ROOT / "7. land_gas_forecaster" / "serve_chain_land_new.py",
    "jeju": ROOT / "3. jeju_solarwind_forecaster" / "serve_chain_jeju_new.py",
}
EST_TABLE = {"land": "est_horizon_land", "jeju": "est_horizon_jeju"}
EST_VAL_COL = {"land": "est_demand_land", "jeju": "est_demand_jeju"}


def patch_db_paths(region: str, new_path: str) -> int:
    """로드된 모든 모듈에서 input_data_<region>.db 를 가리키는 DB 전역을 교체.

    체인이 하위 모듈을 sys.modules 등록 없이 들고 있는 경우가 있어
    (예: serve_chain_land_new 의 `bht = expf.bht`), 각 모듈의 속성으로 매달린
    모듈 객체(1단계)도 함께 걷는다.
    """
    import types
    needle = f"input_data_{region}.db"

    seen: set[int] = set()
    mods: list = []
    for m in list(sys.modules.values()):
        if m is None or id(m) in seen:
            continue
        seen.add(id(m))
        mods.append(m)
        for v in list(vars(m).values()):
            if isinstance(v, types.ModuleType) and id(v) not in seen:
                seen.add(id(v))
                mods.append(v)

    n = 0
    for m in mods:
        for attr in ("DB", "DB_PATH", "DEFAULT_DB"):
            v = getattr(m, attr, None)
            if isinstance(v, str) and v.endswith(needle):
                setattr(m, attr, new_path)
                n += 1
            elif isinstance(v, Path) and str(v).endswith(needle):
                setattr(m, attr, Path(new_path))
                n += 1
    return n


def run_chain(region: str, db_copy: Path, base: str) -> None:
    spec = importlib.util.spec_from_file_location(f"chain_{region}", CHAIN[region])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"chain_{region}"] = mod
    spec.loader.exec_module(mod)          # 모듈 로드 (내부에서 하위 모듈 import)
    n = patch_db_paths(region, str(db_copy))
    print(f"  [dryrun] DB 경로 패치: {n}개 모듈 전역 -> {db_copy.name}")
    argv_bak = sys.argv
    sys.argv = ["serve_chain", "--base", base]
    try:
        mod.main()
    finally:
        sys.argv = argv_bak


def inspect_est(db: Path, region: str, base_like: str) -> pd.DataFrame:
    with sqlite3.connect(db) as c:
        df = pd.read_sql(
            f"SELECT * FROM {EST_TABLE[region]} WHERE base LIKE ?", c,
            params=(base_like + "%",))
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", choices=["land", "jeju"], required=True)
    ap.add_argument("--base", required=True, help="YYYY-MM-DD")
    ap.add_argument("--compare", action="store_true",
                    help="v2 병합 전 사본으로도 실행해 산출 차이 분포 보고")
    args = ap.parse_args()

    import collect_forecast_v2 as cfv2

    src = DATA / f"input_data_{args.region}.db"
    v2db = DATA / f"v2_{args.region}.db"

    results = {}
    variants = (["cur", "v2"] if args.compare else ["v2"])
    for variant in variants:
        copy = DATA / f"dryrun_{variant}_{args.region}.db"
        print(f"\n=== [{variant}] 사본 생성 -> {copy.name}")
        shutil.copyfile(src, copy)
        if variant == "v2":
            cfv2.merge_v2(v2db, copy)
        # 체인은 프로세스 전역 상태(모듈 캐시)를 오염시키므로 variant 별로
        # 하위 프로세스에서 실행한다.
        import subprocess
        code = (
            "import sys; sys.path.insert(0, r'{core}');\n"
            "sys.argv=['x','--region','{region}','--base','{base}','--exec-one',"
            "r'{copy}'];\n"
            "import importlib.util;"
            "spec=importlib.util.spec_from_file_location('me', r'{me}');"
            "m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m);"
            "m.exec_one('{region}', r'{copy}', '{base}')"
        ).format(core=str(CORE), region=args.region, base=args.base,
                 copy=str(copy), me=str(Path(__file__).resolve()))
        r = subprocess.run([sys.executable, "-X", "utf8", "-c", code],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        tail = "\n".join((r.stdout or "").splitlines()[-12:])
        print(tail)
        if r.returncode != 0:
            print("  [dryrun] 체인 실패!")
            print("\n".join((r.stderr or "").splitlines()[-15:]))
            sys.exit(1)
        est = inspect_est(copy, args.region, args.base)
        vc = EST_VAL_COL[args.region]
        n_nan = int(est[vc].isna().sum()) if vc in est else -1
        print(f"  [{variant}] {EST_TABLE[args.region]}: {len(est)}행, "
              f"{vc} NaN {n_nan}건, 범위 "
              f"{est[vc].min():.0f}~{est[vc].max():.0f}" if len(est) else
              f"  [{variant}] 산출 없음!")
        results[variant] = est

    if args.compare and all(len(v) for v in results.values()):
        a = results["cur"].set_index("timestamp")
        b = results["v2"].set_index("timestamp")
        ts = a.index.intersection(b.index)
        num = [c for c in a.columns if c in b.columns
               and pd.api.types.is_numeric_dtype(a[c]) and c != "horizon_d"]
        diff = (b.loc[ts, num] - a.loc[ts, num])
        rel = (diff.abs().mean() / a.loc[ts, num].abs().mean().replace(0, np.nan))
        print("\n=== 산출 차이 (v2 - 현행), 공유 timestamp "
              f"{len(ts)}행 ===")
        out = pd.DataFrame({"평균차": diff.mean().round(2),
                            "MAD": diff.abs().mean().round(2),
                            "상대(%)": (100 * rel).round(2)})
        print(out.to_string())


def exec_one(region: str, db_copy: str, base: str) -> None:
    """하위 프로세스 진입점: 체인 로드 -> DB 패치 -> main()."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    run_chain(region, Path(db_copy), base)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
