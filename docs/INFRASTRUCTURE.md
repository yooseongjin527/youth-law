# INFRASTRUCTURE.md — 청년 생활법률 상담 AI 인프라 (통합본)

> 실제 구축·배포된 인프라의 **단일 기준 문서**. EC2 한 대에 FastAPI·Streamlit·Airflow를
> 올리고, RDS(PostgreSQL+pgvector)로 데이터·로그를 통합, HTTPS·관측까지 붙인 구성.
>
> 상세 절차/배경은 분리 문서 참조:
> - 단계별 구축 가이드: [INFRA_IMPLEMENTATION_GUIDE.md](INFRA_IMPLEMENTATION_GUIDE.md)
> - 운영 대시보드: [OPS_DASHBOARD_GUIDE.md](OPS_DASHBOARD_GUIDE.md)
> - HTTPS 셋업: [../infra/HTTPS_SETUP.md](../infra/HTTPS_SETUP.md)
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

  | domain | chunks |  | 합계 | 1,078 |
  |---|---|---|---|---|
  | consumer | 58 | | finance | 812 |
  | housing | 42 | | labor | 166 |

- 실검색 검증(stub 아님): `DomainRAG(RAG_BACKEND=pgvector).backend == "pgvector"`, `is_real == True`.
  예) "전세 보증금을 안 돌려줘요" → 주택임대차보호법 제10조의2(0.51)/제6조의3/제4조.
- ⚠️ **드라이버는 psycopg2**: `postgresql+psycopg2://…`. (Airflow가 SQLAlchemy 1.4 고정이라 psycopg3 다이얼렉트 없음 → 동거 venv에서 psycopg2 필수.)

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
- `pgvector`: RDS 통합 — 운영/데모. 같은 silver·같은 임베딩이라 검색 결과 동일.
- 둘 다 불가 시 `stub` 폴백(그래프·테스트 항상 동작). 명시적 pgvector 실패는 chroma로 안 넘어가고 stub.
- ⚠️ **pgvector connect_timeout 필수**: 없으면 도달 불가 DB에서 `engine.connect()`가 무한 대기 → 앱 부팅 행. `connect_args={"connect_timeout": 5}`로 빠른 실패+stub 폴백(common/rag.py).

## 6. RDS 로깅 (env `ENABLE_RDS_LOGGING`)
`ENABLE_RDS_LOGGING=true` + `DATABASE_URL` 둘 다 있을 때만 켜짐(기본 off, 미설정/실패 시 no-op — 상담을 절대 안 죽임). 테이블 3종:

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
| 도메인 | 백엔드 | 노출 |
|---|---|---|
| `https://youthlaw-demo.duckdns.org` | FastAPI :8000 | 공개 |
| `https://youthlaw-ops.duckdns.org` | Streamlit :8501 | **basic auth**(user `youthlaw`) |

- 단일 cert(SAN 2개), Let's Encrypt, `certbot.timer` 자동갱신, http→https 301.
- nginx 설정 템플릿: [`infra/nginx/youthlaw.conf`](../infra/nginx/youthlaw.conf), 절차: [`infra/HTTPS_SETUP.md`](../infra/HTTPS_SETUP.md).
- DuckDNS는 A레코드만 잘 되어 ACM(CNAME 검증)과 안 맞음 → ALB+ACM 대신 Certbot 채택 이유.

## 10. 배포·프로비저닝
- **IaC**: `infra/terraform/`(EC2·S3·RDS, `enable_rds` 게이트). `terraform apply`로 인스턴스 생성.
- **앱 프로비저닝**(현재 일부 수동): dev 클론 → venv → `.env` → `build_index.py all`(chroma) 또는 pgvector 적재 → systemd 등록 → nginx/certbot. 절차: [`infra/PROVISIONING.md`](../infra/PROVISIONING.md).
- 배포 방식은 **수동 배포**(CI/CD 자동 배포는 스트레치).
- ⚠️ Ubuntu 24.04엔 python3.11 없음 → **deadsnakes PPA**.

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
- 드라이버: `postgresql+psycopg2://`(psycopg3 아님 — airflow SQLAlchemy 1.4).
- LangSmith: AWS 엔드포인트 + `LANGSMITH_WORKSPACE_ID` 셋트 아니면 403. `list_runs` limit≤100.
- typing-extensions ≥4.14.1(airflow↔chromadb 공존).
- Ubuntu 24.04: python3.11은 deadsnakes.
- (Windows 로컬) 콘솔 인코딩 `PYTHONUTF8=1`.
- 로컬 .env ≠ EC2 .env: 로컬은 chroma·로깅 off·`youth-law-dev` 트레이싱(프로덕션 오염 방지). 자세한 건 `.env.example`.
