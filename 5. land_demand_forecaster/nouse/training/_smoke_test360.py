# -*- coding: utf-8 -*-
"""스모크 테스트(360 단발): 생성 노트북 셀을 로컬 CPU·작은 설정으로 실행. 동작만 검증."""
import os, sys
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass
import nbformat
HERE = os.path.dirname(os.path.abspath(__file__))
nb = nbformat.read(os.path.join(HERE, 'train_landdemand_patchtst360_colab.ipynb'), as_version=4)
cc = [c['source'] for c in nb.cells if c['cell_type'] == 'code']
ns = {}
exec(cc[0], ns); ns['DEVICE'] = 'cpu'
exec(cc[1], ns)
ns['HP'] = dict(ns['HP']); ns['HP']['seq_len'] = 72     # 작게
ns['EPOCHS'] = 1; ns['PATIENCE'] = 1; ns['BATCH_SIZE'] = 16
ns['CSV_PATH'] = os.path.join(HERE, 'demand_raw_land.csv')
ns['OUT_DIR'] = os.path.join(HERE, '_smoke_out360'); os.makedirs(ns['OUT_DIR'], exist_ok=True)
exec(cc[2], ns)
ns['df'] = ns['df'].iloc[:4000].copy()                  # PRED_LEN 360 수용
ns['TRAIN_END'] = ns['df'].index[2600].strftime('%Y-%m-%d %H:%M:%S')
ns['VAL_END']   = ns['df'].index[3200].strftime('%Y-%m-%d %H:%M:%S')
print('smoke360: rows', len(ns['df']), 'PRED_LEN', ns['PRED_LEN'])
for i in range(3, 9):    # dataset, model, loss, defs, run, eval
    exec(cc[i], ns)
import glob
w = glob.glob(os.path.join(ns['OUT_DIR'], 'best_patchtst_landdemand_360.pth'))
assert len(w) == 1, 'expected single 360 weight'
assert os.path.exists(os.path.join(ns['OUT_DIR'], 'test_metrics_360.csv'))
print('\n[SMOKE360] PASS — 단발 360 + MAE + α없음 경로 정상 실행')
