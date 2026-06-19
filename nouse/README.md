# nouse — 미사용·기각 모델 아카이브 (2026-06-19 정리)

현재 서빙에 쓰지 않는 모델 가중치·산출물을 모아둔 곳. **재현용 생성기/평가 코드(`_gen_*.py`·`_ab_*.py`)는
원위치(`5. land_demand_forecaster/training`·`model`)에 보존** — 여기엔 무거운 데이터(가중치·노트북·npz)만 이관.

## 현재 production(전국 수요 하이브리드)이 쓰는 것 — 여기 없음(원위치 유지)
- PatchTST: `5.../training/landdemand_final336/`  (D+1~2 full·D+3~7 주간)
- LGBM: `5.../model/models/lgbm_land_demand_v2hum.txt`  (D+3~15·야간)  + 롤백용 `lgbm_land_demand_v2.txt`

## 이관 내역(미사용 사유)
| 항목 | 사유 |
|---|---|
| `landdemand_aug/` + `forecast_residuals.npz` + `..._aug.ipynb` | 예보오차 증강 — honest 악화로 **기각**(REPORT_5-B §9-5) |
| `landdemand_latefusion/` + `..._latefusion.ipynb` | 시간 Late Fusion — honest≈final2로 **기각**(§10-1) |
| `landdemand_final2/` + `..._final2.ipynb` | seq504 구버전 — 하이브리드는 **final336 채택**(§12)으로 미사용 |
| `lgbm_land_demand_v2comfort.txt`+meta | comfort di/wct — VIF 다중공선성·악화로 **기각**, humidity(v2hum) 채택(§11) |
| `train_landdemand_patchtst360_colab.ipynb`·`..._amp.ipynb` | 초기 탐색 노트북(360 단발·amp) — 미사용 |

복원이 필요하면 해당 폴더/파일을 원위치로 되돌리면 됨. 결론·교훈은 `REPORT_5-B.md`에 보존.
