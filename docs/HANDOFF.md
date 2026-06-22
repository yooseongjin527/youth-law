# 프로젝트 인수인계 (새 채팅 시작용)

> 이 문서를 새 대화 맨 처음에 붙여넣으면 맥락을 그대로 이어갈 수 있습니다.
> 프로젝트의 "무엇을/왜/어떻게"를 한 장에 담았습니다.

---

## 한 줄 요약
청년이 평어로 생활 법률 고민을 입력하면, 시스템이 분야를 자동 판별해
4개 분야 전문 에이전트가 현행 법령을 RAG로 찾아 답하고 공식 연락처까지 안내하는 멀티에이전트 서비스.

## 프로젝트 조건
- 6일, 4명, AI 에이전트 부트캠프 final 프로젝트
- 학습 목표: 4명이 각자 벡터DB 구축 + RAG를 직접 해보는 것
- 스택: LangGraph + Bedrock Claude + Chroma/pgvector RAG + FastAPI/Jinja + Streamlit dashboard
- 협업: Claude Code 등으로 바이브 코딩, CLAUDE.md/SPEC.md로 계약 관리

## 도메인: 청년 생활법률 상담 (노동/주택/소비자/금융)
### 왜 이 도메인인가 (탄생 배경)
청년·사회초년생은 첫 전세·첫 알바·첫 계약에서 법적 문제를 가장 많이 겪지만,
변호사 상담은 비싸고 법령은 어렵다. 포털은 광고·낚시가 많고, 범용 AI는 출처 없이 답해 신뢰가 어렵다.
→ 정부 공식 법령을 근거로, 청년이 평어로 물으면 분야를 자동 판별해 답하는 무료 서비스.

### 왜 4분야가 노동/주택/소비자/금융인가
청년 빈출 + 4개가 모두 "비정형 법령 텍스트"라 4명이 동일 수준의 진짜 RAG를 함.
금융 분야는 채무조정(채무자회생법)·보이스피싱(통신사기피해환급법)·불법추심(채권추심법)으로 구성 — 청년이 '당하는 대응'뿐 아니라 '빚 해결책'까지 다룸.
(분야 라벨로 데이터를 쪼갠 게 아니라, 각 분야가 다른 법·다른 문서라 진짜 이질적)

### 검토했다가 버린 대안들 (다시 제안하지 말 것)
- 창업 정책 매칭: 8종이 다 같은 형식 공고라 RAG가 한 곳에만 belong, 4분할 억지
- 보조금/혜택: 정부24가 이미 함 (강한 경쟁자)
- 식품 성분 분석: 좋았으나 영양(수치)이 섞여 4명 다 RAG가 안 됨
- 질병청 건강정보: B(통계)·D(병원검색)가 RAG가 아니라 API 조회 → 4명 다 RAG 불가
- 영화/전시 추천: 범용 AI가 더 편함 (차별점 없음)
→ 결론: "4명 다 진짜 RAG + 4개 이질적 + 데이터 깔끔" 셋을 동시 만족하는 건 법률(분야 분할)

## 차별점 (범용 AI 대비 — 구조적으로 못 하는 것만)
1. **신뢰성**: 현행 법령(국가법령정보센터) 근거 + 답변에 출처·시행일 표시 + 환각 방지
   (범용 AI는 학습 시점에 갇혀 옛 법으로 답하고, 가짜 조문을 지어냄)
2. **행동 연결**: 답변에 분야별 검증된 공식 연락처·링크 첨부
   (연락처는 LLM 생성 금지, common/contacts.py 하드코딩 → 환각 0)
3. **문서 초안 생성**: 답변에서 끝나지 않고 내용증명·진정서 초안을 법령 근거 담아 생성
   (common/drafter.py, 빈칸 [   ]은 사용자가 채움, 항상 '초안' 명시 + 검토 권장)
- 개인화는 6일 현실상 제외함 (상황 입력받아 자격 매칭 → 욕심)

## 데이터 (공공 API·크롤링 0)
- 근거 조문·검색 코퍼스: 국가법령정보센터 API — 현행 법령 + 시행일
- ⚠️ Day0 전에 국가법령정보센터 OC 인증키 신청 (수동 승인 1~2일)

## 아키텍처 (현재 dev 기준)
- Supervisor가 질문을 4분야로 자동 분류 (사용자는 분야 선택 안 함)
- 1개 분야→전문가 1명 / 복수 분야→동시 실행(fan-out) / 범위 밖→정직하게 거절
- 전문가들 → **Verifier(답변-근거 검증, 하네스 — HARNESS.md)** → Planner 종합 + 출처·연락처 카드
  검증 탈락 답변은 사용자 도달 경로가 구조적으로 없음. 전부 탈락 시 정직 거절.
- 각 전문가는 자기 분야 별도 컬렉션(law_labor 등)으로 독립 RAG
- 공통 검색 인터페이스는 common/rag.py 하나로 통일. finance/labor는 하이브리드(BM25+임베딩+쿼리확장),
  housing/consumer는 현재 임베딩-only 게이트로 운용

## UX 결정사항
- 입력창 하나(분야 선택 체크박스 X). 자동 분류가 멀티에이전트의 핵심 기능이라 사용자에게 안 시킴
- 결과에 "이 질문을 [노동][주택]으로 분석함" 표시 → 자동 분류 시연
- 화면: Streamlit, 상단 자동분류 표시 + 분야별 카드(요약 + '자세히 보기' 펼침 상세) + 근거법령(조문 원문 인용 + 시행일 + 전문 링크) + 공식 연락처
- Planner가 final_answer(텍스트)와 answer_blocks(카드용 구조화)를 함께 반환 → 화면은 answer_blocks로 렌더링

## 현재 상태
- 최신 dev에 반영된 주요 축:
  · RAG: `common/rag.py`가 chroma/pgvector/stub 백엔드를 제공하고, finance/labor는 하이브리드 검색을 사용
  · 데이터 파이프라인: pipeline/ medallion (bronze→silver→gold) + 증분 감지 + Airflow @weekly DAG
  · 하네스: verifier 문장 단위 근거 검증, contacts 환각 차단, llm 구조화 출력 강제
  · 3축 루프: `scripts/evaluate.py` (검색 hit@k/MRR/recall, 비용, grounding) + 결과 이력/RDS 로깅
  · 웹서비스: FastAPI/Jinja 메인 화면, `/api/consult`, `/api/draft`, 멀티턴 질문 재작성, Streamlit ops dashboard
  · 인프라: EC2 + RDS(pgvector/logging) + S3 + Airflow + Nginx/HTTPS 통합 문서 `docs/INFRASTRUCTURE.md`
- 로컬 기준선: `ruff check .` 통과, `python -m pytest tests/ -q` 기준 **50 tests 통과**
- 다음 작업 축: ① 문서/CI/운영 절차 싱크 ② 인프라 재현성 보강 ③ 평가 수치 기반 RAG/라우팅 개선

## 3축 개선 루프
각자 자기 에이전트를 `python scripts/evaluate.py <분야>`로 측정하며 개선:
①평가(hit@k/MRR, evals/<분야>.jsonl 기준) ②비용(티어링+토큰 추적) ③환각(verifier grounding rate).
이력이 evals/results/에 날짜별 누적 → baseline vs 개선안 비교가 발표 자료.

## 함께 보는 문서
- STRUCTURE.md: 전체 구조·파일 역할 지도
- TEAM_GUIDE.md: 팀 협업 절차(Day0 킥오프~Day6) + 리스크 6가지와 해소 시점
- API_SETUP.md: 두 API 신청 절차
- .github/workflows/ci.yml: 계약 테스트 CI 동봉됨

## 새 채팅에서 가장 먼저 할 일
1. `git switch dev && git pull --ff-only origin dev`로 최신 기준선 맞추기
2. `python -m pytest tests/ -q`와 `ruff check .`로 로컬 기준선 확인
3. 작업이 공용 파일/5개 이상이면 `feat/*` 브랜치에서 `dev` PR로 진행
