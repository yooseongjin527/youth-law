# STRUCTURE.md — 프로젝트 구조 & 파일 역할 가이드

> 팀원 누구나 "이 파일이 뭐고, 안에서 무슨 일을 하는지" 한눈에 파악하기 위한 지도.
> 처음 합류했거나, 어디를 고쳐야 할지 막힐 때 여기부터 본다.

## 전체 구조

```
youth_law/
├── .github/workflows/
│   └── ci.yml             # PR마다 ruff + 계약 테스트 자동 실행
│
├── agents/                # 에이전트 노드들
│   ├── __init__.py        #  패키지 표시(빈 파일) — import 가능하게
│   ├── consumer.py        #  [담당 C] 소비자
│   ├── finance.py         #  [담당 D] 금융·채무
│   ├── housing.py         #  [담당 B] 주택
│   ├── labor.py           #  [담당 A] 노동 — RAG 답변 + 문서초안
│   ├── planner.py         #  [공용] 검증 통과분 종합 + 출처·연락처
│   ├── supervisor.py      #  [공용] 질문을 4분야로 자동 분류·라우팅
│   └── verifier.py        #  [공용] 답변-근거 검증 (하네스: 환각 차단)
│
├── app/                   # 웹서비스 레이어 (FastAPI + Streamlit)
│   ├── static/
│   │   └── style.css      #  메인 화면 스타일 (Day6에 다듬기)
│   ├── templates/         #  Jinja2 템플릿 — 페이지 추가 시 base.html 상속
│   │   ├── base.html      #   공통 레이아웃 (헤더·푸터·면책)
│   │   └── index.html     #   메인 화면 — 질문 폼 + 결과 카드 (JS fetch)
│   ├── __init__.py        #  패키지 표시(빈 파일)
│   ├── api.py             #  FastAPI 서버 — /api/consult·/api/draft·메인페이지·/docs
│   ├── schemas.py         #  Pydantic 요청/응답 모델 (SPEC 대응)
│   ├── service.py         #  ★공유 로직★ 그래프 싱글톤 + consult()/draft() — API·Streamlit 공용
│   └── ui_streamlit.py    #  Streamlit 데모 UI (카드+펼침+초안, 발표용)
│
├── airflow/dags/
│   └── law_update_dag.py  # 주1회 증분 갱신 DAG (EC2 Airflow용, INFRA.md)
│
├── common/                # 공용 헬퍼 (4명이 공유, 변경은 PR+전원합의)
│   ├── __init__.py        #  패키지 표시(빈 파일)
│   ├── contacts.py        #  검증된 공식 연락처 (LLM 생성 금지, 환각 0)
│   ├── cost.py            #  모델 티어링 + 토큰·비용 추적
│   ├── drafter.py         #  내용증명·진정서 초안 생성
│   ├── llm.py             #  Bedrock 호출 + 구조화 출력 강제 + 사용량 기록
│   └── rag.py             #  검색 엔진(Chroma 실구현, 미설치 시 stub 폴백) + Day5 고도화
│
├── data/                  # (런타임 생성, 깃 제외) bronze/silver·chroma 벡터DB·manifest.json
│
├── docs/                  # 가이드 모음 (특정 시점에 한 번 읽는 문서)
│   ├── API_SETUP.md       #  데이터 API 인증키 신청 절차
│   ├── HANDOFF.md         #  새 채팅에 맥락 이어주는 인수인계
│   ├── HARNESS.md         #  하네스 엔지니어링 적용 내역
│   ├── INFRA.md           #  EC2 셋업 + $120 예산 설계 + cron/Airflow 배치
│   ├── SPEC.md            #  ★최우선 계약★ State·에이전트 I/O (코드보다 우선)
│   ├── STRUCTURE.md       #  (이 파일) 구조·파일 역할 지도
│   ├── TEAM_GUIDE.md      #  협업 절차 (Day0 킥오프~Day6, 일일 리듬)
│   └── TODO.md            #  작업 보드 (담당별/공용, Day별)
│
├── evals/                 # 평가셋
│   ├── results/           #  evaluate.py 실행 이력 (날짜별 누적 → 발표 자료)
│   │   └── .gitkeep       #   빈 폴더를 깃이 유지하게 하는 표시 파일
│   ├── consumer.jsonl     #  [담당 C] 소비자 평가셋
│   ├── finance.jsonl      #  [담당 D] 금융 평가셋
│   ├── housing.jsonl      #  [담당 B] 주택 평가셋
│   ├── labor.jsonl        #  [담당 A] 노동 평가셋 (각자 10~20개로 확장)
│   └── README.md          #  평가셋 작성법 (형식·예시)
│
├── pipeline/              # 데이터 파이프라인 (medallion)
│   ├── __init__.py        #  패키지 표시(빈 파일)
│   ├── bronze.py          #  [Bronze] 법령 API 수집 → 원본 XML 저장
│   ├── config.py          #  ★동적 내용★ 분야별 법령 목록 LAW_LIST (팀이 채움)
│   ├── detect.py          #  증분 감지 — manifest 시행일 비교, 변경분만 갱신
│   ├── gold.py            #  [Gold] 임베딩 → Chroma 컬렉션 upsert
│   └── silver.py          #  [Silver] 조문 단위 청킹 + 메타데이터(시행일·출처)
│
├── scripts/               # 실행 스크립트
│   ├── __init__.py        #  패키지 표시(빈 파일)
│   ├── build_index.py     #  최초 전체 구축 (pipeline 위임: bronze→silver→gold)
│   ├── evaluate.py        #  3축 스코어카드 (평가/환각/비용) + 이력 누적
│   └── update_laws.py     #  증분 배치 진입점 — cron/Airflow가 호출
│
├── tests/
│   └── test_contracts.py  # 계약 테스트 — CI에서 매 PR 자동 실행
│
├── .env.example           # 환경변수 템플릿 (cp .env.example .env)
├── .gitignore             # 깃 제외 목록 (.env, __pycache__, data/ 등)
├── CLAUDE.md              # ★루트 고정★ Claude Code가 자동으로 읽는 작업 규약
├── graph.py               # 그래프 조립 — 노드를 연결해 전체 흐름을 만듦
├── pyproject.toml         # ruff(린트·포맷) 설정
├── README.md              # 프로젝트 입구 — 개요·실행법·6일 배분
├── requirements.txt       # 의존성 목록 (langgraph, boto3, langsmith 등)
└── state.py               # ★계약의 코드★ 모든 에이전트가 주고받는 State 스키마
```

> `__init__.py`는 파이썬에서 그 폴더를 "패키지"로 인식시켜 `from agents.labor import ...`
> 같은 import가 되게 하는 빈 파일이다. 내용은 없어도 있어야 한다.

## 데이터 흐름 (질문 → 답변)

```
사용자 질문 (평어, 분야 선택 안 함)
   │
   ▼ supervisor.py    질문을 읽고 4분야 중 해당 분야 자동 판별
   │                  (1개 / 복수 / 범위밖)
   ▼ labor/housing/…  해당 분야 전문가가 common/rag.py로 자기 컬렉션 검색
   │  (fan-out)       → 조문 근거로 답변(llm.py) + 연락처(contacts.py) + 초안(drafter.py)
   ▼ verifier.py      답변이 검색된 조문에 근거하는지 검증 → 탈락분 차단
   │                  (검증 안 된 답변은 사용자에게 도달 경로 없음)
   ▼ planner.py       검증 통과분만 종합 → final_answer + answer_blocks(화면 카드용)
   │
   ▼ 답변 + 조문 원문·시행일 + 공식 연락처 + (선택)문서초안
```

State(state.py)가 이 흐름을 관통하며 각 노드가 자기 몫만 채운다.

## "○○을 고치려면 어디?" 빠른 색인

| 하고 싶은 것 | 파일 |
|---|---|
| 새 분야/State 필드 추가 | docs/SPEC.md 먼저(PR) → state.py |
| 내 분야 답변 품질 개선 | agents/<내분야>.py (자기 것만) |
| 검색 정확도 개선 (4분야 공통) | common/rag.py (공용, 선언 후) |
| 연락처 번호 수정 | common/contacts.py |
| 분류 정확도 개선 | agents/supervisor.py |
| 환각 검증 강화 | agents/verifier.py |
| 비용/모델 티어 조정 | common/cost.py |
| 문서초안 양식 | common/drafter.py |
| 평가 질문 추가 | evals/<내분야>.jsonl |
| 내 분야 성적 확인 | python scripts/evaluate.py <분야> |
| 트레이싱 보기 | .env에 LANGSMITH 설정 → smith.langchain.com |
| API 엔드포인트 추가/수정 | app/api.py + app/schemas.py |
| 메인 화면(웹) 수정 | app/templates/index.html + app/static/style.css |
| Streamlit 데모 수정 | app/ui_streamlit.py |
| UI·API 공통 로직 | app/service.py |
| 수집 법령 추가/변경 | pipeline/config.py 의 LAW_LIST |
| 청킹 방식 수정 | pipeline/silver.py |
| 배치 주기 변경 | crontab 또는 airflow/dags/law_update_dag.py |
| EC2·비용 | docs/INFRA.md |
| 의존성 추가 | requirements.txt |
| 린트·포맷 규칙 | pyproject.toml |
| 깃 제외 항목 | .gitignore |
| 환경변수(키 등) | .env.example 복사해서 .env |

## 소유권 규칙 (충돌 방지)

- **[담당]** agents/<분야>.py, evals/<분야>.jsonl → 담당자만 수정
- **[공용]** state / graph / common/* / supervisor / verifier / planner →
  PR + 전원 합의. 작업 전 스탠드업에서 "오늘 제가 잡습니다" 선언
- 자세한 규약: CLAUDE.md / 계약: docs/SPEC.md / 절차: docs/TEAM_GUIDE.md

## 읽는 순서 (신규 합류자)
1. README.md — 뭘 만드는지
2. docs/STRUCTURE.md (이 파일) — 어디에 뭐가 있는지
3. docs/SPEC.md — 지켜야 할 계약
4. CLAUDE.md — 작업 규칙
5. docs/TEAM_GUIDE.md — 언제 뭘 하는지
6. 자기 분야 agents/<분야>.py 의 TODO 주석
