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

> **방향 정리(혼동 방지)**: 평소 **일일 수집 = 서버**(API 한도상 서버에서만, 서버 DB 가 원본). 반면 **모델·가중치를 바꿔 est_* 전체를 다시 만드는 재동기화 = 로컬**(무거운 백필을 약한 서버에서 못 돌리므로, 로컬에서 완성한 DB 를 서버로 올린다 — §8). 즉 raw 수집은 서버→로컬, 모델 갱신 반영은 로컬→서버.

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

## 7. 8단계 Streamlit 기동 (✅ 2026-06-24 검증)

같은 `~/project2026` clone 을 그대로 쓴다 (G-15: 자체 서버, 로컬 DB 실시간 읽기).

**① 의존성** (서빙 venv 에 추가 — pandas/numpy/torch 등은 이미 있음):
```bash
cd ~/project2026
.venv/bin/pip install streamlit plotly google-genai
```

**② 실행** — ★기존 사이트가 8501(streamlit 기본)을 점유 중이라 **다른 포트**를 쓴다:
```bash
.venv/bin/streamlit run "8. streamlit/app.py" --server.address 0.0.0.0 --server.port 8502 --server.headless true
```
- 접속 = `http://100.76.127.38:8502` (Tailscale). 방화벽 켜져 있으면 `sudo ufw allow 8502`.
- 끊어도 유지하려면 `nohup .venv/bin/streamlit run ... > ~/streamlit.log 2>&1 &` (종료 `pkill -f streamlit`), 정식 상시화는 systemd 유저 서비스.

**③ 필요 파일·주의**:
- 앱 데이터는 대부분 `input_data_*.db`(scp 됨). 단 **가스 단가 CSV `7. land_gas_forecaster/model/tab/7c_monthly_price_cost.csv` 는 gitignore(`*.csv`)라 `git pull` 로 안 온다 → scp 필요** (또는 운영 화면 단가 입력 기능으로 대체 예정). 지도 geojson 은 추적되는 `9. design/old design/skorea_provinces_simplified.json` 폴백을 쓰므로 OK.
- AI 브리핑(brief_ai)은 `.env` 의 `GEMINI_API_KEY` 필요. 없으면 경고만 뜨고 **앱은 정상 동작**.
- **4GB RAM**: 단순 조회·차트는 가볍지만 '운영 실행'(주문형 서빙)은 torch 를 로드해 무겁다 → 시연 땐 피한다(데이터는 cron 이 채운다).
- 남은 경고 `st.components.v1.html → st.iframe`(deprecation)은 동작 무관, 다음 세션 정리 예정.

서빙 사전적재는 일일 cron(전국 06:00·제주 06:30·SMP 06:40·도시가스 06:50)이 자동 갱신한다(§5·§8).
- 구체 절차는 8-B 진행 시 이 문서에 추가한다.

## 8. 모델·코드 갱신 시 서버 재동기화 (★ 2026-06-24 최신 — 이전 "서버 백필" 방식 대체)

> 초기 배포(§2~5) 이후, 로컬에서 코드·모델을 갱신했을 때 서버에 반영하는 절차.
>
> **역할 분담 (가장 중요)** — 서버 노트북은 사양이 약하다(i7·RAM 4GB) → **무거운 전구간 백필을 서버에서 돌리지 않는다.**
> - **수집·전구간 백필 = 전부 로컬에서** 끝내 완성된 `input_data_*.db` 를 만든다.
> - **서버는 받기만** 한다: 코드·가중치는 `git pull`, DB 는 `scp`. 이후 서버는 **가벼운 일일 cron(증분 수집 + 당일 서빙)만** 돈다.
>
> **무엇이 어떻게 가는가**
> - 코드 + **모델 가중치**(`*.pth`·LGBM `*.txt`·`*.json`) = **git 추적됨 → `git pull` 로 따라온다**(scp 불필요. 06-23 `16TH` 커밋으로 origin 에 push 완료).
> - `input_data_jeju.db`(~52MB)·`input_data_land.db`(~108MB) = **gitignore → `scp`**(또는 잠시 gitignore 제외 후 git. 단 DB 가 history 에 박히므로 **scp 권장**).
> - 최초 `git pull` 은 추적 가중치가 약 1.1GB 라 시간이 걸린다(이후 pull 은 증분이라 가볍다).

### 8.1 배포 이력 — ✅ 2026-06-24 일괄 배포 완료

> **2026-06-24 동기화 완료**: 로컬 push → 서버 `git pull`(코드·가중치) + `input_data_*.db` scp(서버 백필 대체) + 검증(est_horizon_land/jeju/smp 최신 base = 2026-06-23 확인, 서빙 의존성 ok). 사전에 로컬에서 수집·전구간 backfill 완료(제주 06-17·18 결측 복구 포함, 양 DB base 누락 0).

| 항목 | 출처 | 반영 경로 | 상태 |
|---|---|---|---|
| 문서 정리(§8 로그 분리·`docs/PROJECT_LOG2.md` 신설) | 06-24 | 커밋 + push → `git pull` | ✅ |
| 전국 수요 파인튜닝 하이브리드 가중치 | G-24(06-21) | `git pull`(`5.../demand_lt/weights/`·`calib_lt.json`) | ✅ |
| 전국 가스 v3(최근 원전 관성 피처) | G-25(06-21) | `git pull`(`lgbm_land_gas_v3.txt` + 서빙코드) | ✅ |
| 전국 신재생 장지평 LGBM(`_final`) | G-27(06-22) | `git pull`(`6.../model/models/` + 서빙코드) | ✅ |
| 전국 가스 기후값 블렌딩 OFF | G-28(06-22) | `git pull`(`gas_serving_calib.json` `blend_enabled:false` + 서빙코드) | ✅ |
| 제주 풍력 예보풍속 QM | G-29(06-23) | `git pull`(`wind_qm.json` + 서빙코드) | ✅ |
| 도시가스(10) 서빙 cron | G-26(06-21) | crontab(`run_serve_citygas.sh`, 06:50) | ✅ |
| 신모델 반영 `input_data_*.db` | 위 전부 | **scp**(서버 백필을 대체) | ✅ |
| 8단계 streamlit 서비스 기동 | 06-23 | 서버에서 `streamlit run`(§7 참조) | 🔶 진행 중(8-E) |

> 다음 갱신 시: 이 표를 비우고 새 "미반영 대기 목록"으로 다시 채운다(§0.4 로그 패턴처럼 한 시점의 대기 상태만 유지).

→ **코드·가중치 항목은 한 번의 `git pull` 로 전부 끝난다**(이미 push 됨). 실제로 손이 가는 건 **① 이번 세션 커밋·push ② DB scp ③ crontab 도시가스 줄 ④ streamlit 재시작** 넷뿐이다.

### 8.2 절차

**0) (로컬) 이번 세션 변경 커밋 + push**
```bash
git add -A
git commit -m "문서 정리: PROJECT.md §8 옛 로그 PROJECT_LOG2.md 이관 + DEPLOY 배포 대기 목록"
git push origin main
```

**1) (로컬) 수집·전구간 백필 최신 확인** — DB 가 신모델(G-24/25/27/28/29)로 채워졌는지 확인(06-22~23 백필 완료 상태 — 어긋나면 재백필). **서버가 아니라 로컬에서** 돈다.
```powershell
cd C:\Users\bjkim\Desktop\project2026
python "7. land_gas_forecaster\serve_chain_land_new.py" --backfill 200
python "10. citygas_forecaster\serve_citygas_daily.py"  --backfill 200
python "3. jeju_solarwind_forecaster\serve_chain_jeju_new.py" --backfill 200
python "4. jeju_smp_forecaster\serve_smp_horizon_jeju.py"     --backfill 200
```
(원천까지 최신화하려면 사용자 승인 하에 로컬 1회 수집. 제주 `--backfill` 함정은 §5 ★ 주석 참고 — 기본 모드 + `--no-forecast --historical-days N`.)

**2) (서버) 코드 + 가중치 받기**
```bash
cd ~/project2026 && git pull
.venv/bin/python -c "import torch, lightgbm, pvlib; print('ok')"   # 서빙 의존성(없으면 requirements 설치)
```

**3) (서버) 완성된 DB 받기 — 서버는 백필하지 않는다.** 로컬 DB 로 교체.
```powershell
# 로컬 Windows PowerShell — 홈에 올린 뒤 서버에서 mv(원격 경로 공백 회피)
scp ".\1. data_fetcher_and_db\data\input_data_jeju.db"  kimjourvanne@<서버IP>:~
scp ".\1. data_fetcher_and_db\data\input_data_land.db"  kimjourvanne@<서버IP>:~
```
```bash
# 서버 — cron 과 겹치지 않게(돌고 있으면 잠깐 멈췄다가) 교체
mv ~/input_data_*.db ~/project2026/"1. data_fetcher_and_db"/data/
```

**4) (서버) crontab 갱신** — `deploy/crontab.example` 내용으로 교체(사용자명 확인). **도시가스(06:50)·제주 신경로 포함, 폐기된 전국 줄 제거.**
```bash
crontab -e
```

**5) (서버) 동작 확인 — 무거운 백필이 아니라 당일 증분만.**
```bash
sqlite3 ~/project2026/"1. data_fetcher_and_db"/data/input_data_land.db \
  "SELECT MAX(base) FROM est_horizon_land; SELECT MAX(base) FROM est_horizon_citygas;"
```

**6) (서버) streamlit 재시작**(8단계를 상시 서비스로 띄운 경우). 이후 일일 cron(전국 06:00·제주 06:30·SMP 06:40·도시가스 06:50)이 자동 갱신한다. (streamlit 최초 배포 자체는 8-E 별도 작업.)

> ⚠️ 옛 방식과의 차이: 이전 §8 은 "서버에서 `run_serve_chain_*.sh --backfill` 로 est_* 재생성"이었으나, 서버 사양(4GB) 으로는 버겁다 → **전구간 백필은 로컬에서, 서버는 완성 DB 를 scp 로 받는다.** 서버 cron 의 일일 서빙은 당일 1개 base 만 더하므로 가볍다.

## 9. 8단계 외부 전송 API(serve_api) 기동 — 'AI 활용 확산성'

우리 예측 결과(시계열)와 AI 브리핑을 다른 시스템이 가져다 쓰도록 HTTP 로 노출하는 작은 API.
코드(`8. streamlit/serve_api.py`)는 완성·동작 확인됨(FastAPI). **streamlit 과 별개의 상시 데몬**이라
한 번 돌고 끝나는 다른 cron 작업과 띄우는 방식이 다르다. 전국(land)만 대상. DB만 읽고 수집은
절대 트리거하지 않는다(`use_live=False`).

**엔드포인트**: `GET /forecast`(예측 시계열) · `GET /brief`(AI 브리핑) · **`GET /bundle`(둘을 한 번에)** ·
`GET /briefings`(목록) · `GET /docs`(Swagger UI — 확산성 증거).

**① 의존성** (서빙 venv 에 추가 — streamlit/torch 등은 §7 에서 이미 설치됨):
```bash
cd ~/project2026
.venv/bin/pip install fastapi uvicorn
```

**② 기동** — 멱등 가드 wrapper 를 손으로 한 번 실행하면 백그라운드로 뜬다(끊어도 유지):
```bash
~/project2026/deploy/run_serve_api.sh
tail -20 ~/project2026/deploy/logs/serve_api_$(date +%Y%m).log   # "serve_api 기동(pid …)" 확인
```
- 포트 = **8800**(streamlit 8502 와 분리). 외부 접속하려면 방화벽을 연다: `sudo ufw allow 8800`.
- 접속(예, Tailscale): `http://100.76.127.38:8800/docs` · 묶음 호출 `…:8800/bundle?start=2026-06-26&days=1`.
- 포트를 바꾸려면 `SERVE_API_PORT=9000 ~/project2026/deploy/run_serve_api.sh`.

**③ 상시화(자동 복구)** — `crontab.example` ⑥ 줄(`*/5`)이 5분마다 가드를 호출한다: 떠 있으면 아무것도
안 하고, 재부팅·크래시로 꺼져 있으면 자동으로 되살린다. crontab 에 ⑥ 줄을 넣으면 ②는 부팅 후
자동으로도 뜬다(단, 최초 확인차 한 번은 손으로 ② 실행 권장).

**④ 종료/주의**:
- 종료 = `pkill -f 'uvicorn serve_api:app'`. (crontab ⑥ 줄이 켜져 있으면 5분 내 다시 뜨므로, 영구
  중지하려면 ⑥ 줄을 먼저 주석 처리한다.)
- `/brief`·`/bundle` 의 `generate=true` 는 Gemini 를 호출하므로 `.env` 의 `GEMINI_API_KEY` 가 필요
  (없으면 저장본만 반환). 기본 `generate=false` 는 DB 저장본만 읽어 키 없이도 동작.
- 인증 없음 + CORS 전체 허용(누구나 호출 가능) = 공개 전송이 목적이라 의도된 설정. 비공개가 필요하면
  방화벽(ufw)으로 접근 IP 를 제한한다.
- 4GB RAM: 이 API 는 DB 조회·직렬화뿐이라 가볍다(torch 로드 없음).
