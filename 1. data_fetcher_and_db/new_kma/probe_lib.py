"""probe_lib.py -- KMA 신규 KIM API(2026-07-01 정책) 연구 전용 공용 모듈.

이 폴더(new_kma) 안에서만 쓰는 연구용 코드다.  운영 수집기(core/)와 완전히
분리되어 있고, 운영 DB 에는 아무것도 쓰지 않는다.

핵심 설계
- 캐시 우선: 같은 요청은 probe_cache/ 파일에서 읽고 API 를 다시 부르지 않는다.
  노트북을 몇 번이고 재실행해도 호출 예산이 줄지 않는다.
- 호출 예산: 하드캡 10,000콜 (사용자 승인, 2026-07-04).  calls_log.csv 에
  모든 실호출/캐시히트가 기록되고, 실호출 누계가 캡을 넘으면 예외를 던진다.
- 인증키: .env 의 KMA_API_KEY_SUB3 (예비 키 -- 운영 수집 키와 분리).
- 예의: 실호출 사이 최소 0.3초 간격, 5xx/타임아웃은 2s/4s 백오프 재시도.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import requests
from dotenv import load_dotenv

KST = ZoneInfo("Asia/Seoul")
UTC = timezone.utc

HERE = Path(__file__).resolve().parent               # .../new_kma
load_dotenv(HERE.parent / ".env")                    # 1. data_fetcher_and_db/.env

API_KEY = os.getenv("KMA_API_KEY_SUB3")
if not API_KEY:
    raise RuntimeError("KMA_API_KEY_SUB3 가 .env 에 없습니다 (프로브 전용 예비 키)")

HARD_CAP = 10_000          # 실호출 하드캡 (캐시히트는 제외)
RATE_LIMIT_S = 0.3         # 실호출 간 최소 간격
RETRY_MAX = 3

CACHE_DIR = HERE / "probe_cache"
CACHE_DIR.mkdir(exist_ok=True)
CALLS_LOG = CACHE_DIR / "calls_log.csv"

# ── 엔드포인트 ───────────────────────────────────────────────────────────
# 신규(2026-07-01 정책): 격자 X/Y 기반 표준 API.  group/nwp 로 3모델 선택.
URL_STD = "https://apihub.kma.go.kr/api/typ06/cgi-bin/url/nph-kim_nc_xy_txt2_std"
# 격자 위경도 조회 (g576/r030/l010 등)
URL_LATLON = "https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-nwp_latlon_api"
# 신규(2.2.2 임의 위경도): 위경도 직접 + 콤마 멀티변수 + (data=P, level 생략 시)
# 전 레벨 프로파일 1콜.  ★전구 화면고도 버그 없음(xy_txt2_std 와 달리 정상 디코더).
URL_PT_STD = "https://apihub.kma.go.kr/api/typ06/cgi-bin/url/nph-kim_nc_pt_txt2_std"
# 현행 운영이 쓰는 구 엔드포인트 2종 (교차검증용 -- 읽기만)
URL_OLD_PT = "https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-kim_nc_pt_txt2"
URL_OLD_GRIB = "https://apihub.kma.go.kr/api/typ06/url/kim_grib_pt_tmfc.php"

# ── 수집 지점 (core 의 운영 지점과 동일 좌표) ───────────────────────────
POINTS_LAND = [
    {"name": "Daegwallyeong(100)", "lat": 37.6772, "lon": 128.7185},
    {"name": "Wonju(114)",         "lat": 37.3376, "lon": 127.9466},
    {"name": "Seosan(129)",        "lat": 36.7766, "lon": 126.4939},
    {"name": "Pohang(138)",        "lat": 36.0327, "lon": 129.3799},
    {"name": "Yeonggwang(252)",    "lat": 35.2807, "lon": 126.4750},
]
POINTS_JEJU = [
    {"name": "solar_farm(south)",  "lat": 33.3284, "lon": 126.8366},
    {"name": "West(Gosan)",        "lat": 33.4427, "lon": 126.1713},
    {"name": "East(Seongsan)",     "lat": 33.3868, "lon": 126.8802},
]
POINTS_ALL = POINTS_LAND + POINTS_JEJU

# ── 호출 예산·로그 ───────────────────────────────────────────────────────
_lock = threading.Lock()
_last_call_ts = 0.0


def _count_real_calls() -> int:
    """calls_log.csv 에서 지금까지의 실호출 누계 (세션을 넘어 보존)."""
    if not CALLS_LOG.exists():
        return 0
    with open(CALLS_LOG, newline="", encoding="utf-8") as f:
        return sum(1 for row in csv.DictReader(f) if row.get("cached") == "0")


_real_calls = _count_real_calls()


def budget_status() -> dict:
    return {"real_calls": _real_calls, "hard_cap": HARD_CAP,
            "remaining": HARD_CAP - _real_calls}


_log_lock = threading.Lock()


def _log_call(endpoint: str, params: dict, status: int | str, nbytes: int,
              cached: bool) -> None:
    with _log_lock:
        _log_call_locked(endpoint, params, status, nbytes, cached)


def _log_call_locked(endpoint: str, params: dict, status: int | str, nbytes: int,
                     cached: bool) -> None:
    new_file = not CALLS_LOG.exists()
    with open(CALLS_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["ts_kst", "endpoint", "params", "status", "bytes", "cached"])
        p = {k: v for k, v in params.items() if k != "authKey"}
        w.writerow([datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
                    endpoint.rsplit("/", 1)[-1], json.dumps(p, ensure_ascii=False),
                    status, nbytes, int(cached)])


def _cache_path(endpoint: str, params: dict, binary: bool) -> Path:
    p = {k: str(v) for k, v in sorted(params.items()) if k != "authKey"}
    h = hashlib.sha1((endpoint + json.dumps(p)).encode()).hexdigest()[:10]
    # 사람이 알아볼 수 있는 접두어 (있는 인자만 조합)
    bits = [p.get("group") or p.get("nwp") or "x",
            p.get("nwp", ""), p.get("name", p.get("varn", ""))[:24],
            p.get("tmfc", ""), "hf" + p.get("hf", p.get("ef", ""))[:12],
            p.get("latlon", "")]
    stem = re.sub(r"[^A-Za-z0-9_.,-]", "", "_".join(b for b in bits if b))[:90]
    ext = ".bin" if binary else ".txt"
    return CACHE_DIR / f"{stem}_{h}{ext}"


class BudgetExceeded(RuntimeError):
    pass


def fetch(endpoint: str, params: dict, binary: bool = False,
          timeout: int = 120) -> str | bytes | None:
    """캐시 우선 GET.  성공 body 반환(str 또는 bytes), 실패는 None.

    - 캐시 히트면 API 를 부르지 않는다 (콜 예산 불변).
    - 실호출은 rate-limit + 5xx/타임아웃 백오프 재시도.
    - 4xx 나 빈 body 도 '응답 없음' 마커 파일로 캐시해 재호출을 막는다
      (아카이브 깊이 스캔처럼 '없음' 자체가 답인 프로브가 많다).
    """
    global _real_calls, _last_call_ts
    cpath = _cache_path(endpoint, params, binary)
    miss = cpath.with_suffix(cpath.suffix + ".miss")
    if cpath.exists():
        body = cpath.read_bytes() if binary else cpath.read_text(encoding="utf-8", errors="replace")
        _log_call(endpoint, params, "cache", len(body), cached=True)
        return body
    if miss.exists():
        _log_call(endpoint, params, "cache-miss-marker", 0, cached=True)
        return None

    with _lock:
        if _real_calls >= HARD_CAP:
            raise BudgetExceeded(f"실호출 {_real_calls} >= 하드캡 {HARD_CAP}")
        wait = RATE_LIMIT_S - (time.time() - _last_call_ts)
        if wait > 0:
            time.sleep(wait)
        _last_call_ts = time.time()
        _real_calls += 1

    q = dict(params)
    q["authKey"] = API_KEY
    for attempt in range(RETRY_MAX):
        try:
            r = requests.get(endpoint, params=q, timeout=timeout)
        except (requests.Timeout, requests.ConnectionError) as e:
            if attempt < RETRY_MAX - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            _log_call(endpoint, params, f"EXC:{type(e).__name__}", 0, cached=False)
            return None
        if 500 <= r.status_code < 600 and attempt < RETRY_MAX - 1:
            time.sleep(2 ** (attempt + 1))
            continue
        body = r.content if binary else r.text
        _log_call(endpoint, params, r.status_code, len(body), cached=False)
        if r.status_code == 200 and len(body) > 0:
            if binary:
                cpath.write_bytes(body)
            else:
                cpath.write_text(body, encoding="utf-8")
            return body
        miss.write_text(f"status={r.status_code} bytes={len(body)}", encoding="utf-8")
        return None
    return None


# ── 신규 std API 헬퍼 ────────────────────────────────────────────────────
def fetch_std(group: str, nwp: str, name: str, tmfc: str, hf: int,
              x: int, y: int, data: str = "U", level: str | None = None,
              box: int = 0, help_: int = 0, disp: str = "A") -> str | None:
    """신규 nph-kim_nc_xy_txt2_std 호출.  (x,y)는 1-base 격자, box=n 이면
    (x-n..x+n, y-n..y+n) 사각형을 sub 로 요청한다 (기본 1x1)."""
    params = {
        "group": group, "nwp": nwp, "data": data, "name": name,
        "tmfc": tmfc, "hf": str(hf), "map": "S",
        "sub": f"{x - box},{y - box},{x + box},{y + box}",
        "disp": disp, "help": str(help_),
    }
    if level is not None:
        params["level"] = str(level)
    return fetch(URL_STD, params)


# 응답 파싱: 실제 포맷은 Phase 1 의 help=1 로 확정한 뒤 아래 parse_std 를 조정한다.
# 초기 구현은 구 pt 응답과 같은 '# 헤더 + 공백분리 데이터행' 가정의 관대한 파서.
def parse_std(body: str) -> list[dict]:
    """std ASCII 응답 -> [{컬럼: 값}] (데이터행만).  '#' 헤더의 마지막 줄을
    컬럼명 후보로 쓰고, 실패하면 위치 기반(c0, c1, ...) 이름을 붙인다."""
    header_cols: list[str] | None = None
    rows: list[dict] = []
    for ln in body.splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith("#"):
            cand = s.lstrip("#").split()
            if len(cand) >= 3:
                header_cols = cand
            continue
        parts = s.split()
        cols = (header_cols if header_cols and len(header_cols) == len(parts)
                else [f"c{i}" for i in range(len(parts))])
        rows.append(dict(zip(cols, parts)))
    return rows


def latest_tmfc(utc_hour: int = 12, margin_h: int = 3) -> str:
    """공개 지연 여유(margin_h)를 둔 가장 최근 utc_hour 발표의 tmfc 문자열."""
    cutoff = datetime.now(UTC) - timedelta(hours=margin_h)
    cand = cutoff.replace(hour=utc_hour, minute=0, second=0, microsecond=0)
    if cand > cutoff:
        cand -= timedelta(days=1)
    return cand.strftime("%Y%m%d%H")


# ── 격자 유틸 ────────────────────────────────────────────────────────────
def find_xy(target_lat: float, target_lon: float,
            lats: np.ndarray, lons: np.ndarray) -> tuple[int, int, float]:
    """최근접 격자 (X, Y, 거리km).  X/Y 는 1-base (API sub 규약).
    k030_latlon_grid.ipynb 의 find_nc_xy 와 같은 방식 + 거리(km) 산출."""
    cos_lat = np.cos(np.radians(target_lat))
    dist_sq = (lats - target_lat) ** 2 + ((lons - target_lon) * cos_lat) ** 2
    iy, ix = np.unravel_index(np.argmin(dist_sq, axis=None), dist_sq.shape)
    dist_km = float(np.sqrt(dist_sq[iy, ix])) * 111.0
    return int(ix) + 1, int(iy) + 1, dist_km


def load_grid(name: str) -> tuple[np.ndarray, np.ndarray]:
    """격자 lat/lon 2D 배열 로드.  name = 'g576' | 'r030' | 'l010'."""
    if name in ("g576", "r030"):
        import xarray as xr
        ds = xr.open_dataset(HERE / f"kim_{name}_latlon.nc")
        lats, lons = ds["lat"].values, ds["lon"].values
        ds.close()
        return lats, lons
    if name == "l010":
        z = np.load(HERE / "grids" / "kim_l010_latlon.npz")
        return z["lat"], z["lon"]
    raise ValueError(name)


def fetch_latlon_binary(nwp: str, which: str) -> np.ndarray | None:
    """nph-nwp_latlon_api disp=B -> 2D 배열.

    실측(r030, 2026-07-04): 앞 4byte 는 short 2개가 (첫번째=행수, 두번째=열수)
    순서이고, 반환 격자는 **셀 모서리** 격자다 (자료 격자보다 행·열이 1 크다).
    4모서리 평균이 자료 격자(셀 중심, nc 파일)와 1e-5도 수준으로 일치함을 확인.
    """
    body = fetch(URL_LATLON, {"nwp": nwp, "latlon": which, "disp": "B"},
                 binary=True, timeout=300)
    if body is None:
        return None
    a, b = np.frombuffer(body[:4], dtype="<i2")
    arr = np.frombuffer(body[4:], dtype="<f4")
    if arr.size != int(a) * int(b):
        raise ValueError(f"binary size mismatch: a={a} b={b} floats={arr.size}")
    return arr.reshape(int(a), int(b))


def corners_to_centers(corner: np.ndarray) -> np.ndarray:
    """셀 모서리 격자 (ny+1, nx+1) -> 셀 중심 격자 (ny, nx) (4모서리 평균)."""
    return (corner[:-1, :-1] + corner[1:, :-1]
            + corner[:-1, 1:] + corner[1:, 1:]) / 4.0
