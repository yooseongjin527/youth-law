# TODO 보드

> 각 파일 상단 주석에 같은 TODO가 달려 있습니다. 여기는 전체 한눈에 보기용.
> **자기 분야 끝나면 [공용] 항목을 위에서부터 가져가세요.** (가져갈 때 PR로 "이거 제가 합니다" 공유)

## Day 0 (시작 전 — 상세 절차는 TEAM_GUIDE.md)
- [ ] 킥오프: 역할 4개(A/B/C/D) + 공용 리더 1명 확정
- [ ] 국가법령정보센터 API 신청 (수동 승인 1~2일): open.law.go.kr → OPEN API 신청 (목록+본문)
- [x] ~~GitHub 레포 + 브랜치 규칙 + CI~~ → 규약 정립(CLAUDE.md 브랜치·커밋·계층·직접push 정책), CI 동작 중
- [ ] pre-commit(ruff) 로컬 훅 설정 (CI는 동작 중)
- [ ] 4명 전원 로컬에서 graph.py + pytest(현재 50 tests) 통과 확인
- [ ] Bedrock 계정/리전/모델ID 결정 + invoke_model 1회 성공 (리스크 ④)

## 인프라 (오너 1명 — docs/INFRASTRUCTURE.md)
- [x] EC2 t3.large + RDS(pgvector/logging) + S3 + systemd 3종 + Nginx/HTTPS 구축 문서화
- [x] Airflow standalone + law_incremental_update DAG 활성화 절차 코드화
- [ ] 운영 런북 확정: 배포 전후 health check, RDS 로그 확인, rollback, stop/start 순서
- [ ] 인프라 재현성 점검: EC2 requirements와 DATABASE_URL 드라이버 표기 일치

## 데이터 파이프라인 (medallion — pipeline/)
- [x] ~~Day1: LAW_LIST 법령명 확정~~ → 8개 법령 전부 API 조회 성공 (현행 명칭 유효)
- [x] ~~Day1: bronze 샘플 → silver 태그(_CANDIDATES) 일치 확인~~ → 실응답과 일치 검증 완료
- [x] ~~Day1: 파이프라인 실동작 버그 수정~~ → load_dotenv 누락 / 법령API UA·재시도 / 조문가지번호·전문 중복id (3건 fix, PR #1)
- [x] ~~Day2: 4분야 전체 구축~~ → `build_index.py all` 완료 (labor166/housing42/consumer58/finance812). 증분 멱등성(2회차 스킵)도 확인
- [ ] Day2: evals로 hit@k 첫 측정 (stub 0.0 → 실검색 상승 확인) — 데이터 구축됐으니 evaluate만 돌리면 됨
- [ ] Day5: 증분 갱신 데모 시나리오 (manifest 시행일 임의로 낮춰 갱신 트리거 시연)

## 담당별 (자기 분야 — 병렬)
> 공통 0: **데이터 수집·인덱싱은 `build_index.py all`로 일괄 완료됨**(4분야 컬렉션 적재). 각 담당의 Day1 수집/Day2 인덱싱 항목은 이미 충족 — 바로 Day3(Bedrock 답변)부터 진행 가능.
> 공통 1: Day1~2에 각자 evals/<분야>.jsonl을 **10~20문항으로 확장** (형식·예시 3개 동봉됨)
> 공통 2: Day3부터 **매일 `python scripts/evaluate.py <분야>` 실행** — 3축(평가/비용/환각) 숫자 확인하며 개선. 이력이 자동 누적되어 발표 자료가 됨
### 담당 A (labor 노동) — agents/labor.py, scripts/build_index.py
- [ ] Day1: 노동 데이터 수집 (근로기준법·최저임금법) → load_corpus
- [ ] Day2: labor 컬렉션 인덱싱 (python scripts/build_index.py labor)
- [ ] Day3: Bedrock 답변 생성 (검색 조문 근거만, 환각 방지)
- [ ] Day3: 자기 분야 공식 연락처 확인·갱신 (contacts.py)
- [ ] Day4: 답변-근거 정합성 체크 + 문서초안(labor_draft) 점검

### 담당 B (housing 주택) — agents/housing.py
- [ ] Day1: 주택 데이터 수집 (주택임대차보호법)
- [ ] Day2: housing 컬렉션 인덱싱
- [ ] Day3: Bedrock 답변 생성 + 연락처 확인
- [ ] Day4: 정합성 체크 + 문서초안 점검

### 담당 C (consumer 소비자) — agents/consumer.py
- [ ] Day1: 소비자 데이터 수집 (전자상거래소비자보호법)
- [ ] Day2: consumer 컬렉션 인덱싱
- [ ] Day3: Bedrock 답변 생성 + 연락처 확인
- [ ] Day4: 정합성 체크 + 문서초안 점검

### 담당 D (finance 금융·채무) — agents/finance.py
- [ ] Day1: 데이터 수집 — 채무자회생법 + 통신사기피해환급법 + 채권추심법 + 대부업법
- [ ] Day2: finance 컬렉션 인덱싱
- [ ] Day3: Bedrock 답변 생성 (채무조정·보이스피싱·불법추심) + 연락처 확인
- [ ] Day4: 정합성 체크 + 문서초안 점검

## 공용 (자기 분야 끝낸 사람이 가져감 — 위에서부터 우선순위)
### common/rag.py — RAG 엔진 (가장 중요, 끝나면 1순위)
- [x] ~~벡터DB/임베딩 택1~~ → 확정·구현 완료 (Chroma + ko-sroberta, stub 폴백 포함)
- [x] ~~백엔드 연결·index·search 구현~~ → 완료 (검색=rag.py, 적재=pipeline/gold.py)
- [x] ~~Day1: 법령 API 샘플 호출 — silver 파싱 태그 일치 확인 (리스크 ②)~~ → 완료
- [x] ~~Day1~2: `build_index.py all` 실데이터 구축~~ → 4분야 구축·실검색(is_real=True) 확인. EC2 구축만 남음
- [x] ~~후속: RAG score 정규화~~ → Chroma 컬렉션을 `hnsw:space=cosine`으로 재생성
- [x] ~~Day5: 하이브리드 검색(BM25+임베딩)으로 고도화~~ → finance/labor는 common/rag.py에서 하이브리드 게이트 적용
- [ ] 후속: housing/consumer 하이브리드·동의어 확장 여부를 holdout/evaluate로 결정
- [ ] Day5: 리랭킹(cross-encoder) 추가
- [ ] Day5: 4분야 검색 품질 비교 측정 (발표 지표)

### agents/supervisor.py — 분야 자동 분류
- [x] ~~Day3: 키워드 → Bedrock few-shot 분류로 교체~~ → 실패 시 키워드 백스톱 유지
- [ ] Day4: 모호한 질문 confidence 처리
- [x] ~~Day5: 분류 정확도 평가셋/스크립트~~ → `scripts/eval_routing.py`

### agents/verifier.py — 답변-근거 검증 (하네스 핵심, HARNESS.md)
- [x] ~~Day4: _is_grounded 1차 구현~~ → 인용/snippet 구조 가드
- [x] ~~Day4: 2차 — Bedrock "주장-조문 근거 판정"~~ → 문장 단위 ungrounded 판정
- [x] ~~Day5: 문장 단위 검증 세분화~~ → 환각 문장 제거 후 통과/전부 환각이면 탈락
- [ ] Day5: verification_report → "환각 차단 N건" 발표 지표화

### common/llm.py — Bedrock 호출 + 구조화 출력 강제
- [x] ~~Day3: call_bedrock 구현~~ → boto3 Bedrock 호출 + task별 모델 티어
- [x] ~~Day3: 전문가들이 call_bedrock_json으로 형식 강제~~ → supervisor/answer/verifier 경로 적용

### agents/planner.py — 종합 (조문 원문 + 연락처)
- [ ] Day3: 각 분야 answer를 Bedrock으로 (요약 + 상세 분리)
- [ ] Day4: 답변-근거 정합성 검증 (snippet에 없는 주장 제거)
- [ ] Day5: 복수 분야 우선순위/연결 안내

### common/drafter.py — 문서 초안 생성 (매력 기능)
- [ ] Day4: make_draft 본문을 Bedrock으로 (검색 조문 근거만)
- [ ] Day4: 분야별 문서 양식 정교화 (내용증명/진정서/지급정지신청 차이)
- [ ] Day5: 사용자 입력값 빈칸 [   ] 채우기 UX

### common/cost.py + scripts/evaluate.py — 3축 개선 루프
- [ ] Day3: cost.py 모델 ID·단가를 실제 값으로 (.env)
- [x] ~~Day3: llm.py call_bedrock에 usage 기록 연결~~ → tracker.record + RDS no-op 로깅 연결
- [ ] Day5: "Supervisor Haiku 전환 절감률" + "단순검색 vs 하이브리드 hit@k" 비교표 (발표)

### common/contacts.py — 연락처
- [ ] Day1~3: 각자 자기 분야 연락처 공식 사이트에서 확인·갱신
- [ ] Day4: 상황별 세부 연락처 분기

### graph.py — 파이프라인 / 관측성
- [x] ~~Day2: LangSmith 트레이싱 켜기~~ → raw Bedrock 호출을 common/llm.py에서 명시 traceable 래핑
- [ ] Day5: 응답시간 측정 (LangSmith 트레이스에서 노드별 지연 확인)

### app/ — 웹서비스·UI (골격 구현 완료 — 동작함)
- [x] ~~Streamlit 빈 화면~~ → **UI 골격 구현됨** (ui_streamlit.py: 카드+펼침+초안+검증리포트)
- [x] ~~서버~~ → **FastAPI 구현됨** (api.py: /api/consult·/api/draft·Jinja 메인화면·/docs)
- [ ] Day4: 실데이터로 UI 동작 확인 (`uvicorn app.api:app` / `streamlit run app/ui_streamlit.py` / `streamlit run app/ui_dashboard.py`)
- [ ] Day6: 화면 다듬기 — style.css·문구·로딩 표시 + LangGraph .stream()으로 진행상황 표시(선택)
- [x] ~~Day6: 데모 시나리오 4개 리허설~~ → `scripts/e2e_smoke.py`로 단일/복수/범위밖/초안 스모크 고정
- [ ] Day6: 데모 시나리오 준비 (단일/복수/범위밖/문서초안 4케이스) + 발표자료
