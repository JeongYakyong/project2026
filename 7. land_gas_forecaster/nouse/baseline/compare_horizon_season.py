# -*- coding: utf-8 -*-
"""baseline 비교 (보고서용) — Prophet vs seasonal-naive(lag) vs 우리모델, 지평별·계절별.

기존 baseline(REPORT_baseline.md)은 지평 분해가 없고 평가조건이 불공정했음:
  Prophet=2022-24 1회적합 후 전체외삽(최근 수준 모름)·naive=1주전 실측(D+7 정보, 지평무관).
여기선 셋을 **같은 타깃(forecast_horizon 원점별 D+1~15)·같은 정보조건(원점까지)** 으로 공정 비교:
  - 우리모델 = est_horizon_land.est_gas_gen_land (가스 v2+보정+블렌딩, 정직 백테스트).
  - seasonal naive(honest) = 지평별 가용 최신 주간 lag: D+1~7→168h·D+8~14→336h·D+15→504h(타깃-k≤원점).
  - Prophet(개선) = 각 원점 O까지(최근 540일) 재적합 후 O+1~360h 예측(yearly+weekly+daily, KR휴일).
    ★기존 대비 개선점 = 원점 재적합(최근 수준 anchor) — 1회적합 외삽의 빈약함을 제거.
원점은 계산량 위해 forecast_horizon base 중 균등 subsample(~30), 셋 모두 동일 원점·타깃.
산출: tab/compare_horizon_season.csv, fig/compare_{horizon,season}.png, REPORT_baseline.md 갱신용 표.
"""
from __future__ import annotations
import os, sys, glob, sqlite3, warnings, logging, math
import numpy as np, pandas as pd
warnings.filterwarnings('ignore')
logging.getLogger('cmdstanpy').setLevel(logging.ERROR); logging.getLogger('prophet').setLevel(logging.ERROR)

# Windows 한글(cp949) tbb 우회 (Prophet 생성 전) — [[prophet-cp949-tbb-workaround]]
import prophet as _pp
_tbb = glob.glob(os.path.join(os.path.dirname(_pp.__file__), 'stan_model', 'cmdstan-*', 'stan', 'lib', 'stan_math', 'lib', 'tbb'))
if _tbb:
    os.environ['PATH'] = _tbb[0] + os.pathsep + os.environ.get('PATH', '')
from prophet import Prophet

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')
FIG = os.path.join(HERE, 'fig'); TAB = os.path.join(HERE, 'tab')
os.makedirs(FIG, exist_ok=True); os.makedirs(TAB, exist_ok=True)
HZ = list(range(1, 16))
N_ORIGINS = 30
TRAIN_DAYS = 540
SEASON = {12: '겨울', 1: '겨울', 2: '겨울', 3: '봄', 4: '봄', 5: '봄', 6: '여름', 7: '여름', 8: '여름', 9: '가을', 10: '가을', 11: '가을'}


def mape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean(np.abs(a[m]-p[m])/a[m])*100) if m.any() else np.nan


def main():
    with sqlite3.connect(DB) as con:
        g = pd.read_sql("SELECT timestamp, gen_gas_kr FROM historical WHERE timestamp>='2022-01-01'",
                        con, parse_dates=['timestamp']).sort_values('timestamp')
        ehl = pd.read_sql('SELECT timestamp, base, horizon_d, est_gas_gen_land FROM est_horizon_land '
                          'WHERE est_gas_gen_land IS NOT NULL', con, parse_dates=['timestamp'])
        bases_all = sorted(ehl['base'].unique())
    gas = g.set_index('timestamp')['gen_gas_kr'].replace(0, np.nan)
    gser = gas.copy()                     # 연속 인덱스용
    full_idx = pd.date_range(gas.index.min(), gas.index.max(), freq='h')
    gser = gser.reindex(full_idx)

    bases = bases_all[::max(1, len(bases_all)//N_ORIGINS)][:N_ORIGINS]
    print(f'원점 {len(bases)}개 (전체 {len(bases_all)}), 지평 D+1~15, 모델 3종 공정비교')
    rows = []
    for bi, base in enumerate(bases, 1):
        O = pd.Timestamp(base).normalize() + pd.Timedelta(hours=23)
        sub = ehl[ehl.base == base].copy()
        if sub.empty:
            continue
        tg = pd.DatetimeIndex(sub.timestamp)
        actual = gas.reindex(tg).values
        ours = sub.est_gas_gen_land.values
        # seasonal naive(honest): k=168*ceil(n/7)
        kk = (np.ceil(sub.horizon_d.values / 7) * 168).astype(int)
        naive = np.array([gser.get(t - pd.Timedelta(hours=int(k)), np.nan) for t, k in zip(tg, kk)])
        # Prophet: 원점까지(최근 TRAIN_DAYS) 재적합 → 타깃 예측
        tr = gser.loc[O - pd.Timedelta(days=TRAIN_DAYS):O].dropna()
        dtr = pd.DataFrame({'ds': tr.index, 'y': tr.values})
        try:
            m = Prophet(yearly_seasonality=True, weekly_seasonality=True, daily_seasonality=True,
                        seasonality_mode='additive', uncertainty_samples=0)
            m.add_country_holidays(country_name='KR'); m.fit(dtr)
            fc = m.predict(pd.DataFrame({'ds': tg}))
            proph = fc['yhat'].values
        except Exception as e:
            proph = np.full(len(tg), np.nan)
        d = pd.DataFrame({'base': base, 'horizon': sub.horizon_d.values, 'timestamp': tg,
                          'actual': actual, 'ours': ours, 'naive': naive, 'prophet': proph})
        rows.append(d)
        if bi % 5 == 0 or bi == len(bases):
            print(f'  origin {bi}/{len(bases)} ({base[:10]})')
    r = pd.concat(rows, ignore_index=True)
    r['season'] = pd.DatetimeIndex(r.timestamp).month.map(SEASON)
    r.to_csv(os.path.join(TAB, 'compare_horizon_season.csv'), index=False, encoding='utf-8-sig')

    # 지평별 표
    print('\n' + '=' * 60)
    print('지평별 가스 MAPE (%) — 공정비교(원점별 D+1~15)')
    print('=' * 60)
    print(f'{"지평":>5} | {"우리모델":>8} | {"naive(lag)":>10} | {"Prophet":>8}')
    hz_tab = {}
    for n in HZ:
        gg = r[r.horizon == n]
        a, b, c = mape(gg.actual, gg.ours), mape(gg.actual, gg.naive), mape(gg.actual, gg.prophet)
        hz_tab[n] = (a, b, c)
        print(f'  D+{n:>2} | {a:7.2f}% | {b:9.2f}% | {c:7.2f}%')
    ov = (mape(r.actual, r.ours), mape(r.actual, r.naive), mape(r.actual, r.prophet))
    print(f'  전체 | {ov[0]:7.2f}% | {ov[1]:9.2f}% | {ov[2]:7.2f}%')

    # 계절별 표
    seasons = [s for s in ['겨울', '봄', '여름'] if (r.season == s).sum() > 50]
    print('\n' + '=' * 60); print('계절별 가스 MAPE (%) — 전체 지평 평균'); print('=' * 60)
    print(f'{"계절":>5} | {"우리모델":>8} | {"naive":>8} | {"Prophet":>8}')
    for s in seasons:
        gg = r[r.season == s]
        print(f'  {s} | {mape(gg.actual, gg.ours):7.2f}% | {mape(gg.actual, gg.naive):7.2f}% | {mape(gg.actual, gg.prophet):7.2f}%')

    # 그림
    import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
    plt.rcParams['font.family'] = 'Malgun Gothic'; plt.rcParams['axes.unicode_minus'] = False
    fig, ax = plt.subplots(figsize=(7.2, 4))
    ax.plot(HZ, [hz_tab[n][0] for n in HZ], 'o-', color='#059669', label='우리 모델(가스 v2+블렌딩)')
    ax.plot(HZ, [hz_tab[n][1] for n in HZ], 's--', color='#2563eb', label='seasonal naive(lag, 정직)')
    ax.plot(HZ, [hz_tab[n][2] for n in HZ], '^:', color='#c44e52', label='Prophet(원점 재적합)')
    ax.set_xlabel('horizon (D+n)'); ax.set_ylabel('가스 MAPE (%)'); ax.set_xticks(HZ)
    ax.set_title('베이스라인 공정비교 — 지평별 (원점별 D+1~15)'); ax.legend(frameon=False); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(os.path.join(FIG, 'compare_horizon.png'), dpi=130); plt.close(fig)

    fig, axes = plt.subplots(1, len(seasons), figsize=(3.7*len(seasons), 3.6), sharey=True)
    if len(seasons) == 1:
        axes = [axes]
    for ax, s in zip(axes, seasons):
        gg = r[r.season == s]
        for col, lab, st, cl in [('ours', '우리', 'o-', '#059669'), ('naive', 'naive', 's--', '#2563eb'), ('prophet', 'Prophet', '^:', '#c44e52')]:
            ys = [mape(gg[gg.horizon == n].actual, gg[gg.horizon == n][col]) for n in HZ]
            ax.plot(HZ, ys, st, color=cl, label=lab, ms=4)
        ax.set_title(s); ax.set_xlabel('D+n'); ax.grid(alpha=0.3)
    axes[0].set_ylabel('가스 MAPE (%)'); axes[0].legend(frameon=False, fontsize=8)
    fig.suptitle('베이스라인 공정비교 — 계절별 × 지평'); fig.tight_layout()
    fig.savefig(os.path.join(FIG, 'compare_season.png'), dpi=130); plt.close(fig)
    print('\nsaved fig/compare_horizon.png , fig/compare_season.png , tab/compare_horizon_season.csv')


if __name__ == '__main__':
    try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass
    main()
