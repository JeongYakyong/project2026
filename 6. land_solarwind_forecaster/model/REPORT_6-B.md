# 6-B 요약 — 전국 태양광 PatchTST(D1/2/3) vs LGBM(6-A)

## 설정
- 가중치: landsolar_patchtst(d_model=128·layers=3·d_ff=512, 14피처 3지점 raw).
- 동일 test 2026 origin(D0 23:00) → D+1/2/3 24h. PatchTST=과거336h+대상일기상, LGBM=6-A(지평무관).
- 평가: util MAE(낮 8-17h·흐린날) + true_solar MW MAE(×total_solar_cap). perfect/forecast.

## 결과 (낮시간 util MAE)
| 지평 | PatchTST perfect | LGBM perfect | PatchTST forecast | LGBM forecast |
|---|---|---|---|---|
| D+1 | 0.0407 | 0.1122 | 0.0744 | 0.1288 |
| D+2 | 0.0375 | 0.1142 | 0.0698 | 0.1301 |
| D+3 | 0.0401 | 0.1152 | 0.0707 | 0.1313 |

표 전체(흐린날·true_solar MW 포함): tab/6-B_compare.csv · fig/6-B_compare.png

## 판단(G-13)
- PatchTST가 LGBM 대비 의미 있는(특히 forecast·흐린날·true_solar MW) 개선이면 태양광=PatchTST(D1~3)+LGBM(D4~) 하이브리드.
- 큰 차이 없으면 **태양광도 LGBM 단일**(파시모니·서빙 단순). 아래 수치로 결정.
