# -*- coding: utf-8 -*-
"""train_land_lt_colab.ipynb 생성기 — patchtst_lt 학습 노트북.

Colab 에 업로드: model_lt.py, train_lt.py, land_demand_train.csv.
GPU 런타임에서 전체 실행하면 out/ → landdemand_lt.zip 다운로드.
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'train_land_lt_colab.ipynb')
C = []
md = lambda s: C.append(('markdown', s.strip('\n')))
code = lambda s: C.append(('code', s.strip('\n')))

md(r"""
# 전국 수요 PatchTST-LT v2 (anchor-residual + climatology) — D+1..D+15 학습

장기 지평 열화 개선판. 단일구조 모델 15벌(D1..D15).

## v2 핵심 (EDA 근거, 2026-06-20)
- **anchor = daytype_match**: 타깃과 같은 (주말·공휴일) 상태인 same-DOW 가까운 2주 평균.
  기존 주단위 평균은 공휴일 타깃에서 +19~25% 과대(레벨 오염) → daytype_match 로 bias ~0.
- **climatology 학습 입력**: (월,시,요일타입) 평균을 anchor 와 나란히 헤드에 주입 →
  모델이 지평별로 anchor↔기후값 수축 비중을 스스로 학습(장기 anchor 노이즈 억제).
- **공휴일 캘린더** = `holidays.SouthKorea` (과거·미래 결정적). **기상 = temp·humidity·solar 3개**.
- **exog scaler = RobustScaler**(이상치 견고).

## 실행 순서
1. **런타임 → 런타임 유형 변경 → GPU (T4)**.
2. 아래 업로드 셀에서 `model_lt.py`, `train_lt.py`, `land_demand_train.csv` 3개를 올린다.
3. `holidays` 설치 셀 → 학습 셀 실행(15모델). 끝나면 `landdemand_lt.zip` 자동 다운로드.
4. 압축을 repo `landdemand_weigth_lt/` 에 풀고 로컬에서
   `python serve_land_new.py --model lt` → `est_horizon_land_new` 갱신.
""")

code(r"""
!pip -q install holidays
import torch; print('CUDA', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')
""")

code(r"""
# 3개 파일 업로드: model_lt.py, train_lt.py, land_demand_train.csv
from google.colab import files
up = files.upload()
print(sorted(up))
""")

code(r"""
# ★ 버전 가드 — v1 코드를 잘못 올렸으면 여기서 멈춘다.
import importlib, model_lt; importlib.reload(model_lt)
print('MODEL:', model_lt.VERSION)
assert model_lt.EXOG == ['temp_c', 'humidity', 'solar_rad'] and hasattr(model_lt, 'compute_recent_clim'), \
    f'구버전 model_lt.py 가 올라옴(EXOG={model_lt.EXOG}). 최신(v4) model_lt.py 로 다시 업로드.'
import pandas as pd
cols = list(pd.read_csv('land_demand_train.csv', nrows=1).columns)
assert 'humidity_wonju' in cols and 'cap_ppa' not in cols and 'di' not in cols, \
    f'구버전 CSV 인 듯(cols={cols}). export_train_csv.py 로 새로 만든 CSV 업로드.'
print('최신 확인 OK · CSV 컬럼', len(cols), '개 (recent-clim, cap_ppa 없음)')
""")

code(r"""
# 전체 D1..D15 학습 (GPU T4 기준 대략 1~2시간). 일부만: --horizons 1 8 15
!python train_lt.py --csv land_demand_train.csv --out out --epochs 70
""")

code(r"""
import shutil
shutil.make_archive('landdemand_lt', 'zip', 'out')
from google.colab import files; files.download('landdemand_lt.zip')
""")

md(r"""
## 산출물
`out/` = `best_lt_D{1..15}.pth` + `scaler_exog.pkl` + `metadata_lt.pkl`.
`metadata_lt.pkl['val_MAPE']` 로 지평별 검증 MAPE 확인. 로컬 서빙이 동일 `model_lt.py` 로 재구성한다.
""")


def main():
    nb = {"cells": [{"cell_type": k, "metadata": {}, "source": s.splitlines(keepends=True),
                     **({"outputs": [], "execution_count": None} if k == 'code' else {})}
                    for k, s in C],
          "metadata": {"kernelspec": {"display_name": "Python 3", "name": "python3"},
                       "language_info": {"name": "python"}, "accelerator": "GPU",
                       "colab": {"provenance": []}}, "nbformat": 4, "nbformat_minor": 5}
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(nb, f, ensure_ascii=False, indent=1)
    print('wrote', OUT, '| cells', len(C))


if __name__ == '__main__':
    main()
