# -*- coding: utf-8 -*-
"""AI 브리핑 저장소 — (지역·시작일·지평·종류)로 카테고리화한 별도 데이터.

브리핑은 수집 데이터가 아니라 앱 산출물이므로 원본 DB(input_data_land.db)를 건드리지 않고
전용 파일 `ai_briefings.db`에 따로 적재한다. streamlit·API 양쪽이 공유하도록 순수 sqlite만 사용.

키 = (region, start_date, days, kind)
  - region     : 'land' (제주 확장 대비)
  - start_date : 'YYYY-MM-DD' 브리핑 시작일
  - days       : 지평 = 시작일부터 N일(구간 길이)
  - kind       : overview / sendout / weather
같은 키로 다시 생성하면 갱신(upsert)되고, created_at 만 새로 찍힌다.
"""
from datetime import datetime
from pathlib import Path
import sqlite3

DB_PATH = (Path(__file__).resolve().parent.parent
           / "1. data_fetcher_and_db" / "data" / "ai_briefings.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS briefings (
  region     TEXT    NOT NULL DEFAULT 'land',
  start_date TEXT    NOT NULL,
  days       INTEGER NOT NULL,
  kind       TEXT    NOT NULL,
  brief_text TEXT,
  fact_text  TEXT,
  model      TEXT,
  created_at TEXT,
  PRIMARY KEY (region, start_date, days, kind)
);
"""

_COLS = ["region", "start_date", "days", "kind",
         "brief_text", "fact_text", "model", "created_at"]


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    con.execute(_SCHEMA)        # 첫 호출에 테이블 자동 생성
    return con


def save(start_date: str, days: int, kind: str, brief_text: str,
         fact_text: str = "", model: str = "", region: str = "land") -> str:
    """브리핑 1건 적재(upsert) → 저장 시각(created_at) 반환."""
    created_at = datetime.now().isoformat(timespec="seconds")
    with _conn() as con:
        con.execute(
            "INSERT INTO briefings (region, start_date, days, kind, brief_text, "
            "fact_text, model, created_at) VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(region, start_date, days, kind) DO UPDATE SET "
            "brief_text=excluded.brief_text, fact_text=excluded.fact_text, "
            "model=excluded.model, created_at=excluded.created_at",
            (region, start_date, int(days), kind, brief_text, fact_text, model, created_at))
    return created_at


def load(start_date: str, days: int, kind: str, region: str = "land") -> dict | None:
    """키로 1건 조회 → dict 또는 None."""
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM briefings WHERE region=? AND start_date=? AND days=? AND kind=?",
            (region, start_date, int(days), kind)).fetchone()
    return dict(row) if row else None


def latest_for(start_date: str, region: str = "land", days: int | None = None) -> dict | None:
    """그 시작일의 가장 최근 생성 브리핑 1건(본문 포함) — 표시 전용(메인·예측확인 탭).

    days 를 주면 그 지평으로 한정(예: 1일). 종류(kind)는 가장 최근 생성된 것을 따른다.
    """
    where = "WHERE region=? AND start_date=?"
    params = [region, start_date]
    if days is not None:
        where += " AND days=?"
        params.append(int(days))
    with _conn() as con:
        row = con.execute(
            f"SELECT * FROM briefings {where} ORDER BY created_at DESC LIMIT 1",
            tuple(params)).fetchone()
    return dict(row) if row else None


def list_all(region: str | None = None, limit: int = 100) -> list[dict]:
    """저장된 브리핑 목록(최근 순) — 본문 제외 메타 위주."""
    where = "WHERE region=?" if region else ""
    params = (region,) if region else ()
    with _conn() as con:
        rows = con.execute(
            f"SELECT region, start_date, days, kind, model, created_at, "
            f"substr(brief_text,1,80) AS preview FROM briefings {where} "
            f"ORDER BY created_at DESC LIMIT ?", (*params, int(limit))).fetchall()
    return [dict(r) for r in rows]


def delete(start_date: str, days: int, kind: str, region: str = "land") -> int:
    with _conn() as con:
        cur = con.execute(
            "DELETE FROM briefings WHERE region=? AND start_date=? AND days=? AND kind=?",
            (region, start_date, int(days), kind))
        return cur.rowcount
