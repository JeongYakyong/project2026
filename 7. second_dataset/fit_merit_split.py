# -*- coding: utf-8 -*-
"""
Merit-order LNG/유류 분해함수 적합 (PRD §5.1 / G-4 충실본).
근거: 제주는 급전순위가 유류→LNG. 저부하(fuel<~125MW)는 사실상 유류 100%,
부하가 오를수록 LNG가 한계분을 채워 점유율이 ~0.6까지 상승. 단일 스칼라(0.5421)는
저부하에서 LNG를 과대평가 → 부하수준별(merit) 분해로 교체.

기준연도 = 2024 (only_gen 실측 마지막 해, LNG 증설 후 최신 레짐 = 2025 백필 대상과 동일).
방법: oil_hat = Isotonic(fuel) 단조회귀 → lng = clip(fuel − oil_hat, 0, fuel).
출력: data/merit_split_2024.json  (fuel_grid, oil_grid → np.interp 적용)
백테스트: 2024 내 랜덤 50/50 ×5 로 scalar 대비 검증.
"""
import os, json
import numpy as np, pandas as pd
from sklearn.isotonic import IsotonicRegression

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OG = os.path.join(ROOT, "7. data from csv", "only_gen.csv")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(OUT, exist_ok=True)
BASIS_YEAR = 2024


def metr(pred, act):
    e = np.asarray(pred) - np.asarray(act)
    m = np.asarray(act) > 20
    return np.abs(e).mean(), (np.abs(e[m]) / np.asarray(act)[m]).mean() * 100, e.mean()


def main():
    og = pd.read_csv(OG, parse_dates=["timestamp"])
    g = og[og.timestamp.dt.year == BASIS_YEAR].copy()
    g["fuel"] = g.LNG_Gen + g.Oil_Gen

    # ---- 백테스트: 랜덤 50/50 ×5 (부하효과 분리, 계절 혼재 제거) ----
    rng = np.random.default_rng(0)
    sa, sm = [], []
    for _ in range(5):
        idx = rng.permutation(len(g))
        tr, te = g.iloc[idx[len(g) // 2:]], g.iloc[idx[:len(g) // 2]]
        sh = tr.LNG_Gen.sum() / tr.fuel.sum()
        sa.append(metr(te.fuel * sh, te.LNG_Gen))
        iso = IsotonicRegression(out_of_bounds="clip").fit(tr.fuel, tr.Oil_Gen)
        sm.append(metr(np.clip(te.fuel - iso.predict(te.fuel), 0, te.fuel), te.LNG_Gen))
    sa, sm = np.array(sa).mean(0), np.array(sm).mean(0)

    # ---- 최종 적합: 2024 전체 isotonic → 10MW 격자 knots ----
    iso = IsotonicRegression(out_of_bounds="clip").fit(g.fuel, g.Oil_Gen)
    grid = np.arange(np.floor(g.fuel.min()), np.ceil(g.fuel.max()) + 10, 10.0)
    oil_grid = np.maximum.accumulate(np.round(iso.predict(grid), 2))  # 단조 보장

    scalar = float(g.LNG_Gen.sum() / g.fuel.sum())
    insample_merit = metr(np.clip(g.fuel - np.interp(g.fuel, grid, oil_grid), 0, g.fuel),
                          g.LNG_Gen)
    insample_scalar = metr(g.fuel * scalar, g.LNG_Gen)

    out = {
        "basis_year": BASIS_YEAR,
        "method": "isotonic_oil_on_fuel",
        "fuel_grid": grid.tolist(),
        "oil_grid": oil_grid.tolist(),
        "scalar_share_2024": round(scalar, 4),
        "backtest_random_5050x5": {
            "scalar_MAE": round(float(sa[0]), 2), "scalar_MAPE": round(float(sa[1]), 2),
            "merit_MAE": round(float(sm[0]), 2), "merit_MAPE": round(float(sm[1]), 2),
            "MAE_improve_pct": round((1 - sm[0] / sa[0]) * 100, 1),
            "MAPE_improve_pp": round(float(sa[1] - sm[1]), 1),
        },
        "insample_2024": {
            "scalar_MAE": round(float(insample_scalar[0]), 2),
            "merit_MAE": round(float(insample_merit[0]), 2),
            "scalar_MAPE": round(float(insample_scalar[1]), 2),
            "merit_MAPE": round(float(insample_merit[1]), 2),
        },
    }
    json.dump(out, open(os.path.join(OUT, "merit_split_2024.json"), "w"), indent=2)
    print(f"[merit] knots={len(grid)} scalar={scalar:.4f}")
    print(f"  backtest(random50/50x5): scalar MAE={sa[0]:.1f}/MAPE={sa[1]:.1f}%  "
          f"merit MAE={sm[0]:.1f}/MAPE={sm[1]:.1f}%  "
          f"(MAE -{out['backtest_random_5050x5']['MAE_improve_pct']}%, "
          f"MAPE -{out['backtest_random_5050x5']['MAPE_improve_pp']}pp)")
    print("  saved data/merit_split_2024.json")


if __name__ == "__main__":
    main()
