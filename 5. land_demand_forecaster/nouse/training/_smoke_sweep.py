# -*- coding: utf-8 -*-
"""스모크: 스윕 노트북을 base·anchor·perstation 3 config × D5 만 작은설정 CPU 실행. 동작 검증."""
import os, sys
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass
import nbformat
HERE=os.path.dirname(os.path.abspath(__file__))
nb=nbformat.read(os.path.join(HERE,'train_landdemand_sweep_colab.ipynb'),as_version=4)
cc=[c['source'] for c in nb.cells if c['cell_type']=='code']
ns={}; exec(cc[0],ns); ns['DEVICE']='cpu'
exec(cc[1],ns)
ns['CSV_PATH']=os.path.join(HERE,'demand_raw_land.csv')
ns['OUT_DIR']=os.path.join(HERE,'_smoke_sweep_out'); os.makedirs(ns['OUT_DIR'],exist_ok=True)
ns['HORIZONS']={'D5':96}                              # 1 지평만
ns['EPOCHS']=1; ns['PATIENCE']=1; ns['BATCH_SIZE']=16
ns['DEFAULT_HP']=dict(ns['DEFAULT_HP']); ns['DEFAULT_HP']['seq_len']=72   # 작게
ns['CONFIGS']=[('base','base',{},'mae'),('anchor','anchor',{},'huber'),('perstation','perstation',{},'mse')]
exec(cc[2],ns)                                        # 데이터(전체) — 작게 자르기
ns['raw']=ns['raw'].iloc[:2500].copy()
ns['TRAIN_END']=ns['raw'].index[1500].strftime('%Y-%m-%d %H:%M:%S')
ns['VAL_END']=ns['raw'].index[2000].strftime('%Y-%m-%d %H:%M:%S')
for i in range(3,6): exec(cc[i],ns)                   # DS/model/loss, prep/train, run+eval
import glob, json
w=sorted(os.path.basename(x) for x in glob.glob(os.path.join(ns['OUT_DIR'],'*.pth')))
reg=json.load(open(os.path.join(ns['OUT_DIR'],'registry.json')))
print('\n[SMOKE] weights:', w)
print('[SMOKE] registry configs:', list(reg))
assert len(w)==3 and len(reg)==3
import shutil; shutil.rmtree(ns['OUT_DIR'])
print('[SMOKE] PASS — base/anchor(lag_week)/perstation × 3손실 전부 정상')
