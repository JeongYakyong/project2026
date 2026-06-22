# 서버 배포 가이드 — 데이터 수집 (1단계) + 추후 Streamlit (8단계)

> 대상 서버: 기존 `~/forecast_data_collecting` 가 돌고 있는 Ubuntu 노트북.
> 이 프로젝트는 **별도 폴더 `~/project2026`** 에 clone 하며 기존 crontab 과 공존한다.

## 0. 구성 개요 (무엇이 어떤 경로로 가는가)

| 대상 | 전송 방법 | 비고 |
|---|---|---|
| 코드 | `git clone` / 이후 `git pull` | GitHub `JeongYakyong/project2026` |
| `.env` (KMA/KPX API 키) | `scp` 1회 | gitignore 됨 — git 으로 절대 안 감 |
| `input_data_jeju.db` (~40MB) / `input_data_land.db` (~55MB) | `scp` 1회 | gitignore 됨. 업로드 후엔 **서버 DB 가 원본** |
| 수집 cron | `deploy/crontab.example` | 제주/육지 각 4회/일 |

업로드가 끝나면 데이터의 흐름이 역전된다:
**서버 cron 이 DB 를 계속 갱신 → 로컬(Windows)에서 모델링·백필이 필요할 때 서버에서 내려받는다** (§6).
Streamlit(8단계)은 같은 서버에서 이 DB 를 로컬 파일로 직접 읽는 구조(G-15)라 추가 동기화가 없다.

## 1. 서버 사전 확인

```bash
python3 --version   # 3.10 이상 권장 (최소 3.9 — zoneinfo·pandas 2 요구)
```

3.9 미만이면 deadsnakes PPA 등으로 3.10+ 설치 후 아래 venv 생성 시 그 바이너리를 쓴다.

## 2. clone + venv

```bash
cd ~
git clone https://github.com/JeongYakyong/project2026.git
# private repo 면: GitHub fine-grained PAT 를 비밀번호로 입력하거나,
#   서버 ssh 키(ssh-keygen → GitHub Deploy Key 등록) 후 git@github.com: 주소로 clone.

cd ~/project2026
python3 -m venv .venv
.venv/bin/pip install -r "1. data_fetcher_and_db/requirements.txt"
chmod +x deploy/*.sh
```

> 수집에 필요한 의존성은 requests/pandas/numpy/dotenv/holidays 뿐이다.
> torch 등 모델 의존성은 8단계 배포 때 별도로 추가한다 (§7).

## 3. .env + DB 업로드 (로컬 Windows PowerShell 에서)

원격 경로에 공백(`1. data_fetcher_and_db`)이 있어 scp 따옴표가 꼬이기 쉬우므로,
**홈으로 올리고 서버에서 mv** 하는 방식을 쓴다.

```powershell
cd C:\Users\bjkim\Desktop\project2026
scp ".\1. data_fetcher_and_db\.env"                      kimjourvanne@<서버IP>:~
scp ".\1. data_fetcher_and_db\data\input_data_jeju.db"   kimjourvanne@<서버IP>:~
scp ".\1. data_fetcher_and_db\data\input_data_land.db"   kimjourvanne@<서버IP>:~
```

서버에서:

```bash
mkdir -p ~/project2026/"1. data_fetcher_and_db"/data
mv ~/.env             ~/project2026/"1. data_fetcher_and_db"/
mv ~/input_data_*.db  ~/project2026/"1. data_fetcher_and_db"/data/
```

## 4. 손 실행 검증 (crontab 등록 전 필수)

```bash
~/project2026/deploy/run_collect_jeju.sh
~/project2026/deploy/run_collect_land.sh
tail -50 ~/project2026/deploy/logs/collect_jeju_$(date +%Y%m).log
tail -50 ~/project2026/deploy/logs/collect_land_$(date +%Y%m).log
```

DB 갱신 확인:

```bash
sqlite3 ~/project2026/"1. data_fetcher_and_db"/data/input_data_jeju.db \
  "SELECT MAX(base) FROM forecast_horizon; SELECT MAX(timestamp) FROM historical;"
# (forecast 테이블은 폐기됨 — 전국 06-19·제주 06-20. forecast_horizon 의 최신 base 로 확인.)
```

## 5. crontab 등록

```bash
crontab -e    # 기존 forecast_data_collecting 줄은 그대로 두고 아래에 추가
```

`deploy/crontab.example` 내용을 붙여넣는다 (경로의 사용자명 확인). 요약:

- 제주 `10 6,12,18 * * *` — 기본 동작(forecast 최신 2발표 + historical 2일)
- 제주 `10 0 * * *` — `--bases 1 --forecast-days 7` (12 UTC 발표 7일 예보 → 2-A 장지평. D+5까지 KIMR 1h, D+6 정오까지 KIMG 1h, 이후 D+7까지 KIMG 3h 행만 — 보간은 사용 시)
- 육지 `40 6,12,18 * * *` — 기본 동작
- 육지 `40 0 * * *` — `--bases 1 --kimg-days 12` (12 UTC 발표 12일 예보 → D+12 지평까지. lead 한계로 D+12 22~23시는 빈 값)

시각 근거: KIM 발표 00/06/12/18 UTC(= KST 09/15/21/03) + 가용 지연 ~3h → KST 12/18/00/06 시대.
wrapper 가 `flock` 으로 중복 실행을 막고, 로그는 `deploy/logs/collect_{jeju,land}_YYYYMM.log` 월별 분리.

## 6. 운영 수칙

- **DB 원본은 서버.** 로컬에서 모델링·EDA 할 때는 내려받는다:
  ```powershell
  scp kimjourvanne@<서버IP>:"project2026/1.\ data_fetcher_and_db/data/input_data_land.db" ".\1. data_fetcher_and_db\data\"
  ```
- 코드 수정은 로컬 → commit/push → 서버에서 `git pull`. 서버에서 직접 코드를 고치지 않는다.
- 대량 백필(`--backfill N`)은 cron 과 겹치지 않게 손으로, `flock` 락 충돌 시 cron 쪽이 자동 skip 된다.
- API 한도 보호: 수집은 crontab 으로만. Streamlit 등 사용자 트리거 수집 금지 (PROJECT.md §6.3).

## 7. 추후 확장 (8단계 Streamlit + 서빙 사전적재)

같은 `~/project2026` clone 을 그대로 쓴다 (G-15: 자체 서버, 로컬 DB 실시간 읽기).

- 서빙 사전적재: `serve_*.py` 들을 수집 cron 뒤(예: 매일 06:50)에 실행하는 줄 추가 — 모델 의존성(lightgbm, torch 등) requirements 분리 후.
- Streamlit: `streamlit run "8. streamlit/app.py"` 를 systemd 유저 서비스로 상시 기동.
- 구체 절차는 8-B 진행 시 이 문서에 추가한다.

## 8. 배포 갱신 체크리스트 — 코드·모델·서빙 반영 (2026-06-22)

> 초기 배포(§2~5) 이후, 로컬에서 코드·모델을 갱신했을 때 서버에 반영하는 절차.
> **모델 가중치(수요 하이브리드·가스 v3·솔라)는 git 추적**이라 `git pull` 로 같이 온다(scp 불필요).
> DB 는 서버가 원본(cron 이 raw data 수집) — 서버에서 서빙 체인을 돌려 est_* 를 재생성한다.

**1) (로컬) push** — origin 이 뒤처져 있으면 먼저 push 해야 서버가 받는다.
```bash
git push origin main
```

**2) (서버) 코드 + 가중치 받기**
```bash
cd ~/project2026 && git pull
```

**3) (서버) 서빙 의존성 확인** — 수집 전용 venv 엔 없다(torch 가 핵심).
```bash
.venv/bin/python -c "import torch, lightgbm, pvlib; print('ok')"
# 실패하면:
.venv/bin/pip install -r "3. jeju_solarwind_forecaster/requirements.txt"
```

**4) (서버) crontab 갱신** — `deploy/crontab.example` 내용으로 교체(사용자명 확인).
폐기된 전국 줄(`run_collect_land.sh`)은 제거하고, 도시가스(06:50)·제주 신경로를 추가한다.

**5) (서버) raw data 신선도 확인 → 부족하면 손수집**
```bash
sqlite3 "1. data_fetcher_and_db/data/input_data_land.db" \
  "SELECT MAX(timestamp) FROM historical; SELECT MAX(base) FROM forecast_horizon;"
# 전국 실측·예보
deploy/run_collect_land_new.sh --historical-days 5
deploy/run_collect_forecast.sh --backfill 3
# 제주 예보
deploy/run_collect_forecast.sh --region jeju --backfill 3
# ★ 제주 historical 은 --backfill 을 쓰지 않는다.
#   collect_data_jeju.py 의 --backfill 은 forecast 단계에서 폐기된 run_backfill()
#   (2026-06-20 forecast 테이블 drop 후 RuntimeError)을 호출해 historical 에 닿기 전에 죽는다.
#   대신 기본 모드 + --no-forecast --historical-days N 으로 실측만 받는다(build() 의 미래 _da 가
#   필요하면 --no-forecast 를 빼면 된다 — build() 는 run_backfill 이 아니라 안전).
deploy/run_collect_jeju.sh --no-forecast --historical-days 10
```

**6) (서버) est_* 전구간 백필** — 신모델로 재생성(약 25분, 1회성). N 은 가용 base 보다 넉넉히.
```bash
deploy/run_serve_chain_land.sh --backfill 200
deploy/run_serve_citygas.sh    --backfill 200
deploy/run_serve_chain_jeju.sh --backfill 200
deploy/run_serve_smp_jeju.sh   --backfill 200
```

**7) (서버) streamlit 재시작**(상시 서비스면). 이후 일일 cron(전국 06:00·제주 06:30·SMP 06:40·도시가스 06:50)이 자동 갱신.
