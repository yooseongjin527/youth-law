# CLAUDE.md

> Claude Code가 매 세션 자동으로 읽는 프로젝트 규약. 4명이 각자 Claude를 돌려도 이 파일이 모두를 같은 규약에 세운다.
> 이 파일 규칙은 협상 불가. 위반 코드는 PR에서 막는다.

## 규약 계층 (공통 / 개인)
Claude Code는 여러 CLAUDE 파일을 **넓은 범위 → 좁은 범위 순으로 모두 이어붙여** 읽는다(겹치면 나중에 읽힌 개인 설정이 우선). 우리는 2계층을 쓴다:

| 계층 | 파일 | 공유 | 용도 |
|---|---|---|---|
| **공통** | `CLAUDE.md` (이 파일) | 팀 전체(git 커밋) | 협상 불가 규약 — 모두 동일 |
| **개인** | `CLAUDE.local.md` | 나만(`.gitignore`, 커밋 안 됨) | 내 담당 분야·자주 쓰는 명령·작업 메모 |

- 공통 규약(이 파일)은 **PR + 전원 합의**로만 수정. 개인 메모를 여기 넣지 말 것.
- 개인 설정은 `CLAUDE.local.md`에. **`CLAUDE.local.md.example`를 복사**해서 시작:
  ```bash
  cp CLAUDE.local.md.example CLAUDE.local.md   # 그 뒤 자유롭게 편집 (커밋 안 됨)
  ```
- 로드 확인은 세션에서 `/memory`. 두 파일이 목록에 보이면 정상.
- (선택) 모든 프로젝트 공통 개인 취향은 `~/.claude/CLAUDE.md`에 — 이 레포 밖.

## 프로젝트 개요
- 이름: 청년 생활법률 상담 AI
- 목적: 청년이 평어로 법률 고민을 물으면, 현행 법령 근거로 답하고 공식 연락처를 안내
- 아키텍처: Supervisor + 4 분야 전문가(labor/housing/consumer/finance) + Planner, LangGraph fan-out/fan-in
- 차별점: ① 현행 법령 근거+출처·시행일+환각방지 ② 검증된 공식 연락처 ③ 내용증명·진정서 초안 생성(행동 연결)
- 인원: 4명 / 기간: 6일

## 기술 스택 (버전 고정 — 옛 API로 짜지 말 것)
| 영역 | 도구 | 비고 |
|---|---|---|
| Orchestration | LangGraph >=0.2 | 조건부 엣지 + state 기반 라우팅(동적 리스트 반환) |
| LLM | Bedrock Claude | 모델 ID는 .env |
| 벡터DB/RAG | **Chroma (확정·구현됨)** | common/rag.py — 실구현 + 미설치 시 stub 폴백 |
| 임베딩 | **jhgan/ko-sroberta-multitask (확정)** | pipeline/gold.py·rag.py 공유 싱글톤 |
| 데이터 | 국가법령정보센터 API | open.law.go.kr OC 인증키 |
| 린트/포맷 | ruff | pyproject.toml 따름 |
| 웹서버 | FastAPI + uvicorn | app/api.py — Pydantic 스키마 필수 |
| UI | Streamlit(데모) + Jinja2(메인화면) | app/ui_streamlit.py, app/templates/ |
| 테스트 | pytest | 계약 테스트 필수 |
| 언어 | Python 3.11 | |

> ⚠️ LangGraph 라우팅: 이 프로젝트는 **add_conditional_edges + route()가 노드명 리스트 반환**(복수 분야 fan-out) 방식. 불확실하면 추측 말고 질문.

## 디렉터리 & 파일 소유권
```
state.py              # 공유 State (SPEC §2). 공용 ⚠️
graph.py              # 그래프 조립. 공용 ⚠️
common/rag.py         # 공통 RAG 헬퍼. 공용 ⚠️ (고도화는 여기서만)
common/contacts.py    # 검증 연락처. 공용 ⚠️ (환각 방지 데이터)
common/drafter.py     # 문서 초안 생성. 공용 ⚠️
agents/supervisor.py  # 분야 자동분류. 공용 ⚠️
agents/verifier.py    # 답변-근거 검증(하네스). 공용 ⚠️
agents/planner.py     # 종합+출처+연락처. 공용 ⚠️
common/llm.py         # Bedrock 호출+구조화출력 강제+사용량기록. 공용 ⚠️
common/cost.py        # 모델 티어링+비용 추적. 공용 ⚠️
scripts/evaluate.py   # 3축 스코어카드 (각자 자기 분야 실행)
app/service.py        # UI·API 공유 로직. 공용 ⚠️
app/api.py, schemas.py  # FastAPI. 공용 ⚠️ (UI 오너 주도)
app/templates/, static/, ui_streamlit.py  # 화면 — UI 오너 자유 수정
pipeline/             # medallion 파이프라인. config.py의 LAW_LIST만 동적, 나머지 공용 ⚠️
airflow/dags/         # 배치 DAG. 인프라 오너 관리
evals/<분야>.jsonl    # 평가셋 — 자기 분야는 담당자가 관리
agents/labor.py       # 담당 A 전용 (RAG + 문서초안 labor_draft)
agents/housing.py     # 담당 B 전용
agents/consumer.py    # 담당 C 전용
agents/finance.py     # 담당 D 전용
scripts/build_index.py  # 분야별 벡터DB 인덱싱 (각자 자기 컬렉션)
tests/test_contracts.py
```
- `agents/<분야>.py`는 담당자만 수정.
- ⚠️ 공용 파일(state/graph/rag/contacts/drafter/supervisor/planner)은 PR + 전원 합의 후 수정.

## 코딩 규약
- 타입 힌트 필수. State는 state.py의 TypedDict 사용.
- 노드 시그니처 통일: `def x_agent(state: LegalState) -> dict:` — 변경할 키만 담은 dict 반환.
- 전문가는 domain_answers에 자기 분야 1건만 append. 남의 분야 키 수정 금지.
- 전문가 간 직접 import 금지. 데이터는 State 경유.
- ★ 환각 방지 ★: 답변은 RAG로 검색된 조문 안에서만. 검색 안 된 내용 지어내기 금지.
- ★ 연락처 ★: 반드시 common/contacts.py의 get_contacts()에서. LLM이 전화번호 생성 절대 금지.
- 하드코딩 금지: 모델 ID/엔드포인트/키는 .env. 단, 검증 연락처는 contacts.py에 의도적 하드코딩.
- 네이밍: 함수/변수 snake_case, 클래스 PascalCase.

## 처음이라면
- 전체 구조·파일 역할은 docs/STRUCTURE.md 참조 (어디를 고칠지 색인 포함)

## Claude에게 작업 시킬 때
- 수정 전 docs/SPEC.md와 이 파일 확인. 계약 위반 안 하는지 검토.
- State 스키마/에이전트 I/O 바꿔야 하면 임의로 말고 먼저 알릴 것(SPEC PR 대상).
- 자기 담당 외 파일 수정 금지. 필요하면 알릴 것.
- LangGraph 버전 API 불확실하면 추측 말고 질문.
- 구현 후 계약 테스트 통과 확인.

## 커밋 / PR (일일 절차·체크포인트는 docs/TEAM_GUIDE.md)
- 커밋 전 pre-commit(ruff)이 포맷 자동 정리 — 스타일 신경 X.
- CI에서 pytest tests/ 통과해야 머지. 공용 파일 PR은 전원 승인.

### 브랜치 전략 (3계층: `main` ← `dev` ← `feat/*`)
- **`main` 직접 push 절대 금지.** 4명 누구도, 변경 규모와 무관하게 main에 직접 push하지 않는다. main은 항상 통합·검증 완료된 안정 브랜치다.
- **`dev`가 통합 브랜치.** 평소 개발은 전부 dev 위에서 모인다. 게이트는 변경 규모·공용 여부로 갈린다:
  - **소규모·비공용 → `dev` 직접 push 허용** (공용 파일 미포함 + 변경 5개 미만, **push 전 로컬 `pytest tests/` 통과** 필수).
  - **그 외 → `feat/*` → `dev` PR** (공용 포함 / 5개 이상 / SPEC 영향). 공용 포함은 전원 승인, 분야 전용만이면 담당자 승인.
- **`dev` → `main`은 릴리스/체크포인트 시점에만 PR로 승격.** main 반영 전 `pytest tests/`가 dev에서 통과한 상태여야 한다. ⚠️ **main 머지 PR은 전원 승인.**
- 흐름 요약:
  ```
  feat/<scope>-<주제>  ──PR──▶  dev  ──(릴리스 PR, 전원 승인)──▶  main
  ```
- **PR 규칙 (feat/* → dev):**
  - **push 전 로컬 `pytest tests/` 통과 필수.** 깨진 브랜치를 PR로 올리지 말 것.
  - Squash merge. 머지 후 브랜치 삭제. 길게 끌지 말고 자주 작게 머지(통합 지옥 방지).
  - ⚠️ **공용 파일(소유권 표의 ⚠️ 항목: state/graph/rag/contacts/drafter/supervisor/planner/llm/cost/pipeline …) 포함 PR은 전원 승인.** 분야 전용 파일만 바꾼 PR은 해당 담당자 승인으로 충분.
- **항상 최신 `dev` 기준**에서 시작: `git checkout dev && git pull --rebase origin dev` 후 `feat/*` 분기.
- 네이밍(브랜치 생성 시): **`<type>/<scope>-<주제>`** (kebab-case, 영문).
  - `<type>`: 커밋 type과 동일 (feat/fix/docs/refactor/test/chore).
  - `<scope>`: 분야(labor/housing/consumer/finance) 또는 모듈(pipeline/rag/graph/api…).
  - 예: `feat/consumer-rag`, `fix/pipeline-dedup`, `docs/team-convention`, `refactor/rag-hybrid`.
- **1 브랜치 = 1 관심사.** 분야 작업과 공용 파일 수정을 한 브랜치에 섞지 말 것(리뷰어가 다름).

### 커밋 규칙 (Conventional Commits + 한글 제목)
- 형식: **`<type>(<scope>): <한글 제목>`** — 제목은 명령형, 마침표 없이, ~50자 이내.
  - 예: `feat(consumer): 청약철회 RAG 답변 생성`
  - 예: `fix(pipeline): 조문가지번호 누락으로 인한 중복 id 수정`
- `<type>` 종류: `feat`(기능) `fix`(버그) `docs`(문서) `refactor`(동작불변 구조개선) `test`(테스트) `chore`(빌드·설정·잡일).
- `<scope>`: 분야명 또는 모듈명 (브랜치 scope와 일치시키면 추적 쉬움).
- **본문(왜)**: 무엇이 아니라 **왜** 바꿨는지. 한 줄 띄우고 작성. 사소한 변경은 생략 가능.
- **원자적 커밋**: 한 커밋엔 한 가지 논리적 변경만. 포맷/리팩터와 기능 변경을 섞지 말 것.
- ★ 계약/스키마 변경(State·에이전트 I/O)은 `docs(spec):` 커밋으로 **SPEC PR 먼저** (SPEC.md §0).

## 안전 (의료 아니지만 법률 도메인 주의)
- "법령 정보 안내"로 프레이밍. 단정적 법률 자문 금지 — 답변 끝에 전문가 상담 권유.
- 금융 분야는 투자 조언 아님, 법령 안내로 한정.
- 범위 밖(형사 등) 질문은 정직하게 거절(out_of_scope).

## 실수 축적 규칙 (하네스 — docs/HARNESS.md B-2)
누구의 Claude든 실수하면, 고치고 끝내지 말고 **그 실수를 방지하는 한 줄을
아래 섹션에 추가하는 PR을 같이 올린다.** 구조적 재발 방지.

## 자주 하는 실수 (하지 말 것)
- ❌ 검색 안 된 조문 지어내기 → ✅ RAG 결과 안에서만
- ❌ 연락처를 LLM이 생성 → ✅ contacts.py에서
- ❌ 출처/시행일 누락 → ✅ citation에 항상 포함(신뢰성 차별점)
- ❌ 다른 분야 결과 덮어쓰기 → ✅ 자기 분야 1건만
- ❌ 옛 LangGraph API 추측 → ✅ 불확실하면 질문
- ❌ 법령 API를 기본 UA·단발 호출 → ✅ User-Agent + 재시도 (gov API가 기본 파이썬 UA 거부·간헐 연결 리셋)
- ❌ 조문 청킹 시 가지번호(제43조의2)·전문(장 제목) 무시 → ✅ 가지번호 반영·전문 제외 (안 그러면 중복 id로 chromadb 적재 실패)
- ❌ 청킹 시 조문내용(헤더)만 본문으로 → ✅ 항·호·목 하위요소 본문도 합치기 (긴 조문은 조문내용에 "제17조(청약철회등)" 헤더만 와 본문이 빈 껍데기 됨)
- ❌ Chroma 컬렉션 기본 거리(L2)로 생성 → ✅ `hnsw:space=cosine` (문장 임베딩은 코사인; L2는 비정규화 벡터에서 score=1-dist가 음수 쓰레기값)
- ❌ (Windows) 스크립트 콘솔 인코딩 방치 → ✅ `PYTHONUTF8=1` (cp949에서 ✓ 등 출력 시 크래시)
- ❌ os.getenv 쓰면서 .env 로드 안 함 → ✅ 진입점(config.py)에서 load_dotenv 1회
