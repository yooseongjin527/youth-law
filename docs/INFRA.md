# INFRA.md — AWS EC2 인프라 셋업 (예산 $120)

> EC2 한 대에 벡터DB(Chroma) + Airflow + Streamlit을 올리는 단순 구성.
> 6일 프로젝트 + 발표 후 한 달 유지를 $120 안에서.

## 1. 비용 설계 (us-west-2 오레곤, 온디맨드 기준)

> 팀 리전은 **us-west-2(오레곤)** 로 고정(.env.example). 아래 금액은 서울 기준의 보수적 추정으로,
> 오레곤은 대체로 비슷하거나 약간 낮아 $120 예산은 그대로 유효.


| 항목 | 사양/가정 | 월 비용(상시) | 비고 |
|---|---|---|---|
| EC2 t3.large | 2vCPU·8GB | ~$75 | 임베딩+Airflow+Chroma 여유 |
| EC2 t3.medium | 2vCPU·4GB | ~$38 | 가능하지만 임베딩 시 메모리 빠듯 |
| EBS gp3 30GB | 루트 볼륨 | ~$3 | |
| Bedrock | 개발+데모 6일 | $10~20 | Haiku 분류 + Sonnet 답변 (티어링) |
| LangSmith | 무료 플랜 | $0 | |
| **합계 (t3.large 상시 1개월)** | | **~$98** | 예산 내 |

### 예산 지키는 운영 수칙
- **안 쓸 때 인스턴스 stop** (정지 중엔 EBS $3만 과금) — 개발은 주로 로컬, EC2는 파이프라인·데모용
- 권장 패턴: **t3.large + 작업시간만 가동** → 6일 풀가동해도 ~$15, 이후 주1회 배치만 돌리면 월 $5 미만
- Bedrock 비용은 common/cost.py 티어링 + scripts/evaluate.py 로 추적
- 예산 알림: AWS Budgets에서 $100 알림 걸어두기 (5분 작업)

## 2. EC2 생성 (콘솔 기준 — ★동적 내용: 본인 계정에서★)

1. EC2 → 인스턴스 시작
   - AMI: Ubuntu 24.04 LTS
   - 인스턴스: t3.large (또는 t3.medium)
   - 키페어: 새로 생성 (.pem 보관)
   - 스토리지: gp3 30GB
2. 보안 그룹 인바운드:
   | 포트 | 용도 | 소스 |
   |---|---|---|
   | 22 | SSH | 내 IP |
   | 8080 | Airflow UI | 내 IP (팀 IP들) |
   | 8000 | FastAPI (웹화면+API) | 내 IP → 발표 때만 0.0.0.0/0 |
   | 8501 | Streamlit 데모 | 내 IP → 발표 때만 0.0.0.0/0 |
3. 탄력적 IP는 선택 (stop/start 시 IP 바뀌는 게 불편하면 할당 — 가동 중 무료)

## 3. 서버 셋업 (SSH 접속 후 — 복붙 가능)

```bash
# 기본 도구 + Python 3.11
sudo apt update && sudo apt install -y python3.11 python3.11-venv git
git clone <팀 레포 URL> && cd youth_law

# 가상환경 + 의존성
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install chromadb sentence-transformers   # 무거워서 requirements와 분리 가능

# 환경변수
cp .env.example .env && nano .env   # ★동적 내용: 키 채우기★
export $(grep -v '^#' .env | xargs) # 또는 python-dotenv 사용

# 최초 전체 구축 (bronze→silver→gold, 분야당 수 분)
python scripts/build_index.py all

# 동작 확인
python graph.py
python scripts/evaluate.py all
```

## 4. 배치 — 두 가지 길 (기본 cron, 발표용 Airflow)

### 4-a. cron (가볍고 충분 — 기본값)
```bash
crontab -e
# 매주 월요일 06:00 증분 갱신 + 로그
0 6 * * 1 cd /home/ubuntu/youth_law && .venv/bin/python scripts/update_laws.py >> logs/update.log 2>&1
```

### 4-b. Airflow (DE 포트폴리오 스토리 — 여유 시)
```bash
pip install "apache-airflow==2.10.*" --constraint \
  "https://raw.githubusercontent.com/apache/airflow/constraints-2.10.0/constraints-3.11.txt"

# dags 폴더를 프로젝트의 airflow/dags 로 지정
export AIRFLOW_HOME=~/airflow
airflow config 가 생성된 뒤 airflow.cfg 에서:
  dags_folder = /home/ubuntu/youth_law/airflow/dags
# 프로젝트 모듈 import 되도록
echo 'export PYTHONPATH=/home/ubuntu/youth_law' >> ~/.bashrc && source ~/.bashrc

airflow standalone   # 데모용 단일 프로세스 (UI: http://<EC2-IP>:8080)
# DAG: law_incremental_update (@weekly) 활성화
```
⚠️ Airflow는 메모리를 먹는다 — t3.medium이면 cron을 권장, t3.large면 Airflow 가능.

## 5. 운영 체크
- [ ] AWS Budgets $100 알림 설정
- [ ] manifest 확인: `cat data/manifest.json` (법령별 시행일 기록)
- [ ] 증분 동작 확인: `python scripts/update_laws.py` 2회 연속 실행
      → 2회차는 전부 "변경 없음 — 스킵" 이어야 정상
- [ ] 웹서비스: `uvicorn app.api:app --host 0.0.0.0 --port 8000` (메인화면 + /docs)
- [ ] 발표 데모: `streamlit run app/ui_streamlit.py --server.port 8501` (Day 6)

## 책임 분담 제안
인프라(EC2·cron/Airflow)는 1명이 오너 (CI/CD 경험자 추천),
나머지는 로컬 개발 → 레포 push → EC2에서 pull + 배치 확인.
