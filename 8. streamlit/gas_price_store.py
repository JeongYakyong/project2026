# -*- coding: utf-8 -*-
"""발전용 가스 단가(원/GJ) 저장소 — 월별 수동 입력값을 별도 sqlite 에 적재.

7-C 산출 CSV(`7c_monthly_price_cost.csv`)는 과거 실적 단가의 기본값(폴백)이고,
운영 담당이 최근·앞으로의 월 단가를 화면에서 직접 입력하면 여기에 덮어쓰기(override)된다.
원본 DB(input_data_land.db)·CSV 를 건드리지 않고 전용 파일 `gas_tariff.db` 에 따로 둔다.
streamlit·API 양쪽이 공유하도록 순수 sqlite 만 사용(앱 의존 없음).

키 = ym('YYYY-MM'). 같은 월을 다시 저장하면 갱신(upsert)된다.
환산: 가스비 = 송출량(TON) × 55 GJ/ton × 단가(원/GJ).
"""
from datetime import datetime
from pathlib import Path
import sqlite3

DB_PATH = (Path(__file__).resolve().parent.parent
           / "1. data_fetcher_and_db" / "data" / "gas_tariff.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS gas_tariff (
  ym         TEXT NOT NULL PRIMARY KEY,   -- 'YYYY-MM'
  won_per_gj REAL NOT NULL,               -- 발전용 단가(원/GJ)
  updated_at TEXT
);
"""


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    con.execute(_SCHEMA)        # 첫 호출에 테이블 자동 생성
    return con


def save(ym: str, won_per_gj: float) -> str:
    """월 단가 1건 적재(upsert) → 저장 시각(updated_at) 반환."""
    updated_at = datetime.now().isoformat(timespec="seconds")
    with _conn() as con:
        con.execute(
            "INSERT INTO gas_tariff (ym, won_per_gj, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(ym) DO UPDATE SET "
            "won_per_gj=excluded.won_per_gj, updated_at=excluded.updated_at",
            (ym, float(won_per_gj), updated_at))
    return updated_at


def load_overrides() -> dict[str, float]:
    """저장된 월별 단가 override → {ym: 원/GJ}. 없으면 빈 dict."""
    with _conn() as con:
        rows = con.execute("SELECT ym, won_per_gj FROM gas_tariff").fetchall()
    return {r["ym"]: r["won_per_gj"] for r in rows}


def list_all() -> list[dict]:
    """저장된 단가 목록(월 오름차순) — 화면 표·삭제용."""
    with _conn() as con:
        rows = con.execute(
            "SELECT ym, won_per_gj, updated_at FROM gas_tariff ORDER BY ym").fetchall()
    return [dict(r) for r in rows]


def delete(ym: str) -> int:
    with _conn() as con:
        cur = con.execute("DELETE FROM gas_tariff WHERE ym=?", (ym,))
        return cur.rowcount
