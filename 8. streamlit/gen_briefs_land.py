# -*- coding: utf-8 -*-
"""매일 자동 — 전국 D+1~D+15 '날짜별' 종합 AI 브리핑 생성·저장. 서버 cron 전용.

모든 브리핑은 하루치(단일일). D+1~15 를 3티어(근지평 D+1~3 / 중지평 D+4~10 / 장지평 D+11~15)로 묶어
티어별 1콜(JSON)로 날짜별 브리핑을 받아 저장한다(총 3콜, 누락 시 그 날만 단건 폴백 +α).
DB(input_data_land.db, est_horizon_land 등)만 읽고(use_live=False) Gemini 만 호출한다.
KPX/KMA 수집은 절대 트리거하지 않는다(수집 API 한도 보호 — 수집은 별도 cron).

저장: 전용 sqlite `ai_briefings.db` (brief_store), 키 = (region, 날짜, days=1, 'overview').
streamlit 메인·예측확인 탭이 날짜 선택기로 그 날짜 브리핑을 그대로 읽어 표시한다.

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
    ap = argparse.ArgumentParser(description="전국 D+1~D+15 날짜별 종합 브리핑 자동 생성")
    ap.add_argument("--date", default=None,
                    help="생성 기준일 YYYY-MM-DD (기본=오늘). 이 날짜 기준 D+1~D+15.")
    ap.add_argument("--region", default="land")
    args = ap.parse_args()

    anchor = (pd.Timestamp(args.date) if args.date else pd.Timestamp.now()).normalize()
    print(f"== 날짜별 종합 브리핑 생성 (기준일 {anchor:%Y-%m-%d}, region={args.region}) ==")

    res = B.generate_all_days(args.region, anchor, use_live=False)
    for r in res:
        mark = "OK " if r["ok"] else "FAIL"
        print(f"  [{mark}] D+{r['horizon']:<2} {r['start']}"
              + (f"  {r['msg']}" if r.get("msg") else ""))

    n_ok = sum(1 for r in res if r["ok"])
    print(f"== {n_ok}/{len(res)} days saved ==")
    return 0 if n_ok == len(res) else 1


if __name__ == "__main__":
    sys.exit(main())
