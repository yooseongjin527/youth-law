"""노동 분야 전문가 — 담당 A 전용.
입력: user_query  →  출력: domain_answers(자기 분야 1건 append), messages

★ 4명의 전문가가 모두 이 패턴 ★
1) 자기 분야 DomainRAG로 현행 법령 검색 (자기 컬렉션)
2) 검색 조문을 근거로 답변 생성 (Bedrock) — 검색 밖 내용 금지(환각 방지)
3) 연락처는 get_contacts로 검증 데이터에서 (LLM 생성 금지)
4) DomainAnswer 반환

────────────────────────────────────────────────────────
TODO 우선순위 (담당 A)
  [A/Day1] ① 노동 분야 데이터 수집 → scripts/build_index.py 의 load_corpus
  [A/Day2] ② labor 컬렉션 인덱싱 (python scripts/build_index.py labor)
  [A/Day3] ③ 아래 답변 생성을 Bedrock으로 (검색 조문 근거만, 환각 방지)
  [A/Day4] ④ 답변-근거 정합성 체크 (검색 안 된 주장 제거)
  --- 자기 분야 끝나면 아래 공용으로 ---
  [공용] common/rag.py 고도화 / scripts 평가 / planner 답변 품질 개선
────────────────────────────────────────────────────────
"""
from common.contacts import get_contacts
from common.drafter import make_draft
from common.rag import DomainRAG
from state import LegalState

_rag = DomainRAG(domain="labor", corpus_path="data/labor")


def labor_agent(state: LegalState) -> dict:
    chunks = _rag.search(state["user_query"], k=3)
    # TODO(A/Day3): chunks 근거로 Bedrock 답변 생성. 검색 조문 밖 내용 금지.
    answer: dict = {
        "domain": "labor",
        "answer": "stub: 노동법 관점 답변 (임금체불·부당해고 등)",
        "citations": [
            {
                "law_name": c["law_name"], "article": c["article"],
                "enforced_date": c["enforced_date"], "snippet": c["text"],
                "source_url": c["source_url"],
            } for c in chunks
        ],
        "contacts": get_contacts("labor"),
        "confidence": 0.8,
    }
    return {"domain_answers": [answer], "messages": ["[labor] stub 실행됨 (RAG)"]}

def labor_draft(state: LegalState, doc_type: str | None = None) -> dict:
    """labor 분야 문서 초안 생성. 답변을 먼저 만든 뒤 그 근거로 초안 작성.
    사용자가 '초안 생성'을 요청하면 호출(그래프 흐름과 별개의 진입점)."""
    answer = labor_agent(state)["domain_answers"][0]
    return make_draft(answer, doc_type)
