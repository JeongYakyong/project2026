# forecast_data_collecting — 운영 가이드 (`final/`)

제주 + 육지 재생에너지 발전량 예측 모델의 **입력 데이터**를 기상청(KMA) / 전력거래소(KPX)
API 에서 모아, 모델이 바로 읽는 두 개의 wide SQLite DB 로 만든다.

| 권역 | 지점 | 출력 DB |
|---|---|---|
| 제주 3 지점 | 서/고산(풍력), 동/성산(풍력), 남/태양광 | `data/input_data_jeju.db` |
| 육지 5 지점 | 대관령·원주·서산·포항·영광 | `data/input_data_land.db` |

각 DB 는 `forecast`(예보) / `historical`(관측·실적) 두 테이블을 가지며,
둘 다 `timestamp`(KST) 를 키로 UPSERT 한다 (재실행해도 중복 없이 갱신).

---

## 디렉터리

```
final/
├── core/
│   ├── collect_data_jeju.py   ← 제주 실행 진입점
│   ├── collect_data_land.py   ← 육지 실행 진입점
│   ├── api_fetchers_jeju.py   제주 fetcher: KMA(KIMR + ASOS 3지점) + KPX(제주 수급 / SMP·예상수요)
│   ├── api_fetchers_land.py   육지 fetcher: KMA(ASOS·KIMG-land 5지점) + KPX(육지 수급 / 발전실적 / SMP·예상수요)
│   ├── _common.py             공통 인프라: KIMG fetch/parse/derive core, KPX·ASOS helper, partial_upsert
│   └── postprocess.py         값 범위 클립(clip_ranges) + 요일 구분(add_day_type)
├── data/                      ← 출력 DB 두 개
├── .env                       KMA_API_KEY / KPX_API_KEY
└── requirements.txt
```

**실행하는 파일은 `core/` 의 `collect_data_jeju.py` / `collect_data_land.py` 둘 뿐**이다.
나머지 4 개 파일은 이 둘이 import 해서 쓰는 라이브러리 (직접 실행할 일 없음).

---

## 설치

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`.env` 파일에 인증키 두 개를 넣는다 (`.env.example` 참고):

```
KMA_API_KEY=...   # 기상청 apihub 키 (KIMR / KIMG / ASOS 공용)
KPX_API_KEY=...   # 전력거래소 open API 키 (수급 / SMP / 예상수요 / 발전실적)
```

---

## 실행

### 평소 — 최신 발표 갱신

```powershell
python core/collect_data_jeju.py     # 제주: forecast(최근 2 발표) + historical(최근 2 일)
python core/collect_data_land.py     # 육지: 동일
```

인자 없이 실행하면 `forecast` 와 `historical` 양쪽을 모두 갱신한다.

### 과거 일괄 채우기 — backfill

```powershell
python core/collect_data_jeju.py --backfill 30     # 최근 30 일치 forecast + historical
python core/collect_data_land.py --backfill 30
```

KMA 보존기간이 ~180 일이라 `--backfill 150` 까지 가능 (대용량은 수 시간 소요).
이미 채워진 구간은 자동으로 건너뛰므로(resume-skip) 중단 후 재실행해도 안전.

### 자주 쓰는 옵션

| 옵션 | 설명 |
|---|---|
| `--no-historical` | forecast 만 |
| `--no-forecast` | historical 만 |
| `--base YYYYMMDD HH` | 특정 UTC 발표 하나만 (예: `--base 20260525 12`) |
| `--bases N` | 최근 N 개 발표 (기본 2) |
| `--historical-days N` | historical 윈도우 길이 (기본 2 일) |
| `--start / --end` | (육지) historical 기간 직접 지정 `YYYY-MM-DD` |
| `--no-save` | DB 에 쓰지 않고 요약만 출력 (dry-run) |

라이브러리로도 호출 가능:

```python
from collect_data_jeju import build, build_historical
build(); build_historical()                       # input_data_jeju.db 갱신

from collect_data_land import build_forecast, build_historical as land_hist
build_forecast(); land_hist()                     # input_data_land.db 갱신
```

---

## 출력 DB 와 컬럼 규칙

두 DB 모두 `forecast` + `historical` 테이블, 키는 `timestamp`(KST, `'YYYY-MM-DD HH:MM:SS'`).
모델은 두 DB 를 `timestamp` 범위로 읽어 `forecast` + `historical` 을 join 한다.

컬럼 이름은 **base 이름 + suffix** 규칙을 따른다:

- **지점 weather suffix**
  - 제주: `_west` / `_east` / `_south`
  - 육지: `_daegwallyeong` / `_wonju` / `_seosan` / `_pohang` / `_yeonggwang`
- **전력 계통 suffix**
  - `_jeju` = 제주 계통 수급·실적
  - `_land` = 육지(본토) 수급
  - `_kr` = 전국(제주+육지) 발전원별 실적 (`powerSource.es`, 전국값이라 `_land` 아님)
  - `_da` = day-ahead(전일) 예측 — SMP / 예상수요. 같은 물리량은 두 권역에서 base 이름을 통일하고 suffix 만 다르게 둔다.
- **파생 컬럼** (`historical`, 매 수집 시 자동 재계산)
  - `*_capacity_*` = 발전량의 누적 최대값(cummax) → 설비용량 근사. 첫 해는 그 해 peak 로 평탄화, 이후 단조 증가.
  - `*_utilization_*` = 발전량 / capacity (이용률, 0~1). 예: `real_wind_utilization_jeju`, `gen_solar_utilization_kr`.
  - `day_type` = `weekday` / `weekend` / `holiday` (한국 공휴일·대체공휴일 반영).

---

## 모델 입력으로 쓸 때 알아둘 것

두 DB 는 시계열 모델의 입력이다. 모델은 `timestamp` 범위로 읽어 `forecast`(미래 예보) + `historical`(과거 관측·실적)을 join 한다. 추론은 `WHERE timestamp >= now()`, 학습은 두 테이블(필요하면 jeju ↔ land DB)을 `timestamp` 로 join.

1. **`forecast` 는 timestamp 마다 "가장 최근 발표(freshest base)" 값만 보관한다.** 같은 시각을 여러 발표가 예보하면 더 늦게 만들어진 발표로 덮어쓴다(UPSERT in place). 평소엔 그냥 기본 실행 — 최근 발표를 받아 freshest 로 정리된다.

2. **발표 시각·가용 지연을 보고 base 를 골라라.** 발표 UTC 00/06/12/18 (KST 09/15/21/03), 공개지연 KIMR ~15분 / KIMG ~2–3h. **day-ahead 입찰**(마감 대개 D-1 11:00 KST)에 reliably 가용한 가장 fresh 한 발표는 **D-2 18 UTC(=03 KST)**. 단순하게는 매일 그 발표(또는 최근 4발표)를 받아 freshest 만 쓰면 된다.

3. **(중요) 학습용 과거 forecast 의 lead-time 누수 주의.** `forecast` 는 freshest 만 남기므로, 과거 어떤 시각의 저장값이 그 시각을 **짧은 lead 로** 맞춘 발표일 수 있다(실제 입찰 시점엔 못 봤을 정보 = look-ahead leakage). day-ahead 모델을 누수 없이 학습하려면 그 lead 의 발표만 backfill 하라 — 예: 육지 `--backfill 150 --kimg-issues 18 --kimg-days 1` (18 UTC 발표만 적재).

4. **NaN 을 전제로 전처리하라.** forecast 는 수집 윈도우(대략 D+1~D+2) 밖이면 비고, 미발행 미래 `_da` 나 fetch 실패 구간도 NaN. `radiation_*` 은 KIMG 만 제공. 관측 `solar_rad` 는 무센서 구간을 NaN 으로 둔다(0 으로 위조하지 않음). 미래 시각엔 capacity 만 채워지고(ffill) utilization 은 NaN.

5. **재실행·백필 안전 / 데이터 한계.** 모든 write 는 timestamp 키 partial UPSERT — 같은 구간을 다시 받아도 중복 없이 갱신되고, 배치에 없는 컬럼은 보존된다. KMA 보존 ~180일이라 그 안은 backfill 가능. KPX day-ahead API 는 호출 쿼터(429)가 있어 한 번에 많이 받으면 일부 날짜가 비고 다음 실행에서 채워진다.

---

## 데이터 소스 요약

- **KMA apihub** — KIMR(제주 지역모델: 풍력·기상), KIMG(일사량·구름·기온·10m 풍속), ASOS(지점 관측).
  발표 UTC 00/06/12/18 (= KST 09/15/21/03). 공개지연 KIMR ~15 분, KIMG ~2–3 h.
- **KPX** — 수급(제주/육지), SMP·예상수요(day-ahead), 발전원별 실적.

일사량(`radiation_*`)은 KIMG 만 제공 → 태양광 예측의 핵심 입력.

---

## 참고

- 모든 경로는 repo 루트 기준으로 해석되므로 어느 디렉터리에서 실행해도 동일하게 동작.
- repo 루트의 `core/` (legacy) 와 `vilage_api/` 는 구버전 — **운영은 `final/` 만** 사용.
- 코드 주석/docstring 은 한글, DB 에 저장되는 값·로그 출력은 ASCII (Windows CP949 깨짐 방지).
