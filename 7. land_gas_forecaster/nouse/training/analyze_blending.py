# -*- coding: utf-8 -*-
"""Stage 5 — 가스 기후값 정의 + 예보×기후값 블렌딩 (MAPE 최소, 전체+계절별).

기후값(우리 historical 실측만): doy(연중일) ±7일 슬라이딩(2주 창, 오버랩) × 시각 × 요일유형 평균.
  누설 차단 = 2022~2024 실측만 사용(백테스트 2025-12~2026-06 제외).  표본 부족 슬롯은 요일유형
  무시(시각만) 창으로 폴백.
가스 보정: 새 정직 백테스트(horizon_backtest_v2.parquet)로 낮(09-15)/밤 × 지평별 재적합(Σ실측/Σraw).
블렌딩: gas_final(h) = (1-w)*gas_cal + w*clim.  지평별 w를 전체 MAPE 최소로 탐색, 계절별 MAPE 동시 보고.
"""
from __future__ import annotations
import os, sys, json, sqlite3, importlib.util, warnings
import numpy as np, pandas as pd
warnings.filterwarnings('ignore')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')
PARQUET = os.path.join(HERE, 'horizon_backtest_v2.parquet')
FIG = os.path.join(HERE, 'fig'); os.makedirs(FIG, exist_ok=True)
SEASON = {12: '겨울', 1: '겨울', 2: '겨울', 3: '봄', 4: '봄', 5: '봄', 6: '여름', 7: '여름', 8: '여름', 9: '가을', 10: '가을', 11: '가을'}
HZ = list(range(1, 16))
WIN = 7   # ±7일 = 2주 슬라이딩


def mape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean(np.abs(a[m]-p[m])/a[m])*100) if m.any() else np.nan


def nbias(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean((p[m]-a[m])/a[m])*100) if m.any() else np.nan


def _circ_sum(arr, w):
    padded = np.concatenate([arr[-w:], arr, arr[:w]])
    return np.convolve(padded, np.ones(2*w+1), 'valid')   # len 366


def build_climatology():
    """gas 기후값 lookup: (hour, day_type) -> doy(1..366) 슬라이딩평균.  2022-2024 만."""
    with sqlite3.connect(DB) as con:
        d = pd.read_sql("SELECT timestamp, gen_gas_kr, day_type FROM historical "
                        "WHERE timestamp>='2022-01-01' AND timestamp<'2025-01-01'", con, parse_dates=['timestamp'])
    d = d[d.gen_gas_kr > 0].copy()
    d['doy'] = d.timestamp.dt.dayofyear.clip(1, 366); d['hour'] = d.timestamp.dt.hour
    lut = {}                          # (hour, day_type) -> array doy1..366
    for (hr, dt), g in d.groupby(['hour', 'day_type']):
        agg = g.groupby('doy').gen_gas_kr.agg(['sum', 'count']).reindex(range(1, 367), fill_value=0)
        S = _circ_sum(agg['sum'].values, WIN); C = _circ_sum(agg['count'].values, WIN)
        lut[(hr, dt)] = np.where(C > 0, S / np.maximum(C, 1), np.nan)
    fb = {}                           # 폴백: 요일유형 무시(hour 만)
    for hr, g in d.groupby('hour'):
        agg = g.groupby('doy').gen_gas_kr.agg(['sum', 'count']).reindex(range(1, 367), fill_value=0)
        S = _circ_sum(agg['sum'].values, WIN); C = _circ_sum(agg['count'].values, WIN)
        fb[hr] = np.where(C > 0, S / np.maximum(C, 1), np.nan)
    return lut, fb


def clim_lookup(ts, day_type, lut, fb):
    di = pd.DatetimeIndex(ts)
    doy = np.clip(di.dayofyear.values, 1, 366); hr = di.hour.values
    out = np.full(len(ts), np.nan)
    for i in range(len(ts)):
        v = lut.get((hr[i], day_type[i]))
        x = v[doy[i]-1] if v is not None else np.nan
        if not np.isfinite(x):
            x = fb[hr[i]][doy[i]-1]
        out[i] = x
    return out


def main():
    import importlib.util as iu
    s = iu.spec_from_file_location('bht', os.path.join(HERE, 'build_horizon_backtest.py'))
    bht = iu.module_from_spec(s); s.loader.exec_module(bht)
    d_act = bht.load_actuals()
    dt_map = d_act['day_type']

    r = pd.read_parquet(PARQUET)
    r = r.dropna(subset=['gen_gas_kr']); r = r[r.gen_gas_kr > 0].copy()
    ts = pd.DatetimeIndex(r.timestamp)
    r['day_type'] = dt_map.reindex(ts).values
    r['season'] = ts.month.map(SEASON)
    r['is_day'] = (ts.hour >= 9) & (ts.hour <= 15)

    # 1) 가스 보정 재적합 (낮/밤 × 지평) — Σ실측/Σraw
    calib = {}
    for n in HZ:
        g = r[r.horizon == n]
        cd = g[g.is_day]; cn = g[~g.is_day]
        calib[n] = (float(cd.gen_gas_kr.sum()/cd.est_gas_gen_raw.sum()) if len(cd) else 1.0,
                    float(cn.gen_gas_kr.sum()/cn.est_gas_gen_raw.sum()) if len(cn) else 1.0)
    r['gas_cal'] = [row.est_gas_gen_raw * (calib[row.horizon][0] if row.is_day else calib[row.horizon][1])
                    for row in r.itertuples()]

    # 2) 기후값
    lut, fb = build_climatology()
    r['clim'] = clim_lookup(r.timestamp.values, r.day_type.values, lut, fb)
    r = r.dropna(subset=['clim'])

    # 3) 지평별 블렌딩 w 탐색 (전체 MAPE 최소) + 계절별 동시 측정
    ws = np.round(np.arange(0, 1.01, 0.05), 2)
    print('=' * 92)
    print('가스 보정후 vs 기후값 vs 블렌딩 — 지평별 (전체 MAPE)  [기후값=2022-24, doy±7×시각×요일유형]')
    print('=' * 92)
    print(f'{"지평":>4} | {"예보(cal)":>9} | {"기후값":>7} | {"best w":>6} | {"블렌딩":>7} | {"개선":>6}')
    seasons = ['겨울', '봄', '여름']
    rows_disp = []; wstar = {}
    for n in HZ:
        g = r[r.horizon == n]
        m_cal = mape(g.gen_gas_kr, g.gas_cal); m_clim = mape(g.gen_gas_kr, g.clim)
        best_w, best_m = 0.0, m_cal
        for w in ws:
            mb = mape(g.gen_gas_kr, (1-w)*g.gas_cal + w*g.clim)
            if mb < best_m: best_m, best_w = mb, w
        wstar[n] = best_w
        rows_disp.append((n, m_cal, m_clim, best_w, best_m))
        print(f' D+{n:>2} | {m_cal:8.2f}% | {m_clim:6.2f}% | {best_w:6.2f} | {best_m:6.2f}% | {m_cal-best_m:+5.2f}p')

    # 4) 계절별 — 블렌딩(전체최적 w) vs 무블렌딩
    print('\n' + '=' * 92)
    print('계절별 가스 MAPE — 예보(cal, w=0) vs 블렌딩(전체최적 w*)  ★계절 균형 점검')
    print('=' * 92)
    print(f'{"지평":>4} | ' + ' | '.join(f'{s+"(cal→blend)":>16}' for s in seasons))
    for n in HZ:
        g = r[r.horizon == n]; w = wstar[n]; cells = []
        for s in seasons:
            gs = g[g.season == s]
            if len(gs) < 20: cells.append(f'{"-":>16}'); continue
            mc = mape(gs.gen_gas_kr, gs.gas_cal); mbb = mape(gs.gen_gas_kr, (1-w)*gs.gas_cal + w*gs.clim)
            cells.append(f'{mc:5.1f}→{mbb:5.1f}'.rjust(16))
        print(f' D+{n:>2} | ' + ' | '.join(cells))

    # 5) 그림: 전체 — 예보 vs 기후값 vs 블렌딩
    import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
    plt.rcParams['font.family'] = 'Malgun Gothic'; plt.rcParams['axes.unicode_minus'] = False
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(HZ, [x[1] for x in rows_disp], 'o-', color='#059669', label='예보 가스(보정)')
    ax.plot(HZ, [x[2] for x in rows_disp], 's--', color='#94a3b8', label='기후값(평년)')
    ax.plot(HZ, [x[4] for x in rows_disp], '^-', color='#c44e52', label='블렌딩(지평별 w*)')
    ax.set_xlabel('horizon (D+n)'); ax.set_ylabel('가스 MAPE (%)'); ax.set_xticks(HZ)
    ax.set_title('가스: 예보 vs 기후값 vs 블렌딩 (정직 백테스트)'); ax.legend(frameon=False); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(os.path.join(FIG, 'blend_overall.png'), dpi=130); plt.close(fig)

    # 6) 계절별 교차점 그림 (예보 vs 기후값)
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.4), sharey=True)
    for ax, sname in zip(axes, seasons):
        cal = []; cl = []
        for n in HZ:
            gs = r[(r.horizon == n) & (r.season == sname)]
            cal.append(mape(gs.gen_gas_kr, gs.gas_cal) if len(gs) >= 20 else np.nan)
            cl.append(mape(gs.gen_gas_kr, gs.clim) if len(gs) >= 20 else np.nan)
        ax.plot(HZ, cal, 'o-', color='#059669', label='예보(cal)')
        ax.plot(HZ, cl, 's--', color='#94a3b8', label='기후값')
        ax.set_title(f'{sname}'); ax.set_xlabel('D+n'); ax.grid(alpha=0.3)
    axes[0].set_ylabel('가스 MAPE (%)'); axes[0].legend(frameon=False)
    fig.suptitle('계절별 예보 vs 기후값 교차점'); fig.tight_layout()
    fig.savefig(os.path.join(FIG, 'blend_by_season.png'), dpi=130); plt.close(fig)
    print('\nsaved fig/blend_overall.png , fig/blend_by_season.png')
    print('재적합 보정(낮/밤):', {n: (round(calib[n][0], 4), round(calib[n][1], 4)) for n in [1, 7, 12, 15]})

    # 설정 저장 (사용자 확정 Option A: 지평별 단일 단조 w) — gas_serving_calib.json
    if '--write-config' in sys.argv:
        W_FINAL = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0.05, 6: 0.10, 7: 0.10, 8: 0.20, 9: 0.30,
                   10: 0.35, 11: 0.35, 12: 0.40, 13: 0.40, 14: 0.45, 15: 0.50}
        cj = os.path.join(ROOT, '7. land_gas_forecaster', 'model', 'gas_serving_calib.json')
        old = json.load(open(cj, encoding='utf-8'))
        new = dict(
            bias_calib=round(calib[1][1], 5),
            bias_calib_by_horizon_daypart={str(n): {'day': round(calib[n][0], 5), 'night': round(calib[n][1], 5)} for n in HZ},
            blend_weight_by_horizon={str(n): float(W_FINAL[n]) for n in HZ},
            climatology=dict(window_days=WIN, group='doy,hour,day_type', years='2022-2024',
                             note='가스 기후값=우리 historical 실측 doy±7일 슬라이딩×시각×요일유형 평균. 폴백=시각만.'),
            derivation='Stage5(2026-06-15): 정직 풀체인 백테스트(D+1~15)로 보정 낮/밤×지평 재적합 + '
                       '기후값 블렌딩 w(h)(전체+계절 MAPE 검증, Option A 단조). 전체 13.96→13.72%, 여름 장지평 −3%p.',
            apply='gas_cal=(booster.predict+init_score)×calib(dayahead,daypart); '
                  'final=(1-w(dayahead))×gas_cal + w×climatology(doy,hour,day_type).',
            conv_ton_per_mwh=old.get('conv_ton_per_mwh', 0.1521),
            bias_calib_prev_v2_h288=old.get('bias_calib_by_horizon_daypart'),
            bias_calib_legacy_climatology=old.get('bias_calib_legacy_climatology'))
        json.dump(new, open(cj, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        print('\n[config] gas_serving_calib.json 갱신: 보정(15지평 낮/밤)+블렌딩 w(h)+기후값 스펙')


if __name__ == '__main__':
    try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass
    main()
