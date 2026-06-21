# -*- coding: utf-8 -*-
"""새 체인(v4 수요 + landsolar504 신재생 + 가스 v2) 정직 재검증 — 가스 MAPE 재측정.

배경 (2026-06-21)
----------------
5단계(수요)가 PatchTST v4 + 지평별 파인튜닝(G-24)으로, 6단계(신재생)가 landsolar504(G-19 후속,
06-19)로 구조가 바뀌었다.  서빙(`serve_chain_land_new.py`)은 이미 새 구조로 갱신됐지만, 가스의
공개 정확도(전체 ~13.72%)와 후처리(낮/밤 보정·블렌딩 w(h))는 모두 **옛 수요(하이브리드)·옛
6단계로 측정·적합된 값**이다.  이 스크립트는 배포본 그대로(serve_chain_land_new.build_base)를
forecast_horizon 전 base 에서 돌려 실측(gen_gas_kr)과 대조해 **새 체인의 정직 가스 MAPE**를
지평·계절·낮/밤별로 다시 잰다.

★ 왜 build_horizon_backtest.py 를 안 쓰나
   그 파일은 옛 수요(5-A2 lgbm_land_demand_D{n}) + 옛 가스(7-A2 util)로 굳어 있고, 숨은 의존성
   때문에 이동·수정 금지 대상이다.  대신 현재 배포 체인 함수(build_base)를 그대로 import 재사용해
   "지금 돌아가는 그 코드"를 검증한다(가장 충실).

정직성·누수
   - 기상 = 그 base 의 forecast_horizon 실제 예보(build_base 가 스크래치 forecast 로 주입).
   - 가스 자기회귀 시드(rec24/168·lag)는 origin O(=base 23:00) 이하 historical 만 참조 → 누수 없음.
   - 기후값 폴백은 build_base 의 정책 그대로(예보 보간 ≤4h, 가스 기후값은 블렌딩 항으로만).

사용
    python validate_newchain_gas.py --limit 10                 # 스모크(10 base 표본)
    python validate_newchain_gas.py --horizons 1,2,3,7,12      # 지평 한정(권장: 전 base)
    python validate_newchain_gas.py                            # 전 base × D+1..15 (느림)
출력: 콘솔 표 + training/newchain_gas_backtest.parquet (행 단위 예측·실측)
"""
from __future__ import annotations
import os, sys, json, sqlite3, time, argparse, importlib.util, tempfile
import numpy as np, pandas as pd, lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')
CHAIN_PY = os.path.join(ROOT, '7. land_gas_forecaster', 'serve_chain_land_new.py')


def _imp(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    sys.modules[name] = m
    s.loader.exec_module(m)
    return m


def load_actuals() -> pd.DataFrame:
    """historical 실측 (가스/수요/신재생) — 시간 연속 인덱스, 0가스=결측."""
    with sqlite3.connect(DB) as con:
        d = pd.read_sql('SELECT timestamp, gen_gas_kr, real_demand_land, renew_gen_total_kr, '
                        'net_load_kr FROM historical', con, parse_dates=['timestamp'])
    d = d.sort_values('timestamp').set_index('timestamp')
    idx = pd.date_range(d.index.min(), d.index.max(), freq='h')
    d = d.reindex(idx)
    d.index.name = 'timestamp'
    return d


def _season(month: int) -> str:
    return {12: '겨울', 1: '겨울', 2: '겨울', 3: '봄', 4: '봄', 5: '봄',
            6: '여름', 7: '여름', 8: '여름', 9: '가을', 10: '가을', 11: '가을'}[int(month)]


def main():
    ap = argparse.ArgumentParser(description='새 체인 가스 정직 재검증')
    ap.add_argument('--limit', type=int, default=None, help='base 표본수(스트라이드 샘플, 스모크)')
    ap.add_argument('--horizons', default='1,2,3,7,12', help='평가 지평 (콤마)')
    ap.add_argument('--out', default=os.path.join(HERE, 'newchain_gas_backtest.parquet'))
    a = ap.parse_args()
    horizons = [int(x) for x in a.horizons.split(',')]

    chain = _imp('serve_chain_land_new', CHAIN_PY)
    chain.HZ = tuple(horizons)   # build_base 는 모듈 전역 HZ 를 순회 → 평가 지평만 돌게 제한

    print('[load] 모델·자산 (수요 patchtst_lt v4+보정 / 신재생 landsolar504 / 가스 v2)')
    ctx = {
        'gas_booster': lgb.Booster(model_file=chain.sg.MODEL),
        'gas_off': chain.sg._OFFSET,
        'gas_series': chain.sg.load_gas_series(),
        'A6': chain.serve6.load_assets(),
        'v4': chain.mlt.load_serve(DB, chain.LT_DIR),
        'con': sqlite3.connect(DB),
    }
    print(f'[load] 수요 v4 지평 {sorted(ctx["v4"]["models"])}')
    sc = chain.bht.build_scratch(os.path.join(tempfile.gettempdir(), 'validate_newchain_gas.db'))

    bases = chain.list_bases()
    if a.limit and len(bases) > a.limit:
        bases = bases[::max(1, len(bases) // a.limit)][:a.limit]
    print(f'[run] base {len(bases)}개  지평 {horizons}  ({bases[0][:10]} ~ {bases[-1][:10]})')

    parts = []; t0 = time.time()
    for bi, base in enumerate(bases, 1):
        try:
            r = chain.build_base(base, ctx, sc)
        except Exception as e:
            print(f'  [skip] base {base[:10]}: {str(e)[:80]}')
            continue
        if r is None or r.empty:
            continue
        parts.append(r[['base', 'timestamp', 'horizon_d', 'est_demand_land',
                        'est_market_renew_land', 'est_gas_gen_land_raw',
                        'est_gas_gen_land', 'day_type']].copy())
        if bi % 20 == 0 or bi == len(bases):
            print(f'  base {bi}/{len(bases)} ({base[:10]})  누적 {sum(len(p) for p in parts)}행  {time.time()-t0:.0f}s')
    sc.close(); ctx['con'].close()

    if not parts:
        print('결과 없음'); sys.exit(1)
    res = pd.concat(parts, ignore_index=True)
    res['timestamp'] = pd.to_datetime(res['timestamp'])

    # 실측 join
    act = load_actuals()
    res = res.join(act, on='timestamp')
    res['month'] = res.timestamp.dt.month
    res['hour'] = res.timestamp.dt.hour
    res['season'] = res.month.map(_season)
    res['is_day'] = (res.hour >= 9) & (res.hour <= 15)

    # 가스 평가 표본 = 실측 가스>0
    ev = res[(res.gen_gas_kr > 0) & res.est_gas_gen_land.notna()].copy()
    ev['ape'] = (ev.gen_gas_kr - ev.est_gas_gen_land).abs() / ev.gen_gas_kr * 100
    ev['ape_raw'] = (ev.gen_gas_kr - ev.est_gas_gen_land_raw).abs() / ev.gen_gas_kr * 100
    ev['spe'] = (ev.est_gas_gen_land - ev.gen_gas_kr) / ev.gen_gas_kr * 100   # 부호 bias

    def line(g):
        return (f"MAPE {g.ape.mean():5.2f}%  bias {g.spe.mean():+5.1f}%  "
                f"(raw {g.ape_raw.mean():5.2f}%)  n={len(g)}")

    print('\n' + '=' * 72)
    print(f'새 체인 가스 정직 재검증  —  base {ev.base.nunique()}개,  {ev.timestamp.min()} ~ {ev.timestamp.max()}')
    print('=' * 72)
    print(f'\n[전체]  {line(ev)}')

    print('\n[지평별]')
    for n, g in ev.groupby('horizon_d'):
        gg = g.dropna(subset=['real_demand_land'])
        dmape = (gg.real_demand_land - gg.est_demand_land).abs().div(gg.real_demand_land).mean() * 100
        print(f'  D+{n:>2}: {line(g)}   | 수요 MAPE {dmape:4.2f}%')

    print('\n[계절별]')
    for s in ['겨울', '봄', '여름', '가을']:
        g = ev[ev.season == s]
        if len(g):
            print(f'  {s}: {line(g)}')

    print('\n[낮(09-15h) / 밤]  ★한낮 부호 역전 점검')
    for lbl, mask in [('낮', ev.is_day), ('밤', ~ev.is_day)]:
        g = ev[mask]
        print(f'  {lbl}: {line(g)}')

    print('\n[계절 × 낮]  ★보정/비대칭이 이중작용하는지')
    for s in ['겨울', '봄', '여름']:
        g = ev[(ev.season == s) & ev.is_day]
        if len(g):
            print(f'  {s} 낮: {line(g)}')

    if not a.limit:
        res.to_parquet(a.out)
        print('\nsaved', a.out)
    else:
        print('\n(스모크 — parquet 저장 생략)')
    print(f'[done] {(time.time()-t0)/60:.1f}m')


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main()
