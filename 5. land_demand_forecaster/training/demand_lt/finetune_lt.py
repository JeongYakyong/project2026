# -*- coding: utf-8 -*-
"""patchtst_lt v4 head 파인튜닝 — 새 BTM 체제(2024-11~2025-11) 한낮 구조 반영.

배경: 기존 가중치는 train<2025(BTM≈0)에서 학습 → residual head 가 '한낮 봉우리'를 얹어
      맑은 날 과대(+8%)·흐린 날 과소(-2%). 레벨(anchor/clim)은 신체제를 잘 추적하므로
      ★인코더·cross-attention 은 동결하고 residual head(regressor+weather_bypass)만 재학습한다.

데이터 역할(소스가 다름):
  train/val : historical(실측 기상). 창 2024-11-23~2025-11-30, 격자 split(eda_scaler/finetune_split.csv, p=1/6).
  test      : forecast_horizon(예보 기상) 2025-12-15~ — 이 스크립트 밖, serve_land_new.py→eval_land_new.py 로 채점.
보존: scaler_exog.pkl(재fit 금지)·DMEAN/DSTD/RESID_STD/HP 모두 기존 그대로. .pth 만 새로 산출.

실행: python finetune_lt.py                       (D1..D15 전체)
      python finetune_lt.py --horizons 1          (스모크)
      python finetune_lt.py --epochs 30 --lr 5e-4
산출: weights_ft/best_lt_D{n}.pth + (복사) scaler_exog.pkl·metadata_lt.pkl + metadata_ft.json
"""
from __future__ import annotations
import os, sys, json, argparse, shutil
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import numpy as np, pandas as pd, torch, joblib
import torch.nn as nn
from torch.utils.data import DataLoader
import model_lt as M

DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
HERE = os.path.dirname(os.path.abspath(__file__))
WIN_LO, WIN_HI = pd.Timestamp('2024-11-23'), pd.Timestamp('2025-11-30')
SPLIT_CSV = os.path.join(HERE, 'eda_scaler', 'finetune_split.csv')
SRC_W = os.path.join(HERE, 'weights')           # 기존 production 가중치(초기값)
HEAD_PREFIX = ('regressor', 'weather_bypass')   # ★학습 대상(나머지 동결)


def mape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float)
    k = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean(np.abs(a[k] - p[k]) / a[k]) * 100) if k.any() else np.nan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', default=os.path.join(HERE, 'land_demand_train.csv'))
    ap.add_argument('--out', default=os.path.join(HERE, 'weights_ft'))
    ap.add_argument('--src_w', default=SRC_W, help='기존 production 가중치 폴더(초기값·scaler·meta)')
    ap.add_argument('--split', default=SPLIT_CSV, help='격자 split csv(p=1/6)')
    ap.add_argument('--epochs', type=int, default=30)
    ap.add_argument('--batch', type=int, default=256)
    ap.add_argument('--lr', type=float, default=5e-4)
    ap.add_argument('--patience', type=int, default=8)
    ap.add_argument('--horizons', type=int, nargs='*', default=list(range(1, 16)))
    ap.add_argument('--limit', type=int, default=0, help='>0 이면 train 샘플 수 제한(스모크)')
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    print('DEVICE', DEVICE, '| MODEL', M.VERSION)

    # ── 피처(기존 파이프라인) + 기존 스케일러(재fit 금지) ──
    src_w = args.src_w
    meta = joblib.load(os.path.join(src_w, 'metadata_lt.pkl'))
    scaler = joblib.load(os.path.join(src_w, 'scaler_exog.pkl'))
    HP = meta['HP']; DMEAN, DSTD = meta['DMEAN'], meta['DSTD']
    FW, EXOG = M.FW, M.EXOG; NF = len(FW) + 1; FIDX = list(range(len(FW)))
    feat = M.build_features(pd.read_csv(args.csv))
    A_df = feat[FW].copy(); A_df[EXOG] = scaler.transform(A_df[EXOG])
    A = A_df.values.astype(np.float32)
    dem = feat['Demand'].values.astype(np.float32)
    is_hol = feat['is_holiday'].values; is_wkd = feat['is_weekend'].values

    # ── 격자 split: 시간격자 인덱스별 (창 안인가 / val인가) ──
    sp = pd.read_csv(args.split, parse_dates=['date'])
    val_days = set(pd.to_datetime(sp.loc[sp.split == 'val', 'date']).dt.normalize())
    dnorm = feat.index.normalize()
    in_win = np.asarray((dnorm >= WIN_LO) & (dnorm <= WIN_HI))
    is_val = np.asarray(dnorm.isin(val_days))
    print(f'창 {WIN_LO.date()}~{WIN_HI.date()} | 창내 시간 {int(in_win.sum())} | val일 {len(val_days)}')

    ft_meta = dict(base='patchtst_lt v4 (frozen encoder, head finetuned)',
                   window=[str(WIN_LO.date()), str(WIN_HI.date())], split='grid p=1/6',
                   trained=list(HEAD_PREFIX), lr=args.lr, val_MAPE_ft={}, val_MAPE_src=meta.get('val_MAPE', {}))

    for n in args.horizons:
        off = M.HORIZONS[n]
        anchor = M.compute_anchor(dem, is_hol, is_wkd, off)
        clim = M.compute_recent_clim(dem, is_hol, is_wkd, off)
        rstd = meta['RESID_STD'][f'D{n}']                      # 기존 표준화 상수 보존
        full = M.AnchorDataset(A, dem, anchor, clim, HP['seq_len'], M.PRED_LEN, off, FIDX, len(FW))
        s_t = full.starts + HP['seq_len'] + off                 # 타깃 시작 인덱스
        sel = in_win[s_t]
        s_tr = full.starts[sel & ~is_val[s_t]]
        s_va = full.starts[sel & is_val[s_t]]
        if args.limit:
            s_tr = s_tr[:args.limit]; s_va = s_va[:max(64, args.limit // 4)]
        dtr = M.AnchorDataset(A, dem, anchor, clim, HP['seq_len'], M.PRED_LEN, off, FIDX, len(FW), starts=s_tr)
        dva = M.AnchorDataset(A, dem, anchor, clim, HP['seq_len'], M.PRED_LEN, off, FIDX, len(FW), starts=s_va)
        tl = DataLoader(dtr, batch_size=args.batch, shuffle=True, drop_last=len(dtr) > args.batch)
        vl = DataLoader(dva, batch_size=args.batch)

        # ── 모델: 기존 가중치 로드 → 인코더 동결, head만 학습 ──
        m = M.PatchTST_Anchor(NF, DMEAN, DSTD, rstd, pred_len=M.PRED_LEN, **HP).to(DEVICE)
        m.load_state_dict(torch.load(os.path.join(src_w, f'best_lt_D{n}.pth'), map_location=DEVICE))
        for name, p in m.named_parameters():
            p.requires_grad = name.startswith(HEAD_PREFIX)
        head_params = [p for p in m.parameters() if p.requires_grad]
        ntr_p = sum(p.numel() for p in head_params); nall = sum(p.numel() for p in m.parameters())
        opt = torch.optim.AdamW(head_params, lr=args.lr, weight_decay=1e-5)
        sch = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, 'min', factor=0.5, patience=3)
        crit = nn.SmoothL1Loss(beta=1.0)
        print(f'== D{n} off={off} train={len(dtr)} val={len(dva)} | 학습 파라미터 {ntr_p}/{nall} ({100*ntr_p/nall:.1f}%)')

        # 기준선(파인튜닝 전) val MAPE
        def eval_val():
            m.eval(); P, Y = [], []
            with torch.no_grad():
                for b in vl:
                    P.append(m(b).cpu().numpy()); Y.append(b['future_y'].numpy())
            if not P:
                return np.nan
            return mape(np.concatenate(Y).ravel(), np.clip(np.concatenate(P).ravel(), 0, None))
        base_mape = eval_val()

        best = float('inf'); bad = 0; path = os.path.join(args.out, f'best_lt_D{n}.pth')
        for ep in range(1, args.epochs + 1):
            m.train()
            for b in tl:
                opt.zero_grad()
                y = b['future_y'].to(DEVICE)
                pred = m(b); loss = crit(pred / rstd, y / rstd)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(head_params, 1.0); opt.step()
            vmape = eval_val(); sch.step(vmape)
            if vmape < best - 1e-4:
                best = vmape; bad = 0; torch.save(m.state_dict(), path)
            else:
                bad += 1
                if bad >= args.patience:
                    print(f'   early stop ep{ep}'); break
        ft_meta['val_MAPE_ft'][f'D{n}'] = round(best, 3)
        print(f'   D{n} val MAPE: 파인튜닝전 {base_mape:.3f} → 후 {best:.3f}  (기존학습 {meta["val_MAPE"].get(f"D{n}")})')

    # 서빙용 자산 동봉(스케일러·메타 그대로 복사) + 파인튜닝 메타
    for f in ('scaler_exog.pkl', 'metadata_lt.pkl'):
        shutil.copy(os.path.join(src_w, f), os.path.join(args.out, f))
    with open(os.path.join(args.out, 'metadata_ft.json'), 'w', encoding='utf-8') as f:
        json.dump(ft_meta, f, ensure_ascii=False, indent=2)
    print('DONE →', args.out, '| val_MAPE_ft:', ft_meta['val_MAPE_ft'])


if __name__ == '__main__':
    main()
