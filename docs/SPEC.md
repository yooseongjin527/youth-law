# SPEC.md — 청년 생활법률 상담 AI

> 코드보다 우선하는 단일 계약. State/에이전트 I/O 변경은 코드 전에 이 문서 PR → 4인 합의.
> 바이브 코딩 시 LLM에게 이 파일을 항상 컨텍스트로 전달.

## 0. 합의 규칙 (양보 불가)
- State 스키마(§2)·에이전트 I/O(§3)는 이 문서가 진실의 원천.
- 변경 순서: SPEC.md PR → 4인 리뷰 → merge → 구현. 역순 금지.
- 자기 분야 전문가 내부는 자유. 단 DomainAnswer 계약은 4명 모두 동일하게 지킨다.

## 1. 서비스 개요 & 차별점
청년이 생활 법률 문제를 평어로 입력하면(분야 선택 X), 시스템이 분야를 자동 판별해
해당 전문가가 답한다. 범용 AI 대비 차별점 2가지:
- **신뢰성**: 현행 법령(국가법령정보센터)을 근거로, 답변에 출처·시행일 표시. 환각 방지(검색 조문 밖 내용 금지).
- **행동 연결**: 답변에 분야별 공식 연락처·링크 첨부. 연락처는 LLM 생성 금지, 검증 데이터에서만(환각 0).

## 2. 그래프 (fan-out / fan-in)
```
   user_query (평어, 분야 미선택)
        │
        ▼
   ┌──────────┐  분야 자동 판별
   │Supervisor│  (1개 / 복수 / 범위밖)
   └────┬─────┘
  route()│ 동적 분기
  ┌───┬──┴──┬────┬───────┐
  ▼   ▼     ▼    ▼       ▼ (범위밖)
labor housing consumer finance  │
  └───┴──┬──┴────┘             │
         ▼                      │
   ┌──────────┐                │
   │ Verifier │ 근거 검증(하네스)│
   └────┬─────┘ 탈락분 차단     │
        ▼                       ▼
        ┌─────────┐
        │ Planner │ 검증 통과분만 종합 / 또는 거절
        └────┬────┘
             ▼  END
```

## 3. State 스키마 — `state.py` 참조
- `DomainAnswer`: domain, answer, **citations(law_name·article·enforced_date·snippet=조문원문·source_url)**, **contacts(org·phone·url·note)**, confidence
- `verified_answers`/`verification_report`: Verifier 출력 — 근거 검증 통과분/리포트 (HARNESS.md 참조)
- `answer_blocks`: Planner가 만드는 분야별 구조화 데이터 (Streamlit 카드 렌더링용). 조문 원문 포함.
- `DocumentDraft`: doc_type, domain, title, body(빈칸 [   ] 포함), based_on(근거 법령), guide(초안 경고+연락처)
  → 각 전문가의 `<domain>_draft(state)` 함수가 common/drafter.make_draft로 생성. '행동 연결' 차별점의 정점.
- `domain_answers`: Annotated[list, add] — 여러 전문가 동시 append
- `target_domains`, `in_scope`: Supervisor 라우팅 제어

## 4. 에이전트 I/O 계약
| 에이전트 | 담당 | 읽기 | 쓰기 |
|---|---|---|---|
| Supervisor | 공통 | user_query | target_domains, in_scope, messages |
| labor | A | user_query | domain_answers(+labor), messages |
| housing | B | user_query | domain_answers(+housing), messages |
| consumer | C | user_query | domain_answers(+consumer), messages |
| finance | D | user_query | domain_answers(+finance), messages |
| Verifier | 공통 | domain_answers | verified_answers, verification_report, messages |
| Planner | 공통 | verified_answers, in_scope | final_answer, answer_blocks, messages |

규칙: 전문가는 domain_answers에 자기 분야 1건만 append. 남의 분야/타 키 수정 금지.
연락처는 반드시 common/contacts.py의 get_contacts()에서. LLM 생성 금지.

## 5. 데이터 & RAG (검증 완료)
- 근거 조문·검색 코퍼스: 국가법령정보센터 API. 현행 법령 + 시행일.
- 정식 Open API → 크롤링 0. ⚠️ API 신청(OC)은 Day 0(수동 승인 1~2일).
- 검색: common/rag.py DomainRAG (Chroma/pgvector 백엔드 + stub 폴백, env RAG_BACKEND). 적재: pipeline/ medallion + 증분 갱신(scripts/update_laws.py, 주1회). 검색 고도화는 rag.py에서만 — 하이브리드(BM25+쿼리확장)는 분야별 게이트(finance·labor), consumer는 분야 내 법 라우팅(_route_law).

분야별 핵심 법령:
| 분야 | 담당 | 핵심 법령 |
|---|---|---|
| labor | A | 근로기준법, 최저임금법 |
| housing | B | 주택임대차보호법 |
| consumer | C | 전자상거래법, 방문판매법(구독·계속거래), 할부거래법(할부·상조) |
| finance | D | 채무자회생법(개인회생·파산), 통신사기피해환급법(보이스피싱), 채권추심법·대부업법 |

## 6. 웹서비스 계약 (app/)
- POST /api/consult {question, session_id?} → {domains, in_scope, final_answer, answer_blocks, verification_report, rewritten_question?}
  - session_id 있으면 멀티턴: 직전 대화로 후속 질문을 독립형으로 재작성(app/contextualize) 후 그래프 단발 투입. 재작성됐을 때만 rewritten_question 채움.
- POST /api/draft {question, domain} → DocumentDraft
- DELETE /api/session/{session_id} → {cleared}
- UI(웹·Streamlit)는 answer_blocks 만 렌더링 — State 내부 구조에 직접 의존 금지 (service.py 경유)

## 7. 동결: Day 1 종료 시 §2·§3 freeze.
