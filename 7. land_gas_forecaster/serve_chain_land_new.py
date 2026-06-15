# -*- coding: utf-8 -*-
"""serve_chain_land_new.py -- 전국(육지) 서빙 체인 운영 러너 5→6→7 → est_horizon_land.

역할별 재구성(2026-06-15)의 세 번째 진입점.  cron 한 줄 = 한 역할:
  ① 기상예보 → forecast_horizon   = collect_forecast_new.py
  ② 실측      → historical        = collect_data_land_new.py
  ③ 서빙 체인 → est_horizon_land  = **이 파일**

전국 서빙을 레거시 `forecast` 테이블에서 떼어내 forecast_horizon(기상 입력) → est_horizon_land
(예측 출력)으로 이전(사용자 결정).  기존 백테스트 빌더 3종(전 base 순회)
  - 5: model/archive_demand_horizon.py  → est_demand_land
  - 6+7raw: training/build_chain_horizon.py → est_market_renew_land/est_net_load_land/est_gas_gen_land_raw
  - 7최종: training/finalize_gas_archive.py → est_gas_gen_land/est_gas_sendout_ton_land
의 **검증된 함수를 import 재사용**하되, 운영용으로 **최신 base(들)만** 한 번에 돌려 보정·블렌딩
까지 끝낸 모든 컬럼을 est_horizon_land 에 UPSERT 한다.  (백테스트 빌더 파일은 무수정 — 그들은
실측 대조·parquet 산출용으로 계속 보존.)

운영 러너 ↔ 백테스트 차이:
  - 대상 base = forecast_horizon 의 최신 1건(또는 --base / --backfill N).  미래 타깃을 예측한다.
  - 미래 시각 day_type 은 postprocess.add_day_type(한국 공휴일)로 산출(historical 에 없으므로).
  - 가스는 raw→보정(낮/밤×지평)→기후값 블렌딩(w(h))까지 적용해 최종 컬럼을 채운다.
  - 실측 대조·MAPE·parquet 없음(운영).

사용
    python "7. land_gas_forecaster/serve_chain_land_new.py"               # 최신 base 1건
    python "7. land_gas_forecaster/serve_chain_land_new.py" --base 2026-06-14
    python "7. land_gas_forecaster/serve_chain_land_new.py" --backfill 3  # 최근 3 base
    python "7. land_gas_forecaster/serve_chain_land_new.py" --no-write    # 산출만(적재 생략)
"""
from __future__ import annotations
import os, sys, json, sqlite3, importlib.util, tempfile, time, argparse, warnings
import numpy as np, pandas as pd, lightgbm as lgb
warnings.filterwarnings('ignore')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')


def _imp(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    sys.modules[name] = m
    s.loader.exec_module(m)
    return m


# 검증된 단계 모듈 재사용.  expf 가 내부에서 bht 를 이미 로드하므로 그 인스턴스를 공유한다
# (스크래치/실측 로더 동일).  serve6=신재생, sg=가스 서빙(보정·블렌딩·기후값 헬퍼).
expf = _imp('exp_features', os.path.join(ROOT, '5. land_demand_forecaster', 'model', 'exp_features.py'))
bht = expf.bht
serve6 = _imp('serve_solarwind_land', os.path.join(ROOT, '6. land_solarwind_forecaster', 'serve_solarwind_land.py'))
sg = _imp('serve_land_gas', os.path.join(ROOT, '7. land_gas_forecaster', 'serve_land_gas.py'))
pp = _imp('postprocess', os.path.join(ROOT, '1. data_fetcher_and_db', 'core', 'postprocess.py'))

# 수요 v2 (D+15) — archive_demand_horizon 와 동일 자산.
DEM_DIR = os.path.join(ROOT, '5. land_demand_forecaster', 'model', 'models')
DEM_MODEL = os.path.join(DEM_DIR, 'lgbm_land_demand_v2.txt')
DEM_META = os.path.join(DEM_DIR, 'model_meta_v2.json')
FEAT_DEM = expf.BASEFEAT + ['total_cloud', 'midlow_cloud', 'cap_btmppa']

HZ = tuple(range(1, 16))   # D+1..D+15 (육지 16일 윈도우 = D+15.5)
EST_COLS = ['est_demand_land', 'est_market_renew_land', 'est_net_load_land',
            'est_gas_gen_land_raw', 'est_gas_gen_land', 'est_gas_sendout_ton_land']


def _S(t):
    return pd.Timestamp(t).strftime('%Y-%m-%d %H:%M:%S')


def day_type_for(idx: pd.DatetimeIndex) -> np.ndarray:
    """미래 포함 임의 시각의 day_type (holiday/weekend/weekday) — 수집기 postprocess 와 동일
    한국 공휴일 기준(pp._KR_HOLIDAYS 재사용).  학습·레거시 serve_land_demand 와 같은 정의라
    미래 타깃에 올바른 day_type 을 준다 (백테스트 빌더는 historical 결측분을 NaN 으로 두는 한계)."""
    cache: dict = {}
    def _cl(d):
        if d not in cache:
            if d in pp._KR_HOLIDAYS:
                cache[d] = 'holiday'
            elif d.weekday() >= 5:
                cache[d] = 'weekend'
            else:
                cache[d] = 'weekday'
        return cache[d]
    return np.array([_cl(t.date()) for t in idx])


# ── 대상 base 선택 (forecast_horizon 기준) ─────────────────────────────────
def list_bases() -> list[str]:
    with sqlite3.connect(DB) as con:
        return [r[0] for r in con.execute(
            'SELECT DISTINCT base FROM forecast_horizon ORDER BY base').fetchall()]


def pick_bases(arg_base: str | None, backfill: int | None) -> list[str]:
    bases = list_bases()
    if not bases:
        return []
    if arg_base:
        hit = [b for b in bases if b[:10] == arg_base[:10]]
        if not hit:
            raise SystemExit(f"forecast_horizon 에 base {arg_base} 없음 (최신={bases[-1]})")
        return hit
    if backfill:
        return bases[-backfill:]
    return [bases[-1]]


# ── 한 base 의 5→6→7 풀체인 (보정·블렌딩 포함) ────────────────────────────
def build_base(base: str, ctx: dict, sc) -> pd.DataFrame:
    d_act = ctx['d_act']; ppa = ctx['ppa']; dem = d_act['real_demand_land']
    dem_model = ctx['dem_model']; dem_best = ctx['dem_best']; dem_off = ctx['dem_off']
    booster = ctx['gas_booster']; g_off = ctx['gas_off']
    gas_series = ctx['gas_series']; A6 = ctx['A6']

    O = pd.Timestamp(base).normalize() + pd.Timedelta(hours=23)
    bht.set_scratch_forecast(sc, base)
    rec24g = float(gas_series.loc[O - pd.Timedelta(hours=23):O].mean())
    rec168g = float(gas_series.loc[O - pd.Timedelta(hours=167):O].mean())
    if not (np.isfinite(rec24g) and np.isfinite(rec168g)):
        print(f"  [skip] base {base[:10]} 가스 자기회귀 시드(rec24/168) 결측")
        return pd.DataFrame()

    rec24d = float(dem.loc[O - pd.Timedelta(hours=23):O].mean())
    rec168d = float(dem.loc[O - pd.Timedelta(hours=167):O].mean())
    rows = []
    for n in HZ:
      try:
        h0, h1 = (n - 1) * 24 + 1, n * 24
        H = np.arange(h0, h1 + 1)
        tg = pd.DatetimeIndex([O + pd.Timedelta(hours=int(h)) for h in H])
        dtv = day_type_for(tg)

        # ── 5단계 수요 (v2) ──
        wx, valid = expf.fh_weather(sc, tg)
        ddf = pd.DataFrame(index=tg)
        ddf['h'] = H
        for k in (168, 336, 504):   # 정직 가드: h<=k 일 때만(타깃-k가 원점 이전)
            ddf[f'lag{k}'] = np.where(H <= k, dem.reindex(tg - pd.Timedelta(hours=k)).values, np.nan)
        ddf['lag24'] = np.where(H <= 24, dem.reindex(tg - pd.Timedelta(hours=24)).values, np.nan)
        ddf['rec24'] = rec24d; ddf['rec168'] = rec168d
        for c in ('temp_c', 'solar_rad', 'wind_spd', 'total_cloud', 'midlow_cloud'):
            ddf[c] = wx[c].values
        ddf['cap_btmppa'] = expf.cap_for(tg, ppa)
        ddf['hour_sin'] = np.sin(2*np.pi*tg.hour/24); ddf['hour_cos'] = np.cos(2*np.pi*tg.hour/24)
        ddf['dow_sin'] = np.sin(2*np.pi*tg.dayofweek/7); ddf['dow_cos'] = np.cos(2*np.pi*tg.dayofweek/7)
        ddf['month_sin'] = np.sin(2*np.pi*tg.month/12); ddf['month_cos'] = np.cos(2*np.pi*tg.month/12)
        ddf['day_type'] = pd.Categorical(dtv, categories=expf.DTCATS)
        ok = valid.values & ~np.isnan(ddf['lag504'].values)
        dem_pred = np.full(len(tg), np.nan)
        if ok.any():
            dem_pred[ok] = dem_model.predict(ddf.loc[ok, FEAT_DEM], num_iteration=dem_best) + dem_off

        # ── 6단계 신재생 (PatchTST/LGBM 하이브리드, 스크래치 기상) ──
        out6, *_ = serve6._predict_day(sc, O.normalize(), n, A6)
        mr = pd.Series(out6[serve6.OUT['mr']].values,
                       index=pd.DatetimeIndex(out6['timestamp'])).reindex(tg).values

        m = ~np.isnan(dem_pred) & ~pd.isna(mr)
        if not m.any():
            continue
        tg2 = tg[m]; H2 = H[m]; dem2 = dem_pred[m]; mr2 = mr[m].astype(float); dt2 = dtv[m]

        # ── 7단계 가스 raw (v2 자기회귀) ──
        gf = pd.DataFrame(index=tg2)
        gf['real_demand_land'] = dem2
        gf['renew_util'] = mr2 / sg._renew_cap(tg2)
        gf['gas_lag168'] = np.where(H2 <= 168, gas_series.reindex(tg2 - pd.Timedelta(hours=168)).values, np.nan)
        gf['gas_lag24'] = np.where(H2 <= 24, gas_series.reindex(tg2 - pd.Timedelta(hours=24)).values, np.nan)
        gf['gas_rec24'] = rec24g; gf['gas_rec168'] = rec168g
        gf['h'] = H2; gf['hour'] = tg2.hour; gf['dow'] = tg2.dayofweek; gf['doy'] = tg2.dayofyear
        gas_raw = booster.predict(gf[sg.FEATS]) + g_off

        rows.append(pd.DataFrame({
            'base': base, 'timestamp': tg2, 'horizon_d': n,
            'est_demand_land': dem2, 'est_market_renew_land': mr2,
            'est_net_load_land': dem2 - mr2, 'est_gas_gen_land_raw': gas_raw,
            'day_type': dt2}))
      except Exception as e:
        # 부분 적재 base(근거리 누락)·예보 결손 지평은 건너뛴다 (build_chain_horizon 동일 정책).
        continue

    if not rows:
        return pd.DataFrame()
    r = pd.concat(rows, ignore_index=True)

    # ── 7단계 최종 가스: 보정(낮/밤×지평) + 기후값 블렌딩 (finalize_gas_archive 동일) ──
    day_c, night_c, conv, w_dict, clim_spec = sg._load_calib()
    lut, fb = sg.load_gas_climatology(clim_spec.get('years', '2022-2024'),
                                      clim_spec.get('window_days', 7))
    idx = pd.DatetimeIndex(r.timestamp)
    is_day = (idx.hour.values >= 9) & (idx.hour.values <= 15)
    cal = np.array([(day_c.get(int(h), 1.0) if d else night_c.get(int(h), 1.0))
                    for h, d in zip(r.horizon_d, is_day)])
    gas_cal = r.est_gas_gen_land_raw.values * cal
    clim = sg._clim_vals(idx, r.day_type.values, lut, fb)
    wv = sg._blend_w(r.horizon_d.values.astype(float), w_dict)
    final = gas_cal.copy()
    use = np.isfinite(clim)
    final[use] = (1 - wv[use]) * gas_cal[use] + wv[use] * clim[use]
    r['est_gas_gen_land'] = final
    r['est_gas_sendout_ton_land'] = final * conv
    return r


# ── est_horizon_land UPSERT ────────────────────────────────────────────────
def upsert_est(r: pd.DataFrame, db_path: str) -> int:
    if r.empty:
        return 0
    def _v(x):
        return None if (x is None or (isinstance(x, float) and not np.isfinite(x))) else float(x)
    data = [
        (_S(row.timestamp), str(row.base), int(row.horizon_d),
         *[_v(getattr(row, c)) for c in EST_COLS])
        for row in r.itertuples(index=False)
        if np.isfinite(row.est_demand_land)
    ]
    if not data:
        return 0
    set_clause = ', '.join(f'{c}=excluded.{c}' for c in (['horizon_d'] + EST_COLS))
    col_list = ', '.join(['timestamp', 'base', 'horizon_d'] + EST_COLS)
    ph = ', '.join('?' * (3 + len(EST_COLS)))
    with sqlite3.connect(db_path) as con:
        con.execute('CREATE TABLE IF NOT EXISTS est_horizon_land ('
                    'timestamp TEXT, base TEXT, horizon_d INT, PRIMARY KEY(base, timestamp))')
        cols = [c[1] for c in con.execute('PRAGMA table_info(est_horizon_land)')]
        for c in EST_COLS:
            if c not in cols:
                con.execute(f'ALTER TABLE est_horizon_land ADD COLUMN "{c}" REAL')
        con.executemany(
            f'INSERT INTO est_horizon_land ({col_list}) VALUES ({ph}) '
            f'ON CONFLICT(base, timestamp) DO UPDATE SET {set_clause}', data)
        con.commit()
    return len(data)


def main():
    ap = argparse.ArgumentParser(description='전국 서빙 체인 운영 러너 5→6→7 → est_horizon_land')
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--base', default=None, help='특정 base 날짜 YYYY-MM-DD (기본: forecast_horizon 최신)')
    g.add_argument('--backfill', type=int, default=None, help='최근 N개 base 처리')
    ap.add_argument('--no-write', action='store_true', help='산출만 — est_horizon_land 적재 생략')
    a = ap.parse_args()

    bases = pick_bases(a.base, a.backfill)
    if not bases:
        raise SystemExit('forecast_horizon 비어있음 — 먼저 기상예보 수집(collect_forecast_new) 필요')
    print(f'[serve_chain_land_new] 대상 base {len(bases)}개: {bases[0][:10]} ~ {bases[-1][:10]}')

    # 공용 자산 1회 로드.
    print('[load] 모델·자산 로드 (수요 v2 / 가스 v2 / 신재생 / 실측 시계열)')
    dem_model = lgb.Booster(model_file=DEM_MODEL)
    ctx = {
        'd_act': bht.load_actuals(),
        'ppa': expf.load_capa(),
        'dem_model': dem_model,
        'dem_best': dem_model.num_trees(),
        'dem_off': float(json.load(open(DEM_META, encoding='utf-8'))['init_score']),
        'gas_booster': lgb.Booster(model_file=sg.MODEL),
        'gas_off': sg._OFFSET,
        'gas_series': sg.load_gas_series(),
        'A6': serve6.load_assets(),
    }
    sc = bht.build_scratch(os.path.join(tempfile.gettempdir(), 'serve_chain_land.db'))

    t0 = time.time(); total = 0
    for bi, base in enumerate(bases, 1):
        r = build_base(base, ctx, sc)
        if r.empty:
            print(f'  base {bi}/{len(bases)} ({base[:10]}) — 산출 없음')
            continue
        ev = r.dropna(subset=['est_gas_gen_land'])
        print(f'  base {bi}/{len(bases)} ({base[:10]})  {len(r)}행 D+{r.horizon_d.min()}~{r.horizon_d.max()}'
              f'  수요 {r.est_demand_land.mean():.0f}MW  가스 {ev.est_gas_gen_land.mean():.0f}MW  {time.time()-t0:.0f}s')
        if not a.no_write:
            n = upsert_est(r, DB)
            total += n
    sc.close()

    if a.no_write:
        print('\n(--no-write: 적재 생략)')
    else:
        with sqlite3.connect(DB) as con:
            tot = con.execute('SELECT COUNT(*) FROM est_horizon_land').fetchone()[0]
            rng = con.execute('SELECT MIN(timestamp), MAX(timestamp), COUNT(DISTINCT base) '
                              'FROM est_horizon_land').fetchone()
        print(f'\nest_horizon_land UPSERT {total}행  (전체 {tot}행, base {rng[2]}개, {rng[0]} ~ {rng[1]})')
    print(f'[serve_chain_land_new] done in {(time.time()-t0)/60:.1f}m')


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main()
