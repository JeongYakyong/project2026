# -*- coding: utf-8 -*-
"""스모크 테스트: 생성된 노트북의 코드 셀을 추출해 로컬 CPU·작은 설정으로 실행.
모델 forward/backward·Dataset·손실·eval 이 에러 없이 도는지만 검증(성능 아님).
실행: python "5. land_demand_forecaster/training/_smoke_test.py"
"""
import json, os, sys, types
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass
import nbformat
HERE = os.path.dirname(os.path.abspath(__file__))
NB = os.path.join(HERE, 'train_landdemand_patchtst_colab.ipynb')

nb = nbformat.read(NB, as_version=4)
code_cells = [c['source'] for c in nb.cells if c['cell_type'] == 'code']

ns = {}
# 셀0 imports
exec(code_cells[0], ns)
ns['DEVICE'] = 'cpu'

# 셀1 config — override 로 축소
exec(code_cells[1], ns)
ns['HORIZONS'] = {'D1': 0, 'D2': 24}          # 2개만
ns['HP'] = dict(ns['HP']); ns['HP']['seq_len'] = 72  # 작게(속도)
ns['EPOCHS'] = 1; ns['PATIENCE'] = 1; ns['BATCH_SIZE'] = 32
ns['CSV_PATH'] = os.path.join(HERE, 'demand_raw_land.csv')
ns['OUT_DIR'] = os.path.join(HERE, '_smoke_out'); os.makedirs(ns['OUT_DIR'], exist_ok=True)

# 셀2 데이터로드 — 작은 슬라이스로 자르기 위해 먼저 실행 후 df 축소
exec(code_cells[2], ns)
ns['df'] = ns['df'].iloc[:3000].copy()        # 약 4개월
# split 경계가 슬라이스 밖이면 train/val/test 가 비므로 경계도 조정
ns['TRAIN_END'] = ns['df'].index[1800].strftime('%Y-%m-%d %H:%M:%S')
ns['VAL_END']   = ns['df'].index[2400].strftime('%Y-%m-%d %H:%M:%S')
print('smoke: rows', len(ns['df']), 'TRAIN_END', ns['TRAIN_END'], 'VAL_END', ns['VAL_END'])

# 셀3~7 (Dataset, Attention/Model, Loss, prepare/train, run train)
for i in range(3, 8):
    exec(code_cells[i], ns)

# 셀8 eval
exec(code_cells[8], ns)

# 검증: 가중치 파일·메트릭 생성됐는지
import glob
w = glob.glob(os.path.join(ns['OUT_DIR'], 'best_patchtst_landdemand_*.pth'))
print('\n[SMOKE] weights produced:', sorted(os.path.basename(x) for x in w))
print('[SMOKE] scaler:', os.path.exists(os.path.join(ns['OUT_DIR'], 'scaler_landdemand.pkl')))
print('[SMOKE] test_metrics:', os.path.exists(os.path.join(ns['OUT_DIR'], 'test_metrics.csv')))
assert len(w) == 2, 'expected 2 horizon weights'
print('\n[SMOKE] PASS — 모델/데이터셋/손실/eval 전부 에러 없이 실행')
