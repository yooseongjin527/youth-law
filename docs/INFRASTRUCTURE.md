# INFRASTRUCTURE.md — 청년 생활법률 상담 AI 인프라 (통합본)

> 실제 구축·배포된 인프라의 **단일 기준 문서**. EC2 한 대에 FastAPI·Streamlit·Airflow를
> 올리고, RDS(PostgreSQL+pgvector)로 데이터·로그를 통합, HTTPS·관측까지 붙인 구성.
>
> 상세 절차/배경은 분리 문서 참조:
> - 단계별 구축 가이드: [INFRA_IMPLEMENTATION_GUIDE.md](INFRA_IMPLEMENTATION_GUIDE.md)
> - 운영 대시보드 구현: [`app/ui_dashboard.py`](../app/ui_dashboard.py)
> - 프로비저닝: [../infra/PROVISIONING.md](../infra/PROVISIONING.md)
> - Terraform: [../infra/terraform/README.md](../infra/terraform/README.md)

## 1. 아키텍처 한눈에

```
                 인터넷
                   │  HTTPS(443)
            ┌──────▼──────────────────────────────┐
            │  Nginx (리버스프록시 + Let's Encrypt) │
            │   youthlaw-demo  → :8000 (공개)       │
            │   youthlaw-ops   → :8501 (basic auth) │
            └──────┬───────────────┬───────────────┘
   EC2 t3.large    │               │           (us-west-2, Elastic IP 54.71.248.50)
   ┌───────────────▼──┐  ┌─────────▼────────┐  ┌──────────────────┐
   │ youth-law-api    │  │ youth-law-       │  │ youth-law-airflow│  systemd 3종
   │ FastAPI :8000    │  │ dashboard :8501  │  │ Airflow :8080    │
   └───────┬──────────┘  └───────┬──────────┘  └────────┬─────────┘
           │ Bedrock(IAM 롤)     │ read-only           │ 배치(증분 법령 갱신)
           ▼                     ▼                      ▼
   ┌────────────────────────────────────────────────────────────┐
   │ RDS PostgreSQL + pgvector   law_chunks(벡터) + 로그 3종       │
   └────────────────────────────────────────────────────────────┘
           ▲ S3(youth-law-artifacts-…) 산출물 백업 · LangSmith 트레이싱(AWS 인스턴스)
```

- **단일 인스턴스** 구성(ALB 없음) — 데모·비용 최소화. 확장 필요 시 ALB로 승격 가능.
- **개발/운영 분리**: 로컬 = Chroma(무서버), EC2 = pgvector(RDS 통합). `RAG_BACKEND` 스위치 하나로 동일 인터페이스.

## 2. 컴퓨트 — EC2

| 항목 | 값 |
|---|---|
| 인스턴스 | `i-0f0980060f2a4a403`, **t3.large**(2vCPU·8GB), Ubuntu 24.04 |
| 리전 | us-west-2 (오레곤) |
| 고정 IP | **Elastic IP 54.71.248.50** (stop/start해도 불변) |
| AWS 인증 | **IAM 인스턴스 롤** — Bedrock 호출에 키 불필요(.env에 키 없음) |
| 코드 | `/home/ubuntu/youth_law` (dev 클론), venv `.venv`, python3.11(deadsnakes) |
| 보안그룹 | `sg-046b56d0ab276bae0` |

## 3. 데이터·스토리지 — RDS + S3

### RDS PostgreSQL + pgvector
- 엔드포인트: `youth-law-postgres.c9u2s4ceo4cm.us-west-2.rds.amazonaws.com`
- pgvector **0.8.1**, 테이블 `law_chunks`(벡터=ko-sroberta **768차원**)
- 적재 현황(적재 증빙):

  | domain | chunks |  | 합계 | 1,212 |
  |---|---|---|---|---|
  | consumer | 192 | | finance | 812 |
  | housing | 42 | | labor | 166 |

- 실검색 검증(stub 아님): `DomainRAG(RAG_BACKEND=pgvector).backend == "pgvector"`, `is_real == True`.
  예) "전세 보증금을 안 돌려줘요" → 주택임대차보호법 제10조의2(0.51)/제6조의3/제4조.
- ⚠️ **드라이버는 psycopg3**: `postgresql+psycopg://…`. EC2 앱 venv는 `requirements-ec2.txt`의 `psycopg[binary]`를 설치한다. Airflow는 격리 venv에서 돌며, DAG가 앱 코드를 import할 때도 같은 URL 형식을 사용한다.

### S3
- 버킷 `youth-law-artifacts-363de80c` — `data/`·평가결과 산출물 백업/공유(`scripts/sync_data.py`, `ENABLE_S3_SYNC`).

## 4. 서비스 — systemd 3종

| 유닛 | 포트 | 내용 |
|---|---|---|
| `youth-law-api` | 8000 | FastAPI(상담 API + Jinja 메인) `uvicorn app.api:app` |
| `youth-law-dashboard` | 8501 | Streamlit 운영 대시보드 `app/ui_dashboard.py` |
| `youth-law-airflow` | 8080 | Airflow standalone(배치) |

- 유닛 파일: [`infra/systemd/`](../infra/systemd/), 프로비저닝 스크립트: [`infra/scripts/setup_airflow.sh`](../infra/scripts/setup_airflow.sh)
- 부팅 시 자동 기동. `.env`는 WorkingDirectory(`/home/ubuntu/youth_law`)의 파일을 load_dotenv로 로드.

## 5. RAG 백엔드 (env `RAG_BACKEND`)
- `chroma`(기본): 로컬 파일 벡터DB — 무서버·오프라인, 일상 개발/CI.
- `pgvector`: RDS 통합 — 운영/데모. 같은 silver·임베딩을 쓰되, 하이브리드 분야(finance·labor)는 pgvector에서도 BM25 인덱스를 law_chunks 코퍼스로 구축해 동일 검색기법을 적용한다(chroma와 같은 알고리즘).
- 둘 다 불가 시 `stub` 폴백(그래프·테스트 항상 동작). 명시적 pgvector 실패는 chroma로 안 넘어가고 stub.
- ⚠️ **pgvector connect_timeout 필수**: 없으면 도달 불가 DB에서 `engine.connect()`가 무한 대기 → 앱 부팅 행. `connect_args={"connect_timeout": 5}`로 빠른 실패+stub 폴백(common/rag.py).

## 6. RDS 로깅 (env `ENABLE_RDS_LOGGING`)
`ENABLE_RDS_LOGGING=true` + `DATABASE_URL` 둘 다 있을 때만 켜짐(기본 off, 미설정/실패 시 no-op — 상담을 절대 안 죽임). 테이블 3종:
PostgreSQL 연결에는 `connect_timeout=5`를 적용해 RDS 장애·보안그룹 문제 때 상담 응답이 오래 묶이지 않게 한다.

| 테이블 | 적재 지점 | 내용 |
|---|---|---|
| `consultation_logs` | service.consult | 질문·분야·범위·답변·검증리포트 |
| `llm_usage_logs` | cost.record | task·tier·토큰·비용 |
| `eval_scorecards` | evaluate.run | 분야별 hit@k·grounding |

스키마/초기화: `scripts/init_db.py`. 시각화: 운영 대시보드(아래 8).

## 7. 배치 — Airflow
- apache-airflow **2.10.5** standalone, **격리 venv** `/home/ubuntu/airflow-venv`(앱 venv와 분리).
- DAG: `airflow/dags/law_update_dag.py`(증분 법령 갱신). `airflow dags test`로 4분야+summary SUCCESS, "변경없음 스킵" 실증.
- ⚠️ typing-extensions 충돌: airflow constraints가 4.12.2로 낮춰 chromadb가 깨짐 → `typing-extensions>=4.14.1`로 복구(공존 확인).

## 8. 관측(Observability)
운영 대시보드(8501, Streamlit) 한 화면에서 **RDS(무엇이 저장됐나) + LangSmith(어떻게/얼마나 빨리 돌았나)** 를 본다.

### LangSmith 트레이싱 ★함정 주의★
- 이 계정은 **AWS 호스팅 인스턴스** — 기본 GCP 아님. 아래가 셋트(하나라도 빠지면 403):
  - `LANGSMITH_ENDPOINT` / `LANGCHAIN_ENDPOINT` = `https://aws.api.smith.langchain.com`
  - `LANGSMITH_API_KEY` = 서비스 키(`lsv2_sk_…`), `LANGCHAIN_API_KEY`도 같은 값
  - `LANGSMITH_WORKSPACE_ID` = `757cdc28-…` — **서비스 키엔 필수**(없으면 X-Tenant-Id 누락 → 403)
  - `LANGCHAIN_TRACING_V2=true`, `LANGCHAIN_PROJECT=youth-law`(로컬은 `youth-law-dev`로 분리)
- 구현: `common/llm.py`의 `@_traced`가 `call_bedrock`을 감쌈(raw boto3라 자동추적 안 잡혀 명시적 래핑). LangGraph 노드(supervisor/route/labor/verifier/planner) 아래로 `bedrock_call` LLM 스팬이 nesting.
- ⚠️ AWS 인스턴스 `list_runs` limit 상한 **100**(초과 시 400).

### 대시보드 섹션
① 운영 개요 ② 비용·토큰 ③ 품질(eval) ④ **실행 성능(LangSmith — 노드별 레이턴시·p50/p95·에러율)** ⑤ 최근 상담.

## 9. HTTPS (Nginx + Certbot + DuckDNS)
ALB 없이 Nginx 리버스프록시 + Let's Encrypt(Certbot). 단일 인스턴스·비용 최소화엔 이게 맞다.
**왜 ALB가 아닌가**: DuckDNS는 A레코드만 잘 되어 ACM(CNAME DNS검증)과 안 맞고, ALB는 상시 과금이라 stop/start 비용전략과 충돌.

| 도메인 | 백엔드 | 노출 |
|---|---|---|
| `https://youthlaw-demo.duckdns.org` | FastAPI :8000 | 공개 |
| `https://youthlaw-ops.duckdns.org` | Streamlit :8501 | **basic auth**(user `youthlaw`) |

### 9-1. DuckDNS (무료 서브도메인 2개)
duckdns.org 소셜 로그인 → 상단 **token** 복사(계정 1개=토큰 1개) → `youthlaw-demo`·`youthlaw-ops`
add domain → 각 **current ip**를 Elastic IP `54.71.248.50`으로 update. 확인: `nslookup youthlaw-demo.duckdns.org`.

### 9-2. 설치 + Nginx 설정
```bash
sudo apt-get install -y nginx certbot python3-certbot-nginx apache2-utils
sudo systemctl enable --now nginx
sudo htpasswd -c /etc/nginx/.htpasswd youthlaw   # ops 대시보드 비번(커밋 금지)
```
`/etc/nginx/sites-available/youthlaw` (certbot 적용 '전' 템플릿):
```nginx
# 상담(FastAPI :8000) — 공개
server {
    listen 80;
    server_name youthlaw-demo.duckdns.org;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
# 대시보드(Streamlit :8501) — basic auth + WebSocket(Streamlit 필수)
server {
    listen 80;
    server_name youthlaw-ops.duckdns.org;
    location / {
        auth_basic "youth-law ops";
        auth_basic_user_file /etc/nginx/.htpasswd;
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}
```
```bash
sudo ln -sf /etc/nginx/sites-available/youthlaw /etc/nginx/sites-enabled/youthlaw
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

### 9-3. 인증서 발급 (두 도메인 한 cert)
```bash
sudo certbot --nginx -d youthlaw-demo.duckdns.org -d youthlaw-ops.duckdns.org \
  --non-interactive --agree-tos -m <email> --redirect
```
certbot이 `listen 443 ssl`·인증서 경로·http→https 301 리다이렉트를 자동 주입. SAN 2개 단일 cert,
만료 90일, **`certbot.timer`가 자동갱신**.

### 9-4. 검증
```bash
curl -s -o /dev/null -w "%{http_code}\n" https://youthlaw-demo.duckdns.org/health     # 200
curl -s -o /dev/null -w "%{http_code}\n" https://youthlaw-ops.duckdns.org/            # 401(비번없음)
curl -s -u youthlaw:<pw> -o /dev/null -w "%{http_code}\n" https://youthlaw-ops.duckdns.org/  # 200
sudo certbot renew --dry-run        # 자동갱신 시뮬레이션 성공
```
- `/etc/nginx/.htpasswd`는 EC2 로컬·커밋 금지. 비번 변경: `sudo htpasswd /etc/nginx/.htpasswd youthlaw`.

## 10. 배포·프로비저닝
- **IaC**: `infra/terraform/`(EC2·S3·RDS, `enable_rds` 게이트). `terraform apply`로 인스턴스 생성.
- **앱 프로비저닝**(현재 일부 수동): dev 클론 → venv → `.env` → `build_index.py all`(chroma) 또는 pgvector 적재 → systemd 등록 → nginx/certbot. 절차: [`infra/PROVISIONING.md`](../infra/PROVISIONING.md).
- 배포 방식은 **수동 배포**(CI/CD 자동 배포는 스트레치).
- ⚠️ Ubuntu 24.04엔 python3.11 없음 → **deadsnakes PPA**.

### 10-1. 운영 런북 (수동 배포·검증·복구)

배포는 **dev fast-forward → 의존성 동기화 → DB 스키마 확인 → systemd 재시작 → 외부 검증** 순서로 한다.
작업 전 EC2의 로컬 변경이 있으면 중단하고 원인을 확인한다.

#### 실서버 재현성 검증 기준

외부 URL의 `/health`만 통과해도 Nginx/FastAPI는 살아 있는 것이지만, **실서버 재현성**을
증명하려면 EC2 SSH 세션에서 아래 항목을 한 번에 관통해야 한다. 이 체크가 통과해야
문서화한 런북이 실제 서버 상태와 맞는다고 볼 수 있다.

| 단계 | 명령/확인 | 통과 기준 |
|---|---|---|
| 코드 동기화 | `git status --short --branch`, `git merge --ff-only origin/dev` | 로컬 변경 없음, dev fast-forward 성공 |
| EC2 의존성 | `pip install -r requirements-ec2.txt` | `psycopg[binary]`, `sentence-transformers`, `rank-bm25`, `kiwipiepy` 설치 충돌 없음 |
| RDS 스키마 | `python scripts/init_db.py` | `consultation_logs`, `llm_usage_logs`, `eval_scorecards` 생성/확인 완료 |
| pgvector 실검색 | `RAG_BACKEND=pgvector python scripts/check_rag.py finance` | `실모드: True`, 조문수 > 0, 검색 결과가 stub 아님 |
| systemd | `sudo systemctl restart ...`, `status --no-pager` | `youth-law-api`, `youth-law-dashboard` 둘 다 active |
| 외부 API | `/health`, 대표 `/api/consult`, `scripts/e2e_smoke.py --base-url ...` | health ok, 상담 응답에 domains/answer_blocks/citations 존재, 4케이스 PASS |
| RDS 로그 | `consultation_logs order by id desc limit 5` | 방금 호출한 대표 상담 질문과 domains가 저장됨 |

로컬 노트북에서 확인할 수 있는 것은 외부 API 스모크까지다. `requirements-ec2.txt`,
`init_db.py`, `RAG_BACKEND=pgvector`, RDS 로그 조회는 RDS 보안그룹과 EC2 `.env`에
의존하므로 EC2 내부에서 직접 확인한다.

```bash
cd /home/ubuntu/youth_law
git status --short --branch
git fetch --prune origin
git merge --ff-only origin/dev

source .venv/bin/activate
pip install -r requirements-ec2.txt

# RDS 로깅 테이블 멱등 생성/확인. EC2 .env에는 DATABASE_URL이 있어야 한다.
python scripts/init_db.py
```

로컬 또는 임시 환경에서 같은 절차를 미리 읽어볼 때만 DATABASE_URL이 없으면 건너뛰는
래퍼를 사용한다.

```bash
python - <<'PY'
import os
from dotenv import load_dotenv
load_dotenv(".env")
if not os.getenv("DATABASE_URL"):
    print("DATABASE_URL 없음: init_db 생략")
    raise SystemExit(0)
from scripts.init_db import main
main()
PY
```

EC2에서는 이어서 서비스를 재시작한다.

```bash
sudo systemctl restart youth-law-api youth-law-dashboard
sudo systemctl status youth-law-api --no-pager
sudo systemctl status youth-law-dashboard --no-pager
```

배포 후 외부에서 최소 2가지를 확인한다.

```bash
curl -fsS https://youthlaw-demo.duckdns.org/health
curl -fsS https://youthlaw-demo.duckdns.org/api/consult \
  -H "Content-Type: application/json" \
  -d '{"question":"전세 보증금을 안 돌려줘요"}'
```

데모 직전에는 고정 E2E 스모크로 핵심 4케이스(단일 분야/복수 분야/범위 밖/초안)를
한 번에 확인한다.

```bash
python scripts/e2e_smoke.py --base-url https://youthlaw-demo.duckdns.org
```

pgvector 실검색 배포라면 RAG 백엔드도 직접 확인한다.

```bash
cd /home/ubuntu/youth_law
source .venv/bin/activate
RAG_BACKEND=pgvector python scripts/check_rag.py finance
```

RDS 로깅을 켠 배포라면 EC2에서 최근 상담 로그도 확인한다.

```bash
cd /home/ubuntu/youth_law
source .venv/bin/activate
python - <<'PY'
from dotenv import load_dotenv
load_dotenv(".env")
from sqlalchemy import text
from common.db import get_engine

engine = get_engine()
if engine is None:
    print("DATABASE_URL 없음: RDS 로그 확인 생략")
    raise SystemExit(0)
with engine.connect() as conn:
    rows = conn.execute(text(
        "select id, created_at, question, domains "
        "from consultation_logs order by id desc limit 5"
    )).fetchall()
for row in rows:
    print(row)
PY
```

문제가 있으면 최근 정상 커밋으로 임시 복구한다. 이 방식은 detached HEAD 복구라,
원인 수정 후에는 다시 `dev`로 돌아와 정상 PR/커밋으로 수습한다.

```bash
cd /home/ubuntu/youth_law
git log --oneline -5
git switch --detach <LAST_GOOD_COMMIT>
source .venv/bin/activate
pip install -r requirements-ec2.txt
sudo systemctl restart youth-law-api youth-law-dashboard
curl -fsS https://youthlaw-demo.duckdns.org/health

# 원인 수정이 dev에 반영된 뒤 정상 상태 복귀
git switch dev
git pull --ff-only origin dev
sudo systemctl restart youth-law-api youth-law-dashboard
```

비용 절감을 위해 서비스를 멈출 때는 **EC2/RDS 둘 다 stop**하고, 다시 켤 때는
**RDS available 확인 → EC2 start → systemd/health 확인** 순서로 한다.

```bash
aws rds stop-db-instance --db-instance-identifier youth-law-postgres --region us-west-2
aws ec2 stop-instances --instance-ids i-0f0980060f2a4a403 --region us-west-2

aws rds start-db-instance --db-instance-identifier youth-law-postgres --region us-west-2
aws rds wait db-instance-available --db-instance-identifier youth-law-postgres --region us-west-2
aws ec2 start-instances --instance-ids i-0f0980060f2a4a403 --region us-west-2
```

## 11. 보안 (SecurityGroup `sg-046b56d0ab276bae0`)
| 포트 | 용도 | 소스 |
|---|---|---|
| 80/443 | HTTP/HTTPS(nginx) | `0.0.0.0/0` (공개) |
| 22 | SSH | 내 IP |
| 8080 | Airflow UI | 내 IP |
| ~~8000/8501~~ | 직접 노출 | **제거됨**(nginx 443만 공개) |

- 대시보드는 RDS 로그가 보이므로 **basic auth**로 보호. IP 바뀌어도 안정.
- ⚠️ ISP가 공인 IP를 바꾸면 22/8080 막힘 → `aws ec2 authorize-security-group-ingress`로 현재 IP 추가(`curl https://checkip.amazonaws.com`).

## 12. 비용 관리
- 비용 드라이버는 EC2(t3.large)·RDS. **안 쓸 때 둘 다 stop**(EBS만 소액).
  ```bash
  aws ec2 stop-instances  --instance-ids i-0f0980060f2a4a403 --region us-west-2
  aws rds stop-db-instance --db-instance-identifier youth-law-postgres --region us-west-2
  ```
- ⚠️ stop 전 `RAG_BACKEND=chroma`로 바꿔 두면 다음 부팅 시 RDS 기동 지연에도 api가 행 안 걸림.
- 재시작은 **RDS 먼저(available 대기) → EC2**. RDS stop은 AWS가 최대 7일 후 자동 재시작.
- 계정에 budgets 권한 없음 → Cost Explorer로 모니터링.

## 13. 자주 밟는 함정 (요약)
- pgvector: `connect_timeout` 없으면 부팅 행 → 5초 빠른 실패.
- RDS 로깅: 저장 실패는 no-op이지만 연결 시도는 `connect_timeout=5`로 제한해야 API 응답 지연을 피한다.
- 드라이버: `postgresql+psycopg://` + `psycopg[binary]`(psycopg3 기준).
- LangSmith: AWS 엔드포인트 + `LANGSMITH_WORKSPACE_ID` 셋트 아니면 403. `list_runs` limit≤100.
- typing-extensions ≥4.14.1(airflow↔chromadb 공존).
- Ubuntu 24.04: python3.11은 deadsnakes.
- (Windows 로컬) 콘솔 인코딩 `PYTHONUTF8=1`.
- 로컬 .env ≠ EC2 .env: 로컬은 chroma·로깅 off·`youth-law-dev` 트레이싱(프로덕션 오염 방지). 자세한 건 `.env.example`.
