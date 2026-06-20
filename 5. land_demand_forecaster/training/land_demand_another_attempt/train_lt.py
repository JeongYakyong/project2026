# -*- coding: utf-8 -*-
"""patchtst_lt 학습 — D+1..D+15 anchor-residual PatchTST. Colab(GPU) 또는 로컬에서 실행.

입력 : land_demand_train.csv (export_train_csv.py 산출, historical 원본 컬럼)
산출 : out/ 에 best_lt_D{1..15}.pth + scaler_exog.pkl + metadata_lt.pkl  (→ models_lt/ 로 투입)

실행: python train_lt.py            (전체 D1..D15)
      python train_lt.py --horizons 1 8 15   (일부만)
      python train_lt.py --epochs 60 --csv land_demand_train.csv
모델/피처 정의는 model_lt.py 공용. 서빙과 동일 파이프라인.
"""
from __future__ import annotations
import os, json, argparse
import numpy as np, pandas as pd, torch, joblib
import torch.nn as nn
from sklearn.preprocessing import RobustScaler
from torch.utils.data import DataLoader

import model_lt as M

DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
TRAIN_END = '2025-01-01'; VAL_END = '2026-01-01'
HP = dict(seq_len=336, patch_len=24, stride=12, d_model=256, num_heads=4, num_layers=3, d_ff=1024, dropout=0.2)


def mape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float)
    k = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean(np.abs(a[k] - p[k]) / a[k]) * 100) if k.any() else np.nan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', default='land_demand_train.csv')
    ap.add_argument('--out', default='out')
    ap.add_argument('--epochs', type=int, default=70)
    ap.add_argument('--batch', type=int, default=256)
    ap.add_argument('--lr', type=float, default=1e-3)
    ap.add_argument('--patience', type=int, default=10)
    ap.add_argument('--horizons', type=int, nargs='*', default=list(range(1, 16)))
    ap.add_argument('--limit', type=int, default=0, help='>0 이면 학습 샘플 수 제한(스모크 검증용)')
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    print('DEVICE', DEVICE)
    print('MODEL', M.VERSION)
    assert M.EXOG == ['temp_c', 'humidity', 'solar_rad'] and hasattr(M, 'compute_recent_clim'), \
        f'구버전 model_lt.py 가 올라온 것 같음(EXOG={M.EXOG}). 최신(v4) model_lt.py 를 업로드하세요.'

    feat = M.build_features(pd.read_csv(args.csv))
    FW = M.FW; EXOG = M.EXOG
    tr_mask = np.asarray(feat.index < TRAIN_END)
    va_mask = np.asarray((feat.index >= TRAIN_END) & (feat.index < VAL_END))

    scaler = RobustScaler().fit(feat.loc[tr_mask, EXOG])
    joblib.dump(scaler, f'{args.out}/scaler_exog.pkl')
    A_df = feat[FW].copy(); A_df[EXOG] = scaler.transform(A_df[EXOG])
    A = A_df.values.astype(np.float32)
    dem = feat['Demand'].values.astype(np.float32)
    is_hol = feat['is_holiday'].values; is_wkd = feat['is_weekend'].values
    tr_idx = np.where(tr_mask)[0]; va_idx = np.where(va_mask)[0]
    DMEAN = float(dem[tr_idx].mean()); DSTD = float(dem[tr_idx].std())
    FIDX = list(range(len(FW)))
    NF = len(FW) + 1
    print(f'rows {len(feat)} | train<{TRAIN_END} val<{VAL_END} | DMEAN {DMEAN:.0f} DSTD {DSTD:.0f} | feat {FW}')

    meta = dict(model='anchor-residual PatchTST (patchtst_lt v4)', HP=HP, EXOG=EXOG, TIME=M.TIME, FW=FW,
                TEMP_SEL=M.TEMP_SEL, SOLAR_SEL=M.SOLAR_SEL, DMEAN=DMEAN, DSTD=DSTD,
                TRAIN_END=TRAIN_END, VAL_END=VAL_END, scaler='RobustScaler',
                anchor='daytype_match (weekend+holiday matched same-DOW nearest-2-week mean)',
                climatology=f'recent daytype_match mean (same-DOW last {M.CLIM_WEEKS} weeks), learned head input',
                holiday='holidays.SouthKorea (deterministic past+future)',
                RESID_STD={}, val_MAPE={})

    def split_starts(ds, idxset):
        keep = np.array([ (i + ds.seq_len + ds.offset) in idxset for i in ds.starts ])
        ds.starts = ds.starts[keep]; return ds

    for n in args.horizons:
        off = M.HORIZONS[n]
        anchor = M.compute_anchor(dem, is_hol, is_wkd, off)
        clim = M.compute_recent_clim(dem, is_hol, is_wkd, off)     # 최근 기후값(지평별 honest-lag)
        resid = dem - anchor
        rstd = float(np.nanstd(resid[tr_idx])) or 1.0
        meta['RESID_STD'][f'D{n}'] = rstd
        # 타깃 시작점(s)이 train/val 구간에 속하도록 분리 (벡터화)
        full = M.AnchorDataset(A, dem, anchor, clim, HP['seq_len'], M.PRED_LEN, off, FIDX, len(FW))
        s_target = full.starts + HP['seq_len'] + off
        in_tr = np.zeros(len(dem), bool); in_tr[tr_idx] = True
        in_va = np.zeros(len(dem), bool); in_va[va_idx] = True
        s_tr = full.starts[in_tr[s_target]]; s_va = full.starts[in_va[s_target]]
        if args.limit:
            s_tr = s_tr[:args.limit]; s_va = s_va[:max(64, args.limit // 4)]
        dtr = M.AnchorDataset(A, dem, anchor, clim, HP['seq_len'], M.PRED_LEN, off, FIDX, len(FW), starts=s_tr)
        dva = M.AnchorDataset(A, dem, anchor, clim, HP['seq_len'], M.PRED_LEN, off, FIDX, len(FW), starts=s_va)
        tl = DataLoader(dtr, batch_size=args.batch, shuffle=True, drop_last=True)
        vl = DataLoader(dva, batch_size=args.batch)
        m = M.PatchTST_Anchor(NF, DMEAN, DSTD, rstd, pred_len=M.PRED_LEN, **HP).to(DEVICE)
        opt = torch.optim.AdamW(m.parameters(), lr=args.lr, weight_decay=1e-5)
        sch = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, 'min', factor=0.5, patience=4)
        crit = nn.SmoothL1Loss(beta=1.0)
        amp = (DEVICE == 'cuda'); gs = torch.amp.GradScaler('cuda', enabled=amp) if amp else None
        best = float('inf'); bad = 0; path = f'{args.out}/best_lt_D{n}.pth'
        print(f'== D{n} off={off} w0={M.anchor_w0(off)} rstd={rstd:.0f} train={len(dtr)} val={len(dva)}')
        for ep in range(1, args.epochs + 1):
            m.train()
            for b in tl:
                opt.zero_grad()
                y = b['future_y'].to(DEVICE)
                if amp:
                    with torch.amp.autocast('cuda'):
                        pred = m(b); loss = crit(pred / rstd, y / rstd)
                    gs.scale(loss).backward(); gs.unscale_(opt)
                    torch.nn.utils.clip_grad_norm_(m.parameters(), 1.0); gs.step(opt); gs.update()
                else:
                    pred = m(b); loss = crit(pred / rstd, y / rstd); loss.backward()
                    torch.nn.utils.clip_grad_norm_(m.parameters(), 1.0); opt.step()
            m.eval(); P, Y = [], []
            with torch.no_grad():
                for b in vl:
                    P.append(m(b).cpu().numpy()); Y.append(b['future_y'].numpy())
            P = np.clip(np.concatenate(P).ravel(), 0, None); Y = np.concatenate(Y).ravel()
            vmape = mape(Y, P); sch.step(vmape)
            if vmape < best - 1e-4:
                best = vmape; bad = 0; torch.save(m.state_dict(), path)
            else:
                bad += 1
                if bad >= args.patience:
                    print(f'   early stop ep{ep}'); break
        meta['val_MAPE'][f'D{n}'] = round(best, 3)
        joblib.dump(meta, f'{args.out}/metadata_lt.pkl')
        print(f'   D{n} best val MAPE {best:.2f}%')
    print('DONE. metadata_lt.pkl val_MAPE:', meta['val_MAPE'])


if __name__ == '__main__':
    main()
