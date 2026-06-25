# -*- coding: utf-8 -*-
"""매일 자동 — 전국 지평 밴드(6구간) '종합' AI 브리핑 생성·저장. 서버 cron 전용.

밴드(disjoint): D+1 · D+2 · D+3 · 단지평(D+4~5) · 중지평(D+6~10) · 장지평(D+11~15).
DB(input_data_land.db, est_horizon_land 등)만 읽고(use_live=False) Gemini 만 호출한다.
KPX/KMA 수집은 절대 트리거하지 않는다(수집 API 한도 보호 — 수집은 별도 cron).

저장: 전용 sqlite `ai_briefings.db` (brief_store), 키 = (region, start_date, days, 'overview').
streamlit 메인·예측확인 탭이 이 저장본을 밴드 선택기로 골라 표시한다.

실행:  python "8. streamlit/gen_briefs_land.py"            # 오늘 기준
       python "8. streamlit/gen_briefs_land.py" --date 2026-06-25
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pandas as pd
import brief_ai as B


def main() -> int:
    ap = argparse.ArgumentParser(description="전국 지평 밴드 종합 브리핑 자동 생성")
    ap.add_argument("--date", default=None,
                    help="생성 기준일 YYYY-MM-DD (기본=오늘). 밴드는 이 날짜 기준 D+1~D+15.")
    ap.add_argument("--region", default="land")
    args = ap.parse_args()

    anchor = (pd.Timestamp(args.date) if args.date else pd.Timestamp.now()).normalize()
    print(f"== 지평 밴드 종합 브리핑 생성 (기준일 {anchor:%Y-%m-%d}, region={args.region}) ==")

    res = B.generate_all_bands(args.region, anchor, use_live=False)
    for r in res:
        mark = "OK " if r["ok"] else "FAIL"
        print(f"  [{mark}] {r['band']:<4} {r['target']:<8} key=({r['start']}, {r['days']}d)"
              + (f"  {r['msg']}" if r["msg"] else ""))

    n_ok = sum(1 for r in res if r["ok"])
    print(f"== {n_ok}/{len(res)} bands saved ==")
    return 0 if n_ok == len(res) else 1


if __name__ == "__main__":
    sys.exit(main())
