# -*- coding: utf-8 -*-
"""7단계 서빙 — net_load 체인(5·6단계) → 가스 발전량 + KOGAS 송출량.

체인:  5단계 est_demand_land ─┐
                               ├─→ 7-A2 가스모델(util=gen/LNG_cap) ×용량복원 ×bias보정
       6단계 est_market_renew ─┘                                        → 발전량(MW)
                                                              ×0.1521 → 송출량(TON, 7-C)

설계(2026-06-10 확정):
  - 모델 = 기존 7-A2(`lgbm_land_gas_util.txt`, 실측 학습). A안(체인입력 재학습)은 효과없어 기각.
  - 입력 = forecast 테이블의 est_demand_land(5단계)·est_market_renew_land(6단계) + 달력 + day_type.
  - util 예측 → ×LNG_cap(월별, kr_elec_capa.csv ffill) → ×bias_calib(val2025 전역계수 0.96509).
  - 송출량(TON) = 발전량(MWh) × 0.1521 (7-C 무절편 단일계수).
  - 동시점 회귀라 지평 개념은 입력(5·6 지평)에 들어있음. 검증 D+1/2/3/7/12: training/REPORT_7-A2-A.

출력(forecast 테이블, _land 접미사):
  est_gas_gen_land(발전량 MW), est_gas_sendout_ton_land(송출량 TON/h)

API: predict_gas_to_db(origin, days_ahead) / backfill_gas_to_db(start, end)
CLI: python serve_land_gas.py predict 2026-05-01 --days 7
"""
from __future__ import annotations
import os, sys, sqlite3, json
import numpy as np, pandas as pd, lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
DB   = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')
CAP_CSV = os.path.join(ROOT, '1. data_fetcher_and_db', 'second_dataset', 'kr_elec_capa.csv')
MODEL = os.path.join(HERE, 'model', 'lgbm_land_gas_util.txt')
CALIB_JSON = os.path.join(HERE, 'model', 'gas_serving_calib.json')

DEMAND_COL = 'est_demand_land'           # 5단계
RENEW_COL  = 'est_market_renew_land'     # 6단계 (=시장 solar+wind, 학습 renew_gen_total_kr 정의 일치)
OUT_GEN = 'est_gas_gen_land'
OUT_TON = 'est_gas_sendout_ton_land'
FEATS = ['real_demand_land', 'renew_gen_total_kr', 'hour', 'dow', 'month', 'doy', 'day_type']
DTCATS = ['holiday', 'weekday', 'weekend']


def _conn():
    return sqlite3.connect(DB)


def _load_calib():
    c = json.load(open(CALIB_JSON, encoding='utf-8'))
    return float(c['bias_calib']), float(c['conv_ton_per_mwh'])


def _lng_cap_series():
    cap = pd.read_csv(CAP_CSV, encoding='euc-kr').rename(
        columns={'기간': 'period', '지역': 'region', 'LNG': 'LNG_cap'})
    cap = cap[cap['region'] == '합계'].copy()
    cap['ym'] = pd.to_datetime(cap['period'], format='%b-%y').dt.to_period('M')
    cap['LNG_cap'] = pd.to_numeric(cap['LNG_cap'], errors='coerce')
    return cap[['ym', 'LNG_cap']].dropna().sort_values('ym').set_index('ym')['LNG_cap']


def _lng_cap_for(idx: pd.DatetimeIndex, lng: pd.Series) -> np.ndarray:
    ym = idx.to_period('M')
    full = pd.period_range(min(ym.min(), lng.index.min()), max(ym.max(), lng.index.max()), freq='M')
    s = lng.reindex(full).ffill().bfill()
    return ym.map(s).astype(float).values


def _read_chain_inputs(con, t0, t1):
    df = pd.read_sql(
        f'SELECT timestamp, "{DEMAND_COL}", "{RENEW_COL}", day_type FROM forecast '
        f'WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp',
        con, params=(t0, t1), parse_dates=['timestamp']).set_index('timestamp')
    return df


def predict_gas_to_db(origin_date: str | None = None, days_ahead: int = 7,
                      write: bool = True, verbose: bool = True) -> pd.DataFrame:
    calib, conv = _load_calib()
    lng = _lng_cap_series()
    booster = lgb.Booster(model_file=MODEL)

    with _conn() as con:
        if origin_date is None:
            mx = pd.read_sql(f'SELECT MAX(timestamp) m FROM forecast WHERE "{RENEW_COL}" IS NOT NULL', con).iloc[0]['m']
            O = pd.Timestamp(mx).normalize() - pd.Timedelta(days=1)
        else:
            O = pd.Timestamp(origin_date).normalize()
        t0 = (O + pd.Timedelta(days=1)).strftime('%Y-%m-%d 00:00:00')
        t1 = (O + pd.Timedelta(days=days_ahead)).strftime('%Y-%m-%d 23:00:00')
        ci = _read_chain_inputs(con, t0, t1)

    ci = ci.dropna(subset=[DEMAND_COL, RENEW_COL])
    if not len(ci):
        raise ValueError(f'체인 입력 없음 ({t0}~{t1}) — 5·6단계 서빙을 먼저 실행하세요.')
    idx = ci.index
    df = pd.DataFrame(index=idx)
    df['real_demand_land'] = ci[DEMAND_COL].astype(float).values
    df['renew_gen_total_kr'] = ci[RENEW_COL].astype(float).values
    df['hour'] = idx.hour; df['dow'] = idx.dayofweek; df['month'] = idx.month; df['doy'] = idx.dayofyear
    dt = ci['day_type'].where(ci['day_type'].notna(),
                              np.where(idx.dayofweek >= 5, 'weekend', 'weekday'))
    df['day_type'] = pd.Categorical(dt.values, categories=DTCATS)

    cap = _lng_cap_for(idx, lng)
    util = booster.predict(df[FEATS])
    gen = util * cap * calib                      # 발전량 MW (bias 보정 포함)
    ton = gen * conv                              # 송출량 TON/h (7-C)
    out = pd.DataFrame({'timestamp': idx.strftime('%Y-%m-%d %H:%M:%S'),
                        OUT_GEN: np.round(gen, 1), OUT_TON: np.round(ton, 2)})

    if write:
        with _conn() as con:
            cols = [c[1] for c in con.execute('PRAGMA table_info(forecast)')]
            for c in (OUT_GEN, OUT_TON):
                if c not in cols:
                    con.execute(f'ALTER TABLE forecast ADD COLUMN "{c}" REAL')
            con.executemany(
                f'INSERT INTO forecast ("timestamp","{OUT_GEN}","{OUT_TON}") VALUES (?,?,?) '
                f'ON CONFLICT("timestamp") DO UPDATE SET "{OUT_GEN}"=excluded."{OUT_GEN}", '
                f'"{OUT_TON}"=excluded."{OUT_TON}"',
                [(r.timestamp, float(r[OUT_GEN]), float(r[OUT_TON])) for _, r in out.iterrows()])
            con.commit()
    if verbose:
        print(f'origin={O:%Y-%m-%d} → D+1..D+{days_ahead}  {len(out)}h  '
              f'gas {gen.mean():.0f}MW(avg)  송출 {ton.sum():.0f}TON(합)  calib×{calib}')
        print(out.head(12).to_string(index=False))
    return out


def backfill_gas_to_db(start: str, end: str, days_ahead: int = 1,
                       write: bool = True, verbose: bool = True) -> pd.DataFrame:
    """과거 origin들에 대해 예측 후 실측 gen_gas_kr와 MAPE(체인 입력 존재 구간만)."""
    calib, conv = _load_calib()
    with _conn() as con:
        gas = pd.read_sql('SELECT timestamp, gen_gas_kr FROM historical', con,
                          parse_dates=['timestamp']).set_index('timestamp')['gen_gas_kr']
    origins = pd.date_range(pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize(), freq='D')
    rows = []
    for O in origins:
        try:
            o = predict_gas_to_db(O.strftime('%Y-%m-%d'), days_ahead, write=write, verbose=False)
        except Exception:
            continue
        o = o.copy(); o['actual'] = gas.reindex(pd.DatetimeIndex(o['timestamp'])).values
        rows.append(o)
    if not rows:
        print('예측 가능한 origin 없음'); return pd.DataFrame()
    res = pd.concat(rows, ignore_index=True)
    if verbose:
        m = res.dropna(subset=['actual']); m = m[m.actual > 0]
        mape = float(np.mean(np.abs(m.actual - m[OUT_GEN]) / m.actual) * 100)
        bias = float(np.mean((m[OUT_GEN] - m.actual) / m.actual) * 100)
        print(f'[backfill] {start}~{end}  예측 {len(res)}h  실측대조 {len(m)}h  '
              f'발전량 MAPE {mape:.2f}%  bias {bias:+.1f}%')
    return res


if __name__ == '__main__':
    import argparse
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    p = argparse.ArgumentParser(description='7단계 가스 발전·송출량 서빙 (체인 5·6 → 7-A2 + bias보정)')
    sub = p.add_subparsers(dest='cmd', required=True)
    pp = sub.add_parser('predict'); pp.add_argument('date', nargs='?', default=None)
    pp.add_argument('--days', type=int, default=7); pp.add_argument('--no-write', action='store_true')
    bf = sub.add_parser('backfill'); bf.add_argument('start'); bf.add_argument('end')
    bf.add_argument('--days', type=int, default=1); bf.add_argument('--no-write', action='store_true')
    a = p.parse_args()
    if a.cmd == 'predict':
        predict_gas_to_db(a.date, a.days, write=not a.no_write)
    else:
        backfill_gas_to_db(a.start, a.end, a.days, write=not a.no_write)
